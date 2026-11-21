"""
NET-344: one encoding for a config backup, fitted under the restore limit (plan §2.1, §2.3).

``encode`` is compact JSON in raw UTF-8 with a lone surrogate escaped, per character, so a part's
size never depends on the rest. ``fit`` measures by streaming that encoding and, when the whole
config doesn't fit, leaves out the oldest alert acknowledgements, never an owner setting:
``BackupTooLarge`` when even none of them fit.
"""

import json
import logging
import math
import re
from collections.abc import Iterable, Iterator
from datetime import datetime
from itertools import islice
from typing import Any

from services.backup_checks import _ACKS, LEFT_OUT, _invalid, _labels

logger = logging.getLogger("nettap.services.backup_fit")

# aiohttp refuses a body whose length is >= client_max_size (MAX_REQUEST_BYTES), so a backup
# restores only when it is shorter than this; nginx and adapter-node accept 16 MiB itself
RESTORE_LIMIT_BYTES = 16 * 1024 * 1024
_ENCODER = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False, allow_nan=False)
# A str holds a surrogate only alone (a pair is one code point), and strict UTF-8 refuses it
_SURROGATE = re.compile("[\ud800-\udfff]")

# What the owner can do when a section makes the backup too big (plan §2.3 step 4)
_TOO_LARGE_ADVICE = {
    "alert_suppressions": "NetTap can't remove suppressions yet (NET-346).",
    "device_pictures": "Remove some device pictures, then export again.",
    "notification_rules": "Remove some in Settings › Notifications, then export again.",
}


def _escape_surrogates(text: str) -> str:
    return _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


def encode(obj: Any) -> bytes:
    """The backup encoding: compact JSON, raw UTF-8, a lone surrogate as its \\uXXXX escape.

    The escape is per character, so a part's size never depends on the rest of the file.
    ValueError on NaN or Infinity.
    """
    return _escape_surrogates(_ENCODER.encode(obj)).encode("utf-8")


def _chunks(obj: Any) -> Iterator[bytes]:
    """encode(obj) in pieces, so the whole document is never one string."""
    for chunk in _ENCODER.iterencode(obj):
        yield _escape_surrogates(chunk).encode("utf-8")


def _size(obj: Any) -> int:
    return sum(len(chunk) for chunk in _chunks(obj))


def _entry_size(key: str, value: Any) -> int:
    """`"key":value` in an object."""
    return len(encode(key)) + 1 + len(encode(value))


def _object_size(members: Iterable[int]) -> int:
    """`{a,b,…}` from its members' sizes: two braces and a comma between each pair."""
    total = count = 0
    for size in members:
        total += size
        count += 1
    return 2 + total + max(count - 1, 0)


def _mb(size: int) -> str:
    # decimal MB, as NetTap shows every size (NET-166): the smallest refused size reads 16.8 MB
    return f"{size / 1_000_000:.1f} MB"


class BackupTooLarge(Exception):
    """Even with no alert acknowledgements the backup reaches the restore limit, and no owner
    setting is ever left out (plan §2.3 step 4). The message is written for the owner."""

    def __init__(self, size: int, sizes: dict[str, int]) -> None:
        """``size``: the smallest body possible (no acknowledgements); ``sizes``: each section's."""
        others = {name: n for name, n in sizes.items() if name != _ACKS}
        largest = max(others, key=others.__getitem__, default="")
        super().__init__(
            f"This backup would be {_mb(size)}, over the 16 MB restore limit. The largest "
            f"part is {_labels([largest])} ({_mb(others.get(largest, 0))}). "
            + _TOO_LARGE_ADVICE.get(largest, "The daemon log lists each part's size.")
        )


def _reason_as_text(entry: Any) -> Any:
    """A suppression with its reason as text: reasons are shown, never matched."""
    if not isinstance(entry, dict) or isinstance(entry.get("reason", ""), str):
        return entry
    reason = entry["reason"]
    return {**entry, "reason": "" if reason is None else str(reason)}


def _reasons_as_text(entries: Any) -> Any:
    return (
        [_reason_as_text(e) for e in entries] if isinstance(entries, list) else entries
    )


def _normalised(config: dict) -> dict:
    """The export copy: suppression reasons as text (plan §2.3 step 1), no stale left-out count."""
    sections = config.get("sections", {})
    meta = {k: v for k, v in config.get("metadata", {}).items() if k != LEFT_OUT}
    supp = sections.get("alert_suppressions")
    if isinstance(supp, dict):
        lists = {
            k: _reasons_as_text(supp[k])
            for k in ("global", "false_positives")
            if k in supp
        }
        per_device = supp.get("per_device")
        if isinstance(per_device, dict):
            lists["per_device"] = {
                ip: _reasons_as_text(v) for ip, v in per_device.items()
            }
        sections = {**sections, "alert_suppressions": {**supp, **lists}}
    return {**config, "metadata": meta, "sections": sections}


