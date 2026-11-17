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
"""
import re
import unittest
from pathlib import Path

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))


def indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def key_indent(line: str) -> int:
    """Column of a step's keys: two past the dash on a `- key:` line."""
    return indent(line) + (2 if line.lstrip().startswith("- ") else 0)


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


def unpinned(ref: str) -> str:
    """Why a `uses:` reference is not fixed to one piece of code; empty when it is."""
    if ref.startswith("./"):
        return ""
    if ref.startswith("docker://"):
        return "" if PINNED_IMAGE.fullmatch(ref) else "container image without a sha256 digest"
    return "" if PINNED_ACTION.fullmatch(ref) else "action not pinned to a full commit SHA"


class WorkflowHardeningTests(unittest.TestCase):
    def test_workflows_found(self):
        self.assertTrue(WORKFLOWS)

    def test_every_checkout_drops_its_credentials(self):
        for path in WORKFLOWS:
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
                with self.subTest(workflow=path.name, line=i + 1):
                    self.assertIn("persist-credentials: false", block)

    def test_discovered_matrix_values_stay_out_of_run_scripts(self):
        for path in WORKFLOWS:
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
                with self.subTest(workflow=path.name, line=i):
                    self.assertNotIn("${{ matrix.tool }}", script)

    def test_every_action_is_pinned_to_a_full_commit(self):
        # #180 review (P3-2): only upstream-watch.yml had this check.
        total = 0
        for path in WORKFLOWS:
            text = path.read_text(encoding="utf-8")
            refs = uses_refs(text)
            total += len(refs)
            # A `uses` written some way this reader does not know would go unchecked.
            written = len(re.findall(r"\buses\b", re.sub(r"#.*", "", text)))
            self.assertEqual(len(refs), written, path.name)
            for number, ref in refs:
                with self.subTest(workflow=path.name, line=number, ref=ref):
                    self.assertEqual(unpinned(ref), "")
        self.assertTrue(total)

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

if __name__ == "__main__":
    unittest.main()
