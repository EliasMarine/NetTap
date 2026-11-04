// @vitest-environment node
import { describe, it, expect, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$api/alerts', () => ({ getAlertCount: vi.fn(() => Promise.reject(new Error('must not fetch on the server'))) }));

import { registerPageRefresh, pageRefresh, refreshPage } from './pageRefresh';
import { loadAlertSnapshot, alertSnapshots } from './alertSnapshot';
import { getAlertCount } from '$api/alerts';

describe('stores during server rendering', () => {
	it('registerPageRefresh leaves shared state alone and never runs the loader', async () => {
		const loader = vi.fn(async () => 'ok' as const);
		const handle = registerPageRefresh(loader);
		expect(get(pageRefresh).available).toBe(false);
		expect(await handle.run()).toBe('skipped');
		expect(await refreshPage()).toBe('skipped');
		expect(loader).not.toHaveBeenCalled();
		handle.unregister();
	});

	it('loadAlertSnapshot does not fetch or write the shared store', async () => {
		const snap = await loadAlertSnapshot(24);
		expect(snap.status).toBe('loading');
		expect(getAlertCount).not.toHaveBeenCalled();
		expect(get(alertSnapshots)).toEqual({});
	});
});
