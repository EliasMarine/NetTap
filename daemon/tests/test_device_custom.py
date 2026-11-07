"""DeviceCustomStore: the owner's name, icon and photo per device (NET-200)."""

import base64
import json
import os
from unittest.mock import patch

import pytest

from services import device_custom as dc
from services.device_custom import DeviceCustomStore, StoreUnavailable

MAC = "AA:BB:CC:DD:EE:01"
MAC2 = "AA:BB:CC:DD:EE:02"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 40
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x02" * 40


def b64(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "appdata")


@pytest.fixture
def store(root):
    return DeviceCustomStore(root)


def pictures(root: str) -> set[str]:
    d = os.path.join(root, "device-pictures")
    return set(os.listdir(d)) if os.path.isdir(d) else set()


# --------------------------------------------------------------------------- names


class TestNames:
    def test_set_trims_normalises_and_survives_a_reload(self, store, root):
        store.set_name("aa-bb-cc-dd-ee-01", "  Café TV  ")
        assert store.name_for(MAC) == "Café TV"  # NFC
        assert DeviceCustomStore(root).name_for(MAC) == "Café TV"

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "x" * 65, "TV‮VT", "line\nbreak", "zero​width", 42, None],
    )
    def test_bad_names_are_refused(self, store, bad):
        with pytest.raises(ValueError):
            store.set_name(MAC, bad)
        assert store.get(MAC) is None

    def test_64_characters_is_allowed(self, store):
        store.set_name(MAC, "x" * 64)
        assert store.name_for(MAC) == "x" * 64

    @pytest.mark.parametrize(
        "bad", ["../../etc/passwd", "AA:BB", "ZZ:BB:CC:DD:EE:01", 7]
    )
    def test_bad_macs_are_refused(self, store, bad):
        with pytest.raises(ValueError):
            store.set_name(bad, "TV")

    def test_name_for_anything_not_a_mac_is_none(self, store):
        assert store.name_for(None) is None
        assert store.name_for("not a mac") is None

    def test_clear_removes_the_entry(self, store, root):
        store.set_name(MAC, "TV")
        store.clear_name(MAC)
        assert store.get(MAC) is None
        assert (
            json.loads(open(os.path.join(root, "device_custom.json")).read())["devices"]
            == {}
        )

    def test_matching_ignores_case(self, store):
        store.set_name(MAC, "Living room TV")
        store.set_name(MAC2, "Laptop")
        assert store.matching("room tv") == [MAC]
        assert store.matching("") == []


# --------------------------------------------------------------------------- pictures


