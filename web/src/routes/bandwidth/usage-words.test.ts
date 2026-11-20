import { describe, it, expect } from 'vitest';
import type { UsageDay, UsageDayStatus, UsageMonth } from '$lib/api/usage';
import { formatWhen } from '$lib/utils/drilldown';
import type { BandwidthCap } from '$lib/api/bandwidth';
// OLD CODE: import { monthNote, noRateReason, notFinalLine, sameAsUtc } from './usage-words'; (F6: the cap's use line)
import { capUseLines, formatGB, monthNote, noRateReason, notFinalLine, sameAsUtc } from './usage-words';

// F4 (NET-329): the month card's subtitle and the daily chart's note, per plan §4.6

const day = (date: string, status: UsageDayStatus): UsageDay => ({
	date, start: `${date}T08:00:00Z`, end: `${date}T08:00:00Z`, cutoff: null,
	download: 1, upload: 1, local: 0, total: 2, status, counted_at: null,
});

const month = (statuses: UsageDayStatus[], extra: Partial<UsageMonth> = {}): UsageMonth => ({
	tz: 'America/Los_Angeles', pending_tz: null, since: '2026-10-02', generation: 1, updated_at: '2026-11-18T09:30:00Z',
	days: statuses.map((s, i) => day(`2026-11-${String(i + 1).padStart(2, '0')}`, s)),
	bytes: { download: 0, upload: 0, local: 0, total: 0 }, complete: true, gaps: [],
	year: 2026, month: 11, month_start: '2026-11-01T00:00:00-07:00', month_end: '2026-12-01T00:00:00-08:00',
	projected: null, daily_rate: null, days_remaining: null, sweep: null,
	...extra,
});

describe('monthNote', () => {
	it('names the month and the zone its days are counted in', () => {
		expect(monthNote(month(['counted', 'counted', 'future']))).toBe('November 2026, America/Los_Angeles');
	});

	it('says since when counting began inside the month, and nothing when it began before', () => {
		expect(monthNote(month(['not_counted', 'counted'], { since: '2026-11-02' }))).toBe('November 2026, America/Los_Angeles · Since 2 Nov');
		expect(monthNote(month(['counted'], { since: '2026-11-01' }))).toBe('November 2026, America/Los_Angeles');
	});

	it('says still counting for a day not counted yet, or waiting for a recount, but never for a future day', () => {
		expect(monthNote(month(['counted', 'pending']))).toMatch(/ · Still counting$/);
		expect(monthNote(month(['recount_pending', 'counted']))).toMatch(/ · Still counting$/);
		expect(monthNote(month(['counted', 'future', 'future']))).not.toMatch(/Still counting/);
	});

	it('says approximate, earlier exclusions and not updated, each once', () => {
		expect(monthNote(month(['approximate', 'approximate']))).toBe(
			'November 2026, America/Los_Angeles · Approximate: some raw data was cleared before the day was final',
		);
		expect(monthNote(month(['old_rules']))).toBe('November 2026, America/Los_Angeles · Counted under earlier exclusions');
		expect(monthNote(month(['counted', 'stale']))).toBe(`November 2026, America/Los_Angeles · Not updated since ${formatWhen('2026-11-18T09:30:00Z')}`);
		expect(monthNote(month(['stale'], { updated_at: null }))).toBe('November 2026, America/Los_Angeles · Not updated yet');
	});

	it('lists every caveat that applies, in a fixed order', () => {
		const note = monthNote(month(['not_counted', 'approximate', 'old_rules', 'stale', 'pending', 'future'], { since: '2026-11-02' }));
		expect(note.split(' · ').map((part) => part.split(':')[0].split(' since')[0])).toEqual([
			'November 2026, America/Los_Angeles', 'Since 2 Nov', 'Still counting', 'Approximate', 'Counted under earlier exclusions', 'Not updated',
		]);
	});
});

describe('notFinalLine', () => {
	it('groups the days that are not final by what they are, and leaves counted days out', () => {
		const days = [day('2026-11-01', 'counted'), day('2026-11-02', 'approximate'), day('2026-11-03', 'approximate'), day('2026-11-04', 'stale')];
		expect(notFinalLine(days)).toBe('Approximate: 2 Nov, 3 Nov · Not updated lately: 4 Nov');
		expect(notFinalLine([day('2026-11-01', 'counted')])).toBe('');
	});

	it('counts more than three days instead of listing them', () => {
		const days = ['01', '02', '03', '04'].map((d) => day(`2026-11-${d}`, 'not_counted'));
		expect(notFinalLine(days)).toBe('Not counted: 4 days');
	});
});

