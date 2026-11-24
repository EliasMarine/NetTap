// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Page from './+page.svelte';

// NET-368: the server-rendered page is on screen until the browser takes over, and no loader runs
// on the server, so it must say the cards are loading, never that the month had no usage or devices.
describe('Bandwidth: the server-rendered page', () => {
	it('says each card is loading, not that there is nothing', () => {
		const { body } = render(Page);
		for (const loading of ["Loading this month's usage", 'Loading daily usage', 'Loading top consumers', 'Loading the per-device breakdown']) {
			expect(body).toContain(loading);
		}
		for (const empty of ['No usage this month yet', 'No devices yet', 'This month · 0 devices']) {
			expect(body).not.toContain(empty);
		}
	});
});
