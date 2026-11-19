"""Small robots.txt parser following RFC 9309.

Supports `*` and `$` in paths, longest-match precedence (Allow wins a tie), grouping of
consecutive User-agent lines, and Crawl-delay. The standard library's RobotFileParser does
plain prefix matching, so a rule like `Disallow: /*?` would be ignored; this one honours it.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

MAX_ROBOTS_BYTES = 512 * 1024  # RFC 9309: parse at least the first 500 KiB


@dataclass
class Robots:
    rules: list = field(default_factory=list)  # [(allow: bool, pattern: str, regex)]
    crawl_delay: float | None = None
    allow_all: bool = False
    disallow_all: bool = False
    note: str | None = None  # why allow_all / disallow_all was chosen
    fetch_error: str | None = None  # network error while fetching robots.txt (site unreachable)

    def can_fetch(self, url: str) -> bool:
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        path = parts.path or '/'
        if path == '/robots.txt':
            return True
        if self.allow_all or not self.rules:
            return True
        target = _norm(path + ('?' + parts.query if parts.query else ''))
        best_len, best_allow = -1, True
        for allow, pattern, rx in self.rules:
            if rx.match(target):
                n = len(pattern)
                if n > best_len or (n == best_len and allow):
                    best_len, best_allow = n, allow
        return best_allow


def _norm(s: str) -> str:
    # Compare decoded forms so that /%E0%B8%95 and the raw UTF-8 path match the same rule.
    try:
        return unquote(s)
    except Exception:  # noqa: BLE001
        return s


def _compile(pattern: str):
    anchored = pattern.endswith('$')
    body = pattern[:-1] if anchored else pattern
    rx = '.*'.join(re.escape(p) for p in body.split('*'))
    return re.compile(rx + ('$' if anchored else ''), re.S)


def _matches_agent(value: str, token: str) -> bool:
    v = value.strip().lower()
    if not v or v == '*':
        return False
    t = token.lower()
    return t == v or t.startswith(v)


def parse(text: str, token: str) -> Robots:
    """Parse robots.txt text and return the rules that apply to `token` (falling back to `*`)."""
    groups = []  # each: {'agents': [...], 'rules': [...], 'delay': None}
    cur = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or ':' not in line:
            continue
        key, val = line.split(':', 1)
        key, val = key.strip().lower(), val.strip()
        if key in ('user-agent', 'useragent'):
            if cur is None or not last_was_agent:
                cur = {'agents': [], 'rules': [], 'delay': None}
                groups.append(cur)
            cur['agents'].append(val)
            last_was_agent = True
            continue
        last_was_agent = False
        if cur is None:
            continue
        if key in ('allow', 'disallow'):
            if not val:
                continue  # empty Disallow = allow everything; empty Allow means nothing
            if not val.startswith(('/', '*')):
                val = '/' + val
            p = _norm(val)
            cur['rules'].append((key == 'allow', p, _compile(p)))
        elif key == 'crawl-delay':
            try:
                cur['delay'] = float(val)
            except ValueError:
                pass

    specific = [g for g in groups if any(_matches_agent(a, token) for a in g['agents'])]
    chosen = specific or [g for g in groups if any(a.strip() == '*' for a in g['agents'])]
    r = Robots()
    for g in chosen:
        r.rules.extend(g['rules'])
        if g['delay'] is not None:
            r.crawl_delay = max(r.crawl_delay or 0.0, g['delay'])
    if not chosen:
        r.allow_all = True
    return r


def from_status(status: int | None, text: str | None, token: str) -> Robots:
    """Rules for a robots.txt fetch result (status None = network error).

    2xx -> parse. 404/410 and other 4xx -> no rules (RFC 9309). 401/403 are treated as
    disallow-all on purpose (a site that refuses robots.txt usually refuses crawlers).
    429, 5xx and network errors -> disallow-all (RFC 9309: "unreachable").
    """
    if status is None:
        return Robots(disallow_all=True, note='robots.txt unreachable: treated as disallow-all')
    if 200 <= status < 300:
        return parse(text or '', token)
    if status in (401, 403):
        return Robots(disallow_all=True, note=f'robots.txt returned HTTP {status}: treated as disallow-all')
    if status == 429 or status >= 500:
        return Robots(disallow_all=True, note=f'robots.txt returned HTTP {status}: treated as disallow-all')
    return Robots(allow_all=True, note=f'robots.txt returned HTTP {status}: no rules')
