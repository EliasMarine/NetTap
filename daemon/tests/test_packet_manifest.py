"""The search manifest and re-read admission (NET-188)."""

import json
import os

import pytest

from services.packet_manifest import (
    MAX_BYTES,
    PacketError,
    admit,
    parse_manifest,
    valid_file_id,
)


def manifest(**over):
    m = {
        "from": "1700000000",
        "to": "1700000002.5",
        "filter": "tcp",
        "files": [
            {"id": "a.pcap", "size": 10, "mtime_ns": "1000000000000", "recent": False}
        ],
        "frames": [
            {"n": 1, "t": "1700000000.000001000", "cap_len": 54, "md5": "a" * 32},
            {"n": 4, "t": "1700000000.500001000", "cap_len": 96, "md5": "b" * 32},
        ],
    }
    m.update(over)
    return m


def write(tmp_path, name, size, mtime_s=1000):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    os.utime(p, (mtime_s, mtime_s))
    return p


class TestParse:
    def test_valid(self):
        m = parse_manifest(manifest())
        assert m.files[0].mtime_ns == 1_000_000_000_000 and m.frame(4).cap_len == 96

    def test_big_numbers_survive_json_as_strings(self):
        # 2**63-ish: not safe as a JavaScript number, so it travels as a string
        big = "9223372036854775807"
        raw = json.loads(
            json.dumps(manifest(files=[{"id": "a.pcap", "size": 1, "mtime_ns": big}]))
        )
        assert parse_manifest(raw).files[0].mtime_ns == int(big)

    @pytest.mark.parametrize(
        "over",
        [
            {"from": "1700000002.5"},  # empty window
            {"to": "1700001801"},  # longer than 30 minutes
            {"from": "17e8"},
            {"files": []},
            {"files": [{"id": "../etc/passwd.pcap", "size": 1, "mtime_ns": "1"}]},
            {"files": [{"id": "/abs.pcap", "size": 1, "mtime_ns": "1"}]},
            {"files": [{"id": "a.txt", "size": 1, "mtime_ns": "1"}]},
            {"files": [{"id": "a.pcap", "size": -1, "mtime_ns": "1"}]},
            {"files": [{"id": "a.pcap", "size": True, "mtime_ns": "1"}]},
            {"files": [{"id": "a.pcap", "size": 1, "mtime_ns": "1"}] * 2},
            {
                "files": [
                    {"id": f"f{i}.pcap", "size": 1, "mtime_ns": "1"} for i in range(65)
                ]
            },
            {"frames": []},
            {
                "frames": [
                    {"n": 2, "t": "1", "cap_len": 1, "md5": "a" * 32},
                    {"n": 2, "t": "1", "cap_len": 1, "md5": "a" * 32},
                ]
            },
            {"frames": [{"n": 0, "t": "1", "cap_len": 1, "md5": "a" * 32}]},
            {"frames": [{"n": 1, "t": "1", "cap_len": 1, "md5": "XYZ"}]},
            {
                "frames": [
                    {"n": i + 1, "t": "1", "cap_len": 1, "md5": "a" * 32}
                    for i in range(1001)
                ]
            },
            {"filter": "x" * 501},
        ],
    )
    def test_malformed_is_400(self, over):
        with pytest.raises(PacketError) as err:
            parse_manifest(manifest(**over))
        assert err.value.status == 400

    def test_unknown_frame_is_400(self):
        with pytest.raises(PacketError) as err:
            parse_manifest(manifest()).frame(2)
        assert err.value.status == 400

    def test_file_ids(self):
        assert valid_file_id("sub/x.pcapng")
        assert not valid_file_id("sub//x.pcap") and not valid_file_id("a\nb.pcap")


class TestAdmit:
    def test_unchanged_files_pass(self, tmp_path):
        write(tmp_path, "a.pcap", 10)
        assert admit(parse_manifest(manifest()), str(tmp_path)) == ["/pcap/a.pcap"]

    def test_unrelated_rotation_doesnt_matter(self, tmp_path):
        write(tmp_path, "a.pcap", 10)
        write(tmp_path, "new.pcap", 99)  # a file written after the search
        admit(parse_manifest(manifest()), str(tmp_path))

    def test_changed_finished_file_is_409(self, tmp_path):
        write(tmp_path, "a.pcap", 11)
        with pytest.raises(PacketError) as err:
            admit(parse_manifest(manifest()), str(tmp_path))
        assert err.value.status == 409

    def test_touched_finished_file_is_409(self, tmp_path):
        write(tmp_path, "a.pcap", 10, mtime_s=1001)
        with pytest.raises(PacketError):
            admit(parse_manifest(manifest()), str(tmp_path))

    def test_deleted_file_is_409(self, tmp_path):
        with pytest.raises(PacketError) as err:
            admit(parse_manifest(manifest()), str(tmp_path))
        assert err.value.status == 409

    def test_recent_file_may_grow_but_not_shrink(self, tmp_path):
        files = [{"id": "a.pcap", "size": 10, "mtime_ns": "5", "recent": True}]
        write(tmp_path, "a.pcap", 15, mtime_s=2000)
        admit(parse_manifest(manifest(files=files)), str(tmp_path))
        write(tmp_path, "a.pcap", 5, mtime_s=2001)
        with pytest.raises(PacketError):
            admit(parse_manifest(manifest(files=files)), str(tmp_path))

    def test_symlink_is_refused(self, tmp_path):
        write(tmp_path, "real.pcap", 10)
        os.symlink(tmp_path / "real.pcap", tmp_path / "a.pcap")
        with pytest.raises(PacketError):
            admit(parse_manifest(manifest()), str(tmp_path))

    def test_budget_uses_sizes_on_disk_not_the_manifest(self, tmp_path):
        half = MAX_BYTES // 2 + 1
        files = []
        for name in ("a.pcap", "b.pcap"):
            with open(tmp_path / name, "wb") as fh:
                fh.truncate(half)  # sparse
            files.append({"id": name, "size": "0", "mtime_ns": "1", "recent": True})
        with pytest.raises(PacketError) as err:
            admit(parse_manifest(manifest(files=files)), str(tmp_path))
        assert err.value.status == 409
