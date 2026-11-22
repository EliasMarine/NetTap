/**
 * Fixtures for the weekly report (NET-340, daemon/api/reports.py), reached through the web proxies and
 * the catch-all. Shapes: plans/2026-11-21-weekly-report.contract.md. The populated list puts an
 * API-only daily schedule first, so the page and the card must find the card's schedule by `card`.
 */
import type { Report, ReportSchedule, ReportSummary, ScheduleList } from '../../../src/lib/api/reports.ts';
import { DAY, iso, type FixtureRoute } from './types.ts';

/** The daemon's words when the rule ranking is left out (report_sections.py `_rank`): they start with "Not included this time". */
export const WORST_LEFT_OUT = 'Not included this time. It ran out of time.';

/** A data cap section with figures and every kind of warning, for the tests that render one. */
export const DATA_CAP_OK = {
	status: 'ok',
	coverage: '15 of 15 days this month counted under the current rules',
	note: null,
	cap_bytes: 1000e9,
	month: '2026-11',
	used_counted: 812.3e9,
	used_provisional: 830.1e9,
	percent: 81.2,
	days_counted: 15,
	days_so_far: 15,
	crossings: [
		{ month: '2026-11', threshold: 80, cap: 1000e9, at: '2026-11-14T09:12:00Z' },
		{ month: '2026-11', threshold: 'projected', cap: 1000e9, at: '2026-11-15T09:00:00Z' },
	],
} satisfies Report['sections']['data_cap'];

const SECTIONS = ['traffic_summary', 'alerts', 'devices'];
const GB = 1e9;

export const CARD_SCHEDULE = {
	id: '6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b',
	name: 'Weekly report',
	frequency: 'weekly',
	format: 'json',
	recipients: ['owner@example.com', 'family@example.com'],
	sections: SECTIONS,
	enabled: true,
	last_run: '2026-11-16T08:00:12Z',
	next_run: iso(-2 * DAY),
	created_at: '2026-10-20T09:14:00Z',
	rev: 3,
	confirm_token: '9f2c4e6a8b0d1f3e5a7c9e1b3d5f7a9c2e4b6d8f0a1c3e5b7d9f1a3c5e7b9d0f',
	weekday: 0,
	hour: 8,
	tz: 'Europe/London',
	next_send: iso(-2 * DAY),
	confirmed: true,
	needs_review: false,
	card: true,
	sending: false,
	last_period: { first: '2026-11-09', last: '2026-11-15' },
	last_delivery: { result: 'sent', at: '2026-11-16T08:00:12Z', report_id: '20261116T080012Z-a1b2c3' },
} satisfies ReportSchedule;

/** An API-only schedule the card must never bind to. */
export const DAILY_SCHEDULE = {
	...CARD_SCHEDULE,
	id: '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d',
	name: 'Daily check',
	frequency: 'daily',
	recipients: ['noc@example.com'],
	rev: 9,
	confirm_token: '0d1c2b3a4f5e6d7c8b9a0f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6b7a8f9e0d1c',
	hour: 6,
	card: false,
	last_period: { first: '2026-11-20', last: '2026-11-20' },
	last_delivery: { result: 'sent', at: '2026-11-21T06:00:04Z', report_id: '20261121T060004Z-d4e5f6' },
} satisfies ReportSchedule;

export const SCHEDULES_EMPTY = { schedules: [], tz: 'Europe/London' } satisfies ScheduleList;
export const SCHEDULES = { schedules: [DAILY_SCHEDULE, CARD_SCHEDULE], tz: 'Europe/London' } satisfies ScheduleList;

const STATUS_OK = { traffic: 'ok', alerts: 'ok', new_devices: 'ok', offline: 'ok', data_cap: 'ok' } as const;

export const HISTORY = {
	reports: [
		{
			id: '20261116T080012Z-a1b2c3',
			schedule_id: CARD_SCHEDULE.id,
			trigger: 'scheduled',
			period: { first: '2026-11-09', last: '2026-11-15' },
			generated_at: '2026-11-16T08:00:12Z',
			delivery: { result: 'sent' },
			status: { ...STATUS_OK, alerts: 'partial', data_cap: 'unavailable' },
		},
		{
			id: '20261112T141530Z-0f9e8d',
			schedule_id: CARD_SCHEDULE.id,
			trigger: 'manual',
			period: { first: '2026-11-02', last: '2026-11-08' },
			generated_at: '2026-11-12T14:15:30Z',
			delivery: { result: 'not_emailed' },
			status: STATUS_OK,
		},
		{
			id: '20261109T080009Z-7c6b5a',
			schedule_id: CARD_SCHEDULE.id,
			trigger: 'scheduled',
			period: { first: '2026-11-02', last: '2026-11-08' },
			generated_at: '2026-11-09T08:00:09Z',
			delivery: { result: 'failed' },
			status: { ...STATUS_OK, traffic: 'partial', offline: 'unavailable' },
		},
	],
} satisfies { reports: ReportSummary[] };

