import { describe, it, expect } from 'vitest';
import type { UsageDay, UsageDayStatus, UsageMonth } from '$lib/api/usage';
import { formatWhen } from '$lib/utils/drilldown';
import { monthNote, notFinalLine } from './usage-words';

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
