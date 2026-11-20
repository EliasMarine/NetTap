import { describe, it, expect } from 'vitest';
import { hasFigures, type UsageMonth } from '../../../src/lib/api/usage.ts';
import type { BandwidthCap } from '../../../src/lib/api/bandwidth.ts';
import { BANDWIDTH_ROUTES } from './bandwidth.ts';

const month = BANDWIDTH_ROUTES.find((r) => r.path === '/api/usage/month')!;

// F4 (NET-329): a ledger reply the daemon can't send would test nothing (plan §4.5)
describe('usage ledger fixtures', () => {
	it('populated has local traffic, so a total that took it in would show', () => {
		expect((month.populated as UsageMonth).bytes.local).toBeGreaterThan(0);
	});

	it.each(['empty', 'populated'] as const)('%s: bytes sum the days with figures, and only those days carry figures', (mode) => {
		const body = month[mode] as UsageMonth;
		const withFigures = body.days.filter(hasFigures);
		expect(body.bytes.total).toBe(withFigures.reduce((t, d) => t + (d.total ?? 0), 0));
		// total is what crossed the ISP link; local traffic is beside it, never in it
		expect(body.bytes.download + body.bytes.upload).toBe(body.bytes.total);
		for (const d of body.days) {
			expect(d.total === null).toBe(!hasFigures(d));
			if (d.total !== null) expect((d.download ?? 0) + (d.upload ?? 0)).toBe(d.total);
		}
		// nothing is projected unless every elapsed day is counted
		if (body.projected !== null) expect(body.days.every((d) => d.status === 'counted' || d.status === 'future')).toBe(true);
		expect(body.complete).toBe(body.days.every((d) => d.status === 'counted' || d.status === 'future'));
	});
});

// F6 (NET-339): the cap reply describes the same month as /api/usage/month, as the daemon's does
describe('cap fixtures', () => {
	const capRoute = BANDWIDTH_ROUTES.find((r) => r.path === '/api/bandwidth/cap')!;

	it.each(['empty', 'populated'] as const)("%s: the use, start and completeness are the month's, and the lower bound is never higher", (mode) => {
		const cap = capRoute[mode] as BandwidthCap;
		const body = month[mode] as UsageMonth;
		expect(cap.current_usage_bytes).toBe(body.bytes.total);
		expect([cap.tz, cap.since, cap.complete]).toEqual([body.tz, body.since, body.complete]);
		expect(cap.lower_bound_bytes).toBeLessThanOrEqual(cap.current_usage_bytes);
	});

	it('a fresh install has no cap; populated has one', () => {
		expect((capRoute.empty as BandwidthCap).monthly_cap_bytes).toBe(0);
		expect((capRoute.populated as BandwidthCap).monthly_cap_bytes).toBeGreaterThan(0);
	});
});
