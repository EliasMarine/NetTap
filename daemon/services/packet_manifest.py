"""The search manifest the page sends back for a packet's detail or a download (NET-188).

The manifest names the window, the capture files the search read (with their size
and mtime then) and each packet's identity. Nothing is stored on the server, so a
re-read checks the manifest against the files on disk now (admission), and every
packet it reads against its identity. A forged manifest can only ask for a window
the same user could search.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from services.capture_index import CAPTURE_EXTENSIONS, CONTAINER_ROOT
from services.packet_parse import EPOCH, MD5, Frame, epoch_ns

MAX_WINDOW_NS = 30 * 60 * 1_000_000_000
MAX_FILES = 64
MAX_BYTES = 3_000_000_000
MAX_FRAMES = 1000
MAX_FILTER = 500
CHANGED = (
    "The capture files behind this search have changed (old captures are deleted "
    "to free space). Run the search again."
)


class PacketError(Exception):
    """A request the packet reader can't serve; `status` is the HTTP status."""

    def __init__(self, status: int, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class ManifestFile:
    id: str
    size: int
    mtime_ns: int
    recent: bool

    @property
    def container_path(self) -> str:
        return f"{CONTAINER_ROOT}/{self.id}"


@dataclass(frozen=True)
class Manifest:
    start: str
    end: str
    filter: str
    files: tuple[ManifestFile, ...]
    frames: tuple[Frame, ...]

    def frame(self, n: int) -> Frame:
        for f in self.frames:
            if f.n == n:
                return f
        raise PacketError(400, "That packet isn't part of this search.")


def _bad(what: str) -> PacketError:
    return PacketError(400, f"The search details sent back are not valid ({what}).")


def check_window(start: str, end: str) -> tuple[int, int]:
    if not (isinstance(start, str) and isinstance(end, str)):
        raise _bad("window")
    if not (EPOCH.match(start) and EPOCH.match(end)):
        raise _bad("window")
    a, b = epoch_ns(start), epoch_ns(end)
    if a >= b or b - a > MAX_WINDOW_NS:
        raise _bad("window")
    return a, b


def valid_file_id(file_id: object) -> bool:
    if not isinstance(file_id, str) or not 0 < len(file_id) <= 1024:
        return False
    parts = file_id.split("/")
    return (
        not file_id.startswith("/")
        and all(p not in ("", ".", "..") for p in parts)
        and not any(c in file_id for c in "\x00\r\n\\")
        and file_id.lower().endswith(CAPTURE_EXTENSIONS)
    )


def _int(value: object, what: str) -> int:
    if isinstance(value, bool):
        raise _bad(what)
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():  # not "²"
        return int(value)
    raise _bad(what)


def parse_manifest(obj: object) -> Manifest:
    """Shape checks only; a malformed manifest is a 400."""
    if not isinstance(obj, dict):
        raise _bad("not an object")
    start, end = obj.get("from"), obj.get("to")
    check_window(start, end)  # type: ignore[arg-type]
    filt = obj.get("filter", "")
    if not isinstance(filt, str) or len(filt) > MAX_FILTER:
        raise _bad("filter")
    raw_files, raw_frames = obj.get("files"), obj.get("frames")
    if not isinstance(raw_files, list) or not 0 < len(raw_files) <= MAX_FILES:
        raise _bad("files")
    if not isinstance(raw_frames, list) or not 0 < len(raw_frames) <= MAX_FRAMES:
        raise _bad("frames")
    files = []
    for f in raw_files:
        if not isinstance(f, dict) or not valid_file_id(f.get("id")):
            raise _bad("file id")
        if not isinstance(f.get("recent", False), bool):
            raise _bad("file")
        files.append(
            ManifestFile(
                f["id"],
                _int(f.get("size"), "file size"),
                _int(f.get("mtime_ns"), "file time"),
                f.get("recent", False),
            )
        )
    if len({f.id for f in files}) != len(files):
        raise _bad("repeated file")
    frames = []
    for fr in raw_frames:
        if not isinstance(fr, dict):
            raise _bad("frame")
        n, t, md5 = _int(fr.get("n"), "frame"), fr.get("t"), fr.get("md5")
        if n < 1 or not isinstance(t, str) or not EPOCH.match(t):
            raise _bad("frame")
        if not isinstance(md5, str) or not MD5.match(md5):
            raise _bad("frame")
        frames.append(Frame(n, t, _int(fr.get("cap_len"), "frame"), md5))
    if any(b.n <= a.n for a, b in zip(frames, frames[1:])):
        raise _bad("frame order")
    return Manifest(start, end, filt, tuple(files), tuple(frames))


def admit(manifest: Manifest, root: str) -> list[str]:
    """Check the manifest's own files on disk now; return their container paths.

    A file finished at search time must be unchanged. A file that was still being
    written may have grown. The budget is checked on the sizes on disk now, so a
    manifest can't understate them. Any difference is a 409.
    """
    real_root = os.path.realpath(root)
    total = 0
    for f in manifest.files:
        path = os.path.join(root, f.id)
        if os.path.islink(path) or not os.path.realpath(path).startswith(
            real_root + os.sep
        ):
            raise PacketError(409, CHANGED)
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            raise PacketError(409, CHANGED) from None
        if not stat.S_ISREG(st.st_mode):
            raise PacketError(409, CHANGED)
        if f.recent:
            if st.st_size < f.size:
                raise PacketError(409, CHANGED)
        elif st.st_size != f.size or st.st_mtime_ns != f.mtime_ns:
            raise PacketError(409, CHANGED)
        total += st.st_size
    if total > MAX_BYTES:
        raise PacketError(409, CHANGED)
    return [f.container_path for f in manifest.files]