def _instant(entry: Any) -> float:
    """acknowledged_at as a UTC instant; missing, unparsable or zone-less counts as oldest."""
    try:
        when = datetime.fromisoformat(entry["acknowledged_at"].replace("Z", "+00:00"))
        return when.timestamp() if when.tzinfo else -math.inf
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return -math.inf


def _newest_first(acks: dict) -> list:
    """Alert IDs newest first by instant, never by string (+01:00 against Z); ties by ID ascending."""
    ids = sorted(acks)
    ids.sort(
        key=lambda key: _instant(acks[key]), reverse=True
    )  # stable: ties stay ascending
    return ids


def _section_sizes(sections: dict) -> dict[str, int]:
    """Each section's encoded size, streamed; BackupRefused names one JSON can't carry."""
    sizes: dict[str, int] = {}
    for name, value in sections.items():
        try:
            if name == _ACKS and isinstance(value, dict):
                sizes[name] = _object_size(_entry_size(k, v) for k, v in value.items())
            else:
                sizes[name] = _size(value)
        except ValueError as exc:  # NaN or Infinity (allow_nan=False)
            logger.error(
                "Backup refused: %s holds a value JSON can't carry: %s", name, exc
            )
            raise _invalid([name]) from exc
    return sizes


def _too_large(size: int, sizes: dict[str, int]) -> BackupTooLarge:
    logger.warning(
        "Backup refused: %d bytes with no acknowledgements, over the %d-byte restore limit; "
        "section sizes: %s",
        size,
        RESTORE_LIMIT_BYTES,
        sizes,
    )
    return BackupTooLarge(size, sizes)


def _fit(config: dict) -> tuple[dict, int, int]:
    """(the copy to export, its exact encoded size, acknowledgements left out). See fit()."""
    config = _normalised(config)
    sections, meta = config["sections"], config["metadata"]
    sizes = _section_sizes(sections)
    acks = sections.get(_ACKS)
    acks = acks if isinstance(acks, dict) else {}
    # every section whole, the acknowledgements as {}; the sections object, then the rest
    members = {name: len(encode(name)) + 1 + n for name, n in sizes.items()}
    if acks:
        members[_ACKS] -= sizes[_ACKS] - 2
    base = _size({**config, "sections": {}}) - 2 + _object_size(members.values())
    full = base + (sizes[_ACKS] - 2 if acks else 0)
    if full < RESTORE_LIMIT_BYTES:
        return config, full, 0
    if not acks:
        raise _too_large(full, sizes)

    # The newest prefix that fits with its commas and `"acknowledgements_left_out":<count>`.
    # Each entry adds more than a digit can take away, so the total only grows.
    key_size = _size({**meta, LEFT_OUT: 0}) - _size(meta) - 1  # the key and its comma
    ids = _newest_first(acks)
    total, used, kept = len(acks), 0, 0
    for key in ids:
        cost = _entry_size(key, acks[key]) + (1 if kept else 0)
        left = total - kept - 1
        if base + used + cost + key_size + len(str(left)) >= RESTORE_LIMIT_BYTES:
            break
        used += cost
        kept += 1
    left = total - kept
    size = base + used + key_size + len(str(left))
    if size >= RESTORE_LIMIT_BYTES:  # not even one acknowledgement fits
        raise _too_large(size, sizes)
    logger.info(
        "Backup fitted to %d bytes: the %d oldest of %d alert acknowledgements left out",
        size,
        left,
        total,
    )
    fitted = {
        **config,
        "metadata": {**meta, LEFT_OUT: left},
        "sections": {**sections, _ACKS: {key: acks[key] for key in islice(ids, kept)}},
    }
    return fitted, size, left


def _encode_exact(obj: dict, size: int) -> bytearray:
    """obj encoded once, into a buffer of the measured size: a bytearray, so the body is never
    copied (fit's workspace stays under twice the limit)."""
    body = bytearray(size)
    pos = 0
    for chunk in _chunks(obj):
        end = pos + len(chunk)
        if end > size:
            raise AssertionError(f"Backup encoding passed its measured {size} bytes")
        body[pos:end] = chunk
        pos = end
    if pos != size or size >= RESTORE_LIMIT_BYTES:
        raise AssertionError(f"Backup encoding is {pos} bytes, measured {size}")
    return body


def fit(config: dict) -> tuple[bytearray, int]:
    """The backup's bytes (under RESTORE_LIMIT_BYTES) and how many acknowledgements it leaves out.

    Sizes are measured by streaming the encoding, never by building the file. When the whole
    config doesn't fit, the newest acknowledgements that do are kept (by UTC instant; zone-less,
    missing or unparsable times count as oldest; ties by alert ID) and the count of the rest goes
    in the metadata. Every other section is kept whole: BackupTooLarge when even no
    acknowledgements don't fit, BackupRefused for a value JSON can't carry. The input is never
    changed; suppression reasons that aren't text become text in the copy.
    """
    fitted, size, left_out = _fit(config)
    return _encode_exact(fitted, size), left_out
