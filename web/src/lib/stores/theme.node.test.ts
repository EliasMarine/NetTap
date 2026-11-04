// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { theme, setTheme } from './theme';

describe('theme store (server)', () => {
	it('is ember with no browser access', () => {
		expect(typeof document).toBe('undefined');
		expect(get(theme)).toBe('ember');
	});

	it('setTheme is a no-op on the server', () => {
		expect(() => setTheme('graphite')).not.toThrow();
		expect(get(theme)).toBe('ember');
	});
});
