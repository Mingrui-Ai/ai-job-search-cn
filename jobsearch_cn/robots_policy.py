"""Offline, bounded robots decision for one explicit posting URL.

The wildcard table walk and cautious longest-match/Disallow tie rule are adapted
from tools/robots_check.py. Importing that tool would also import its online curl
gate; keep this small pure part here without widening the package import boundary.
Unlike the older gate, malformed/unsupported rules and crawl delays fail closed.
"""

import hashlib
import re
from urllib.parse import unquote, urlsplit

USER_AGENT = "JobSearchCN/1"
AGENTS = ("JobSearchCN", "*", "Claude-User", "ChatGPT-User")
MAX_BYTES = 64_000  # acceptance/decoding bound, not a transport download limit
MAX_RULES = 512
MAX_PATTERN = 2048


def _match(pattern, path):
    if not pattern:
        return -1
    pattern = unquote(pattern, errors="strict")
    anchored = pattern.endswith("$")
    pat = re.sub(r"\*{2,}", "*", pattern[:-1] if anchored else pattern)
    reach = [True] + [False] * len(pat)
    for index, char in enumerate(pat, 1):
        if char != "*":
            break
        reach[index] = True
    if reach[-1] and not anchored:
        return len(pattern)
    for char in path:
        step = [False] * (len(pat) + 1)
        for index, expected in enumerate(pat, 1):
            if expected == "*":
                step[index] = step[index - 1] or reach[index]
            elif expected == char:
                step[index] = reach[index - 1]
        reach = step
        if reach[-1] and not anchored:
            return len(pattern)
    return len(pattern) if reach[-1] else -1


def _parse(text):
    groups, agents, rules, delays = [], [], [], []
    count, recognised = 0, False
    for raw in text.removeprefix("\ufeff").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        field, colon, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if not colon or field not in ("user-agent", "allow", "disallow", "crawl-delay", "sitemap", "host"):
            raise ValueError("robots 包含无法可靠解释的指令")
        recognised = True
        if any(ord(char) < 32 or ord(char) == 127 for char in line):
            raise ValueError("robots 包含控制字符")
        if field == "user-agent":
            if not re.fullmatch(r"\*|[A-Za-z_-]+", value):
                raise ValueError("robots 的 User-agent 无法识别")
            if rules or delays:
                groups.append((agents, rules, delays))
                agents, rules, delays = [], [], []
            agents.append(value.lower())
        elif field in ("allow", "disallow", "crawl-delay"):
            if not agents:
                raise ValueError("robots 的规则缺少 User-agent")
            count += 1
            if count > MAX_RULES:
                raise ValueError("robots 规则数量超过接受上限")
            if field == "crawl-delay":
                if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                    raise ValueError("robots 的 Crawl-delay 无法识别")
                delays.append(float(value))
            else:
                if (len(value) > MAX_PATTERN or (value and not value.startswith(("/", "*")))
                        or any(char.isspace() for char in value) or re.search(r"%(?![0-9A-Fa-f]{2})", value)):
                    raise ValueError("robots 的路径规则无法可靠解释")
                unquote(value, errors="strict")
                rules.append((field == "allow", value))
        # Sitemap/Host identify metadata only: never request their values.
    if agents:
        groups.append((agents, rules, delays))
    if text.strip() and not recognised:
        raise ValueError("robots 非空但没有可识别指令")
    return groups


def decide(url, body, status, *, checked_at, error=None):
    """One response -> JSON decision; no network or storage. Failures never permit the detail."""
    parts = urlsplit(url)
    result = {"status": "unconfirmed", "url": f"{parts.scheme}://{parts.netloc}/robots.txt",
              "http_status": status, "checked_at": checked_at, "reason": None, "sha256": None,
              "user_agents": list(AGENTS), "delay_seconds": 0.0}
    if error:
        result["reason"] = "robots 读取失败，未确认访问许可"
        return result
    if status == 404:
        result.update(status="allowed", reason="no_robots")
        return result
    if status != 200:
        result["reason"] = "robots 未返回 HTTP 200 或 404，未确认访问许可"
        return result
    if not isinstance(body, bytes) or len(body) > MAX_BYTES:
        result["reason"] = "robots 无法读取或超过 64000 字节接受上限"
        return result
    result["sha256"] = hashlib.sha256(body).hexdigest()
    try:
        text = body.decode("utf-8-sig")
        groups = _parse(text)
        if "\ufffd" in text:
            raise ValueError("robots 包含损坏的字符")
        path = unquote(parts.path or "/", errors="strict")
        if parts.query:
            path += "?" + unquote(parts.query, errors="strict")
        delay = 0.0
        for agent in AGENTS:
            # Check every matching product group, plus '*' independently. This is
            # intentionally more cautious than dropping wildcard restrictions.
            applicable = [(rules, delays) for names, rules, delays in groups
                          if any(name == "*" if agent == "*" else name != "*" and name in agent.lower()
                                 for name in names)]
            best, permitted = -1, True
            for rules, delays in applicable:
                delay = max([delay, *delays])
                for allow, pattern in rules:
                    length = _match(pattern, path)
                    if length > best or (length == best and length >= 0 and not allow):
                        best, permitted = length, allow
            if not permitted:
                result.update(status="disallowed", reason=f"robots 禁止 {agent} 访问该详情路径")
                return result
        if delay > 9:
            raise ValueError("robots 的 Crawl-delay 超过本功能 9 秒等待上限")
        result.update(status="allowed", reason="robots 允许该详情路径", delay_seconds=delay)
    except (ValueError, UnicodeError, OverflowError) as exc:
        result["reason"] = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) \
            else "robots 编码或规则无法可靠解释"
    return result
