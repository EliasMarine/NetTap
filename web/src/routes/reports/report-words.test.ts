import { describe, it, expect } from 'vitest';
import type { Report, ReportSchedule } from '$lib/api/reports';
import { CARD_SCHEDULE, REPORT } from '../../../e2e/visual/fixtures/reports';
import { crossingWords, dayNote, dayWords, daysCoveredKpi, deliveryKpis, deliveryWords, durationWords, gb, nextReportKpi, periodNoun, periodWords, zonedTime } from './report-words';

const schedule = (over: Partial<ReportSchedule> = {}): ReportSchedule => ({ ...CARD_SCHEDULE, ...over });

describe('report words (NET-340)', () => {
	it.each([
		[{ first: '2026-11-10', last: '2026-11-16' }, '10–16 Nov 2026'],
		[{ first: '2026-10-27', last: '2026-11-02' }, '27 Oct – 2 Nov 2026'],
		[{ first: '2026-12-28', last: '2027-01-03' }, '28 Dec 2026 – 3 Jan 2027'],
		[{ first: '2026-11-16', last: '2026-11-16' }, '16 Nov 2026'],
		[{ first: 'x', last: 'y' }, 'x to y'],
	])('periodWords(%o) is %s', (period, words) => {
		expect(periodWords(period)).toBe(words);
	});

	it('names a local date by its own day, whatever the browser zone', () => {
		expect(dayWords('2026-11-12')).toBe('Thu 12 Nov');
	});

	it('writes an instant in the ledger zone, on a 24-hour clock', () => {
		expect(zonedTime('2026-11-16T08:00:12Z', 'Europe/London')).toBe('Mon 16 Nov, 08:00');
		expect(zonedTime('2026-07-13T07:00:00Z', 'Europe/London')).toBe('Mon 13 Jul, 08:00');
		expect(zonedTime('2026-11-16T08:00:12Z', 'Asia/Tokyo')).toBe('Mon 16 Nov, 17:00');
		expect(zonedTime(null, 'Europe/London')).toBe('—');
		// an unknown zone still shows the time rather than throwing
		expect(zonedTime('2026-11-16T08:00:12Z', 'Not/AZone')).toMatch(/16 Nov/);
	});

	it.each([
		[{ count: 0, stored: 'full' as const }, "No alerts recorded: a quiet day, or Suricata wasn't running"],
		[{ count: 40, stored: 'full' as const }, ''],
		[{ count: 40, stored: 'partial' as const }, 'Only part of this day is stored'],
		[{ count: 0, stored: 'absent' as const }, 'Not stored'],
		[{ count: 3, stored: 'unknown' as const }, "Couldn't check what is stored"],
	])('dayNote(%o)', (day, note) => {
		expect(dayNote(day)).toBe(note);
	});

	it('delivery results read in words, an unknown one as itself', () => {
		expect(deliveryWords('unknown')).toBe('Unknown: NetTap stopped while sending');
		expect(deliveryWords('not_configured')).toBe('Email not set up');
		expect(deliveryWords('queued')).toBe('queued');
	});

	it('Next report says why nothing is due', () => {
		expect(nextReportKpi(null).value).toBe('Not set up');
		expect(nextReportKpi(schedule({ enabled: false })).value).toBe('Off');
		expect(nextReportKpi(schedule({ needs_review: true }))).toEqual({ value: 'Paused', note: 'Check the recipients and save in Settings' });
		// the day is the value and the clock goes in the note, so the KPI fits on one line
		expect(nextReportKpi(schedule({ next_send: '2026-11-23T08:00:00Z' }))).toEqual({ value: '23 Nov', note: 'Mon 08:00 · Europe/London' });
	});

	it('Last sent and Delivery come from the last delivery; no recipients reads as kept, not emailed', () => {
		const none = deliveryKpis(schedule({ last_delivery: null, last_period: null, recipients: [] }));
		expect(none.last).toEqual({ value: 'Never', note: undefined });
		expect(deliveryKpis(schedule()).last).toEqual({ value: '16 Nov', note: 'Mon 08:00 · 9–15 Nov 2026' });
		expect(none.delivery).toEqual({ value: '—', note: 'No recipients: kept here, not emailed' });
		expect(deliveryKpis(schedule({ sending: true })).delivery.note).toBe('Sending now');
		expect(deliveryKpis(schedule({ recipients: ['a@example.com'] })).delivery.note).toBe('To 1 address');
		expect(deliveryKpis(null).last.value).toBe('—');
	});

	it('Days covered is the shown report\'s counted days, never a guess', () => {
		expect(daysCoveredKpi(REPORT)).toEqual({ value: '7 of 7', note: 'Days of internet use counted, 9–15 Nov 2026', sub: '6 of 7 days of alerts stored' });
		const short: Report = { ...REPORT, sections: { ...REPORT.sections, traffic: { ...REPORT.sections.traffic, days_covered: 2 } } };
		expect(daysCoveredKpi(short).value).toBe('2 of 7');
		expect(daysCoveredKpi(null).value).toBe('—');
	});

	it.each([
		[null, '—'],
		[42, '42 min'],
		[60, '1 h'],
		[185, '3 h 5 min'],
		[1440, '1 d'],
		[3120, '2 d 4 h'],
	])('durationWords(%s) is %s', (minutes, words) => {
		expect(durationWords(minutes)).toBe(words);
	});

	it('a cap warning reads as a threshold passed or the month on track to go over', () => {
		expect(crossingWords({ month: '2026-11', threshold: 100, cap: 1000e9, at: '2026-11-20T18:30:00Z' }, 'Europe/London')).toBe('Passed 100% of 1,000 GB on Fri 20 Nov, 18:30.');
		expect(crossingWords({ month: '2026-11', threshold: 'projected', cap: 500e9, at: '2026-11-10T09:00:00Z' }, 'Europe/London')).toBe('On track to go over 500 GB, noted Tue 10 Nov, 09:00.');
	});

	it('names the period by its frequency', () => {
		expect(periodNoun('weekly')).toBe('this week');
		expect(periodNoun('daily')).toBe('that day');
		expect(periodNoun('monthly')).toBe('this month');
		expect(periodNoun('yearly')).toBe('in this period');
	});

	it('GB has thousands separators, and a lower bound never rounds up', () => {
		expect(gb(1000e9)).toBe('1,000 GB');
		expect(gb(82.46e9)).toBe('82.5 GB');
		expect(gb(82.46e9, true)).toBe('82.4 GB');
		expect(gb(null)).toBe('—');
	});
});
