"""
NetTap device details: the owner's watch time, group, owner and notes per device (F2, NET-320).

Kept in its own file beside device_custom.json, never inside it: that store's loader refuses
unknown keys, so new keys there would make a rolled-back daemon lose every name and picture.

    device_details.json  {"version": 1, "devices": {MAC: {"watch_after_min"?, "group"?, "owner"?, "notes"?}}}

One compact UTF-8 format is written, budgeted and read back, so a write that fits always
reopens. A file that can't be trusted latches the store off until the daemon restarts.
"""

import copy
import json
import logging
import os
import re
import threading
import unicodedata
from typing import Any

from services.capture_config import write_file_atomic
from services.device_custom import DEVICES_MAX, StoreUnavailable

logger = logging.getLogger("nettap.services.device_details")

FIELDS = ("watch_after_min", "group", "owner", "notes")
WATCH_CHOICES = (15, 30, 60, 240, 1440)
# the budget #5 (watched devices) is planned for
WATCH_MAX = 50
TEXT_MAX = {"group": 32, "owner": 64, "notes": 1000}
# the file's exact bytes; keeps F2's share of a backup under 768 KiB as the browser saves it
DETAILS_MAX_BYTES = 512 * 1024
PROBLEMS_MAX = 5
EMPTY: dict[str, Any] = dict.fromkeys(FIELDS)

# six hex pairs, one separator throughout; fullmatch so "…:FF:00" or "…:FF:" never edits "…:FF"
_STRICT_MAC = re.compile(r"[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}")
_CANON_MAC = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
# control, format (bidi overrides), surrogate, line and paragraph separators
_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_LABEL = {"group": "The group", "owner": "The owner", "notes": "Notes"}

BAD_MAC = "Not a valid MAC address."
NO_FIELDS = "Send at least one of watch_after_min, group, owner or notes."
UNKNOWN_FIELD = "Only watch_after_min, group, owner and notes can be set."
BAD_WATCH = "Pick 15, 30, 60, 240 or 1440 minutes."
TOO_MANY = f"Device details are limited to {DEVICES_MAX:,} devices. Remove some first."
WATCH_FULL = f"At most {WATCH_MAX} devices can be watched. Stop watching one first."
TOO_BIG = f"Device details are full ({DETAILS_MAX_BYTES // 1024} KB). Shorten or remove some notes first."
UNREADABLE = "Device details can't be saved: their file is unreadable."


def strict_mac(raw: Any) -> str:
    """AA:BB:CC:DD:EE:FF from exactly six hex pairs (":" or "-"), or ValueError. Never truncates."""
    if not isinstance(raw, str) or not _STRICT_MAC.fullmatch(raw):
        raise ValueError(BAD_MAC)
    return raw.upper().replace("-", ":")


def clean_field(key: str, value: Any) -> Any:
    """The stored form of one field, None for "clear"; ValueError with a plain-English reason."""
    if value is None:
        return None
    if key == "watch_after_min":
        # type() and not isinstance(): True is an int
        if type(value) is not int or value not in WATCH_CHOICES:
            raise ValueError(BAD_WATCH)
        return value
    label = _LABEL[key]
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    # before trimming, so "\n" is refused rather than read as "clear"
    if any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in value):
        raise ValueError(
            f"{label} can't contain line breaks, control or formatting characters."
        )
    cleaned = unicodedata.normalize("NFC", value).strip()
    if len(cleaned) > TEXT_MAX[key]:
        raise ValueError(f"{label} can be at most {TEXT_MAX[key]:,} characters.")
    return cleaned or None