class TestPictures:
    @pytest.mark.parametrize(
        "data,mime,ext",
        [
            (PNG, "image/png", "png"),
            (JPEG, "image/jpeg", "jpg"),
            (WEBP, "image/webp", "webp"),
        ],
    )
    def test_types_come_from_the_bytes(self, store, data, mime, ext):
        store.set_photo(MAC, b64(data, "image/gif"))  # the declared type is ignored
        got = store.photo(MAC)
        assert got[0] == data and got[1] == mime
        assert store.get(MAC)["photo"]["file"].endswith("." + ext)

    @pytest.mark.parametrize(
        "data",
        [
            b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            b"GIF89a" + b"\x00" * 20,
            b"<html><body>hi</body></html>",
            b"RIFF\x00\x00",  # truncated WebP
        ],
    )
    def test_other_content_is_refused(self, store, data):
        with pytest.raises(ValueError, match="PNG, JPEG or WebP"):
            store.set_photo(MAC, b64(data))

    def test_bare_base64_works_and_bad_base64_is_refused(self, store):
        store.set_photo(MAC, base64.b64encode(PNG).decode())
        assert store.photo(MAC)[0] == PNG
        with pytest.raises(ValueError, match="base64"):
            store.set_photo(MAC, "data:image/png;base64,***")
        with pytest.raises(ValueError, match="base64"):
            store.set_photo(MAC, "data:image/png,notbase64")

    def test_oversize_is_refused(self, store):
        big = PNG + b"\x00" * dc.PHOTO_MAX_BYTES
        with pytest.raises(ValueError, match="too large"):
            store.set_photo(MAC, b64(big))

    def test_the_total_budget_holds(self, store, monkeypatch):
        monkeypatch.setattr(dc, "PHOTOS_MAX_TOTAL", 100)
        store.set_photo(MAC, b64(PNG))  # 48 bytes
        with pytest.raises(ValueError, match="storage is full"):
            store.set_photo(MAC2, b64(PNG + b"\x01" * 60))
        store.set_photo(
            MAC, b64(PNG + b"\x02" * 10)
        )  # replacing its own photo doesn't count twice

    def test_icon_and_photo_replace_each_other(self, store, root):
        store.set_photo(MAC, b64(PNG))
        store.set_icon(MAC, "tv")
        assert store.get(MAC) == {"icon": "tv"}
        assert pictures(root) == set()
        store.set_photo(MAC, b64(JPEG))
        assert "icon" not in store.get(MAC)

    def test_unknown_icon_is_refused(self, store):
        with pytest.raises(ValueError):
            store.set_icon(MAC, "rocket")

    @pytest.mark.parametrize("bad", [["tv"], {"tv": 1}, None, 3])
    def test_a_non_string_icon_is_a_value_error(self, store, bad):
        # an unhashable icon used to raise TypeError, which no caller maps
        with pytest.raises(ValueError):
            store.set_icon(MAC, bad)
        with pytest.raises(ValueError):
            store.restore(None, {MAC: {"icon": bad}})

    def test_the_device_cap_refuses_a_new_mac_but_not_an_edit(self, store, monkeypatch):
        monkeypatch.setattr(dc, "DEVICES_MAX", 1)
        store.set_name(MAC, "TV")
        with pytest.raises(ValueError, match="limited to"):
            store.set_icon(MAC2, "tv")
        store.set_icon(MAC, "tv")  # an existing device can still change
        with pytest.raises(ValueError, match="limited to"):
            store.restore({MAC: "TV", MAC2: "Laptop"}, None)
        assert store.names() == {MAC: "TV"}

    def test_clearing_nothing_does_not_rewrite_the_file(self, store):
        store.set_name(MAC, "TV")
        with patch.object(dc, "write_file_atomic") as write:
            store.clear_picture(MAC)
            store.clear_name(MAC2)
        write.assert_not_called()

    def test_a_new_photo_deletes_the_old_file_only_after_commit(self, store, root):
        store.set_photo(MAC, b64(PNG))
        first = store.get(MAC)["photo"]["file"]
        store.set_photo(MAC, b64(JPEG))
        second = store.get(MAC)["photo"]["file"]
        assert first != second and pictures(root) == {second}

    def test_the_same_photo_twice_keeps_its_file(self, store, root):
        store.set_photo(MAC, b64(PNG))
        store.set_photo(MAC, b64(PNG))
        assert store.photo(MAC)[0] == PNG
        assert pictures(root) == {store.get(MAC)["photo"]["file"]}

    def test_clear_picture_removes_the_file(self, store, root):
        store.set_photo(MAC, b64(PNG))
        store.set_name(MAC, "TV")
        store.clear_picture(MAC)
        assert store.get(MAC) == {"name": "TV"} and pictures(root) == set()

    def test_a_damaged_photo_reads_as_none(self, store, root):
        store.set_photo(MAC, b64(PNG))
        path = os.path.join(root, "device-pictures", store.get(MAC)["photo"]["file"])
        open(path, "wb").write(b"tampered")
        assert store.photo(MAC) is None

    def test_owner_fields_and_present(self, store):
        store.set_name(MAC, "TV")
        store.set_photo(MAC, b64(PNG))
        fields = store.owner_fields(MAC.lower())
        digest = store.get(MAC)["photo"]["file"].split("-")[1].split(".")[0]
        assert fields == {
            "custom_name": "TV",
            "icon": None,
            "picture": f"/api/devices/registry/{MAC}/picture?v={digest}",
        }
        row = {"mac": MAC, "hostname": "android-123", "ip": "10.0.0.2"}
        shown = store.present(row)
        assert (shown["hostname"], shown["discovered_name"]) == ("TV", "android-123")
        assert row["hostname"] == "android-123"  # not mutated
        assert store.present({"mac": MAC2, "hostname": "x"})["hostname"] == "x"
        assert store.owner_fields(None)["custom_name"] is None


# --------------------------------------------------------------------------- crash safety


class TestCommitOrder:
    def test_a_failed_metadata_write_keeps_the_old_photo(self, store, root):
        store.set_photo(MAC, b64(PNG))
        before = store.get(MAC)
        with patch.object(dc, "write_file_atomic", side_effect=OSError("disk full")):
            with pytest.raises(OSError):
                store.set_photo(MAC, b64(JPEG))
        assert store.get(MAC) == before
        assert store.photo(MAC)[0] == PNG
        # the new file is an orphan; a restart sweeps it and keeps the referenced one
        assert DeviceCustomStore(root).photo(MAC)[0] == PNG
        assert pictures(root) == {before["photo"]["file"]}

    def test_a_failed_photo_write_changes_nothing(self, store, root):
        store.set_name(MAC, "TV")
        with patch.object(dc.os, "replace", side_effect=OSError("io")):
            with pytest.raises(OSError):
                store.set_photo(MAC, b64(PNG))
        assert store.get(MAC) == {"name": "TV"}
        assert {n for n in pictures(root) if not n.startswith(".")} == set()


