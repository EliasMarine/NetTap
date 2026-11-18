import { describe, it, expect } from 'vitest';
import { hasFigures, type UsageMonth } from '../../../src/lib/api/usage.ts';
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
