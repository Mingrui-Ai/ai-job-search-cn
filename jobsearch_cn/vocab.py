"""Skill vocabulary: the terms jd parse recognises as skills, grouped by direction.

The built-in vocabulary ships as jobsearch_cn/skills.json, grouped by job
direction (tech, data, product, ops, design), so a non-technical JD is read as
well as a technical one and matching can tell which direction a skill belongs
to. A user extends it in <data dir>/config/skills.json with the same shape:
terms add to an existing group, and a new group key adds a group. Nothing a
user writes can remove a built-in term.

    {"version": 1, "groups": {"ops": {"terms": ["私域运营"]},
                              "game": {"label": "游戏", "terms": ["Unity"]}}}
"""

import json
from pathlib import Path

from jobsearch_cn import schema

BUILTIN = Path(__file__).resolve().parent / "skills.json"
USER_FILE = Path("config") / "skills.json"
VERSION = 1
MAX_TERM = 50
_GROUP_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


class VocabularyError(Exception):
    """A vocabulary file is missing, unreadable or malformed."""


class Vocabulary:
    def __init__(self, groups: dict):
        # groups: key -> {"label": str, "terms": [str, ...]}, terms unique across groups.
        self.groups = groups
        self._group_of = {}
        for key, group in groups.items():
            for term in group["terms"]:
                self._group_of.setdefault(schema.normalize_for_match(term), key)

    @property
    def terms(self) -> list:
        return [term for group in self.groups.values() for term in group["terms"]]

    def group_of(self, term: str):
        """The group key a term belongs to, or None."""
        return self._group_of.get(schema.normalize_for_match(term))


def load(data_dir=None) -> Vocabulary:
    """The built-in vocabulary, extended by <data_dir>/config/skills.json when it exists."""
    groups = {}
    _merge(groups, _read(BUILTIN), str(BUILTIN.name), builtin=True)
    if data_dir is not None:
        user = Path(data_dir) / USER_FILE
        if user.is_file():
            _merge(groups, _read(user), str(user), builtin=False)
    return Vocabulary(groups)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except OSError as exc:
        raise VocabularyError(f"cannot read {path}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise VocabularyError(f"{path} is not UTF-8 text; save it as UTF-8") from None
    except json.JSONDecodeError as exc:
        raise VocabularyError(f"{path} is not valid JSON: {exc}") from None


def _merge(groups: dict, doc, where: str, *, builtin: bool) -> None:
    if not isinstance(doc, dict) or doc.get("version") != VERSION or not isinstance(doc.get("groups"), dict):
        raise VocabularyError(f'{where}: expected {{"version": {VERSION}, "groups": {{...}}}}')
    seen = {schema.normalize_for_match(t) for g in groups.values() for t in g["terms"]}
    for key, group in doc["groups"].items():
        at = f"{where}: groups.{key}"
        if not (isinstance(key, str) and key and set(key) <= _GROUP_KEY_CHARS):
            raise VocabularyError(f"{at}: group keys are lowercase letters, digits, - and _")
        if not isinstance(group, dict) or not isinstance(group.get("terms"), list):
            raise VocabularyError(f'{at}: must be an object with a "terms" list')
        label = group.get("label")
        if label is not None and not (isinstance(label, str) and label.strip()):
            raise VocabularyError(f"{at}.label: must be a non-empty string")
        if key not in groups:
            groups[key] = {"label": label or key, "terms": []}
        for index, term in enumerate(group["terms"]):
            if not (isinstance(term, str) and term.strip() and term == term.strip() and len(term) <= MAX_TERM):
                raise VocabularyError(f"{at}.terms[{index}]: must be a trimmed, non-empty string of at most "
                                      f"{MAX_TERM} characters")
            folded = schema.normalize_for_match(term)
            if folded in seen:
                if builtin:
                    raise VocabularyError(f"{at}.terms[{index}]: {term!r} is listed twice")
                continue  # a user re-listing a known term is harmless
            seen.add(folded)
            groups[key]["terms"].append(term)
