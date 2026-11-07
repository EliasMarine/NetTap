"""Owner rules: the subset of Suricata rules an owner may add (NET-191 slice 3).

Detection only, read the way Suricata 8 reads a rule file (detect-engine-loader.c, detect-parse.c):
- lines end at LF only; Suricata joins a line ending in "\" to the next one, stops a line at a NUL
  and reads a file in 8 KiB pieces, so those characters and long lines are refused;
- a rule is exactly 7 header fields ("alert" first), then its options in "( … )";
- an option ends at every ";" without a backslash just before it. Quotes don't protect a ";".
Keywords that run code, change the engine or read or write files are refused. Each rule needs its
own sid in the owner range, which no rule source uses. Suricata's own test (-T) checks everything
else, and an analysis of the owner rules alone checks the keywords again as Suricata parsed them.
"""

import re
from typing import Any

MAX_RULES = 2000
# The plan said 1 MB; the request must also pass adapter-node (512K), nginx (1m) and aiohttp
# (1 MiB) body limits, and JSON escaping grows the text by about a third
MAX_BYTES = 256 * 1024
# Suricata reads a rule file line with fgets into 8,192 bytes: a longer line is cut, and the rest
# is read as a rule of its own
MAX_LINE_BYTES = 8190
SID_MIN, SID_MAX = 1_000_000, 1_999_999
# action, protocol, source, source port, direction, destination, destination port
HEADER_FIELDS = 7
# tls.store is Suricata's alias of tls_store; luajit and datajson aren't 8.0.7 keywords yet
FORBIDDEN = frozenset(
    {
        "lua",
        "luajit",
        "luaxform",
        "config",
        "bypass",
        "dataset",
        "datarep",
        "datajson",
        "filestore",
        "filemd5",
        "filesha1",
        "filesha256",
        "tls_store",
        "tls.store",
    }
)
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f\x85\u2028\u2029]")
_KEYWORD = re.compile(r"[a-z0-9_.-]+")  # every 8.0.7 keyword name has this shape
_SID = re.compile(r"[0-9]{1,7}")


def split_options(body: str) -> list[str]:
    """Split the text between a rule's parentheses as Suricata does: at each ";" that has no
    backslash just before it. ValueError if text follows the last ";"."""
    *options, tail = re.split(r"(?<!\\);", body)
    if tail.strip(" \t"):
        raise ValueError('The last option must end with ";".')
    return [option.strip(" \t") for option in options]


def check_rule(line: str) -> tuple[str | None, int | None]:
    """(why the rule can't be used or None, its sid or None). `line` has no surrounding spaces."""
    fields = re.split(r"[ \t]+", line, maxsplit=HEADER_FIELDS)
    if fields[0] != "alert":
        return "Only alert rules can be used.", None
    if len(fields) <= HEADER_FIELDS or not (
        fields[-1].startswith("(") and fields[-1].endswith(")")
    ):
        return (
            'A rule is "alert", 6 more header fields, then its options in "( … )". '
            "Lists in [ ] can't contain spaces.",
            None,
        )
    body = fields[-1][1:-1]
    if body.lstrip(" \t").startswith("("):
        return 'The options start with one "(".', None
    try:
        options = split_options(body)
    except ValueError as exc:
        return str(exc), None
    sids: list[str] = []
    for option in options:
        if not option:
            return 'An option is empty (";;").', None
        name, _, value = option.partition(":")
        name = name.strip(" \t").lower()
        if not _KEYWORD.fullmatch(name):
            return f'"{name[:40]}" is not an option name.', None
        if name in FORBIDDEN:
            return f'"{name}" can\'t be used in your own rules.', None
        if name == "sid":
            sids.append(value.strip(" \t"))
    if len(sids) != 1:
        return "Each rule needs exactly one sid.", None
    if not _SID.fullmatch(sids[0]) or not SID_MIN <= int(sids[0]) <= SID_MAX:
        return f"The sid must be a number from {SID_MIN} to {SID_MAX}.", None
    return None, int(sids[0])


def check_line(line: str) -> str | None:
    """Why Suricata would read this line differently than it looks, or None."""
    if _CONTROL.search(line):
        return "This line has a control character. Only tabs and LF line breaks can be used."
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        return f"This line is over {MAX_LINE_BYTES:,} bytes, the most Suricata reads as one rule."
    if line.rstrip(" \t").endswith("\\"):
        return 'A line can\'t end with "\\": Suricata would join it to the next line.'
    if line[:1] in (" ", "\t") and line.strip(" \t"):
        return "Start each line at the left edge: Suricata skips a line that starts with a space."
    return None


def rule_sids(content: str) -> set[int]:
    """The sids of `content`, which validate() has accepted."""
    lines = (raw.strip(" \t") for raw in content.split("\n"))
    return {check_rule(line)[1] for line in lines if line and not line.startswith("#")}


def validate(content: str) -> tuple[list[dict[str, Any]], int]:
    """(errors as [{"line": n or None, "message": ...}], number of rules)."""
    try:
        size = len(content.encode("utf-8"))
    except UnicodeEncodeError:  # a lone surrogate from JSON ("\ud800")
        return [
            {
                "line": None,
                "message": "Your rules contain text that isn't valid Unicode.",
            }
        ], 0
    if size > MAX_BYTES:
        return [
            {"line": None, "message": f"Your rules are over {MAX_BYTES // 1024} KB."}
        ], 0
    errors: list[dict[str, Any]] = []
    seen: dict[int, int] = {}
    count = 0
    for number, raw in enumerate(content.split("\n"), start=1):
        message = check_line(raw)
        line = raw.strip(" \t")
        sid = None
        if not message and line and not line.startswith("#"):
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
