"""Owner rules: the subset of Suricata rules an owner may add (NET-191 slice 3).

Detection only. Each non-blank line is a comment ("#") or one rule whose action is exactly
"alert". The options are split by a parser that knows quotes and backslash escapes, so a ";" or
a keyword inside msg/content text is just text. Keywords that run code, change the engine or read
or write files are refused. Each rule needs its own sid in the owner range, which no rule source
uses. Suricata's own test (-T) checks everything else before a rule is ever loaded.
"""

from typing import Any

MAX_RULES = 2000
# The plan said 1 MB; the request must also pass adapter-node (512K), nginx (1m) and aiohttp
# (1 MiB) body limits, and JSON escaping grows the text by about a third
MAX_BYTES = 256 * 1024
SID_MIN, SID_MAX = 1_000_000, 1_999_999
FORBIDDEN = frozenset(
    {
        "lua",
        "luajit",
        "luaxform",
        "config",
        "bypass",
        "dataset",
        "datarep",
        "filestore",
    }
)


def split_options(body: str) -> list[str]:
    """Split the text between a rule's parentheses on ";" outside quotes. ValueError if a quote
    is left open or the text ends in a lone backslash."""
    options: list[str] = []
    current: list[str] = []
    quoted = escaped = False
    for ch in body:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            current.append(ch)
            escaped = True
        elif ch == '"':
            current.append(ch)
            quoted = not quoted
        elif ch == ";" and not quoted:
            options.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if quoted or escaped:
        raise ValueError("A quote is never closed.")
    tail = "".join(current).strip()
    if tail:
        raise ValueError('The last option must end with ";".')
    return options


def check_rule(line: str) -> tuple[str | None, int | None]:
    """(why the rule can't be used or None, its sid or None)."""
    head, paren, rest = line.partition("(")
    if head.split()[:1] != ["alert"]:
        return "Only alert rules can be used.", None
    if not paren or not rest.endswith(")"):
        return 'A rule needs its options in "( … )" on one line.', None
    try:
        options = split_options(rest[:-1])
    except ValueError as exc:
        return str(exc), None
    sids: list[str] = []
    for option in options:
        name, _, value = option.partition(":")
        name = name.strip().lower()
        if name in FORBIDDEN:
            return f'"{name}" can\'t be used in your own rules.', None
        if name == "sid":
            sids.append(value.strip())
    if len(sids) != 1:
        return "Each rule needs exactly one sid.", None
    if not sids[0].isdigit() or not SID_MIN <= int(sids[0]) <= SID_MAX:
        return f"The sid must be a number from {SID_MIN} to {SID_MAX}.", None
    return None, int(sids[0])


def validate(content: str) -> tuple[list[dict[str, Any]], int]:
    """(errors as [{"line": n or None, "message": ...}], number of rules)."""
    errors: list[dict[str, Any]] = []
    if len(content.encode("utf-8")) > MAX_BYTES:
        return [
            {"line": None, "message": f"Your rules are over {MAX_BYTES // 1024} KB."}
        ], 0
    seen: dict[int, int] = {}
    count = 0
    for number, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        count += 1
        message, sid = check_rule(line)
        if sid is not None and sid in seen:
            message = f"sid {sid} is already used on line {seen[sid]}."
        elif sid is not None:
            seen[sid] = number
        if message:
            errors.append({"line": number, "message": message})
    if count > MAX_RULES:
        errors.append(
            {
                "line": None,
                "message": f"That is {count} rules; the most is {MAX_RULES}.",
            }
        )
    return errors, count
