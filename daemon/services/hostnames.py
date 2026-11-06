"""Host names as the drill-down pages match them (NET-160).

A name is canonical with one trailing dot stripped, in lower case. Records hold either form
in any case, so every filter matches `name` and `name.` with case-insensitive terms. Those
match whole values only on keyword fields: require_keyword fails the request when a field
is mapped as anything else, so a name is never counted with the wrong rule. For optional
fields, keyword_paths says which can be matched (directly or through `.keyword`) and which
can't, so a figure built on them can say it is partial instead of failing (NET-178).
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
# OLD CODE START — NET-178: the mapping read moved to _field_types, shared with keyword_paths
# def require_keyword(client: Any, fields: list[str], budget: Budget) -> None:
#     """QueryFailed ("name matching unavailable") unless every index maps `fields` as keyword."""
#     budget.check("checking the name fields")
#     try:
#         reply = client.indices.get_field_mapping(
#             fields=",".join(fields),
#             index=NETWORK_INDEX,
#             request_timeout=max(1.0, budget.remaining()),
#         )
#     except ConnectionTimeout as exc:
#         logger.warning("Reading the name field mappings ran out of time: %s", exc)
#         raise TooSlow("checking the name fields took too long") from exc
#     except OpenSearchException as exc:
#         logger.error("Failed to read the name field mappings: %s", exc)
#         raise QueryFailed("name matching unavailable: mappings unreadable") from exc
#     if not isinstance(reply, dict):
#         raise QueryFailed("name matching unavailable: malformed mapping reply")
#     for index_name, entry in reply.items():
#         for field, mapping in ((entry or {}).get("mappings") or {}).items():
#             leaf = field.rsplit(".", 1)[-1]
#             kind = ((mapping or {}).get("mapping") or {}).get(leaf, {}).get("type")
#             if kind != "keyword":
#                 raise QueryFailed(
#                     f"name matching unavailable: {field} is {kind or 'unmapped'} "
#                     f"in {index_name}, not keyword"
#                 )
# OLD CODE END
def _field_types(client: Any, fields: list[str], budget: Budget) -> dict:
    """{field: {index: its mapping parameters}} for each index that lists the field;
    {} as the parameters when an index lists it without a type."""
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
    types: dict = {}
    for index_name, entry in reply.items():
        for field, mapping in ((entry or {}).get("mappings") or {}).items():
            leaf = field.rsplit(".", 1)[-1]  # "keyword" for a multi-field f.keyword
            params = ((mapping or {}).get("mapping") or {}).get(leaf, {})
            types.setdefault(field, {})[index_name] = params
    return types


def require_keyword(client: Any, fields: list[str], budget: Budget) -> None:
    """QueryFailed ("name matching unavailable") unless every index maps `fields` as keyword."""
    for field, per_index in _field_types(client, fields, budget).items():
        for index_name, params in per_index.items():
            kind = params.get("type")
            if kind != "keyword":
                raise QueryFailed(
                    f"name matching unavailable: {field} is {kind or 'unmapped'} "
                    f"in {index_name}, not keyword"
                )


# A 253-character name plus the trailing dot name_match also tries
_LONGEST = MAX_NAME + 1


def _exact(per_index: dict) -> bool:
    """Mapped, and keyword keeping values of _LONGEST characters in every index that maps it."""
    return bool(per_index) and all(
        params.get("type") == "keyword"
        and isinstance(limit := params.get("ignore_above", _LONGEST), int)
        and limit >= _LONGEST
        for params in per_index.values()
    )


def keyword_paths(
    client: Any, fields: list[str], budget: Budget
) -> tuple[list[str], list[str]]:
    """(paths name_match can use, mapped fields it can't) for optional name fields.

    A field no index maps is in neither list: it holds no names. Otherwise the field
    itself when it matches exactly, else its `.keyword` subfield when that matches
    exactly in every index that maps the field, else the field is unmatched (a text
    field matches words, never a whole name).
    """
    types = _field_types(client, [*fields, *(f + ".keyword" for f in fields)], budget)
    matched: list[str] = []
    unmatched: list[str] = []
    for field in fields:
        own, sub = types.get(field, {}), types.get(field + ".keyword", {})
        if not own:
            continue
        if _exact(own):
            matched.append(field)
        elif _exact(sub) and own.keys() <= sub.keys():
            matched.append(field + ".keyword")
        else:
            logger.warning(
                "%s can't be matched to a whole name (mapped as %s); "
                "names held only there aren't counted",
                field,
                ", ".join(sorted({str(p) for p in own.values()})),
            )
            unmatched.append(field)
    return matched, unmatched