describe('noRateReason', () => {
	it('when counting began inside the month, the rate waits for next month, not for the days to be counted', () => {
		expect(noRateReason(month(['not_counted', 'counted', 'future'], { since: '2026-11-02', complete: false }))).toBe(
			'Shown from next month, the first one counted from its first day',
		);
	});

	it('otherwise it waits for every day so far to be counted, or for the first hour', () => {
		expect(noRateReason(month(['counted', 'pending'], { complete: false }))).toBe('Shown once every day so far is counted');
		expect(noRateReason(month(['counted', 'future'], { complete: true }))).toBe('Shown after the first hour of the month');
	});
});

describe('sameAsUtc', () => {
	it("reads UTC's other names as UTC, and leaves every other zone alone", () => {
		expect(['UTC', 'Etc/UTC', 'Etc/Universal'].map(sameAsUtc)).toEqual(['UTC', 'UTC', 'UTC']);
		expect(sameAsUtc('Europe/London')).toBe('Europe/London');
	});
});

// F6 (NET-339): Settings › Network's use line, with a figure that is never too high
describe('formatGB', () => {
	it('is decimal GB with one decimal, as ISPs state caps', () => {
		expect(formatGB(82_400_000_000)).toBe('82.4 GB');
		expect(formatGB(100e9)).toBe('100.0 GB');
		expect(formatGB(0)).toBe('0.0 GB');
	});
});

describe('capUseLines', () => {
	const GB = 1e9;
	const cap = (extra: Partial<BandwidthCap> = {}): BandwidthCap => ({
		monthly_cap_bytes: 100 * GB, monthly_cap_gb: 100, enabled: true, current_usage_bytes: 82.4 * GB, usage_percent: 82.4,
		tz: 'Europe/London', since: '2026-10-01', complete: true, lower_bound_bytes: 82.4 * GB, first_day: '2026-11-01',
		...extra,
	});

	it('a complete month: the total of the cap', () => {
		expect(capUseLines(cap())).toEqual(['82.4 GB of 100.0 GB used this month']);
	});

	it('an incomplete month whose counting began inside it: at least the lower bound, counted since that day', () => {
		expect(capUseLines(cap({ complete: false, since: '2026-11-13' }))).toEqual(['At least 82.4 GB of 100.0 GB used this month, counted since 13 Nov']);
	});

	it.each([
		['began before the month', '2026-10-01', '2026-11-01'],
		["began on the month's first day", '2026-11-01', '2026-11-01'],
		['an older daemon sent no first day', '2026-11-13', undefined],
	])('an incomplete month whose counting %s: some days are still being counted', (_name, since, firstDay) => {
		expect(capUseLines(cap({ complete: false, since, first_day: firstDay }))).toEqual([
			'At least 82.4 GB of 100.0 GB used this month, some days are still being counted',
		]);
	});

	it('days under earlier exclusions: the lower bound, never the total, and says it is recounting', () => {
		expect(capUseLines(cap({ complete: false, since: '2026-11-13', lower_bound_bytes: 50 * GB }))).toEqual([
			'At least 50.0 GB of 100.0 GB used this month, counted since 13 Nov',
			'Recounting under your new exclusions',
		]);
	});

	it('no ledger count yet: still counting', () => {
		expect(capUseLines(cap({ since: null, complete: false, current_usage_bytes: 0, lower_bound_bytes: 0 }))).toEqual(['Still counting']);
	});

	it('no cap: the use without "of …"', () => {
		const none = { monthly_cap_bytes: 0, monthly_cap_gb: 0, enabled: false };
		expect(capUseLines(cap(none))).toEqual(['82.4 GB used this month']);
		expect(capUseLines(cap({ ...none, complete: false, since: '2026-11-13' }))).toEqual(['At least 82.4 GB used this month, counted since 13 Nov']);
	});

	it("an older daemon's missing fields are unknown, never zero use or an unsafe total", () => {
		const unknown = ["This month's use isn't available"];
		expect(capUseLines(cap({ since: undefined, complete: undefined, lower_bound_bytes: undefined }))).toEqual(unknown);
		// incomplete without the lower bound: the total could count days under old exclusions
		expect(capUseLines(cap({ complete: false, lower_bound_bytes: undefined }))).toEqual(unknown);
		// complete without it: the total is the counted figure
		expect(capUseLines(cap({ lower_bound_bytes: undefined }))).toEqual(['82.4 GB of 100.0 GB used this month']);
	});
});
