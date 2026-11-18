/**
 * The Bandwidth page's words for the usage ledger (F4, NET-329): day labels, what each day status
 * means, and the month card's subtitle (plan §4.6). Moved out of +page.svelte with formatDate and
 * monthName, which they need.
 */
import type { UsageDay, UsageDayStatus, UsageMonth } from '$lib/api/usage';
import { formatWhen } from '$lib/utils/drilldown';

export function formatDate(dateStr: string): string {
	try {
		const d = new Date(dateStr);
		// OLD CODE START — 2026-11-01: local time shifted each UTC-midnight bucket back a day west of UTC
		// return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
		// OLD CODE END
		// A day is its date (F4: the ledger's local YYYY-MM-DD, which parses as UTC midnight), so label it in UTC
		// OLD CODE: return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }); (NET-192 PR 4: "Nov 6" in a US browser; the app writes en-GB)
		return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric', timeZone: 'UTC' });
	} catch {
		return dateStr;
	}
}

/** "November 2026" for the daemon's year and 1-based month. */
export const monthName = (year: number, month: number) =>
	new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });

/** What a day's status means, for its tooltip and the chart's note; '' for a final day */
export const STATUS_WORDS: Record<UsageDayStatus, string> = {
	future: '',
	counted: '',
	not_counted: 'not counted',
	stale: 'not updated lately',
	pending: 'still counting',
	recount_pending: 'waiting for a recount',
	old_rules: 'counted under earlier exclusions',
	approximate: 'approximate',
};

/** "November 2026, Europe/London", then each caveat the month's days carry */
export function monthNote(m: UsageMonth): string {
	const has = (...statuses: UsageDayStatus[]) => m.days.some((d) => statuses.includes(d.status));
	return [
		`${monthName(m.year, m.month)}, ${m.tz}`,
		m.since && m.days.length > 0 && m.since > m.days[0].date && `Since ${formatDate(m.since)}`,
		has('pending', 'recount_pending') && 'Still counting',
		has('approximate') && 'Approximate: some raw data was cleared before the day was final',
		has('old_rules') && 'Counted under earlier exclusions',
		has('stale') && (m.updated_at ? `Not updated since ${formatWhen(m.updated_at)}` : 'Not updated yet'),
	]
		.filter(Boolean)
		.join(' · ');
}

/** The days that aren't final, by status: "Approximate: 3 Nov, 4 Nov" (more than three: "18 days"); '' when all are */
export function notFinalLine(days: readonly UsageDay[]): string {
	const byStatus = new Map<string, string[]>();
	for (const d of days) {
		const words = STATUS_WORDS[d.status];
		if (words) byStatus.set(words, [...(byStatus.get(words) ?? []), formatDate(d.date)]);
	}
	return [...byStatus]
		.map(([words, dates]) => `${words.charAt(0).toUpperCase()}${words.slice(1)}: ${dates.length > 3 ? `${dates.length} days` : dates.join(', ')}`)
		.join(' · ');
}
