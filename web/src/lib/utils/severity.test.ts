import { describe, it, expect } from 'vitest';
import { severityBuckets, suricataLevel } from './severity';

const sum = (b: { count: number }[]) => b.reduce((a, x) => a + x.count, 0);

describe('severityBuckets', () => {
	it('partitions the total, with info as the remainder', () => {
		const b = severityBuckets({ total: 37, high: 5, medium: 12, low: 8 });
		expect(b.map((x) => x.level)).toEqual(['high', 'medium', 'low', 'info']);
		expect(b.at(-1)!.count).toBe(12);
		expect(sum(b)).toBe(37);
	});

	it('includes critical only when the API supplies it', () => {
		const b = severityBuckets({ total: 10, critical: 2, high: 3, medium: 1, low: 1 });
		expect(b[0]).toEqual({ level: 'critical', count: 2 });
		expect(sum(b)).toBe(10);
	});

	it('clamps info at zero when the named levels exceed the total', () => {
		const b = severityBuckets({ total: 3, high: 2, medium: 2, low: 0 });
		expect(b.at(-1)!.count).toBe(0);
	});

	it('treats a zero total as all zeros', () => {
		expect(sum(severityBuckets({ total: 0, high: 0, medium: 0, low: 0 }))).toBe(0);
	});

	it('ignores negative and non-finite input', () => {
		const b = severityBuckets({ total: Number.NaN, high: -4, medium: Infinity, low: 2 });
		expect(b.every((x) => Number.isFinite(x.count) && x.count >= 0)).toBe(true);
	});
});

describe('suricataLevel', () => {
	it('reads Suricata 1, 2 and 3 as high, medium and low, and anything else as info', () => {
		expect([1, 2, 3, 4, 0, undefined, null].map(suricataLevel)).toEqual(['high', 'medium', 'low', 'info', 'info', 'info', 'info']);
	});
});
