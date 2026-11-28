"""
A report as a branded HTML email (NET-381), the HTML sibling of report_text. Pure, except
logo_png reading the packaged logo.

The same report dict, sections, order, wording and figures as the plain-text part: the lines come
from report_text's helpers. Every value is HTML-escaped, and network text is clean()ed first as in
the text part. Email-safe: tables with inline styles and bgcolor, at most 600 px wide, no script,
no remote resources (the only image is the inline logo, by cid). Colours are the Ember tokens of
nettap-design-system/tokens.css, copied as literals because email clients have no CSS variables.
"""

import html
import logging
from datetime import date
from functools import cache
from pathlib import Path

from services.notification_dispatcher import _gb
from services.report_text import (
    POSTURE_LINE,
    RECIPIENT_LINE,
    _NOUN,
    _count,
    _data_cap,
    _local,
    _offline,
    _severity,
    _span,
    _traffic,
    _weekday,
    clean,
    day_count,
    explanations,
    heading,
)

logger = logging.getLogger(__name__)

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "report-logo.png"

# Ember tokens (nettap-design-system/tokens.css)
BG = "#000000"  # --bg
CARD = "#110e0c"  # --card-top (a solid fill: gradients are unreliable in email)
SURFACE_2 = "#161310"  # --surface-2
SURFACE_3 = "#1f1b17"  # --surface-3
LINE = "#26211c"  # --line
TEXT_1 = "#f6f1ec"  # --text-1
TEXT_2 = "#b8afa5"  # --text-2
TEXT_3 = "#938a80"  # --text-3
ACCENT = "#ff7a1a"  # --accent
ACCENT_STRONG = "#ffa35c"  # --accent-strong
SEV_HIGH = "#ff9142"  # --sev-high
SEV_MEDIUM = "#f5c84c"  # --sev-medium
SEV_LOW = "#5aa9ff"  # --sev-low
SEV_INFO = "#a0a0ac"  # --sev-info

_SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
DISPLAY = f"'Sora',{_SANS}"  # --font-display, used only where installed
BODY = f"'Manrope',{_SANS}"  # --font-body
MONO = "ui-monospace,Menlo,Consolas,monospace"  # --font-mono's fallbacks: it repeats per row
# the HTML lists this many outages; the plain-text part lists them all
HTML_INCIDENTS = 20

# Suricata severity → word, shape, colour: SeverityPill's colour + shape + word
_SHAPES = {1: ("▲", SEV_HIGH), 2: ("■", SEV_MEDIUM), 3: ("●", SEV_LOW)}
_OTHER = ("○", SEV_INFO)

_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


@cache
def logo_png() -> bytes | None:
    """The packaged logo, or None (the header then shows the wordmark alone)."""
    try:
        return LOGO_PATH.read_bytes()
    except OSError as exc:
        logger.warning("Report logo unreadable, sending the wordmark alone: %s", exc)
        return None


def render_html(report: dict, logo_cid: str | None) -> str:
    """The whole HTML document. logo_cid: the logo's Content-ID without <>, or None."""
    period = report["period"]
    first, last = (
        date.fromisoformat(period["first"]),
        date.fromisoformat(period["last"]),
    )
    tz = period["tz"]
    noun = _NOUN.get(report.get("frequency"), "period")
    title = heading(report)
    sections = report.get("sections") or {}
    rows = [
        _header(title, f"{_span(first, last)} · times in {tz}", logo_cid),
        _kpis(sections, noun),
        _card(
            "Internet use", sections.get("traffic"), lambda s: _lines(_traffic(s, noun))
        ),
        _card("Alerts", sections.get("alerts"), _alerts),
        _card(
            "New devices", sections.get("new_devices"), lambda s: _new_devices(s, tz)
        ),
        _card("Offline incidents", sections.get("offline"), lambda s: _outages(s, tz)),
        _card(
            "Data cap",
            sections.get("data_cap"),
            lambda s: _lines(_data_cap(s, tz, last)),
        ),
        _footer(),
    ]
    return (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">'
        f"<title>NetTap {e(title.lower())}</title></head>"
        f'<body style="margin:0;padding:0;background:{BG}" bgcolor="{BG}">'
        f'<table {_TABLE} bgcolor="{BG}" style="background:{BG}"><tr>'
        '<td align="center" style="padding:24px 12px">'
        '<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'border="0"><tr><td><![endif]-->'
        f'<table {_TABLE} style="max-width:600px">{"".join(rows)}</table>'
        "<!--[if mso]></td></tr></table><![endif]-->"
        "</td></tr></table></body></html>"
    )


