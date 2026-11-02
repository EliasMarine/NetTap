"""Daemon queries must use Malcolm's field names, never .keyword sub-fields (Chain 24).

The .keyword sub-fields only existed while malcolm_template's index pattern was
a placeholder and every index was dynamically mapped. With Malcolm's mapping the
fields are keyword/ip/long with no .keyword, so a query on one silently matches
nothing (aggregations, terms filters) or fails (sorts).
"""

import re
from pathlib import Path

DAEMON = Path(__file__).resolve().parent.parent
# A quoted field ending in .keyword, in Python or in a Painless script string
_KEYWORD_FIELD = re.compile(r"""\w\.keyword["']""")


def test_no_keyword_field_names_in_queries():
    offenders = []
    for folder in ("api", "services", "storage"):
        for path in sorted((DAEMON / folder).rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                if _KEYWORD_FIELD.search(line):
                    offenders.append(
                        f"{path.relative_to(DAEMON)}:{number}: {line.strip()}"
                    )
    assert not offenders, "Use Malcolm field names, not .keyword:\n" + "\n".join(
        offenders
    )
