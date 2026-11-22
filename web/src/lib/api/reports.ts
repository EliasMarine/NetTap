/**
 * Client-side API helpers for scheduled report endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 *
 * NET-340 (the weekly report): every helper throws on failure with the daemon's own sentence
 * (a 409's "A report is being sent. Try again in a minute.") and the HTTP status, so a failure
 * never reads as "no schedules". Shapes: plans/2026-11-21-weekly-report.contract.md.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// OLD CODE START — NET-340: the schedule reply carries the weekly report's state too
// export interface ReportSchedule {
// 	id: string;
// 	name: string;
// 	frequency: string;
// 	format: string;
// 	recipients: string[];
// 	sections: string[];
// 	enabled: boolean;
// 	last_run: string | null;
// 	next_run: string | null;
// 	created_at: string;
// }
// OLD CODE END

/** A schedule's delivery: `pending` appears only on a report that is still being sent. */
export type DeliveryResult = 'sent' | 'partly_sent' | 'failed' | 'not_configured' | 'not_emailed' | 'unknown' | 'pending';
export type SectionStatus = 'ok' | 'partial' | 'unavailable';

/** Local dates (YYYY-MM-DD) in the ledger's zone, both inclusive. */
export interface ReportPeriod {
	first: string;
	last: string;
}

export interface ReportSchedule {
	id: string;
	name: string;
	frequency: string;
	format: string;
	recipients: string[];
	sections: string[];
	enabled: boolean;
	last_run: string | null;
	next_run: string | null;
	created_at: string;
	rev: number;
	/** Sent back with a confirming save, so it confirms exactly the settings shown. */
	confirm_token: string;
	/** 0 = Monday … 6 = Sunday. */
	weekday: number;
	hour: number;
	/** The ledger's zone: every schedule's weekday and hour are in it. */
	tz: string;
	next_send: string | null;
	confirmed: boolean;
	/** Changed without a confirming save, so it sends nothing until saved again. */
	needs_review: boolean;
	/** The one schedule the Settings card manages. */
	card: boolean;
	/** A report is being emailed right now. */
	sending: boolean;
	last_period: ReportPeriod | null;
	last_delivery: { result: DeliveryResult; at: string; report_id?: string } | null;
}

export interface ScheduleList {
	schedules: ReportSchedule[];
	/** The ledger's zone, when the daemon sends it (so the card can name it before any schedule exists). */
	tz?: string;
}

/** What a create or update may send. `sections` is left out: the daemon refuses it (every email has all five). */
export interface ScheduleInput {
	name?: string;
	frequency?: string;
	recipients?: string[];
	enabled?: boolean;
	weekday?: number;
	hour?: number;
	rev?: number;
	confirm?: boolean;
	confirm_token?: string;
}

/** The Settings card's save: always a confirmation; the token and rev only once the schedule exists. */
export interface ReportCardInput {
	enabled: boolean;
	weekday: number;
	hour: number;
	recipients: string[];
	confirm: true;
	confirm_token?: string;
	rev?: number;
}

export type SectionKey = 'traffic' | 'alerts' | 'new_devices' | 'offline' | 'data_cap';

export interface ReportSummary {
	id: string;
	schedule_id: string;
	trigger: 'scheduled' | 'manual';
	period: ReportPeriod;
	generated_at: string;
	delivery: { result: DeliveryResult };
	status: Record<SectionKey, SectionStatus>;
}

interface SectionBase {
	status: SectionStatus;
	coverage: string;
	note: string | null;
}

export interface TrafficSection extends SectionBase {
	download: number;
	upload: number;
	total: number;
	local: number;
	/** Counted under the current exclusions: never too high. */
	counted_total: number;
	provisional: boolean;
	days_covered: number;
	days_total: number;
	busiest: { date: string; total: number } | null;
	/** A day without figures has null download, upload and total (never 0). */
	days: { date: string; download: number | null; upload: number | null; total: number | null; covered: boolean }[];
}

export type StoredDay = 'full' | 'partial' | 'absent' | 'unknown';

export interface WorstRule {
	rule: string;
	/** Suricata's 1 high … 3 low; null when unknown. */
	severity: number | null;
	count: number;
	family: string;
	what: string;
	risk: string;
	todo: string;
}