# --- building blocks ---------------------------------------------------------------


def _p(text: str, style: str = "") -> str:
    return f'<p style="margin:0 0 6px;{style}">{e(text)}</p>'


def _lines(lines: list[str]) -> str:
    """report_text's lines as paragraphs: an item marker goes, a "Label: value" label is muted."""
    out = []
    for line in lines:
        text = line.strip().removeprefix("- ")
        label, sep, rest = text.partition(": ")
        if sep and label[:1].isupper() and len(label) <= 40:
            out.append(
                f'<p style="margin:0 0 6px"><span style="color:{TEXT_2}">{e(label)}:</span> '
                f"{e(rest)}</p>"
            )
        else:
            out.append(_p(text))
    return "".join(out)


def _box(inner: str, pad: str = "20px") -> str:
    return (
        f'<table {_TABLE} bgcolor="{CARD}" style="background:{CARD};border:1px solid {LINE};'
        f'border-radius:16px"><tr><td style="padding:{pad};font-family:{BODY};font-size:15px;'
        f'line-height:1.5;color:{TEXT_1};word-break:break-word">{inner}</td></tr></table>'
    )


def _row(inner: str) -> str:
    return f'<tr><td style="padding:0 0 12px">{inner}</td></tr>'


def _header(title: str, subtitle: str, logo_cid: str | None) -> str:
    # alt="" because the wordmark beside it already reads "NetTap"
    logo = (
        f'<td style="padding-right:10px;vertical-align:middle"><img src="cid:{e(logo_cid)}" '
        'width="32" height="32" alt="" style="display:block;border:0"></td>'
        if logo_cid
        else ""
    )
    return (
        '<tr><td style="padding:0 4px 20px">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{logo}'
        f'<td style="vertical-align:middle;font-family:{DISPLAY};font-weight:600;font-size:18px;'
        f'color:{TEXT_1}">NetTap</td></tr></table>'
        f'<h1 style="margin:20px 0 4px;font-family:{DISPLAY};font-weight:300;font-size:30px;'
        f'line-height:1.2;color:{TEXT_1}">{e(title)}</h1>'
        f'<p style="margin:0;font-family:{BODY};font-size:14px;color:{TEXT_2}">{e(subtitle)}</p>'
        "</td></tr>"
    )


def _ok(section: object) -> bool:
    return isinstance(section, dict) and section.get("status") in ("ok", "partial")


def _kpis(sections: dict, noun: str) -> str:
    traffic, alerts = sections.get("traffic"), sections.get("alerts")
    devices, offline = sections.get("new_devices"), sections.get("offline")
    tiles = [
        _tile(
            "Internet use",
            *(_traffic_kpi(traffic, noun) if _ok(traffic) else ("–", "Not available")),
        ),
        _tile(
            "Alerts", *(_alerts_kpi(alerts) if _ok(alerts) else ("–", "Not available"))
        ),
        _tile(
            "New devices",
            *(_devices_kpi(devices) if _ok(devices) else ("–", "Not available")),
        ),
        _tile(
            "Offline incidents",
            *(_offline_kpi(offline) if _ok(offline) else ("–", "Not available")),
        ),
    ]
    cell = '<td width="50%" style="padding:{};vertical-align:top">{}</td>'
    grid = "".join(
        f"<tr>{cell.format('0 6px 12px 0', left)}{cell.format('0 0 12px 6px', right)}</tr>"
        for left, right in (tiles[:2], tiles[2:])
    )
    return f'<tr><td style="padding:0"><table {_TABLE}>{grid}</table></td></tr>'


def _tile(label: str, value: str, sub: str) -> str:
    return _box(
        f'<div style="font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;'
        f'color:{TEXT_3}">{e(label)}</div>'
        f'<div style="padding-top:6px;font-family:{DISPLAY};font-weight:300;font-size:26px;'
        f'line-height:1.2">{e(value)}</div>'
        f'<div style="padding-top:2px;font-size:13px;color:{TEXT_2}">{sub}</div>',
        pad="16px",
    )


def _traffic_kpi(s: dict, noun: str) -> tuple[str, str]:
    return _gb(s["total"]), e(
        "Provisional total" if s["provisional"] else f"This {noun}"
    )


