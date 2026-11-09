"""A small HTML reader: a DOM tree, a CSS selector subset and innerText-like text.

The collector (collect.py, docs/cn/collect.md) asks the browser for the page it has rendered
(the serialised DOM) and reads a few fields out of it here, in Python with the standard library.
That keeps the site rules testable offline against saved HTML samples, without a browser.
Only what the site rules need is supported:

* Selectors: tag, `.class`, `#id`, `[attr]`, `[attr=v]`, `[attr^=v]`, `[attr$=v]`, `[attr*=v]`,
  combined without spaces (`a.job-name[href]`) and joined by a space (descendant) or `>`
  (child). Values may not contain spaces. No commas: a site rule lists fallback selectors and
  takes the first that matches anything. The same strings are valid CSS, so the browser can
  wait for them too.
* Text: an approximation of innerText. Block elements and `<br>` break lines, runs of
  whitespace collapse to one space, each line is stripped and empty lines are dropped.
  script, style, template, svg and elements marked hidden (the `hidden` attribute, an inline
  `display:none` or `visibility:hidden`) are skipped. Stylesheets are not applied, so a rule
  names the container it wants rather than relying on what CSS would hide.
"""

import re
from html.parser import HTMLParser

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
SKIP = frozenset("script style noscript template svg head iframe object canvas select".split())
RENDERED_NONTEXT = frozenset("iframe canvas svg object".split())
BLOCK = frozenset("""address article aside blockquote body dd details dialog div dl dt fieldset
    figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr html li main nav ol p pre section
    summary table tbody tfoot thead tr ul""".split())

_SPACES = re.compile(r"[ \t\n\r\f ]+")
_HIDDEN_STYLE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important)?\s*(?:;|$)", re.I)
_PART = re.compile(
    r"(?P<tag>[a-zA-Z][a-zA-Z0-9-]*|\*)"
    r"|\.(?P<cls>[\w-]+)"
    r"|#(?P<id>[\w-]+)"
    r"|\[(?P<attr>[\w-]+)(?:(?P<op>[\^$*]?=)(?P<quote>[\"']?)(?P<value>[^\]\"'\s]*)(?P=quote))?\]"
)