export interface AlertsSection extends SectionBase {
	total: number;
	by_severity: { '1': number; '2': number; '3': number; other: number };
	days: { date: string; count: number; stored: StoredDay }[];
	/** [] when there were no alerts; null, with `worst_note` saying why, when the ranking was left out. */
	worst: WorstRule[] | null;
	worst_note: string | null;
}

export interface NewDevicesSection extends SectionBase {
	count: number;
	listed: { mac: string; name: string | null; vendor: string | null; ip: string | null; first_seen: string }[];
	examined_from: string | null;
	truncated: boolean;
}

export type IncidentState = 'returned' | 'returned_unrecorded' | 'still_offline' | 'return_unrecorded';

export interface OfflineSection extends SectionBase {
	/** `name` is null for a device with no name (show the MAC). */
	incidents: { mac: string; name: string | null; from: string; to: string | null; minutes: number | null; state: IncidentState; detail: string | null }[];
	watched_now: number | null;
}

export interface DataCapSection extends SectionBase {
	cap_bytes: number | null;
	month: string;
	used_counted: number;
	used_provisional: number;
	percent: number | null;
	days_counted: number;
	days_so_far: number;
	/** null when the journal couldn't be read. */
	crossings: { month: string; threshold: 80 | 100 | 'projected'; cap: number; at: string }[] | null;
}

/** An `unavailable` section is only its status, coverage and note: none of its own fields. */
export interface ReportSections {
	traffic: Partial<TrafficSection> & SectionBase;
	alerts: Partial<AlertsSection> & SectionBase;
	new_devices: Partial<NewDevicesSection> & SectionBase;
	offline: Partial<OfflineSection> & SectionBase;
	data_cap: Partial<DataCapSection> & SectionBase;
}

export interface Report {
	id: string;
	schedule_id: string;
	schedule_name: string;
	trigger: 'scheduled' | 'manual';
	frequency: string;
	period: ReportPeriod & { start: string; end: string; tz: string; days: number };
	generated_at: string;
	duration_s: number;
	delivery: { result: DeliveryResult; at: string | null; recipients: number; refused: number; error: string | null };
	sections: ReportSections;
}

/** A failed request: the daemon's sentence when it sent one, with the HTTP status (0 when unreachable). */
export class ReportsError extends Error {
	readonly status: number;

	constructor(message: string, status: number) {
		super(message);
		this.status = status;
	}
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/** The parsed reply, or a ReportsError with a reason fit to show. */
async function call<T>(url: string, init?: RequestInit): Promise<T> {
	let res: Response;
	try {
		res = await fetch(url, init);
	} catch {
		throw new ReportsError("Couldn't reach NetTap. Check the connection and try again.", 0);
	}
	if (!res.ok) {
		const body = await res.json().catch(() => null);
		throw new ReportsError(body && typeof body.error === 'string' ? body.error : `NetTap answered HTTP ${res.status}.`, res.status);
	}
	return res.json();
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };
const scheduleUrl = (id: string) => `/api/reports/schedules/${encodeURIComponent(id)}`;

/**
 * Get all report schedules.
 */
// OLD CODE START — NET-340: a failed request read as "no schedules"
// export async function getReportSchedules(): Promise<{ schedules: ReportSchedule[] }> {
// 	const res = await fetch('/api/reports/schedules');
//
// 	if (!res.ok) {
// 		return { schedules: [] };
// 	}
//
// 	return res.json();
// }
// OLD CODE END
export function getReportSchedules(): Promise<ScheduleList> {
	return call('/api/reports/schedules');
}

/**
 * Create a new report schedule.
 */
// OLD CODE START — NET-340: helpers throw on failure
// export async function createReportSchedule(
// 	data: Partial<ReportSchedule>
// ): Promise<ReportSchedule | null> {
// 	const res = await fetch('/api/reports/schedules', {
// 		method: 'POST',
// 		headers: { 'Content-Type': 'application/json' },
// 		body: JSON.stringify(data),
// 	});
//
// 	if (!res.ok) {
// 		return null;
// 	}
//
// 	return res.json();
// }
// OLD CODE END
export function createReportSchedule(data: ScheduleInput): Promise<ReportSchedule> {
	return call('/api/reports/schedules', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data) });
}

