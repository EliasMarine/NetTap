import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLocalServices } from '../../../src/lib/api/local-services';
import { LOCAL_SERVICES, LOCAL_SERVICES_EMPTY, LOCAL_SERVICES_ROUTES } from './local-services';

// The fixture daemon's answers must pass the page's own reply check, or the visual run shows errors
describe('local services fixtures', () => {
	afterEach(() => vi.unstubAllGlobals());

	it.each([
		['populated', LOCAL_SERVICES],
		['empty', LOCAL_SERVICES_EMPTY],
	])('the %s reply is well formed', async (_, body) => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => body })));
		await expect(getLocalServices({ from: 'a', to: 'b' })).resolves.toEqual(body);
	});

	it('answers the daemon path in both modes, with every VLAN state shown', () => {
		expect(LOCAL_SERVICES_ROUTES).toEqual([{ path: '/api/local-services', empty: LOCAL_SERVICES_EMPTY, populated: LOCAL_SERVICES }]);
		expect(new Set(LOCAL_SERVICES.rows.map((r) => r.sender.vlan_state))).toEqual(new Set(['tagged', 'untagged', 'unknown']));
	});
});