def _alerts_kpi(s: dict) -> tuple[str, str]:
    return f"{s['total']:,}", _chip(1, f"{s['by_severity']['1']:,} high", plain=True)


def _devices_kpi(s: dict) -> tuple[str, str]:
    count = s["count"]
    at_least = "At least " if s.get("truncated") and count else ""
    return f"{at_least}{count:,}", e("Seen for the first time")


def _offline_kpi(s: dict) -> tuple[str, str]:
    watched = s.get("watched_now")
    sub = f"{watched:,} watched now" if watched is not None else "Watched devices only"
    return f"{len(s['incidents']):,}", e(sub)


def _card(title: str, section: object, render) -> str:
    head = (
        f'<h2 style="margin:0 0 14px;font-family:{DISPLAY};font-weight:500;font-size:18px;'
        f'color:{TEXT_1}">{e(title)}</h2>'
    )
    if not _ok(section):
        note = section.get("note") if isinstance(section, dict) else None
        return _row(
            _box(
                head
                + _p(
                    f"Not available this time. {note or ''}".rstrip(), f"color:{TEXT_2}"
                )
            )
        )
    foot = f"Coverage: {section['coverage']}."
    if section["status"] == "partial" and section.get("note"):
        foot += f" Note: {section['note']}"
    return _row(
        _box(
            head
            + render(section)
            + f'<p style="margin:14px 0 0;padding-top:12px;border-top:1px solid {LINE};'
            f'font-size:12px;color:{TEXT_3}">{e(foot)}</p>'
        )
    )


def _chip(level: object, word: str, plain: bool = False) -> str:
    shape, colour = _SHAPES.get(level, _OTHER)
    mark = f'<span style="color:{colour}" aria-hidden="true">{shape}</span> {e(word)}'
    if plain:
        return mark
    return (
        f'<span style="display:inline-block;margin:0 6px 6px 0;padding:3px 10px;border-radius:999px;'
        f'background:{SURFACE_3};font-size:13px;font-weight:600;color:{TEXT_1}">{mark}</span>'
    )


# --- the sections -------------------------------------------------------------------


def _alerts(s: dict) -> str:
    sev = s["by_severity"]
    chips = [
        _chip(1, f"{sev['1']:,} high"),
        _chip(2, f"{sev['2']:,} medium"),
        _chip(3, f"{sev['3']:,} low"),
    ]
    if sev["other"]:
        chips.append(_chip(None, f"{sev['other']:,} other"))
    parts = [
        _p(_count(s["total"], "alert")),
        f'<div style="padding:4px 0 10px">{"".join(chips)}</div>',
    ]
    parts.append(_days(s["days"]))
    worst = s.get("worst")
    if worst is None:
        parts.append(
            _p(f"Worst rules: {s.get('worst_note') or 'Not included this time.'}")
        )
    elif worst:
        parts.append(_worst(worst))
    return "".join(parts)


def _days(days: list[dict]) -> str:
    """Weekday, a bar scaled to the busiest day (none when every day is 0), the count, the note."""
    top = max((d["count"] for d in days), default=0)
    rows = []
    for d in days:
        shown, why = day_count(d)
        pct = round(d["count"] * 100 / top) if top else 0
        fill = (
            f'<td width="{max(pct, 1)}%" height="8" bgcolor="{ACCENT}" style="background:{ACCENT};'
            'border-radius:999px;font-size:0;line-height:0">&nbsp;</td>'
            if d["count"]
            else ""
        )
        bar = (
            f'<table {_TABLE} bgcolor="{SURFACE_2}" style="background:{SURFACE_2};border-radius:999px">'
            f'<tr>{fill}<td height="8" style="font-size:0;line-height:0">&nbsp;</td></tr></table>'
        )
        rows.append(
            f'<tr><td width="92" style="padding:5px 0;font-size:13px;color:{TEXT_2};white-space:nowrap">'
            f'{e(_weekday(d["date"]))}</td><td style="padding:5px 10px">{bar}</td>'
            f'<td width="56" align="right" style="padding:5px 0;font-size:13px;'
            f'font-variant-numeric:tabular-nums">{e(shown)}</td></tr>'
        )
        if why:
            rows.append(
                f'<tr><td colspan="3" style="padding:0 0 4px;font-size:12px;color:{TEXT_3}">{e(why)}</td></tr>'
            )
    return f'<table {_TABLE} style="margin:0 0 8px">{"".join(rows)}</table>'


