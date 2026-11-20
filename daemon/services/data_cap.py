"""
Data cap warnings (NET-339, roadmap #6): at 80% of the monthly cap, at 100%, and when the month
is on track to go over, each at most once a month for each cap.

The event journal is the only record of "sent" (plan §3.1): a warning is one append whose id is
(threshold, "<YYYY-MM>|<cap bytes>"), so a retry, a restart or a return to an earlier cap finds
it and sends nothing again. The dispatcher delivers it like any journal event. Only the owner's
current month is checked (§3.5), from the usage ledger's snapshot: no OpenSearch query.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any

from api.usage import month_reply
from services import owner_tz, usage_report
from services.usage_days import parse_iso, utc_iso

logger = logging.getLogger("nettap.services.data_cap")

PROJECT_FROM = timedelta(days=3)  # a projection from fewer days says little


def _thresholds(
    low: int, cap: int, projected: int | None, elapsed: timedelta
) -> list[str]:
    """The warnings due, in order: "80", "100", "projected"."""
    due = []
    if low * 5 >= cap * 4:  # 80%, in whole numbers
        due.append("80")
    if low >= cap:
        due.append("100")
    elif projected is not None and projected > cap and elapsed >= PROJECT_FROM:
        due.append("projected")
    return due


def _elapsed(m: dict) -> timedelta:
    """Today's cutoff from the month's start, in real time; zero without one."""
    rows = [r for r in m["days"] if r["status"] != "future"]
    cutoff = parse_iso(rows[-1]["cutoff"]) if rows else None
    if cutoff is None:
        return timedelta(0)
    return cutoff - datetime.fromisoformat(m["month_start"])


class DataCapWatch:
    """The data-cap job: appends each warning that is due to the event journal."""

    def __init__(self, tracker: Any, ledger: Any, journal: Any) -> None:
        self._tracker = tracker
        self._ledger = ledger
        self._journal = journal

    def now(self) -> tuple[str, int]:
        """(the owner's month "YYYY-MM", the cap in bytes, 0 for none): the dispatcher's
        data_cap_now, from the clock and zone month_reply uses for run()'s month."""
        snapshot, now = self._ledger.snapshot(), self._ledger.now()
        year, month = usage_report.current_month(snapshot, now, owner_tz.read())
        return f"{year:04d}-{month:02d}", self._tracker.get_cap()["monthly_cap_bytes"]

    def run(self, _deadline: float) -> dict:
        """Append the warnings due this month; {"sent": [the keys appended]}.

        An OSError from an append is raised once the others were tried, so the job records it;
        the failed one is left out of the journal and the next run appends it.
        """
        cap = self._tracker.get_cap()["monthly_cap_bytes"]
        if not cap:
            return {"sent": []}
        m = month_reply(self._ledger)
        if m["since"] is None:  # no ledger snapshot yet: nothing counted
            return {"sent": []}
        low = m["bytes"]["lower_bound"]
        month = f"{m['year']:04d}-{m['month']:02d}"
        data = {
            "month": month,
            "month_label": date(m["year"], m["month"], 1).strftime("%B"),
            "used": low,
            "cap": cap,
            "projected": m["projected"],
            "tz": m["tz"],
            "since": m["since"],
            "complete": m["complete"],
        }
        observed_at = utc_iso(self._ledger.now())
        sent, failed = [], None
        for key in _thresholds(low, cap, m["projected"], _elapsed(m)):
            try:
                entry = self._journal.append(
                    "data_cap",
                    key,
                    observed_at,
                    {**data, "threshold": key},
                    instance=f"{month}|{cap}",
                )
            except OSError as exc:
                logger.warning(
                    "Data cap warning %s not recorded, will retry: %s", key, exc
                )
                failed = failed or exc
                continue
            if entry is not None:  # None: already in the journal, so already sent
                sent.append(key)
        if failed:
            raise failed
        return {"sent": sent}
