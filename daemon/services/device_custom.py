"""
NetTap device customisation store: the owner's own name, icon or photo per device (NET-200).

Keyed by normalised MAC and kept on the daemon's data volume, outside the OpenSearch
device registry, so the registry's refresh loop (read, merge, write the whole doc) can
never drop an owner's edit.

Layout under the data dir:
    device_custom.json   {"version": 1, "devices": {MAC: {"name"?, "icon"?, "photo"?}}}
    device-pictures/     <12 hex MAC>-<16 hex sha256>.<png|jpg|webp>, immutable

A photo change writes the new content-named file, commits the metadata atomically, swaps
the in-memory copy, then deletes old-minus-new referenced files. A failure at any step
leaves the last committed state served; leftovers are orphans for the startup sweep, which
only runs when the metadata is valid (a damaged file must never cost the owner a photo).
"""

import base64
import binascii
import copy
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import unicodedata
from typing import Any

from services.capture_config import write_file_atomic
from services.device_registry import DeviceRegistry

logger = logging.getLogger("nettap.services.device_custom")

NAME_MAX = 64
PHOTO_MAX_BYTES = 256 * 1024
# All photos together; keeps an exported backup under the 16 MB body limits (PLAN size contract)
PHOTOS_MAX_TOTAL = 8 * 1024 * 1024
# The system's device-type icons (web/src/lib/components/ui/device-icon.ts)
ICONS = frozenset(
    {
        "laptop",
        "phone",
        "tablet",
        "tv",
        "nas",
        "gamepad",
        "camera",
        "speaker",
        "printer",
        "iot",
        "infra",
        "devices",
    }
)
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_MAC_RE = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
_FILE_RE = re.compile(r"^([0-9a-f]{12})-([0-9a-f]{16})\.(png|jpg|webp)$")
_TMP_PREFIX = ".photo-"
_ENTRY_KEYS = {"name", "icon", "photo"}

BAD_TYPE = "Pictures must be PNG, JPEG or WebP."
TOO_BIG = f"The picture is too large (the limit is {PHOTO_MAX_BYTES // 1024} KB)."
STORAGE_FULL = f"Picture storage is full ({PHOTOS_MAX_TOTAL // (1024 * 1024)} MB). Remove a picture first."


class StoreUnavailable(RuntimeError):
    """The metadata file exists but can't be trusted, so nothing may be written or exported."""


def normalize_mac(mac: Any) -> str:
    """The registry's MAC form (upper, colons, six octets), or ValueError."""
    if not isinstance(mac, str):
        raise ValueError("Not a valid MAC address.")
    norm = DeviceRegistry._normalize_mac(mac)
    if not _MAC_RE.match(norm):
        raise ValueError("Not a valid MAC address.")
    return norm


def clean_name(name: Any) -> str:
    """A device name as stored: NFC, trimmed, 1-64 characters, no control or format characters."""
    if not isinstance(name, str):
        raise ValueError("The name must be text.")
    cleaned = unicodedata.normalize("NFC", name).strip()
    if not cleaned:
        raise ValueError("The name can't be empty.")
    if len(cleaned) > NAME_MAX:
        raise ValueError(f"The name can be at most {NAME_MAX} characters.")
    # Cc: control characters; Cf: format characters such as bidi overrides that spoof text
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in cleaned):
        raise ValueError("The name can't contain control or formatting characters.")
    return cleaned


