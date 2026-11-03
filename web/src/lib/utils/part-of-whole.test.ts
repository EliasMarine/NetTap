import { describe, expect, it } from 'vitest';
import { partOfWhole } from './part-of-whole';

describe('partOfWhole', () => {
	it('names the true total, not the length of a capped list', () => {
		expect(partOfWhole(15, 4213)).toBe('15 of 4,213');
		expect(partOfWhole(50, 60)).toBe('50 of 60');
	});
});
