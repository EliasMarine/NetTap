/**
 * The Bandwidth page's words for the usage ledger (F4, NET-329): day labels, what each day status
 * means, and the month card's subtitle (plan §4.6). Moved out of +page.svelte with formatDate and
 * monthName, which they need.
 */
import type { UsageDay, UsageDayStatus, UsageMonth } from '$lib/api/usage';
import type { BandwidthCap } from '$lib/api/bandwidth';
import { formatWhen } from '$lib/utils/drilldown';

/** Decimal GB (10^9 bytes, as ISPs state caps), one decimal: "82.4 GB". Moved from +page.svelte (F6) so Settings' cap card says the same. */
export const formatGB = (bytes: number): string => `${(bytes / 1e9).toFixed(1)} GB`;

/**
 * Settings › Network's use line for the cap reply (F6, NET-339), with a figure that is never too high:
 * a complete month's total; otherwise the lower bound, as "at least", with why it isn't the whole month.
 * A field an older daemon leaves out is unknown, never zero use.
 */
export function capUseLines(cap: BandwidthCap): string[] {
	const unknown = ["This month's use isn't available"];
	if (cap.since === null) return ['Still counting'];
	if (cap.since === undefined || cap.complete === undefined) return unknown;
	const of = cap.monthly_cap_bytes > 0 ? ` of ${formatGB(cap.monthly_cap_bytes)}` : '';
	const low = cap.lower_bound_bytes;
	const recounting = low !== undefined && low < cap.current_usage_bytes ? ['Recounting under your new exclusions'] : [];
	if (cap.complete) return [`${formatGB(cap.current_usage_bytes)}${of} used this month`, ...recounting];
	// the total isn't a safe "at least" under changed exclusions, so without the lower bound there is no figure
	if (low === undefined) return unknown;
	// OLD CODE START — F6 review: a ledger begun before this month read "counted since 1 Oct" when only a later day was missing
	// return [`At least ${formatGB(low)}${of} used this month, counted since ${formatDate(cap.since)}`, ...recounting];
	// OLD CODE END
	// counting began inside this month (as startsBeforeSince): the days before it are what's missing
	// OLD CODE: ... : 'some days are still being counted'; (review: a not_counted gap is never counted)
	const why = cap.first_day !== undefined && cap.since > cap.first_day ? `counted since ${formatDate(cap.since)}` : "some days aren't counted";
	// OLD CODE: return [`At least ${formatGB(low)}${of} used …`] (review: rounding up made 82.46 read "at least 82.5")
	// "at least" floors to 0.1 GB, so the figure is never above what was counted
	return [`At least ${formatGB(Math.floor(low / 1e8) * 1e8)}${of} used this month, ${why}`, ...recounting];
}

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

/** Counting began after the month's first day, so the month can't be complete */
const startsBeforeSince = (m: UsageMonth): boolean => !!m.since && m.days.length > 0 && m.since > m.days[0].date;

/** "November 2026, Europe/London", then each caveat the month's days carry */
export function monthNote(m: UsageMonth): string {
	const has = (...statuses: UsageDayStatus[]) => m.days.some((d) => statuses.includes(d.status));
	return [
		`${monthName(m.year, m.month)}, ${m.tz}`,
		startsBeforeSince(m) && `Since ${formatDate(m.since!)}`,
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

/** Why the daily rate (and the projection) is missing: they need every elapsed day counted under the current rules */
export function noRateReason(m: UsageMonth): string {
	if (startsBeforeSince(m)) return 'Shown from next month, the first one counted from its first day';
	return m.complete ? 'Shown after the first hour of the month' : 'Shown once every day so far is counted';
}

/** UTC under any of its names, as UTC: a browser in "Etc/UTC" is in the zone NetTap counts in by default */
export const sameAsUtc = (zone: string): string => (['UTC', 'Etc/UTC', 'Etc/Universal'].includes(zone) ? 'UTC' : zone);
