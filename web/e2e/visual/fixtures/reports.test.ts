import { describe, it, expect } from 'vitest';
import { periodWords } from '../../../src/routes/reports/report-words.ts';
import { CARD_SCHEDULE, HISTORY, REPORT, SCHEDULES } from './reports.ts';

// NET-340: a reply the daemon can't send would test nothing (plans/2026-11-21-weekly-report.contract.md)
describe('weekly report fixtures', () => {
	it('exactly one card schedule, listed after an API-only one, so binding by position would fail', () => {
		expect(SCHEDULES.schedules.filter((s) => s.card)).toEqual([CARD_SCHEDULE]);
		expect(SCHEDULES.schedules[0].card).toBe(false);
	});

	it("the history is the card schedule's, newest first, and starts with the report it serves", () => {
		expect(HISTORY.reports.every((r) => r.schedule_id === CARD_SCHEDULE.id)).toBe(true);
		const times = HISTORY.reports.map((r) => r.generated_at);
		expect([...times].sort().reverse()).toEqual(times);
		expect(HISTORY.reports[0].id).toBe(REPORT.id);
		expect(CARD_SCHEDULE.last_delivery.report_id).toBe(REPORT.id);
	});

	it('the report covers seven local days, and its day rows match its period', () => {
		const { traffic, alerts } = REPORT.sections;
		expect(REPORT.period.days).toBe(7);
		expect(periodWords(REPORT.period)).toBe('9–15 Nov 2026');
		expect(traffic.days.map((d) => d.date)).toEqual(alerts.days.map((d) => d.date));
		expect(alerts.days[0].date).toBe(REPORT.period.first);
		expect(alerts.days.at(-1)!.date).toBe(REPORT.period.last);
		expect(alerts.days.reduce((t, d) => t + d.count, 0)).toBe(alerts.total);
		const { other, ...named } = alerts.by_severity;
		expect(Object.values(named).reduce((t, n) => t + n, other)).toBe(alerts.total);
		expect(traffic.download + traffic.upload).toBeCloseTo(traffic.total, 0);
	});

	it('covers a partial and an unavailable section, the unavailable one with no fields of its own', () => {
		const statuses = Object.values(REPORT.sections).map((x) => x.status);
		expect(statuses).toContain('partial');
		expect(Object.keys(REPORT.sections.data_cap).sort()).toEqual(['coverage', 'note', 'status']);
		expect(REPORT.sections.data_cap.status).toBe('unavailable');
	});
});
