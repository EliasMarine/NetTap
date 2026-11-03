"""GET /api/pcap/download-file serves files inside the PCAP directory only."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from api.pcap import handle_pcap_download_file


def _download(pcap_dir: str, file: str) -> web.StreamResponse:
    request = MagicMock()
    request.query = {"file": file}
    request.app = {"pcap_search": SimpleNamespace(_pcap_dir=pcap_dir)}
    return asyncio.run(handle_pcap_download_file(request))


@pytest.fixture
def dirs(tmp_path):
    pcap_dir = tmp_path / "pcap"
    pcap_dir.mkdir()
    (pcap_dir / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1")
    sibling = tmp_path / "pcap-old"
    sibling.mkdir()
    (sibling / "other.pcap").write_bytes(b"x")
    (tmp_path / "secret.txt").write_text("secret")
    os.symlink(tmp_path / "secret.txt", pcap_dir / "link.pcap")
    return pcap_dir, tmp_path


def test_a_file_inside_is_served(dirs):
    pcap_dir, _ = dirs
    response = _download(str(pcap_dir), str(pcap_dir / "capture.pcap"))
    assert isinstance(response, web.FileResponse)


@pytest.mark.parametrize(
    "name",
    ["sibling", "dotdot", "symlink", "the directory itself"],
)
def test_paths_outside_are_refused(dirs, name):
    pcap_dir, tmp_path = dirs
    file = {
        "sibling": str(tmp_path / "pcap-old" / "other.pcap"),
        "dotdot": str(pcap_dir / ".." / "secret.txt"),
        "symlink": str(pcap_dir / "link.pcap"),
        "the directory itself": str(pcap_dir),
    }[name]
    response = _download(str(pcap_dir), file)
    assert response.status == 400
