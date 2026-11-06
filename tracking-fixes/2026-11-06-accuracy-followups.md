# 2026-11-06 — Threat score states its scale; ping says when it didn't finish; Changelog offers only recorded types (NET-164, NET-169, NET-173)

**Status:** fixed on `fix/accuracy-followups`. The PR is pending. Plan: `plans/2026-11-06-accuracy-followups-net164-169-173.md` (Codex approved in round 2 after 4 findings).

**NET-164: the threat score has no scale**
- **Problem:** the Alerts page showed the score in a ring labelled "threat score", with no scale and no word on how it is worked out. Threats showed "/100" but not the method.
- **Fix:**
  - The ring keeps its default label, "of 100".
  - One sentence, `THREAT_SCORE_HOW` in `web/src/lib/api/alerts.ts`, shows under the Alerts card's chips and as the Threats KPI sub: "Each alert group adds 10 (critical), 5 (high), 2 (medium) or 0.5 (low), rounded down and capped at 100. A busier-than-usual window adds 15 while the score is under 75. The level never exceeds the worst alert."
  - Daemon tests in `daemon/tests/test_smart_alert_paging.py` pin every rule the sentence states: rounding down, the cap, the bonus only under 75, and the level cap.

**NET-169: ping shows blanks when it didn't finish**
- **Problem:** ping printed its header, then failed or was cut short, with no statistics line.
  - `_tool_error` returned None because stdout wasn't empty.
  - `api/tools.py` then defaulted the loss to 100%, so the page showed a made-up "100% loss" with blank round trips and no reason.
- **Fix:** in `ping()` (`daemon/services/network_diag_service.py`), a run with no summary line is an error. It carries ping's own stderr, or "Ping didn't finish: it printed no summary". The page shows its error card instead of figures. Traceroute is unchanged.

**NET-173: the Changelog filter offers types that are never recorded**
- **Problem:** only `device_joined` and `storage_pruned` are ever written. The filter came from a `terms` aggregation on `event_type`, which is dynamically mapped as text, so the query failed and the fallback offered all 8 types.
- **Fix:**
  - `CHANGELOG_EVENT_TYPES` lists the two recorded types; the old set is kept as OLD CODE.
  - `get_event_types` returns those two types with no OpenSearch query.
    - **Change from the approved plan:** the plan kept the aggregation on `event_type.keyword`. The repo guard `tests/test_query_field_names.py` forbids `.keyword`, which is right for Malcolm's indices. Malcolm's template covers `arkime_sessions3-*` only, so the changelog index really is dynamically mapped.
    - Dropping the query avoids an exception to the guard. It also removes a round trip, and the filter still offers exactly the recorded types.
  - A `shortcut:` comment on `_index_name` notes that events are filed by the day they're written. A manual date-based cleanup can therefore keep a backdated join a day longer. Changelog has no automatic retention tier.

**Not done here**
- NET-168 (amber "incomplete" on the health strip) needs an owner design decision: the existing `.chip.is-warn` is orange, the failure colour.

**Tests**
- Daemon:
  - two ping tests: header plus stderr, and header with no stderr;
  - the changelog types are the literal two-type list, with no query;
  - four threat-score tests.
- Web: the Alerts ring says "of 100" and shows the sentence; the Threats KPI shows the sentence; a ping reply with HTTP 200 and an `error` shows the error and none of the default figures.

**Lessons**
- A sentence that explains a figure must be pinned by tests of the exact rules it states. Codex caught two wrong claims in the first draft.
- A fallback list that "follows the constant" in tests can't catch the bug it exists to prevent. Assert the literal values.
