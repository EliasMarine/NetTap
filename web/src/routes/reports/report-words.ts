/**
 * The Reports page's words (NET-340): periods, times in the ledger's zone, delivery and section
 * states, and the KPI lines. Figures come only from the daemon's reply; these only phrase them.
 */
import type { AlertsSection, DataCapSection, DeliveryResult, IncidentState, Report, ReportPeriod, ReportSchedule, SectionStatus, StoredDay } from '$lib/api/reports';
import { fmt } from '$lib/utils/drilldown';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** A local YYYY-MM-DD as [year, month index, day], or null when it isn't one. */
function parts(date: string): [number, number, number] | null {
	const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
	return m ? [Number(m[1]), Number(m[2]) - 1, Number(m[3])] : null;
}

/** "10–16 Nov 2026", "27 Oct – 2 Nov 2026", "16 Nov 2026"; the dates as given when they aren't dates. */
export function periodWords({ first, last }: ReportPeriod): string {
	const a = parts(first);
	const b = parts(last);
	if (!a || !b) return `${first} to ${last}`;
	const [y1, m1, d1] = a;
	const [y2, m2, d2] = b;
	if (first === last) return `${d2} ${MONTHS[m2]} ${y2}`;
	if (y1 === y2 && m1 === m2) return `${d1}–${d2} ${MONTHS[m2]} ${y2}`;
	if (y1 === y2) return `${d1} ${MONTHS[m1]} – ${d2} ${MONTHS[m2]} ${y2}`;
	return `${d1} ${MONTHS[m1]} ${y1} – ${d2} ${MONTHS[m2]} ${y2}`;
}

/** A local date as "Thu 12 Nov" (the day it names, whatever the browser's zone). */
export function dayWords(date: string): string {
	const p = parts(date);
	if (!p) return date;
	return new Date(Date.UTC(...p)).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
}

const DAY_OPTS: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' };
const CLOCK_OPTS: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };

/** An ISO instant written in `tz`; the input as given when it isn't a date, "—" when there is none. */
function inZone(iso: string | null | undefined, tz: string | undefined, opts: Intl.DateTimeFormatOptions): string {
	if (!iso) return '—';
	const d = new Date(iso);
	if (!Number.isFinite(d.getTime())) return iso;
	try {
		return d.toLocaleString('en-GB', { ...opts, timeZone: tz });
	} catch {
		// an unknown zone name: the browser's own zone rather than nothing
		return d.toLocaleString('en-GB', opts);
	}
}

/** An instant in the ledger's zone, where the schedule's weekday and hour live: "Mon 24 Nov, 08:00". */
export const zonedTime = (iso: string | null | undefined, tz: string | undefined): string => inZone(iso, tz, { ...DAY_OPTS, ...CLOCK_OPTS });
/** Its date alone, "24 Nov": a KPI's value, which a weekday would wrap at a quarter of the page. */
export const zonedDay = (iso: string | null | undefined, tz: string | undefined): string => inZone(iso, tz, { day: 'numeric', month: 'short' });
/** Its weekday and clock, "Mon 08:00": the KPI's note under that date. */
export const zonedClock = (iso: string | null | undefined, tz: string | undefined): string => inZone(iso, tz, { weekday: 'short', ...CLOCK_OPTS });

export const DELIVERY_WORDS: Record<DeliveryResult, string> = {
	sent: 'Sent',
	partly_sent: 'Partly sent',
	failed: 'Failed',
	not_configured: 'Email not set up',
	not_emailed: 'Not emailed',
	unknown: 'Unknown: NetTap stopped while sending',
	pending: 'Sending…',
};

/** A result an older or newer daemon sends that this page doesn't know reads as itself. */
export const deliveryWords = (result: string): string => DELIVERY_WORDS[result as DeliveryResult] ?? result;

export const TRIGGER_WORDS: Record<string, string> = { scheduled: 'Scheduled', manual: 'Manual' };

/** A section's state as a chip: words plus the chip's colour class. */
export const STATUS_CHIP: Record<SectionStatus, { text: string; cls: string }> = {
	ok: { text: 'Complete', cls: 'is-ok' },
	partial: { text: 'Partial', cls: 'is-caution' },
	unavailable: { text: 'Unavailable', cls: 'is-bad' },
};

/** What a day's alert count can't show by itself; '' for a fully stored day with alerts. */
export function dayNote(day: { count: number; stored: StoredDay }): string {
	if (day.stored === 'partial') return 'Only part of this day is stored';
	if (day.stored === 'absent') return 'Not stored';
	if (day.stored === 'unknown') return "Couldn't check what is stored";
	return day.count === 0 ? "No alerts recorded: a quiet day, or Suricata wasn't running" : '';
}

