import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLocalServices } from './local-services';
import { LOCAL_SERVICES, LOCAL_SERVICES_EMPTY } from '../../../e2e/visual/fixtures/local-services';

// NET-264: the daemon half has its own tests over Zeek-shaped records
const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });

describe('getLocalServices', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the window and returns the rows', async () => {
		const fetchMock = vi.fn(async () => reply(200, LOCAL_SERVICES));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getLocalServices({ from: '2026-11-12T14:00:00.000Z', to: '2026-11-13T14:00:00.000Z' })).resolves.toEqual(LOCAL_SERVICES);
		const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
		expect(url.pathname).toBe('/api/local-services');
		expect(Object.fromEntries(url.searchParams)).toEqual({ from: '2026-11-12T14:00:00.000Z', to: '2026-11-13T14:00:00.000Z' });
	});

	it('takes an empty window as no rows', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, LOCAL_SERVICES_EMPTY)));
		await expect(getLocalServices({ from: 'a', to: 'b' })).resolves.toEqual(LOCAL_SERVICES_EMPTY);
	});

	it.each([
		[503, { error: 'Working this out took too long. Try a shorter time range.' }, 'Working this out took too long. Try a shorter time range.'],
		[400, { error: 'The window can be at most 7 days.' }, 'The window can be at most 7 days.'],
		[500, {}, 'Local services failed: HTTP 500'],
	])("throws the daemon's reason on HTTP %s", async (status, body, message) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(status, body)));
		await expect(getLocalServices({ from: 'a', to: 'b' })).rejects.toThrow(message);
	});

	const first = LOCAL_SERVICES.rows[0];
	it.each([
		['no rows', { ...LOCAL_SERVICES, rows: undefined }],
		['a row without an id', { ...LOCAL_SERVICES, rows: [{ ...first, id: undefined }] }],
		['no truncated flag', { ...LOCAL_SERVICES, truncated: undefined }],
		['an unknown protocol', { ...LOCAL_SERVICES, rows: [{ ...first, protocol: 'llmnr' }] }],
		['a row without a sender', { ...LOCAL_SERVICES, rows: [{ ...first, sender: undefined }] }],
		['an unknown VLAN state', { ...LOCAL_SERVICES, rows: [{ ...first, sender: { ...first.sender, vlan_state: 'maybe' } }] }],
		['no last_seen', { ...LOCAL_SERVICES, rows: [{ ...first, last_seen: null }] }],
	])('throws on a malformed reply (%s) instead of showing a blank', async (_, body) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getLocalServices({ from: 'a', to: 'b' })).rejects.toThrow('malformed');
	});
});