class TestStartup:
    def test_sweep_removes_only_orphans_and_temp_files(self, store, root):
        store.set_photo(MAC, b64(PNG))
        keep = store.get(MAC)["photo"]["file"]
        d = os.path.join(root, "device-pictures")
        for name in ("aabbccddee02-0123456789abcdef.png", ".photo-abc", "notes.txt"):
            open(os.path.join(d, name), "wb").write(b"x")
        DeviceCustomStore(root)
        assert pictures(root) == {keep, "notes.txt"}

    @pytest.mark.parametrize(
        "content",
        [
            "{not json",
            json.dumps({"version": 2, "devices": {}}),
            json.dumps({"version": 1, "devices": []}),
            json.dumps(
                {
                    "version": 1,
                    "devices": {"aa:bb:cc:dd:ee:01": {"name": "lower-case key"}},
                }
            ),
            json.dumps(
                {
                    "version": 1,
                    "devices": {
                        MAC: {
                            "photo": {
                                "file": "../x.png",
                                "type": "image/png",
                                "bytes": 1,
                            }
                        }
                    },
                }
            ),
            json.dumps({"version": 1, "devices": {MAC: {"icon": []}}}),
            json.dumps(
                {
                    "version": 1,
                    "devices": {
                        MAC: {
                            "photo": {
                                "file": "aabbccddee01-0123456789abcdef.png",
                                "type": [],
                                "bytes": 1,
                            }
                        }
                    },
                }
            ),
        ],
    )
    def test_bad_metadata_deletes_nothing_and_refuses_writes(
        self, store, root, content
    ):
        store.set_photo(MAC, b64(PNG))
        files = pictures(root)
        meta = os.path.join(root, "device_custom.json")
        open(meta, "w").write(content)
        broken = DeviceCustomStore(root)
        assert pictures(root) == files  # no sweep on metadata it can't trust
        assert not broken.healthy and broken.get(MAC) is None
        with pytest.raises(StoreUnavailable):
            broken.set_name(MAC2, "TV")
        with pytest.raises(StoreUnavailable):
            broken.export()
        assert open(meta).read() == content  # never overwritten


# --------------------------------------------------------------------------- backup


class TestBackup:
    def test_export_holds_names_icons_and_photos(self, store):
        store.set_name(MAC, "TV")
        store.set_icon(MAC, "tv")
        store.set_photo(MAC2, b64(PNG))
        names, pics = store.export()
        assert names == {MAC: "TV"}
        assert pics[MAC] == {"icon": "tv"}
        assert pics[MAC2] == {"image": b64(PNG, "image/png")}

    def test_export_fails_on_a_missing_photo(self, store, root):
        store.set_photo(MAC, b64(PNG))
        os.unlink(
            os.path.join(root, "device-pictures", store.get(MAC)["photo"]["file"])
        )
        with pytest.raises(ValueError, match=MAC):
            store.export()

    def test_restore_replaces_present_sections_only(self, store, tmp_path):
        store.set_name(MAC, "Old name")
        store.set_icon(MAC, "tv")
        store.set_name(MAC2, "Laptop")
        store.restore({MAC2: "New laptop"}, None)
        assert store.get(MAC) == {"icon": "tv"}  # name cleared; picture section absent
        assert store.name_for(MAC2) == "New laptop"
        store.restore(None, {})
        assert store.get(MAC) is None and store.get(MAC2) == {"name": "New laptop"}

    def test_an_empty_section_clears_onto_a_customised_store(self, store, root):
        store.set_name(MAC, "TV")
        store.set_photo(MAC, b64(PNG))
        store.restore({}, {})
        assert store.get(MAC) is None and pictures(root) == set()

    def test_restore_is_all_or_nothing(self, store):
        store.set_name(MAC, "TV")
        with pytest.raises(ValueError, match="picture for"):
            store.restore({MAC2: "Laptop"}, {MAC: {"image": b64(b"<svg/>")}})
        assert store.names() == {MAC: "TV"}
        with pytest.raises(ValueError):
            store.restore({"../etc": "x"}, None)
        with pytest.raises(ValueError):
            store.restore(None, {MAC: {"icon": "tv", "image": b64(PNG)}})

    def test_restoring_the_same_backup_twice_keeps_photos(self, store, root, tmp_path):
        store.set_photo(MAC, b64(PNG))
        store.set_photo(MAC2, b64(JPEG))
        names, pics = store.export()
        store.restore(names, pics)
        store.restore(names, pics)
        assert store.photo(MAC)[0] == PNG and store.photo(MAC2)[0] == JPEG
        # mixed: MAC unchanged, MAC2 changed, a third removed
        store.set_icon("AA:BB:CC:DD:EE:03", "nas")
        keep = store.get(MAC)["photo"]["file"]
        store.restore(None, {MAC: pics[MAC], MAC2: {"image": b64(WEBP)}})
        assert store.get(MAC)["photo"]["file"] == keep
        assert store.photo(MAC2)[0] == WEBP
        assert store.get("AA:BB:CC:DD:EE:03") is None
        assert pictures(root) == {keep, store.get(MAC2)["photo"]["file"]}

    def test_restore_checks_the_total_budget(self, store, monkeypatch):
        monkeypatch.setattr(dc, "PHOTOS_MAX_TOTAL", 60)
        with pytest.raises(ValueError, match="storage is full"):
            store.restore(None, {MAC: {"image": b64(PNG)}, MAC2: {"image": b64(JPEG)}})
