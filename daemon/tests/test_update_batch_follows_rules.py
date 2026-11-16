"""A rules update in an Updates page batch is followed to its own end: it was recorded as failed
after 270 s while it kept running, and the batch then started Malcolm, which restarts Suricata."""

import asyncio

from services.malcolm_upgrade import TESTED_MALCOLM_TAG
from services.update_executor import UpdateExecutor
from tests.test_update_executor import FakeMalcolm, FakeRuleManager


class HeldRuleManager(FakeRuleManager):
    """A rule update that runs until the test releases it."""

    def __init__(self, result):
        super().__init__(result)
        self.gate = asyncio.Event()

    async def update_rules(self, follow=False):
        self.follow = follow
        await self.gate.wait()
        self.updates += 1
        return self.result


async def _run(result):
    malcolm = FakeMalcolm()
    rules = HeldRuleManager(result)
    ue = UpdateExecutor(malcolm_upgrade=malcolm)
    ue._rule_manager = rules
    _, code = await ue.start_update(["suricata-rules", "malcolm"])
    for _ in range(5):
        await asyncio.sleep(0)
    during = await ue.get_status()
    _, again = await ue.start_update(["malcolm"])
    targets_during = list(malcolm.targets)
    rules.gate.set()
    await ue._task
    return code, during, again, targets_during, malcolm, rules, await ue.get_status()


def test_the_batch_waits_for_the_rules_update_then_runs_malcolm():
    code, during, again, targets_during, malcolm, rules, done = asyncio.run(
        _run({"success": True, "output": "", "reload_output": "active"})
    )
    assert code == 202
    assert rules.follow is True
    assert during["state"] == "in_progress"
    assert during["current_step"] == "Updating the Suricata rules"
    assert again == 409  # Malcolm alone can't start meanwhile
    assert targets_during == []  # nor did the batch's own Malcolm
    assert malcolm.targets == [TESTED_MALCOLM_TAG]
    by = {r["component"]: r for r in done["results"]}
    assert by["suricata-rules"]["success"] is True
    assert by["malcolm"]["success"] is True


def test_an_unconfirmed_rules_update_is_not_called_failed():
    *_, done = asyncio.run(
        _run(
            {
                "success": False,
                "running": True,
                "output": "It was still running after 40 minutes, so something may be stuck.",
                "reload_output": "",
            }
        )
    )
    rules = next(r for r in done["results"] if r["component"] == "suricata-rules")
    assert rules["success"] is False
    assert rules["error"].startswith("Couldn't confirm Suricata's rule update finished")
    assert "may be stuck" in rules["error"]


def test_a_rules_update_that_fails_late_records_its_own_reason():
    *_, done = asyncio.run(
        _run(
            {
                "success": False,
                "output": "The rule update failed. The daemon log has the details.",
                "reload_output": "Lock held by another rule operation for 900 s",
            }
        )
    )
    rules = next(r for r in done["results"] if r["component"] == "suricata-rules")
    assert rules["success"] is False
    assert "Lock held by another rule operation" in rules["error"]
    assert "still running" not in rules["error"]
