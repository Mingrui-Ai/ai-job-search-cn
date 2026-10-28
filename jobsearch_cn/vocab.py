"""Skill vocabulary: the terms jd parse recognises as skills, grouped by direction.

The built-in vocabulary ships as jobsearch_cn/skills.json, grouped by job
direction (tech, data, product, ops, design, market) plus general, the office
software every direction uses, so a non-technical JD is read as well as a
technical one and matching can tell which direction a skill belongs to. A
term is the skill as a JD asks for it (文案写作, not 文案). Synonyms - K8s and
Kubernetes - are listed together in same_as: one skill to matching, while the
parser still reports the JD's own spelling. A user extends it in
<data dir>/config/skills.json with the same shape: terms add to an existing
group, a new group key adds a group, and a same_as entry that shares a term
with another joins it. Nothing a user writes can remove a built-in term.

    {"version": 1, "groups": {"ops": {"terms": ["私域运营", "私域流量运营"]},
                              "game": {"label": "游戏", "terms": ["Unity"]}},
     "same_as": [["私域运营", "私域流量运营"]]}
"""

import json
from pathlib import Path

from jobsearch_cn import schema

BUILTIN = Path(__file__).resolve().parent / "skills.json"
USER_FILE = Path("config") / "skills.json"
VERSION = 1
MAX_TERM = 50
GENERAL = "general"  # office software every direction uses: never a job's or a candidate's direction
_KEYS = {"version", "groups", "same_as"}
_GROUP_KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


class VocabularyError(Exception):
    """A vocabulary file is missing, unreadable or malformed."""


class Vocabulary:
    def __init__(self, groups: dict, same_as=()):
        # groups: key -> {"label": str, "terms": [str, ...]}, terms unique across groups.
        # same_as: lists of terms from one group that name one skill.
        self.groups = groups
        self.same_as = [list(terms) for terms in same_as]
        self._group_of = {}
        for key, group in groups.items():
            for term in group["terms"]:
                self._group_of.setdefault(schema.normalize_for_match(term), key)
        self._key = {schema.normalize_for_match(term): schema.normalize_for_match(terms[0])
                     for terms in self.same_as for term in terms}

    @property
    def terms(self) -> list:
        return [term for group in self.groups.values() for term in group["terms"]]

    def group_of(self, term: str):
        """The group key a term belongs to, or None."""
        return self._group_of.get(schema.normalize_for_match(term))

    def key(self, name: str) -> str:
        """What a skill name compares as: folded, and the same for every term of a same_as entry."""
        folded = schema.normalize_for_match(name)
        return self._key.get(folded, folded)

    def same(self, a: str, b: str) -> bool:
        """Whether two skill names - a JD's and a profile's, say - name the same skill."""
        return self.key(a) == self.key(b)


def load(data_dir=None) -> Vocabulary:
    """The built-in vocabulary, extended by <data_dir>/config/skills.json when it exists."""
    groups, same_as = {}, []
    _merge(groups, same_as, _read(BUILTIN), str(BUILTIN.name), builtin=True)
    if data_dir is not None:
        user = Path(data_dir) / USER_FILE
        if user.is_file():
            _merge(groups, same_as, _read(user), str(user), builtin=False)
    return Vocabulary(groups, same_as)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_bytes().decode("utf-8-sig"))
    except OSError as exc:
        raise VocabularyError(f"cannot read {path}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise VocabularyError(f"{path} is not UTF-8 text; save it as UTF-8") from None
    except json.JSONDecodeError as exc:
        raise VocabularyError(f"{path} is not valid JSON: {exc}") from None


def _merge(groups: dict, same_as: list, doc, where: str, *, builtin: bool) -> None:
    if not isinstance(doc, dict) or doc.get("version") != VERSION or not isinstance(doc.get("groups"), dict):
        raise VocabularyError(f'{where}: expected {{"version": {VERSION}, "groups": {{...}}}}')
    unknown = sorted(str(key) for key in doc if key not in _KEYS)
    if unknown:
        raise VocabularyError(f"{where}: unknown key {unknown[0]!r} (the keys are {', '.join(sorted(_KEYS))})")
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
    _merge_same_as(groups, same_as, doc.get("same_as", []), where, builtin=builtin)


def _merge_same_as(groups: dict, same_as: list, entries, where: str, *, builtin: bool) -> None:
    """Add a file's same_as entries; one that shares a term with an entry already there joins it."""
    fold = schema.normalize_for_match
    if not isinstance(entries, list):
        raise VocabularyError(f"{where}: same_as must be a list of term lists")
    group_of = {}
    for key, group in groups.items():
        for term in group["terms"]:
            group_of.setdefault(fold(term), key)
    for index, entry in enumerate(entries):
        at = f"{where}: same_as[{index}]"
        if not (isinstance(entry, list) and len(entry) >= 2 and all(isinstance(t, str) for t in entry)):
            raise VocabularyError(f"{at}: must be a list of at least two terms")
        folded = [fold(term) for term in entry]
        if len(set(folded)) < len(folded):
            raise VocabularyError(f"{at}: lists a term twice")
        for term, key in zip(entry, folded):
            if key not in group_of:
                raise VocabularyError(f"{at}: {term!r} is in no group; add it to a group's terms first")
        owners = sorted({group_of[key] for key in folded})
        if len(owners) > 1:
            raise VocabularyError(f"{at}: synonyms belong to one group, but these are in {' and '.join(owners)}")
        joined = [i for i, terms in enumerate(same_as) if {fold(t) for t in terms} & set(folded)]
        if joined and builtin:
            raise VocabularyError(f"{at}: shares a term with another same_as entry; make them one entry")
        merged = [term for i in joined for term in same_as[i]]
        merged += [term for term in entry if fold(term) not in {fold(t) for t in merged}]
        for i in reversed(joined):
            del same_as[i]
        same_as.append(merged)
