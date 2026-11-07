import { describe, it, expect } from 'vitest';

describe('Test Setup', () => {
	it('should have test environment configured', () => {
		expect(true).toBe(true);
	});

	it('gives jsdom a scrollIntoView, so a page scrolling from a timer cannot throw', () => {
		const el = document.createElement('div');
		expect(() => el.scrollIntoView({ behavior: 'smooth' })).not.toThrow();
	});
});
