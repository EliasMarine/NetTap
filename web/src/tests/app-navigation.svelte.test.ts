/** NET-357: the test router's history, which page tests use to check Back and Forward. */
import { describe, it, expect } from 'vitest';
import { goto, historyState, page, resetNavigation, traverse } from './app-navigation.svelte';

describe('app-navigation test router', () => {
	it('pushes an entry for a plain goto, and Back returns to the one before', async () => {
		resetNavigation('http://localhost/?range=1h');
		await goto('/devices');
		expect(historyState()).toEqual({ entries: ['/?range=1h', '/devices'], index: 1 });
		traverse(-1);
		expect(page.url.pathname + page.url.search).toBe('/?range=1h');
	});

	it('replaces the current entry for goto with replace, as SvelteKit does', async () => {
		resetNavigation('http://localhost/?range=1h');
		await goto('/?range=6h', { replace: true });
		expect(historyState()).toEqual({ entries: ['/?range=6h'], index: 0 });
		expect(page.url.search).toBe('?range=6h');
	});

	it('replaces only the entry Back landed on, keeping the ones after it', async () => {
		resetNavigation('http://localhost/traffic/streaming?range=1h');
		await goto('/traffic/streaming?from=a&to=b');
		traverse(-1);
		await goto('/traffic/streaming?range=24h', { replace: true });
		expect(historyState()).toEqual({ entries: ['/traffic/streaming?range=24h', '/traffic/streaming?from=a&to=b'], index: 0 });
	});
});
