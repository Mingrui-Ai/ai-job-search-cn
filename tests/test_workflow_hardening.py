"""Pin the workflow settings zizmor checks, without needing zizmor or PyYAML.

- Every `actions/checkout` sets `persist-credentials: false`. Otherwise the job
  token stays in `.git/config` for every later step, including the CLI code a
  pull request brings (`artipacked`).
- A matrix value that comes from repository content - `cli-checks` discovers
  `matrix.tool` from directory names, which a pull request controls - never
  appears expanded inside a `run:` script (`template-injection`).
- Every `uses:` names an action by its full commit SHA (`unpinned-uses`). A tag
  or a branch can be moved to other code after review; a commit cannot. A
  reference into this repository (`./`) has no version to pin, and a
  `docker://` image must carry its `sha256` digest.

Each check is a function over a list of workflow files, so the tests can aim it
at a directory of their own as well as at `.github/workflows/`. GitHub runs a
`.yaml` workflow like a `.yml` one, so both are listed.
"""
import re
import tempfile
import unittest
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def workflow_files(directory: Path) -> list:
    """The workflow files in a directory, `.yml` and `.yaml` alike, in name order."""
    return sorted(path for pattern in ("*.yml", "*.yaml") for path in directory.glob(pattern))


WORKFLOWS = workflow_files(WORKFLOW_DIR)


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def key_indent(line: str) -> int:
    """Column of a step's keys: two past the dash on a `- key:` line."""
    return indent(line) + (2 if line.lstrip().startswith("- ") else 0)


def kept_credentials(paths) -> list:
    """`file:line` of every `actions/checkout` step that does not set `persist-credentials: false`."""
    found = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "uses: actions/checkout@" not in line:
                continue
            keys = key_indent(line)
            block = []
            for following in lines[i + 1 :]:
                if following.strip() and indent(following) < keys:
                    break
                block.append(following.strip())
            if "persist-credentials: false" not in block:
                found.append(f"{path.name}:{i + 1}")
    return found


def expanded_matrix_values(paths) -> list:
    """`file:line` of every `run:` script line that has `matrix.tool` expanded into it."""
    found = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        run_keys = None  # indent of the active `run:` key, None outside one
        for i, line in enumerate(lines, 1):
            if run_keys is not None and line.strip() and indent(line) <= run_keys:
                run_keys = None
            stripped = line.strip()
            if run_keys is None and stripped.startswith(("run:", "- run:")):
                run_keys = key_indent(line)
                script = stripped.split("run:", 1)[1]
            else:
                script = line if run_keys is not None else ""
            if "${{ matrix.tool }}" in script:
                found.append(f"{path.name}:{i}")
    return found


USES_KEY = re.compile(r"""^\s*(?:-\s+)?["']?uses["']?\s*:""")
PINNED_ACTION = re.compile(r"[\w.-]+/[\w.-]+(?:/[^@\s]+)?@[0-9a-f]{40}")
PINNED_IMAGE = re.compile(r"docker://[^@\s]+@sha256:[0-9a-f]{64}")