/** Days whose alerts are fully stored, out of the period's days, or null without the day list. */
export function storedDays(alerts: Partial<AlertsSection> | undefined): string | null {
	if (!alerts?.days?.length) return null;
	return `${fmt(alerts.days.filter((d) => d.stored === 'full').length)} of ${fmt(alerts.days.length)} days of alerts stored`;
}

/** A count with its noun: "1 address", "3 addresses". */
export const countOf = (n: number, one: string, many: string): string => `${fmt(n)} ${n === 1 ? one : many}`;

export interface Kpi {
	value: string;
	note?: string;
	sub?: string;
}

/** Next report: when it is due, or why nothing is. */
export function nextReportKpi(schedule: ReportSchedule | null): Kpi {
	if (!schedule) return { value: 'Not set up', note: 'Turn it on in Settings' };
	if (!schedule.enabled) return { value: 'Off', note: 'Turn it on in Settings' };
	if (schedule.needs_review) return { value: 'Paused', note: 'Check the recipients and save in Settings' };
	if (!schedule.next_send) return { value: '—', note: schedule.tz };
	return { value: zonedDay(schedule.next_send, schedule.tz), note: `${zonedClock(schedule.next_send, schedule.tz)} · ${schedule.tz}` };
}

/** Last sent and Delivery: the schedule's last delivery and where it goes. */
export function deliveryKpis(schedule: ReportSchedule | null): { last: Kpi; delivery: Kpi } {
	const last = schedule?.last_delivery ?? null;
	const to = !schedule
		? undefined
		: schedule.sending
			? 'Sending now'
			: schedule.recipients.length
				? `To ${countOf(schedule.recipients.length, 'address', 'addresses')}`
				: 'No recipients: kept here, not emailed';
	return {
		last: {
			value: last ? zonedDay(last.at, schedule?.tz) : schedule ? 'Never' : '—',
			note: [last && zonedClock(last.at, schedule?.tz), schedule?.last_period && periodWords(schedule.last_period)].filter(Boolean).join(' · ') || undefined,
		},
		delivery: { value: last ? deliveryWords(last.result) : '—', note: to },
	};
}

/** Days covered: the shown report's counted days of internet use, with its stored alert days beside. */
export function daysCoveredKpi(report: Report | null): Kpi {
	const traffic = report?.sections.traffic;
	if (!report || traffic?.days_covered == null || traffic.days_total == null) return { value: '—', note: report ? 'Internet use not counted' : undefined };
	return {
		value: `${fmt(traffic.days_covered)} of ${fmt(traffic.days_total)}`,
		note: `Days of internet use counted, ${periodWords(report.period)}`,
		sub: storedDays(report.sections.alerts) ?? undefined,
	};
}

/** "42 min", "3 h 5 min", "2 d 4 h"; "—" when unknown. */
export function durationWords(minutes: number | null | undefined): string {
	if (minutes == null || !Number.isFinite(minutes)) return '—';
	const m = Math.max(0, Math.round(minutes));
	if (m < 60) return `${m} min`;
	if (m < 1440) return m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m / 60} h`;
	const h = Math.floor((m % 1440) / 60);
	return h ? `${Math.floor(m / 1440)} d ${h} h` : `${Math.floor(m / 1440)} d`;
}

const PERIOD_NOUN: Record<string, string> = { daily: 'that day', weekly: 'this week', monthly: 'this month' };
/** The report's period in a sentence: "No alerts this week." */
export const periodNoun = (frequency: string): string => PERIOD_NOUN[frequency] ?? 'in this period';

/** One data cap warning the journal recorded: a threshold passed, or the month on track to go over. */
export function crossingWords(x: NonNullable<DataCapSection['crossings']>[number], tz: string): string {
	return x.threshold === 'projected'
		? `On track to go over ${gb(x.cap)}, noted ${zonedTime(x.at, tz)}.`
		: `Passed ${x.threshold}% of ${gb(x.cap)} on ${zonedTime(x.at, tz)}.`;
}

/** An incident's end when it has no time of its own. */
export const UNRECORDED_END: Partial<Record<IncidentState, string>> = {
	still_offline: 'Still offline',
	return_unrecorded: 'Return time not recorded',
	returned_unrecorded: 'Returned, time not recorded',
};

/**
 * Decimal GB with up to one decimal ("1,000 GB", "82.4 GB"). `floor` for a lower bound, so an
 * "at least" figure is never rounded above what was counted.
 */
export function gb(bytes: number | null | undefined, floor = false): string {
	if (bytes == null || !Number.isFinite(bytes)) return '—';
	const tenths = floor ? Math.floor(bytes / 1e8) : Math.round(bytes / 1e8);
	return `${(tenths / 10).toLocaleString('en-GB', { maximumFractionDigits: 1 })} GB`;
}
