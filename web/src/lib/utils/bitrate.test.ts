import { describe, it, expect } from 'vitest';
import { formatBitRate } from './bitrate';

describe('formatBitRate', () => {
	it('writes decimal units at three significant figures, dropping trailing zeros', () => {
		expect(formatBitRate(0)).toBe('0 bit/s');
		expect(formatBitRate(950)).toBe('950 bit/s');
		expect(formatBitRate(949.6)).toBe('950 bit/s');
		expect(formatBitRate(1_200)).toBe('1.2 kbit/s');
		expect(formatBitRate(12_345_678)).toBe('12.3 Mbit/s');
		expect(formatBitRate(123_456_789)).toBe('123 Mbit/s');
		expect(formatBitRate(1_050_000_000)).toBe('1.05 Gbit/s');
	});

	it('divides by 1,000, not 1,024 (NET-166)', () => {
		expect(formatBitRate(1_000)).toBe('1 kbit/s');
		expect(formatBitRate(1_000_000)).toBe('1 Mbit/s');
		expect(formatBitRate(1_024)).toBe('1.02 kbit/s');
	});

	it('rolls over to the next unit instead of printing 1000', () => {
		expect(formatBitRate(999.5)).toBe('1 kbit/s');
		expect(formatBitRate(999_950)).toBe('1 Mbit/s');
		expect(formatBitRate(999_950_000)).toBe('1 Gbit/s');
	});

	it('stays in Gbit/s above it', () => {
		expect(formatBitRate(2_500_000_000_000)).toBe('2500 Gbit/s');
	});

	it('gives a dash for anything that is not a rate', () => {
		for (const v of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, -1]) expect(formatBitRate(v)).toBe('—');
	});
});
