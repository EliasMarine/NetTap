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


# A byte sum over Zeek's payload-only client/server.bytes (dashboard accuracy #13)
_PAYLOAD_BYTES_SUM = re.compile(
    r"""doc\['(client|server)\.bytes'\]|"field": "(client|server)\.bytes\""""
)


def test_byte_totals_use_source_and_destination_bytes():
    """Every byte total sums source/destination.bytes, so pages agree.

    Malcolm maps Zeek orig_ip_bytes/resp_ip_bytes (on the wire) to
    source/destination.bytes and orig_bytes/resp_bytes (payload only) to
    client/server.bytes. Mixing them made the summary, bandwidth and top-talker
    totals disagree.
    """
    offenders = []
    for folder in ("api", "services"):
        for path in sorted((DAEMON / folder).rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                if _PAYLOAD_BYTES_SUM.search(line):
                    offenders.append(
                        f"{path.relative_to(DAEMON)}:{number}: {line.strip()}"
                    )
    assert not offenders, "Sum source/destination.bytes:\n" + "\n".join(offenders)
