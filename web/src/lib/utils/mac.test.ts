import { describe, expect, it } from 'vitest';
import { isPrivateMac } from './mac';

describe('isPrivateMac', () => {
	it("is false for a maker's MAC", () => {
		expect(isPrivateMac('bc:24:11:00:00:01')).toBe(false);
		expect(isPrivateMac('00:1a:2b:3c:4d:5e')).toBe(false);
	});

	it.each(['02', '06', '0a', '0e', 'f2', 'da'])('is true when the first byte is %s', (first) => {
		expect(isPrivateMac(`${first}:11:22:33:44:55`)).toBe(true);
	});

	it('reads upper case and dashes', () => {
		expect(isPrivateMac('DA:A1:19:00:00:01')).toBe(true);
		expect(isPrivateMac('da-a1-19-00-00-01')).toBe(true);
		expect(isPrivateMac('BC-24-11-00-00-01')).toBe(false);
	});

	it('is false for anything that is not a MAC', () => {
		for (const text of ['', 'not a mac', '02:11:22:33:44', '02:11:22:33:44:55:66', '0g:11:22:33:44:55', '0211.2233.4455']) {
			expect(isPrivateMac(text)).toBe(false);
		}
	});
});