def _worst(worst: list[dict]) -> str:
    out = [
        f'<p style="margin:14px 0 4px;font-size:11px;font-weight:600;letter-spacing:0.08em;'
        f'text-transform:uppercase;color:{TEXT_3}">Worst rules</p>'
    ]
    for n, (w, (what, todo)) in enumerate(zip(worst, explanations(worst)), 1):
        out.append(
            f'<div style="padding:12px 0;border-top:1px solid {LINE}">'
            f'<div style="font-family:{MONO};font-size:13px;color:{TEXT_1}">{n}. {e(clean(w["rule"]))}</div>'
            f'<div style="padding:6px 0 0">{_chip(w["severity"], _severity(w["severity"]))}'
            f'<span style="font-size:13px;color:{TEXT_2}">{e(_count(w["count"], "alert"))}</span></div>'
        )
        if what:
            out.append(_p(what, f"font-size:14px;color:{TEXT_2}"))
        if todo:
            out.append(
                f'<div style="margin-top:6px;padding:10px 12px;border-radius:10px;background:{SURFACE_2}">'
                f'<div style="font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;'
                f'color:{ACCENT_STRONG}">What to do</div>'
                f'<div style="padding-top:2px;font-size:14px">{e(todo)}</div></div>'
            )
        out.append("</div>")
    return "".join(out)


def _new_devices(s: dict, tz: str) -> str:
    count, listed = s["count"], s["listed"]
    at_least = "At least " if s.get("truncated") else ""
    parts = [
        _p(
            f"{at_least}{_count(count, 'device')} seen for the first time."
            if count
            else "No new devices were recorded."
        )
    ]
    rows = []
    for d in listed:
        mac = clean(d["mac"])
        name = clean(d["name"]) if d.get("name") else ""
        title = (
            f'<div style="font-weight:600">{e(name)}</div>'
            if name
            else f'<div style="font-family:{MONO};font-size:14px">{e(mac)}</div>'
        )
        vendor = (
            f'<div style="font-size:13px;color:{TEXT_2}">{e(clean(d["vendor"]))}</div>'
            if d.get("vendor")
            else ""
        )
        sub_mac = (
            f'<div style="font-family:{MONO};font-size:12px;color:{TEXT_3}">{e(mac)}</div>'
            if name
            else ""
        )
        ip = (
            f'<div style="font-family:{MONO};font-size:13px;word-break:break-all">{e(clean(d["ip"]))}</div>'
            if d.get("ip")
            else ""
        )
        rows.append(
            f'<tr><td style="padding:10px 0;border-top:1px solid {LINE};vertical-align:top">{title}{vendor}{sub_mac}</td>'
            f'<td width="150" align="right" style="padding:10px 0 10px 12px;border-top:1px solid {LINE};vertical-align:top">'
            f'{ip}<div style="font-size:12px;color:{TEXT_3}">First seen {e(_local(d["first_seen"], tz))}</div></td></tr>'
        )
    if rows:
        parts.append(f"<table {_TABLE}>{''.join(rows)}</table>")
    if count > len(listed):
        parts.append(
            _p(
                f"and {count - len(listed):,} more: see Devices in NetTap.",
                f"padding-top:8px;color:{TEXT_2}",
            )
        )
    return "".join(parts)


def _outages(s: dict, tz: str) -> str:
    """_offline's lines (a summary, one per outage, then Watched now) with the outages cut to
    HTML_INCIDENTS, so a flapping device can't push the page past Gmail's clipping size."""
    lines, n = _offline(s, tz), len(s["incidents"])
    if n > HTML_INCIDENTS:
        more = f"and {n - HTML_INCIDENTS:,} more: see the Reports page in NetTap."
        lines = [*lines[: 1 + HTML_INCIDENTS], more, *lines[1 + n :]]
    return _lines(lines)


def _footer() -> str:
    return (
        f'<tr><td style="padding:8px 4px 0;font-family:{BODY};font-size:13px;line-height:1.6;color:{TEXT_2}">'
        + _p(POSTURE_LINE)
        + _p(
            "The full report and its history are on the Reports page in NetTap.",
            f"color:{TEXT_3}",
        )
        + _p(RECIPIENT_LINE, f"color:{TEXT_3}")
        + "</td></tr>"
    )
