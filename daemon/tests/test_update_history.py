"""The update history survives daemon restarts (it was kept in memory only, so every deploy lost
it, including the G11's 26.02.0 -> 26.10.0 update), and a bad saved entry can't break /status."""

import asyncio
import json
import os

from services.update_executor import UpdateExecutor
from tests.test_update_executor import FakeMalcolm

UNFINISHED = {
    "old_version": "26.02.0",
    "new_version": "26.10.0",
    "step": "starting",
    "backup_volume": "docker_opensearch-data-before-update",
    "at": "2026-11-03T00:00:00+00:00",
}


def _executor(path, malcolm=None):
    return UpdateExecutor(
        malcolm_upgrade=malcolm or FakeMalcolm(), history_file=str(path)
    )


def test_a_batch_survives_a_new_executor_on_the_same_file(tmp_path):
    path = tmp_path / "update-history.json"
    asyncio.run(_executor(path).apply_update(["malcolm"]))

    history = asyncio.run(_executor(path).get_history())

    assert len(history) == 1
    assert history[0]["components"] == ["malcolm"]
    assert history[0]["results"][0]["new_version"] == "26.10.0"


def test_the_default_file_comes_from_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "from-env.json"
    monkeypatch.setenv("UPDATE_HISTORY_FILE", str(path))
    asyncio.run(UpdateExecutor(malcolm_upgrade=FakeMalcolm()).apply_update(["malcolm"]))
    assert path.exists()


def test_history_is_trimmed_to_fifty_batches(tmp_path):
    path = tmp_path / "update-history.json"
    ue = _executor(path)
    for _ in range(52):
        asyncio.run(ue.apply_update(["malcolm"]))
    assert len(json.loads(path.read_text())) == 50
    assert len(asyncio.run(_executor(path).get_history())) == 50


def test_corrupt_or_non_list_files_read_as_empty(tmp_path):
    for content in ("{not json", '{"history": []}', "null"):
        path = tmp_path / "update-history.json"
        path.write_text(content)
        ue = _executor(path)
        assert asyncio.run(ue.get_history()) == []
        assert asyncio.run(ue.get_status())["state"] == "idle"


def test_malformed_entries_are_dropped_or_rebuilt(tmp_path):
    path = tmp_path / "update-history.json"
    path.write_text(
        json.dumps(
            [
                {"results": [None]},  # nothing usable: dropped
                {"results": [{"success": True}]},  # no component: dropped
                "a string",
                {
                    "results": [
                        {"component": "malcolm", "success": False, "error": 7},
                        {
                            "component": "malcolm",
                            "success": "yes",
                        },  # not a bool: dropped
                    ],
                    "components": "malcolm",
                    "started_at": 5,
                },
            ]
        )
    )
    ue = _executor(path)

    history = asyncio.run(ue.get_history())
    status = asyncio.run(ue.get_status())

    assert len(history) == 1
    (result,) = history[0]["results"]
    assert result == {
        "component": "malcolm",
        "success": False,
        "old_version": "unknown",
        "new_version": "unknown",
        "started_at": "",
        "completed_at": "",
        "error": None,
        "rollback_available": False,
    }
    assert history[0]["components"] == ["malcolm"]
    assert (history[0]["total"], history[0]["failed"]) == (1, 1)
    assert history[0]["started_at"] == ""
    assert status["state"] == "completed"
    assert status["components"] == ["malcolm"]


def test_an_unwritable_file_keeps_the_batch_result(tmp_path, caplog):
    path = tmp_path / "missing-dir" / "update-history.json"
    result = asyncio.run(_executor(path).apply_update(["malcolm"]))
    assert result["success"] is True
    assert "Couldn't save the update history" in caplog.text


def test_an_unfinished_update_is_saved_then_cleared(tmp_path):
    path = tmp_path / "update-history.json"
    malcolm = FakeMalcolm(unfinished=dict(UNFINISHED))

    _executor(path, malcolm)

    saved = json.loads(path.read_text())
    assert saved[0]["results"][0]["component"] == "malcolm"
    assert "interrupted" in saved[0]["results"][0]["error"]
    assert malcolm.unfinished is None


def test_a_failed_save_keeps_the_record_for_the_next_start_and_records_it_once(
    tmp_path,
):
    malcolm = FakeMalcolm(unfinished=dict(UNFINISHED))
    _executor(tmp_path / "missing-dir" / "update-history.json", malcolm)
    assert malcolm.unfinished is not None  # not saved, so not forgotten

    path = tmp_path / "update-history.json"
    _executor(path, malcolm)  # the next start, now with a writable file
    assert malcolm.unfinished is None
    assert len(json.loads(path.read_text())) == 1


def test_an_entry_already_saved_is_not_repeated(tmp_path):
    path = tmp_path / "update-history.json"
    _executor(path, FakeMalcolm(unfinished=dict(UNFINISHED)))
    # the save worked but the clear didn't: the same record is there on the next start
    malcolm = FakeMalcolm(unfinished=dict(UNFINISHED))

    ue = _executor(path, malcolm)

    assert len(asyncio.run(ue.get_history())) == 1
    assert malcolm.unfinished is None


def test_no_file_means_no_history(tmp_path):
    path = tmp_path / "update-history.json"
    assert asyncio.run(_executor(path).get_history()) == []
    assert not os.path.exists(path)