/**
 * Get a single report schedule by ID.
 */
// OLD CODE START — NET-340: helpers throw on failure
// export async function getReportSchedule(id: string): Promise<ReportSchedule | null> {
// 	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}`);
//
// 	if (!res.ok) {
// 		return null;
// 	}
//
// 	return res.json();
// }
// OLD CODE END
export function getReportSchedule(id: string): Promise<ReportSchedule> {
	return call(scheduleUrl(id));
}

/**
 * Update an existing report schedule.
 */
// OLD CODE START — NET-340: helpers throw on failure
// export async function updateReportSchedule(
// 	id: string,
// 	data: Partial<ReportSchedule>
// ): Promise<ReportSchedule | null> {
// 	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}`, {
// 		method: 'PUT',
// 		headers: { 'Content-Type': 'application/json' },
// 		body: JSON.stringify(data),
// 	});
//
// 	if (!res.ok) {
// 		return null;
// 	}
//
// 	return res.json();
// }
// OLD CODE END
export function updateReportSchedule(id: string, data: ScheduleInput): Promise<ReportSchedule> {
	return call(scheduleUrl(id), { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(data) });
}

/**
 * Delete a report schedule.
 */
// OLD CODE START — NET-340: helpers throw on failure
// export async function deleteReportSchedule(id: string): Promise<boolean> {
// 	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}`, {
// 		method: 'DELETE',
// 	});
//
// 	return res.ok;
// }
// OLD CODE END
export async function deleteReportSchedule(id: string): Promise<void> {
	await call(scheduleUrl(id), { method: 'DELETE' });
}

/**
 * Enable a report schedule.
 */
// OLD CODE START — NET-340: helpers throw on failure
// export async function enableSchedule(id: string): Promise<boolean> {
// 	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}/enable`, {
// 		method: 'POST',
// 	});
//
// 	return res.ok;
// }
// OLD CODE END
export async function enableSchedule(id: string): Promise<void> {
	await call(`${scheduleUrl(id)}/enable`, { method: 'POST' });
}

/**
 * Disable a report schedule.
 */
// OLD CODE START — NET-340: helpers throw on failure
// export async function disableSchedule(id: string): Promise<boolean> {
// 	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}/disable`, {
// 		method: 'POST',
// 	});
//
// 	return res.ok;
// }
// OLD CODE END
export async function disableSchedule(id: string): Promise<void> {
	await call(`${scheduleUrl(id)}/disable`, { method: 'POST' });
}

/**
 * Generate a report on-demand from a schedule.
 */
// OLD CODE START — NET-340: helpers throw on failure (the 409 "A report is being generated" must reach the page)
// export async function generateReport(id: string): Promise<Record<string, unknown> | null> {
// 	const res = await fetch(`/api/reports/generate/${encodeURIComponent(id)}`, {
// 		method: 'POST',
// 	});
//
// 	if (!res.ok) {
// 		return null;
// 	}
//
// 	return res.json();
// }
// OLD CODE END
/** The latest completed period, stored as a manual report and not emailed. */
export function generateReport(id: string): Promise<Report> {
	return call(`/api/reports/generate/${encodeURIComponent(id)}`, { method: 'POST' });
}

/** Saves the Settings card's schedule, creating it on the first save. */
export function upsertReportCard(data: ReportCardInput): Promise<ReportSchedule> {
	return call('/api/reports/card', { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify(data) });
}

/** One schedule's reports (every schedule's without an id), newest first, without their sections. */
export function getReportHistory(scheduleId?: string): Promise<{ reports: ReportSummary[] }> {
	const query = scheduleId ? `?schedule=${encodeURIComponent(scheduleId)}` : '';
	return call(`/api/reports/history${query}`);
}

/** One stored report, sections included. */
export function getReport(scheduleId: string, reportId: string): Promise<Report> {
	return call(`/api/reports/history/${encodeURIComponent(scheduleId)}/${encodeURIComponent(reportId)}`);
}