def uses_refs(text: str) -> list:
    """Every `uses:` in a workflow as (line number, reference), comment and quotes removed."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if not USES_KEY.match(line):
            continue
        value = re.split(r"\s#", line.split(":", 1)[1], maxsplit=1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        found.append((number, value))
    return found


def unread_uses(text: str) -> list:
    """Numbers of the lines where `uses` stands outside a comment and outside what `uses_refs` read.

    A `uses` written some way this reader does not know would otherwise go unchecked. A step name
    or a script that only mentions the word is reported too: this errs toward reporting.
    """
    read = {number for number, _ in uses_refs(text)}
    unread = []
    for number, line in enumerate(text.splitlines(), 1):
        written = len(re.findall(r"\buses\b", re.sub(r"#.*", "", line)))
        if written > (1 if number in read else 0):
            unread.append(number)
    return unread


def unpinned(ref: str) -> str:
    """Why a `uses:` reference is not fixed to one piece of code; empty when it is."""
    if ref.startswith("./"):
        return ""
    if ref.startswith("docker://"):
        return "" if PINNED_IMAGE.fullmatch(ref) else "container image without a sha256 digest"
    return "" if PINNED_ACTION.fullmatch(ref) else "action not pinned to a full commit SHA"


def unpinned_uses(paths) -> list:
    """`file:line: why` for every `uses:` that is not pinned and every `uses` that could not be read."""
    found = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for number, ref in uses_refs(text):
            if unpinned(ref):
                found.append(f"{path.name}:{number}: {unpinned(ref)}: {ref}")
        for number in unread_uses(text):
            found.append(f"{path.name}:{number}: `uses` outside a reference this check can read")
    return found


class WorkflowHardeningTests(unittest.TestCase):
    def test_workflows_found(self):
        self.assertTrue(WORKFLOWS)

    def test_every_checkout_drops_its_credentials(self):
        self.assertEqual(kept_credentials(WORKFLOWS), [])

    def test_discovered_matrix_values_stay_out_of_run_scripts(self):
        self.assertEqual(expanded_matrix_values(WORKFLOWS), [])

    def test_every_action_is_pinned_to_a_full_commit(self):
        # #180 review (P3-2): only upstream-watch.yml had this check.
        self.assertTrue(any(uses_refs(path.read_text(encoding="utf-8")) for path in WORKFLOWS))
        self.assertEqual(unpinned_uses(WORKFLOWS), [])

    def test_the_pin_check_tells_references_apart(self):
        sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
        digest = "a" * 64
        pinned = (f"actions/checkout@{sha}", f"github/codeql-action/init@{sha}",
                  "./.github/actions/setup", f"docker://ghcr.io/owner/image@sha256:{digest}")
        loose = ("actions/checkout@v7", "actions/checkout@v7.0.1", "actions/checkout@main", "actions/checkout",
                 f"actions/checkout@{sha[:7]}", f"actions/checkout@{sha[:39]}", f"actions/checkout@{sha}0",
                 f"actions/checkout@{sha.upper()}", f"checkout@{sha}", f"actions/checkout@{sha} extra",
                 "docker://alpine", "docker://alpine:3.20", f"docker://alpine@sha256:{digest[:63]}",
                 "${{ matrix.action }}", "")
        for ref in pinned:
            with self.subTest(pinned=ref):
                self.assertEqual(unpinned(ref), "")
        for ref in loose:
            with self.subTest(loose=ref):
                self.assertNotEqual(unpinned(ref), "")

    def test_the_pin_check_reads_each_way_a_step_writes_uses(self):
        sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
        text = "\n".join((
            "jobs:",
            "  call:",
            "    uses: ./.github/workflows/reusable.yml",
            "  build:",
            "    steps:",
            f"      - uses: actions/checkout@{sha} # v7.0.1",
            "      - name: Review",
            "        uses: 'actions/dependency-review-action@v5'  # moved tag",
            "      - name: Bun",
            '        "uses": "oven-sh/setup-bun@main"',
            "      # uses: actions/setup-python@v7",
            "      - run: echo uses nothing",
        ))
        refs = uses_refs(text)
        self.assertEqual(refs, [(3, "./.github/workflows/reusable.yml"), (6, f"actions/checkout@{sha}"),
                                (8, "actions/dependency-review-action@v5"), (10, "oven-sh/setup-bun@main")])
        self.assertEqual([number for number, ref in refs if unpinned(ref)], [8, 10])
        self.assertEqual(unread_uses(text), [12])


class WorkflowDirectoryTests(unittest.TestCase):
    """#183 review (P2-1): `*.yml` alone left a `.yaml` workflow out of every check here.

    The workflows are written to a directory of the test's own, never to the repository's.
    """

    SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def write(self, name: str, *steps: str) -> None:
        """A one-job workflow; its steps start on line 7."""
        head = ("name: Extra", "on: pull_request", "jobs:", "  extra:", "    runs-on: ubuntu-latest", "    steps:")
        text = "\n".join((*head, *("      " + line for line in steps))) + "\n"
        (self.directory / name).write_text(text, encoding="utf-8")

    def test_a_yaml_workflow_is_listed_and_checked(self):
        self.write("ci.yml", f"- uses: actions/checkout@{self.SHA}", "  with:", "    persist-credentials: false")
        self.write("extra.yaml", "- uses: actions/checkout@v7", "- run: echo ${{ matrix.tool }}")
        self.write("notes.txt", "- uses: actions/checkout@v7")
        files = workflow_files(self.directory)
        self.assertEqual([path.name for path in files], ["ci.yml", "extra.yaml"])
        self.assertEqual(unpinned_uses(files),
                         ["extra.yaml:7: action not pinned to a full commit SHA: actions/checkout@v7"])
        self.assertEqual(kept_credentials(files), ["extra.yaml:7"])
        self.assertEqual(expanded_matrix_values(files), ["extra.yaml:8"])

    def test_a_pinned_yaml_workflow_passes(self):
        self.write("extra.yaml", f"- uses: actions/checkout@{self.SHA} # v7.0.1", "  with:",
                   "    persist-credentials: false", '- run: echo "$TOOL"')
        files = workflow_files(self.directory)
        self.assertEqual([path.name for path in files], ["extra.yaml"])
        self.assertEqual(unpinned_uses(files) + kept_credentials(files) + expanded_matrix_values(files), [])

    def test_a_uses_that_was_not_read_is_named_by_file_and_line(self):
        # #183 review (P3-1): the count check failed with `15 != 16 : ci.yml` and named no line.
        self.write("ci.yml", "- name: Step that uses a cache", f"  uses: actions/cache@{self.SHA}",
                   "- {uses: actions/checkout@v7}", "- run: echo done  # uses nothing")
        self.assertEqual(unpinned_uses(workflow_files(self.directory)),
                         ["ci.yml:7: `uses` outside a reference this check can read",
                          "ci.yml:9: `uses` outside a reference this check can read"])


if __name__ == "__main__":
    unittest.main()
