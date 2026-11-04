import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

async function loadStore() {
	vi.resetModules();
	return import('./theme');
}

describe('theme store (browser)', () => {
	beforeEach(() => {
		delete document.documentElement.dataset.variant;
		localStorage.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		document.head.querySelectorAll('style[data-test-theme]').forEach((el) => el.remove());
	});

	it('starts as ember when the bootstrap set no attribute', async () => {
		const { theme } = await loadStore();
		expect(get(theme)).toBe('ember');
	});

	it('starts from the attribute the bootstrap set', async () => {
		document.documentElement.dataset.variant = 'graphite';
		const { theme } = await loadStore();
		expect(get(theme)).toBe('graphite');
	});

	it('treats an unknown attribute as ember', async () => {
		document.documentElement.dataset.variant = 'neon';
		const { theme } = await loadStore();
		expect(get(theme)).toBe('ember');
	});

	it('never reads or writes storage on init', async () => {
		localStorage.setItem('nettap-theme', 'spectrum');
		const getItem = vi.spyOn(Storage.prototype, 'getItem');
		const setItem = vi.spyOn(Storage.prototype, 'setItem');
		const { theme } = await loadStore();
		expect(get(theme)).toBe('ember');
		expect(getItem).not.toHaveBeenCalled();
		expect(setItem).not.toHaveBeenCalled();
	});

	it('setTheme sets the attribute, the store and storage', async () => {
		const { theme, setTheme } = await loadStore();
		setTheme('spectrum');
		expect(document.documentElement.dataset.variant).toBe('spectrum');
		expect(get(theme)).toBe('spectrum');
		expect(localStorage.getItem('nettap-theme')).toBe('spectrum');
	});

	it('setTheme("ember") removes the attribute', async () => {
		document.documentElement.dataset.variant = 'graphite';
		const { theme, setTheme } = await loadStore();
		setTheme('ember');
		expect(document.documentElement.hasAttribute('data-variant')).toBe(false);
		expect(get(theme)).toBe('ember');
		expect(localStorage.getItem('nettap-theme')).toBe('ember');
	});

	it('still applies the theme when storage throws', async () => {
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new DOMException('denied', 'SecurityError');
		});
		const { theme, setTheme } = await loadStore();
		expect(() => setTheme('graphite')).not.toThrow();
		expect(document.documentElement.dataset.variant).toBe('graphite');
		expect(get(theme)).toBe('graphite');
	});

	it('ignores a value that is not a variant', async () => {
		const { theme, setTheme } = await loadStore();
		// @ts-expect-error: runtime guard for untyped callers
		setTheme('neon');
		expect(get(theme)).toBe('ember');
		expect(document.documentElement.hasAttribute('data-variant')).toBe(false);
	});

	it('changes the attribute before subscribers are notified', async () => {
		const style = document.createElement('style');
		style.dataset.testTheme = '';
		style.textContent =
			':root { --accent: #ff7a1a; } :root[data-variant="graphite"] { --accent: #f4f4f5; }';
		document.head.appendChild(style);

		const { theme, setTheme } = await loadStore();
		const seen: string[] = [];
		const unsubscribe = theme.subscribe((v) => {
			if (v === 'graphite') {
				seen.push(
					getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
				);
			}
		});
		setTheme('graphite');
		unsubscribe();
		expect(seen).toEqual(['#f4f4f5']);
	});
});
