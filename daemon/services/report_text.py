"""
A report as a plain-text email (NET-340, plans/2026-11-21-weekly-report.md §3.5). Pure, no I/O.

The subject is built from the dates only. Text that came from the network (device names,
vendors, rule names, addresses) loses its control, format and line-break characters and is
clipped to 120 characters, so nothing a device announces can shape the message. Voice as the
web app: sentence case, UK spelling, no emoji.
"""

import unicodedata
from datetime import date
from typing import Any, Callable
from zoneinfo import ZoneInfo

from services.device_details import _BAD_CATEGORIES
from services.notification_dispatcher import _cap_gb, _gb
from services.usage_days import parse_iso
from services.watch_events import _away

NETWORK_TEXT_MAX = 120
POSTURE_LINE = (
    "Security posture: open NetTap and choose Security posture (/compliance) for the "
    "full picture."
)
_NOUN = {"daily": "day", "weekly": "week", "monthly": "month"}
_SEVERITY = {1: "high", 2: "medium", 3: "low"}
_QUIET = "No alerts recorded: a quiet day, or Suricata wasn't running"
_STORED = {
    "partial": "Only part of this day is stored",
    "absent": "Not stored",
    "unknown": "Not known whether this day is stored",
}
_CROSSED = {80: "Passed 80%", 100: "Passed 100%", "projected": "On track to go over"}


def clean(raw: Any, limit: int | None = NETWORK_TEXT_MAX) -> str:
    """Network text on one plain line: control, format and separator characters removed, then
    clipped to `limit` (None: not clipped, for NetTap's own longer explanations)."""
    text = "".join(
        ch for ch in str(raw) if unicodedata.category(ch) not in _BAD_CATEGORIES
    ).strip()
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def render_email(report: dict) -> tuple[str, str]:
    """(subject, plain-text body) for a full report dict (the contract's shape)."""
    period = report["period"]
    first, last = (
        date.fromisoformat(period["first"]),
        date.fromisoformat(period["last"]),
    )
    tz = period["tz"]
    frequency = report.get("frequency")
    title = " ".join(
        w for w in ("NetTap", frequency if frequency in _NOUN else "", "report") if w
    )
    dates = _span(first, last)
    noun = _NOUN.get(frequency, "period")
    sections = report.get("sections") or {}
    blocks = [
        [title, f"{dates}, times in {tz}"],
        _block("Internet use", sections.get("traffic"), lambda s: _traffic(s, noun)),
        _block("Alerts", sections.get("alerts"), _alerts),
        _block(
            "New devices", sections.get("new_devices"), lambda s: _new_devices(s, tz)
        ),
        _block("Offline incidents", sections.get("offline"), lambda s: _offline(s, tz)),
        _block("Data cap", sections.get("data_cap"), lambda s: _data_cap(s, tz, last)),
        [POSTURE_LINE],
    ]
    return f"{title}: {dates}", "\n\n".join("\n".join(b) for b in blocks) + "\n"


# --- formatting --------------------------------------------------------------------


def _span(first: date, last: date) -> str:
    """10–16 November 2026; 28 October – 3 November 2026; 16 November 2026."""
    if first == last:
        return f"{last.day} {last:%B %Y}"
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}–{last.day} {last:%B %Y}"
    if first.year == last.year:
        return f"{first.day} {first:%B} – {last.day} {last:%B %Y}"
    return f"{first.day} {first:%B %Y} – {last.day} {last:%B %Y}"


def _local(iso: Any, tz: str, clock: bool = True) -> str:
    """14 Nov 09:12 in the report's zone (14 Nov without the clock)."""
    t = parse_iso(iso)
    if t is None:
        return "an unknown time"
    t = t.astimezone(ZoneInfo(tz))
    return f"{t.day} {t:%b %H:%M}" if clock else f"{t.day} {t:%b}"


def _weekday(key: str) -> str:
    d = date.fromisoformat(key)
    return f"{d:%a} {d.day} {d:%b}"


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}{'' if n == 1 else 's'}"


