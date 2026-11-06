"""Host names as the drill-down pages match them (NET-160).

A name is canonical with one trailing dot stripped, in lower case. Records hold either form
in any case, so every filter matches `name` and `name.` with case-insensitive terms. Those
match whole values only on keyword fields: require_keyword fails the request when a field
is mapped as anything else, so a name is never counted with the wrong rule.
"""

import logging
import re
from typing import Any

from opensearchpy import ConnectionTimeout, OpenSearchException

from storage.snapshot_search import NETWORK_INDEX, Budget, QueryFailed, TooSlow

logger = logging.getLogger("nettap.services.hostnames")

MAX_NAME = 253
_LABEL = re.compile(r"[a-z0-9_-]{1,63}")


def canonical_name(raw: Any) -> str | None:
    """`raw` lower-cased with one trailing dot stripped, or None if not an RFC 1123 host name."""
    if not isinstance(raw, str):
        return None
    name = (raw[:-1] if raw.endswith(".") else raw).lower()
    if not name or len(name) > MAX_NAME:
        return None
    return name if all(_LABEL.fullmatch(label) for label in name.split(".")) else None


def _term(field: str, value: str) -> dict:
    return {"term": {field: {"value": value, "case_insensitive": True}}}


def name_match(field: str, name: str) -> dict:
    """`field` equal to the canonical `name`, with or without a trailing dot, in any case."""
    return {
        "bool": {
            "should": [_term(field, name), _term(field, name + ".")],
            "minimum_should_match": 1,
        }
    }


# OLD CODE START — NET-160 review: no caller set index; a timeout read as a failure
# def require_keyword(
#     client: Any, fields: list[str], budget: Budget, index: str = NETWORK_INDEX
# ) -> None:
#     """QueryFailed ("name matching unavailable") unless every index maps `fields` as keyword."""
#     budget.check("checking the name fields")
#     try:
#         reply = client.indices.get_field_mapping(
#             fields=",".join(fields),
#             index=index,
#             request_timeout=max(1.0, budget.remaining()),
#         )
#     except OpenSearchException as exc:
#         logger.error("Failed to read the name field mappings: %s", exc)
#         raise QueryFailed("name matching unavailable: mappings unreadable") from exc
# OLD CODE END
def require_keyword(client: Any, fields: list[str], budget: Budget) -> None:
    """QueryFailed ("name matching unavailable") unless every index maps `fields` as keyword."""
    budget.check("checking the name fields")
    try:
        reply = client.indices.get_field_mapping(
            fields=",".join(fields),
            index=NETWORK_INDEX,
            request_timeout=max(1.0, budget.remaining()),
        )
    except ConnectionTimeout as exc:
        logger.warning("Reading the name field mappings ran out of time: %s", exc)
        raise TooSlow("checking the name fields took too long") from exc
    except OpenSearchException as exc:
        logger.error("Failed to read the name field mappings: %s", exc)
        raise QueryFailed("name matching unavailable: mappings unreadable") from exc
    if not isinstance(reply, dict):
        raise QueryFailed("name matching unavailable: malformed mapping reply")
    for index_name, entry in reply.items():
        for field, mapping in ((entry or {}).get("mappings") or {}).items():
            leaf = field.rsplit(".", 1)[-1]
            kind = ((mapping or {}).get("mapping") or {}).get(leaf, {}).get("type")
            if kind != "keyword":
                raise QueryFailed(
                    f"name matching unavailable: {field} is {kind or 'unmapped'} "
                    f"in {index_name}, not keyword"
                )