def encode(devices: dict[str, dict]) -> bytes:
    """The file's exact bytes: the one format that is written, budgeted and read back."""
    return json.dumps(
        {"version": 1, "devices": devices},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _count_problem(devices: dict[str, dict]) -> str | None:
    if len(devices) > DEVICES_MAX:
        return TOO_MANY
    if sum("watch_after_min" in e for e in devices.values()) > WATCH_MAX:
        return WATCH_FULL
    return None


def _entry_problem(mac: Any, entry: Any) -> str | None:
    if not isinstance(mac, str) or not _CANON_MAC.fullmatch(mac):
        shown = repr(mac)[:40]
        return f"{shown} is not a MAC address written as AA:BB:CC:DD:EE:FF."
    if not isinstance(entry, dict) or not entry:
        return f"Device details for {mac} are malformed."
    if not set(entry) <= set(FIELDS):
        return f"Device details for {mac} have an unknown field."
    for key, value in entry.items():
        try:
            if value is None or clean_field(key, value) != value:
                return f"Device details for {mac}: {key} is not stored clean."
        except ValueError as exc:
            return f"Device details for {mac}: {exc}"
    return None


def problems(devices: Any) -> list[str]:
    """Why a devices map can't be stored or restored: at most PROBLEMS_MAX reasons, [] if none."""
    if not isinstance(devices, dict):
        return ["Device details must be an object keyed by MAC address."]
    reasons: list[str] = []
    for mac, entry in devices.items():
        reason = _entry_problem(mac, entry)
        if reason:
            reasons.append(reason)
            if len(reasons) >= PROBLEMS_MAX:
                return reasons
    if reasons:
        return reasons
    reason = _count_problem(devices)
    if reason is None and len(encode(devices)) > DETAILS_MAX_BYTES:
        reason = TOO_BIG
    return [reason] if reason else []


def _validated(raw: Any) -> dict[str, dict]:
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("unsupported or missing version")
    reasons = problems(raw.get("devices"))
    if reasons:
        raise ValueError(reasons[0])
    return raw["devices"]


def _snapshot(entry: dict | None) -> dict[str, Any]:
    return {**EMPTY, **(entry or {})}


class DeviceDetailsStore:
    """Watch time, group, owner and notes, one entry per MAC. Thread-safe."""

    def __init__(self, root: str | None = None) -> None:
        self._root = root or os.environ.get("NETTAP_DATA_DIR", "/opt/nettap/data")
        self._path = os.path.join(self._root, "device_details.json")
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}
        self._problem: str | None = None
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "rb") as fh:
                data = fh.read(DETAILS_MAX_BYTES + 1)
        except FileNotFoundError:
            return
        except OSError as exc:  # a directory, no permission, an I/O error
            self._damaged(exc)
            return
        try:
            if len(data) > DETAILS_MAX_BYTES:
                raise ValueError(f"larger than {DETAILS_MAX_BYTES} bytes")
            self._devices = _validated(json.loads(data.decode("utf-8")))
        # JSONDecodeError and UnicodeDecodeError are ValueErrors; deep nesting is RecursionError
        except (ValueError, RecursionError) as exc:
            self._damaged(exc)

    def _damaged(self, exc: BaseException) -> None:
        self._problem = f"Device details file is unreadable: {self._path} ({exc})"
        self._devices = {}
        logger.error(
            "%s; to recover, move it aside, restart the daemon, then restore a backup "
            "or set the details again",
            self._problem,
        )

    @property
    def healthy(self) -> bool:
        return self._problem is None

    def _require_healthy(self) -> None:
        if self._problem is not None:
            raise StoreUnavailable(self._problem)

    def _commit(self, devices: dict[str, dict], data: bytes) -> None:
        """Write then swap; the caller holds the lock. An OSError leaves both as they were."""
        # write_file_atomic's mkstemp needs the directory; nothing else creates it before a first write
        os.makedirs(self._root, exist_ok=True)
        # the owner's own words: 0600, the roadmap's state-file rule
        write_file_atomic(
            self._path, data.decode("utf-8"), mode=0o600, encoding="utf-8"
        )
        self._devices = devices

    def _put(self, mac: str, entry: dict) -> dict[str, Any]:
        devices = {m: e for m, e in self._devices.items() if m != mac}
        if entry:
            devices[mac] = entry
        if devices != self._devices:
            reason = _count_problem(devices)
            if reason:
                raise ValueError(reason)
            data = encode(devices)
            if len(data) > DETAILS_MAX_BYTES:
                raise ValueError(TOO_BIG)
            self._commit(devices, data)
        return _snapshot(self._devices.get(mac))

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def update(self, mac: Any, changes: Any) -> dict[str, Any]:
        """Merge `changes` (null or "" clears a field); returns the committed four fields."""
        mac = strict_mac(mac)
        if not isinstance(changes, dict) or not changes:
            raise ValueError(NO_FIELDS)
        if not set(changes) <= set(FIELDS):
            raise ValueError(UNKNOWN_FIELD)
        cleaned = {k: clean_field(k, v) for k, v in changes.items()}
        with self._lock:
            self._require_healthy()
            merged = {**self._devices.get(mac, {}), **cleaned}
            return self._put(mac, {k: v for k, v in merged.items() if v is not None})

    def clear(self, mac: Any) -> dict[str, Any]:
        mac = strict_mac(mac)
        with self._lock:
            self._require_healthy()
            return self._put(mac, {})

    # ------------------------------------------------------------------
    # Reads (never raise: a bad MAC or a damaged file reads as nothing set)
    # ------------------------------------------------------------------

    def get(self, mac: Any) -> dict[str, Any]:
        """All four fields from one revision, each None when unset."""
        try:
            mac = strict_mac(mac)
        except ValueError:
            return dict(EMPTY)
        with self._lock:
            return _snapshot(self._devices.get(mac))

    def row_fields(self, mac: Any) -> dict[str, Any]:
        """{group, owner, watch_after_min} for list rows; notes stay on the device pages."""
        return {k: v for k, v in self.get(mac).items() if k != "notes"}

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def export(self) -> dict[str, dict]:
        """{MAC: entry}; raises rather than hand back an incomplete backup."""
        with self._lock:
            self._require_healthy()
            return copy.deepcopy(self._devices)

    def restore(self, section: Any) -> None:
        """Replace the whole set; ValueError lists the problems and nothing is written."""
        reasons = problems(section)
        if reasons:
            raise ValueError("; ".join(reasons))
        devices = copy.deepcopy(section)
        with self._lock:
            self._require_healthy()
            if devices != self._devices:
                self._commit(devices, encode(devices))