def _at_least(n: int) -> str:
    """An "at least" figure floors to 0.1 GB, so it is never above what was counted."""
    return _gb(n // 10**8 * 10**8)


def _severity(level: Any) -> str:
    if level is None:
        return "severity unknown"
    return _SEVERITY.get(level, f"severity {level}")


def _block(title: str, section: Any, render: Callable[[dict], list[str]]) -> list[str]:
    lines = [title, "-" * len(title)]
    if not isinstance(section, dict) or section.get("status") not in ("ok", "partial"):
        note = section.get("note") if isinstance(section, dict) else None
        return [*lines, f"Not available this time. {note or ''}".rstrip()]
    lines = [*lines, *render(section), f"Coverage: {section['coverage']}."]
    if section["status"] == "partial" and section.get("note"):
        lines = [*lines, f"Note: {section['note']}"]
    return lines


# --- the sections -------------------------------------------------------------------


def _traffic(s: dict, noun: str) -> list[str]:
    provisional = ", provisional" if s["provisional"] else ""
    lines = [
        f"Total: {_gb(s['total'])} (download {_gb(s['download'])}, "
        f"upload {_gb(s['upload'])}){provisional}."
    ]
    if s["counted_total"] != s["total"]:
        lines.append(
            f"Counted under the current rules: at least {_at_least(s['counted_total'])}."
        )
    if s["local"]:
        lines.append(f"Local traffic (not in the total): {_gb(s['local'])}.")
    busiest = s.get("busiest")
    lines.append(
        f"Busiest day: {_weekday(busiest['date'])}, {_gb(busiest['total'])}."
        if busiest
        else f"No usage was counted for this {noun}."
    )
    return lines


def _alerts(s: dict) -> list[str]:
    sev = s["by_severity"]
    other = f", {sev['other']:,} other" if sev["other"] else ""
    lines = [
        f"{_count(s['total'], 'alert')}: {sev['1']:,} high, {sev['2']:,} medium, "
        f"{sev['3']:,} low{other}."
    ]
    for d in s["days"]:
        stored, count = d["stored"], d["count"]
        shown = "–" if stored == "absent" and not count else f"{count:,}"
        why = _STORED.get(stored) or ("" if count else _QUIET)
        lines.append(f"  {_weekday(d['date']):<10} {shown:>7}  {why}".rstrip())
    worst = s.get("worst")
    if worst is None:
        return [
            *lines,
            f"Worst rules: {s.get('worst_note') or 'Not included this time.'}",
        ]
    if worst:
        lines.append("Worst rules:")
    for n, w in enumerate(worst, 1):
        lines += [
            f"  {n}. {clean(w['rule'])} ({_severity(w['severity'])}, "
            f"{_count(w['count'], 'alert')})",
            f"     {clean(w.get('what', ''), None)}",
            f"     What to do: {clean(w.get('todo', ''), None)}",
        ]
    return lines


def _new_devices(s: dict, tz: str) -> list[str]:
    count, listed = s["count"], s["listed"]
    at_least = "At least " if s.get("truncated") else ""
    lines = [
        f"{at_least}{_count(count, 'device')} seen for the first time."
        if count
        else "No new devices were recorded."
    ]
    for d in listed:
        mac = clean(d["mac"])
        label = f"{clean(d['name'])} ({mac})" if d.get("name") else mac
        extras = [clean(v) for v in (d.get("vendor"), d.get("ip")) if v]
        seen = _local(d["first_seen"], tz)
        lines.append(f"  - {', '.join([label, *extras])}, first seen {seen}")
    if count > len(listed):
        lines.append(f"  and {count - len(listed):,} more: see Devices in NetTap.")
    return lines


def _offline(s: dict, tz: str) -> list[str]:
    incidents = s["incidents"]
    lines = [
        f"{_count(len(incidents), 'outage')} of watched devices."
        if incidents
        else "No watched device went offline."
    ]
    for i in incidents:
        mac = clean(i["mac"])
        label = f"{clean(i['name'])} ({mac})" if i.get("name") else mac
        if i["to"]:
            took = _away(i["minutes"]) or "under a minute"
            when = f"offline {_local(i['from'], tz)} to {_local(i['to'], tz)} ({took})"
        else:
            when = f"offline from {_local(i['from'], tz)}"
        detail = f". {i['detail']}" if i.get("detail") else ""
        lines.append(f"  - {label}: {when}{detail}.")
    if s.get("watched_now") is not None:
        lines.append(f"Watched now: {s['watched_now']:,}.")
    return lines


def _data_cap(s: dict, tz: str, last: date) -> list[str]:
    cap, crossings = s.get("cap_bytes"), s.get("crossings") or []
    if not cap and not crossings:
        return ["No data cap set."]
    month = date.fromisoformat(f"{s['month']}-01")
    lines = (
        [
            f"{s['percent']:.1f}% of your current cap of {_cap_gb(cap)} used in "
            f"{month:%B} up to {last.day} {last:%B}, at least "
            f"{_at_least(s['used_counted'])} counted under the current rules."
        ]
        if cap
        else ["No data cap is set now."]
    )
    if cap and s["used_provisional"] != s["used_counted"]:
        lines.append(f"Provisional total: {_gb(s['used_provisional'])}.")
    for c in crossings:
        what = _CROSSED.get(c.get("threshold"), "Passed a warning level")
        of = f" of {_cap_gb(c['cap'])}" if isinstance(c.get("cap"), int) else ""
        lines.append(f"{what}{of} on {_local(c.get('at'), tz, clock=False)}.")
    return lines