const days = (from: number, counts: number[]) => counts.map((c, i) => ({ date: `2026-11-${String(from + i).padStart(2, '0')}`, c }));

export const REPORT = {
	id: '20261116T080012Z-a1b2c3',
	schedule_id: CARD_SCHEDULE.id,
	schedule_name: 'Weekly report',
	trigger: 'scheduled',
	frequency: 'weekly',
	period: { first: '2026-11-09', last: '2026-11-15', start: '2026-11-09T00:00:00Z', end: '2026-11-16T00:00:00Z', tz: 'Europe/London', days: 7 },
	generated_at: '2026-11-16T08:00:12Z',
	duration_s: 12.4,
	delivery: { result: 'sent', at: '2026-11-16T08:00:14Z', recipients: 2, refused: 0, error: null },
	sections: {
		traffic: {
			status: 'ok',
			coverage: '7 of 7 days counted',
			note: null,
			download: 182.4 * GB,
			upload: 21.6 * GB,
			total: 204 * GB,
			local: 38.2 * GB,
			counted_total: 204 * GB,
			provisional: false,
			days_covered: 7,
			days_total: 7,
			busiest: { date: '2026-11-14', total: 41.2 * GB },
			days: days(9, [24, 27, 26, 29, 31, 41, 26]).map(({ date, c }) => ({ date, download: c * 0.9 * GB, upload: c * 0.1 * GB, total: c * GB, covered: true })),
		},
		alerts: {
			status: 'partial',
			coverage: 'Alerts stored for 6 of 7 days',
			note: 'Only part of Wednesday 11 November is stored.',
			total: 1840,
			by_severity: { '1': 12, '2': 308, '3': 1514, other: 6 },
			days: days(9, [212, 0, 96, 318, 402, 455, 357]).map(({ date, c }, i) => ({ date, count: c, stored: i === 2 ? 'partial' : 'full' })),
			worst: [
				{ rule: 'ET MALWARE Possible Cobalt Strike Beacon Activity', severity: 1, count: 12, family: 'Malware', what: 'A device may be talking to a remote-control server.', risk: 'High', todo: 'Check the device named in the alert.' },
				{ rule: 'ET POLICY Possible External IP Lookup ipinfo.io', severity: 2, count: 204, family: 'Policy', what: 'A device looked up its public address.', risk: 'Low', todo: 'Usually harmless.' },
				{ rule: 'Unnamed rule', severity: null, count: 6, family: 'Unknown', what: 'An alert with no rule name recorded.', risk: 'Unknown', todo: 'Look it up in Alerts.' },
			],
			worst_note: null,
		},
		new_devices: {
			status: 'ok',
			coverage: 'First sightings recorded between 9 Nov 00:00 and 16 Nov 00:00',
			note: null,
			count: 3,
			listed: [
				{ mac: '02:00:5e:10:00:31', name: 'Kitchen speaker', vendor: 'Sonos', ip: '192.168.1.31', first_seen: '2026-11-10T18:22:00Z' },
				{ mac: '02:00:5e:10:00:44', name: null, vendor: 'Espressif', ip: '192.168.1.44', first_seen: '2026-11-12T07:05:00Z' },
				{ mac: '02:00:5e:10:00:52', name: null, vendor: null, ip: null, first_seen: '2026-11-15T21:40:00Z' },
			],
			examined_from: '2026-11-02T00:00:00Z',
			truncated: false,
		},
		offline: {
			status: 'ok',
			coverage: 'Watched devices only',
			note: null,
			incidents: [
				{ mac: '02:00:5e:10:00:20', name: 'Office NAS', from: '2026-11-11T02:10:00Z', to: '2026-11-11T02:52:00Z', minutes: 42, state: 'returned', detail: null },
				{ mac: '02:00:5e:10:00:27', name: 'Garage camera', from: '2026-11-14T16:30:00Z', to: null, minutes: null, state: 'return_unrecorded', detail: 'Return time not recorded' },
				// an unnamed device whose return was only seen later
				{ mac: '02:00:5e:10:00:33', name: null, from: '2026-11-13T22:05:00Z', to: null, minutes: null, state: 'returned_unrecorded', detail: 'Returned before 14 Nov 09:12, time not recorded' },
			],
			watched_now: 3,
		},
		// alerts is the partial section; this is the unavailable one: its status, coverage and note only
		data_cap: { status: 'unavailable', coverage: 'Not available this time', note: 'This section took too long and was left out.' },
	},
} satisfies Report;

export const REPORT_ROUTES: FixtureRoute[] = [
	{ path: '/api/reports/schedules', method: 'GET', empty: SCHEDULES_EMPTY, populated: SCHEDULES },
	{ path: '/api/reports/history', method: 'GET', empty: { reports: [] }, populated: HISTORY },
	// Every listed id answers the same report; the empty history never asks
	{ path: /^\/api\/reports\/history\/[^/]+\/[^/]+$/, method: 'GET', empty: REPORT, populated: REPORT },
];