class Node:
    """One element. children holds Nodes and text strings in document order."""

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent

    def get(self, name: str, default=None):
        return self.attrs.get(name, default)

    def classes(self) -> list:
        return self.attrs.get("class", "").split()

    def iter(self):
        """Descendant elements in document order (not self)."""
        stack = [child for child in reversed(self.children) if isinstance(child, Node)]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(child for child in reversed(node.children) if isinstance(child, Node))

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<{self.tag} {self.attrs!r}>"


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.current = self.root

    def _attrs(self, attrs):
        return {name: (value if value is not None else "") for name, value in attrs}

    def handle_starttag(self, tag, attrs):
        node = Node(tag, self._attrs(attrs), self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, self._attrs(attrs), self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:  # a stray end tag with nothing open by that name is ignored
            self.current = node.parent

    def handle_data(self, data):
        if data:
            self.current.children.append(data)


def parse(html: str) -> Node:
    """The document as a tree; its root is a "#document" node."""
    builder = _Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def _compile_compound(text: str, selector: str):
    tests, position = [], 0
    for match in _PART.finditer(text):
        if match.start() != position or (match.group("tag") and position):
            break
        position = match.end()
        tests.append(match)
    if position != len(text) or not tests:
        raise ValueError(f"unsupported selector: {selector!r}")
    compound = {"tag": None, "classes": [], "id": None, "attrs": []}
    for match in tests:
        if match.group("tag"):
            compound["tag"] = None if match.group("tag") == "*" else match.group("tag").lower()
        elif match.group("cls"):
            compound["classes"].append(match.group("cls"))
        elif match.group("id"):
            compound["id"] = match.group("id")
        else:
            compound["attrs"].append((match.group("attr").lower(), match.group("op"), match.group("value")))
    return compound


def compile_selector(selector: str):
    """[(combinator, compound), ...]; the first combinator is None, the rest " " or ">"."""
    tokens = re.findall(r">|[^\s>]+", selector.strip())
    chain, combinator = [], None
    for token in tokens:
        if token == ">":
            if combinator == ">" or not chain:
                raise ValueError(f"unsupported selector: {selector!r}")
            combinator = ">"
            continue
        chain.append((combinator if chain else None, _compile_compound(token, selector)))
        combinator = " "
    if not chain or combinator == ">":
        raise ValueError(f"unsupported selector: {selector!r}")
    return chain


def _attr_matches(node: Node, name: str, op, value) -> bool:
    if name not in node.attrs:
        return False
    actual = node.attrs[name]
    if op is None:
        return True
    if op == "=":
        return actual == value
    if not value:
        return False
    if op == "^=":
        return actual.startswith(value)
    if op == "$=":
        return actual.endswith(value)
    return value in actual  # *=


def _matches(node: Node, compound) -> bool:
    if compound["tag"] and node.tag != compound["tag"]:
        return False
    if compound["id"] and node.attrs.get("id") != compound["id"]:
        return False
    if compound["classes"]:
        classes = node.classes()
        if any(name not in classes for name in compound["classes"]):
            return False
    return all(_attr_matches(node, *test) for test in compound["attrs"])


def _matches_chain(node: Node, chain, index: int) -> bool:
    if not _matches(node, chain[index][1]):
        return False
    if index == 0:
        return True
    ancestor = node.parent
    if chain[index][0] == ">":
        return ancestor is not None and ancestor.tag != "#document" and _matches_chain(ancestor, chain, index - 1)
    while ancestor is not None and ancestor.tag != "#document":
        if _matches_chain(ancestor, chain, index - 1):
            return True
        ancestor = ancestor.parent
    return False


def select(root: Node, selector: str) -> list:
    """Elements under root matching selector, in document order (like querySelectorAll)."""
    chain = compile_selector(selector)
    last = len(chain) - 1
    return [node for node in root.iter() if _matches_chain(node, chain, last)]


def select_first_rule(root: Node, selectors) -> list:
    """The matches of the first selector in the list that matches anything; [] if none does."""
    for selector in selectors:
        found = select(root, selector)
        if found:
            return found
    return []


def first(root: Node, selectors):
    """The first element matched by the first selector that matches anything, or None."""
    found = select_first_rule(root, selectors)
    return found[0] if found else None


def visible(node: Node, *, include_nontext: bool = False) -> bool:
    """Markup visibility; text extraction also skips non-text tags by default.

    Security markers can live on iframe/canvas/svg/object elements, which do not
    supply innerText. Only these tags can opt in; script/template and other
    skipped contexts remain invisible.
    """
    if node.tag in SKIP and not (include_nontext and node.tag in RENDERED_NONTEXT):
        return False
    if "hidden" in node.attrs:
        return False
    return not _HIDDEN_STYLE.search(node.attrs.get("style", ""))


def text(node: Node, *, keep_newlines: bool = False) -> str:
    """innerText-like text: lines joined by newlines, each stripped, empty lines dropped.

    keep_newlines treats line breaks inside text as line breaks, as `white-space: pre-line`
    does; a site rule sets it for a description block whose text is written that way.
    """
    lines = [[]]

    def newline():
        if lines[-1]:
            lines.append([])

    def walk(parent: Node):
        for child in parent.children:
            if isinstance(child, str):
                if keep_newlines:
                    for number, part in enumerate(child.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
                        if number:
                            newline()
                        lines[-1].append(part)
                else:
                    lines[-1].append(child)
            elif visible(child):
                if child.tag == "br":
                    newline()
                elif child.tag in BLOCK:
                    newline()
                    walk(child)
                    newline()
                else:
                    if child.tag in ("td", "th"):
                        lines[-1].append(" ")
                    walk(child)

    if visible(node):
        walk(node)
    cleaned = (_SPACES.sub(" ", "".join(pieces)).strip() for pieces in lines)
    return "\n".join(line for line in cleaned if line)


def page_title(root: Node) -> str:
    """The text of the first <title>, which text() skips (it is inside <head>)."""
    for node in root.iter():
        if node.tag == "title":
            return _SPACES.sub(" ", "".join(c for c in node.children if isinstance(c, str))).strip()
    return ""
