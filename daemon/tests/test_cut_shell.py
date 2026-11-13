"""The real `cut()` shell (packet_search._CUT) with Wireshark's own tools (NET-188).

The service tests replace the container, so this is the only test that runs the
shell function itself: the "cut:" route through editcap and a FIFO, the stage
reports, and the clean-up. It runs where mergecap, editcap and capinfos are
installed (a developer's machine with Wireshark); elsewhere it is skipped.

TShark 4.0.17's mergecap (the G11's) stops merging every file at a partly written
packet; newer ones carry on, so this can't show that loss. It shows the route that
avoids it, and that the daemon's check rejects a damaged file editcap waved through.
"""

import glob
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from services import packet_search as ps
from services.container_exec import ExecResult

TOOLS = ("mergecap", "editcap", "capinfos")
pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in TOOLS), reason="needs Wireshark's tools"
)

SYNTHETIC = Path(__file__).parent / "fixtures" / "packets" / "synthetic.pcap"
PACKETS = 6  # in synthetic.pcap
# The window cut, then a count of what it passed on.
JOB = ps._CUT + 'from="$1"; to="$2"; shift 2\ncut "" "$@" | capinfos -c -T -r -\n'


def run(*paths: str) -> tuple[int | None, dict[str, int], str]:
    """(packets out, stage statuses, stderr) for `cut` over `paths`."""
    p = subprocess.run(
        ["sh", "-c", JOB, "_", "1600000000", "1800000000", *paths],
        env={**os.environ, "NT": "#nt-test"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    statuses = {
        k: int(v)
        for k, v in re.findall(r"^#nt-test status (\S+) (\d+)$", p.stderr, re.M)
    }
    counts = re.findall(r"^-\t(\d+)$", p.stdout, re.M)
    return (int(counts[0]) if counts else None), statuses, p.stderr


def cut_short_copy(tmp_path: Path) -> str:
    """synthetic.pcap with its last packet only partly written."""
    out = tmp_path / "cut.pcap"
    out.write_bytes(SYNTHETIC.read_bytes()[:-5])
    return str(out)


def damaged_copy(tmp_path: Path) -> str:
    """synthetic.pcap with its 2nd record claiming an impossible length."""
    data = bytearray(SYNTHETIC.read_bytes())
    second = 24 + 16 + struct.unpack("<I", data[32:36])[0]
    data[second + 8 : second + 12] = struct.pack("<I", 0x7FFFFFFF)
    out = tmp_path / "damaged.pcap"
    out.write_bytes(bytes(data))
    return str(out)


def judged(statuses: dict[str, int], stderr: str, cuts: int) -> bool:
    return ps.cut_ok(ExecResult(b"", stderr, statuses, 0, False, 1, 0.1), cuts)


def test_a_cut_short_file_through_editcap_keeps_every_other_file(tmp_path):
    before = set(glob.glob("/tmp/nt-*"))
    count, statuses, stderr = run(f"cut:{cut_short_copy(tmp_path)}", str(SYNTHETIC))
    # every complete packet of the cut file, and all of the whole one
    assert count == (PACKETS - 1) + PACKETS
    assert statuses == {"pre-0": 0, "mergecap": 0, "editcap": 0}
    assert judged(statuses, stderr, cuts=1)
    assert set(glob.glob("/tmp/nt-*")) == before  # its FIFO was removed


def test_a_damaged_file_is_not_taken_for_a_cut_short_one(tmp_path):
    count, statuses, stderr = run(f"cut:{damaged_copy(tmp_path)}", str(SYNTHETIC))
    assert statuses.get("pre-0") == 0  # editcap exits 0 on damage too
    assert count is not None and count < 2 * PACKETS  # it stopped at the damage
    assert not judged(statuses, stderr, cuts=1)  # and the daemon won't call it whole


def test_files_without_cut_go_straight_to_mergecap(tmp_path):
    count, statuses, stderr = run(str(SYNTHETIC), str(SYNTHETIC))
    assert count == 2 * PACKETS
    assert statuses == {"mergecap": 0, "editcap": 0}
    assert judged(statuses, stderr, cuts=0)


needs_tshark = pytest.mark.skipif(not shutil.which("tshark"), reason="needs tshark")


def run_download(filt: str, *paths: str) -> tuple[bytes, dict[str, int], str]:
    """(stdout, stage statuses, stderr) of PCAP Search's download job (NET-189) over
    [1700000000.25, 1700000001); asserts it left no FIFO in /tmp, whatever happened."""
    before = set(glob.glob("/tmp/nt-*"))
    p = subprocess.run(
        [
            "sh",
            "-c",
            ps.FILTER_DOWNLOAD_JOB,
            "_",
            "1700000000.25",
            "1700000001",
            filt,
            *paths,
        ],
        env={**os.environ, "NT": "#nt-test"},
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert set(glob.glob("/tmp/nt-*")) == before  # the old merge left a 100 MB file
    stderr = p.stderr.decode()
    statuses = {
        k: int(v) for k, v in re.findall(r"^#nt-test status (\S+) (\d+)$", stderr, re.M)
    }
    return p.stdout, statuses, stderr


@needs_tshark
def test_the_filtered_download_job_reads_every_file_in_the_window(tmp_path):
    # NET-189: PCAP Search's download over two files, one cut short, with a filter
    out, statuses, stderr = run_download(
        "tcp", f"cut:{cut_short_copy(tmp_path)}", str(SYNTHETIC)
    )
    assert statuses["tshark"] == 0
    assert judged(statuses, stderr, cuts=1)
    capture = tmp_path / "out.pcapng"
    capture.write_bytes(out)
    times = subprocess.run(
        ["tshark", "-r", str(capture), "-T", "fields", "-e", "frame.time_epoch"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    # in [.25, 1.0) both files hold packets 3 (tcp), 4 (dns over udp) and 5 (tls over
    # tcp); packet 6 (1.000001) is after the window
    assert [t[:15] for t in times] == ["1700000000.2500"] * 2 + ["1700000000.7500"] * 2


@needs_tshark
def test_a_failed_filter_stage_leaves_nothing_behind(tmp_path):
    # the editcap feeding the cut file's FIFO is blocked when tshark quits at once
    _, statuses, _ = run_download(
        "nosuchfield", f"cut:{cut_short_copy(tmp_path)}", str(SYNTHETIC)
    )
    assert statuses["tshark"] != 0


@needs_tshark
def test_a_failed_merge_leaves_nothing_behind(tmp_path):
    garbage = tmp_path / "garbage.pcap"
    garbage.write_bytes(b"not a capture file at all")
    _, statuses, stderr = run_download(
        "tcp", f"cut:{cut_short_copy(tmp_path)}", str(garbage)
    )
    assert statuses["mergecap"] != 0
    assert not judged(statuses, stderr, cuts=1)  # the daemon calls it a failure
