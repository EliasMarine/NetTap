import { describe, it, expect } from 'vitest';
import { loadFailed } from './load-failed';

describe('loadFailed', () => {
	it('says the section could not load', () => {
		expect(loadFailed('traffic categories')).toBe("Couldn't load traffic categories: the request failed.");
	});

	it('says older figures are still on screen when stale', () => {
		expect(loadFailed('traffic totals', true)).toBe("Couldn't refresh traffic totals; showing the last figures loaded.");
	});
});