def sniff(data: bytes) -> str | None:
    """The image type from its first bytes, never from a declared type or extension."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_image(value: Any) -> tuple[bytes, str]:
    """(bytes, mime) from a data URL or bare base64; ValueError with a plain-English reason."""
    if not isinstance(value, str) or not value:
        raise ValueError("The picture must be a base64 image.")
    payload = value
    if value.startswith("data:"):
        head, sep, payload = value.partition(",")
        if not sep or not head.endswith(";base64"):
            raise ValueError("The picture must be a base64 image.")
    # base64 is 4/3 the size; refuse a huge string before decoding it
    if len(payload) > (PHOTO_MAX_BYTES * 4) // 3 + 4:
        raise ValueError(TOO_BIG)
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The picture must be a base64 image.") from None
    if len(data) > PHOTO_MAX_BYTES:
        raise ValueError(TOO_BIG)
    mime = sniff(data)
    if mime is None:
        raise ValueError(BAD_TYPE)
    return data, mime


def _photo_record(mac: str, data: bytes, mime: str) -> dict:
    """The metadata for a photo: its content-named file, type and size."""
    digest = hashlib.sha256(data).hexdigest()[:16]
    name = f"{mac.replace(':', '').lower()}-{digest}.{_EXT[mime]}"
    return {"file": name, "type": mime, "bytes": len(data)}


def _refs(devices: dict[str, dict]) -> set[str]:
    return {e["photo"]["file"] for e in devices.values() if "photo" in e}


def _validated(raw: Any) -> dict[str, dict]:
    """The devices map from parsed metadata, or ValueError on anything structurally wrong."""
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("unsupported or missing version")
    devices = raw.get("devices")
    if not isinstance(devices, dict):
        raise ValueError("'devices' is not an object")
    out: dict[str, dict] = {}
    for mac, entry in devices.items():
        if normalize_mac(mac) != mac:
            raise ValueError(f"{mac!r} is not a normalised MAC")
        if not isinstance(entry, dict) or not entry or not set(entry) <= _ENTRY_KEYS:
            raise ValueError(f"entry for {mac} is malformed")
        if "icon" in entry and "photo" in entry:
            raise ValueError(f"entry for {mac} has both an icon and a photo")
        if "name" in entry and clean_name(entry["name"]) != entry["name"]:
            raise ValueError(f"name for {mac} is not stored clean")
        if "icon" in entry and entry["icon"] not in ICONS:
            raise ValueError(f"icon for {mac} is unknown")
        if "photo" in entry:
            _check_photo_meta(mac, entry["photo"])
        out[mac] = copy.deepcopy(entry)
    return out


def _check_photo_meta(mac: str, photo: Any) -> None:
    if not isinstance(photo, dict):
        raise ValueError(f"photo for {mac} is malformed")
    match = _FILE_RE.match(str(photo.get("file", "")))
    if (
        not match
        or match.group(1) != mac.replace(":", "").lower()
        or _EXT.get(photo.get("type")) != match.group(3)
        or not isinstance(photo.get("bytes"), int)
        or isinstance(photo.get("bytes"), bool)
    ):
        raise ValueError(f"photo for {mac} is malformed")


class DeviceCustomStore:
    """Owner names, icons and photos, one entry per MAC. Thread-safe."""

    def __init__(self, root: str | None = None) -> None:
        root = root or os.environ.get("NETTAP_DATA_DIR", "/opt/nettap/data")
        self._meta_path = os.path.join(root, "device_custom.json")
        self._photo_dir = os.path.join(root, "device-pictures")
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}
        self._problem: str | None = None
        self._load()

    # ------------------------------------------------------------------
    # Load and sweep
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self._meta_path):
            self._sweep(set())
            return
        try:
            with open(self._meta_path, encoding="utf-8") as fh:
                self._devices = _validated(json.load(fh))
        except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
            self._problem = f"Device names file is unreadable: {self._meta_path} ({exc})"
            self._devices = {}
            logger.error("%s; names and pictures are off until it is fixed", self._problem)
            return
        self._sweep(_refs(self._devices))

    def _sweep(self, referenced: set[str]) -> None:
        """Delete unreferenced photo files and temp leftovers. Only call on valid metadata."""
        try:
            names = os.listdir(self._photo_dir)
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Couldn't list %s: %s", self._photo_dir, exc)
            return
        for name in names:
            orphan = _FILE_RE.match(name) and name not in referenced
            if orphan or name.startswith(_TMP_PREFIX):
                self._unlink(name)

    def _unlink(self, name: str) -> None:
        try:
            os.unlink(os.path.join(self._photo_dir, name))
            logger.info("Removed unused device picture %s", name)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Couldn't remove device picture %s: %s", name, exc)

    @property
    def healthy(self) -> bool:
        return self._problem is None

    def _require_healthy(self) -> None:
        if self._problem is not None:
            raise StoreUnavailable(self._problem)

    # ------------------------------------------------------------------
    # Commit (caller holds the lock)
    # ------------------------------------------------------------------

    def _write_photo(self, name: str, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._photo_dir, prefix=_TMP_PREFIX)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o644)
            # a same-named file holds the same bytes (the name is their hash), so this is harmless
            os.replace(tmp, os.path.join(self._photo_dir, name))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _commit(self, devices: dict[str, dict], files: dict[str, bytes]) -> None:
        self._require_healthy()
        os.makedirs(self._photo_dir, exist_ok=True)
        for name, data in files.items():
            self._write_photo(name, data)
        write_file_atomic(
            self._meta_path, json.dumps({"version": 1, "devices": devices}, indent=2)
        )
        stale = _refs(self._devices) - _refs(devices)
        self._devices = devices
        for name in stale:
            self._unlink(name)

    def _change(
        self,
        mac: str,
        update: dict,
        drop: tuple[str, ...],
        files: dict[str, bytes] | None = None,
    ) -> None:
        """Commit one entry with `update` merged in and `drop` keys removed."""
        with self._lock:
            self._require_healthy()
            if "photo" in update:
                others = sum(
                    e["photo"]["bytes"]
                    for m, e in self._devices.items()
                    if m != mac and "photo" in e
                )
                if others + update["photo"]["bytes"] > PHOTOS_MAX_TOTAL:
                    raise ValueError(STORAGE_FULL)
            entry = {
                k: v for k, v in self._devices.get(mac, {}).items() if k not in drop
            }
            entry.update(update)
            devices = {k: v for k, v in self._devices.items() if k != mac}
            if entry:
                devices[mac] = entry
            self._commit(devices, files or {})

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def set_name(self, mac: str, name: Any) -> None:
        mac, name = normalize_mac(mac), clean_name(name)
        self._change(mac, {"name": name}, ())

    def clear_name(self, mac: str) -> None:
        self._change(normalize_mac(mac), {}, ("name",))

    def set_icon(self, mac: str, icon: Any) -> None:
        mac = normalize_mac(mac)
        if icon not in ICONS:
            raise ValueError("Pick one of the built-in device icons.")
        self._change(mac, {"icon": icon}, ("photo",))

    def set_photo(self, mac: str, value: Any) -> None:
        mac = normalize_mac(mac)
        data, mime = decode_image(value)
        photo = _photo_record(mac, data, mime)
        self._change(mac, {"photo": photo}, ("icon", "photo"), {photo["file"]: data})

    def clear_picture(self, mac: str) -> None:
        self._change(normalize_mac(mac), {}, ("icon", "photo"))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get(self, mac: str) -> dict | None:
        mac = normalize_mac(mac)
        with self._lock:
            entry = self._devices.get(mac)
            return copy.deepcopy(entry) if entry else None

    def name_for(self, mac: Any) -> str | None:
        """The owner's name, or None (also for anything that isn't a MAC)."""
        try:
            mac = normalize_mac(mac)
        except ValueError:
            return None
        with self._lock:
            return self._devices.get(mac, {}).get("name")

    def names(self) -> dict[str, str]:
        with self._lock:
            return {m: e["name"] for m, e in self._devices.items() if "name" in e}

    def matching(self, query: str) -> list[str]:
        """MACs whose owner name contains `query`, ignoring case."""
        q = query.casefold()
        return [m for m, n in self.names().items() if q and q in n.casefold()]

    def owner_fields(self, mac: Any) -> dict[str, str | None]:
        """{custom_name, icon, picture} for a response row; all None when there is nothing."""
        empty: dict[str, str | None] = {"custom_name": None, "icon": None, "picture": None}
        try:
            mac = normalize_mac(mac)
        except ValueError:
            return empty
        with self._lock:
            entry = self._devices.get(mac)
        if not entry:
            return empty
        picture = None
        if "photo" in entry:
            digest = _FILE_RE.match(entry["photo"]["file"]).group(2)
            picture = f"/api/devices/registry/{mac}/picture?v={digest}"
        return {"custom_name": entry.get("name"), "icon": entry.get("icon"), "picture": picture}

    def present(self, row: dict) -> dict:
        """A copy of a response row (with "mac" and "hostname") showing the owner's name first.

        Presentation only: call it after any classification that reads the hostname.
        """
        owner = self.owner_fields(row.get("mac"))
        return {**row, **owner, "hostname": owner["custom_name"] or row.get("hostname")}

    def photo(self, mac: str) -> tuple[bytes, str, str] | None:
        """(bytes, mime, hash) of the committed photo, read as one snapshot; None if absent or damaged."""
        mac = normalize_mac(mac)
        with self._lock:
            meta = self._devices.get(mac, {}).get("photo")
            if not meta:
                return None
            return self._read_photo(mac, meta)

    def _read_photo(self, mac: str, meta: dict) -> tuple[bytes, str, str] | None:
        digest = _FILE_RE.match(meta["file"]).group(2)
        try:
            with open(os.path.join(self._photo_dir, meta["file"]), "rb") as fh:
                data = fh.read(PHOTO_MAX_BYTES + 1)
        except OSError as exc:
            logger.warning("Picture for %s is missing: %s", mac, exc)
            return None
        if hashlib.sha256(data).hexdigest()[:16] != digest:
            logger.warning("Picture for %s is damaged (%s)", mac, meta["file"])
            return None
        return data, meta["type"], digest

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def export(self) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        """(names, pictures) for a backup. Raises rather than hand back an incomplete one."""
        with self._lock:
            self._require_healthy()
            names: dict[str, str] = {}
            pictures: dict[str, dict[str, str]] = {}
            for mac, entry in self._devices.items():
                if "name" in entry:
                    names[mac] = entry["name"]
                if "icon" in entry:
                    pictures[mac] = {"icon": entry["icon"]}
                elif "photo" in entry:
                    got = self._read_photo(mac, entry["photo"])
                    if got is None:
                        raise ValueError(
                            f"Picture for {mac} is missing or damaged; reset it and export again."
                        )
                    data, mime, _ = got
                    pictures[mac] = {
                        "image": f"data:{mime};base64,{base64.b64encode(data).decode()}"
                    }
            return names, pictures

    def restore(self, names: Any = None, pictures: Any = None) -> None:
        """Replace each present section (None = leave it); all or nothing, ValueError lists problems."""
        new_names, errors = _restore_names(names)
        new_pictures, files, picture_errors = _restore_pictures(pictures)
        errors += picture_errors
        if errors:
            more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
            raise ValueError("; ".join(errors[:5]) + more)
        if names is None and pictures is None:
            return
        with self._lock:
            self._require_healthy()
            devices: dict[str, dict] = {}
            for mac in set(self._devices) | set(new_names or {}) | set(new_pictures or {}):
                entry = copy.deepcopy(self._devices.get(mac, {}))
                if new_names is not None:
                    entry.pop("name", None)
                    if mac in new_names:
                        entry["name"] = new_names[mac]
                if new_pictures is not None:
                    entry.pop("icon", None)
                    entry.pop("photo", None)
                    entry.update(new_pictures.get(mac, {}))
                if entry:
                    devices[mac] = entry
            self._commit(devices, files)


def _restore_names(names: Any) -> tuple[dict[str, str] | None, list[str]]:
    if names is None:
        return None, []
    if not isinstance(names, dict):
        return None, ["device_aliases must be an object of MAC → name"]
    out: dict[str, str] = {}
    errors: list[str] = []
    for mac, name in names.items():
        try:
            out[normalize_mac(mac)] = clean_name(name)
        except ValueError as exc:
            errors.append(f"name for {str(mac)[:32]}: {exc}")
    return out, errors


def _restore_pictures(
    pictures: Any,
) -> tuple[dict[str, dict] | None, dict[str, bytes], list[str]]:
    if pictures is None:
        return None, {}, []
    if not isinstance(pictures, dict):
        return None, {}, ["device_pictures must be an object of MAC → picture"]
    out: dict[str, dict] = {}
    files: dict[str, bytes] = {}
    errors: list[str] = []
    total = 0
    for raw_mac, value in pictures.items():
        label = str(raw_mac)[:32]
        try:
            mac = normalize_mac(raw_mac)
            if not isinstance(value, dict) or len(value) != 1:
                raise ValueError("needs exactly one of icon or image")
            if "icon" in value:
                if value["icon"] not in ICONS:
                    raise ValueError("unknown icon")
                out[mac] = {"icon": value["icon"]}
            elif "image" in value:
                data, mime = decode_image(value["image"])
                photo = _photo_record(mac, data, mime)
                files[photo["file"]] = data
                total += len(data)
                out[mac] = {"photo": photo}
            else:
                raise ValueError("needs exactly one of icon or image")
        except ValueError as exc:
            errors.append(f"picture for {label}: {exc}")
    if total > PHOTOS_MAX_TOTAL:
        errors.append(STORAGE_FULL)
    return out, files, errors
