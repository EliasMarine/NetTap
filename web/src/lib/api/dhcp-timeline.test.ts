import { describe, it, expect, vi, afterEach } from 'vitest';
import { getDhcpTimeline } from './dhcp-timeline';
import { DHCP_MAC, DHCP_TIMELINE, DHCP_TIMELINE_EMPTY } from '../../../e2e/visual/fixtures/dhcp';

// NET-263: the daemon half has its own tests (daemon/tests/test_dhcp_timeline_api.py)
const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const opts = { mac: DHCP_MAC, from: '2026-11-12T00:00:00.000Z', to: '2026-11-13T00:00:00.000Z' };

describe('getDhcpTimeline', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the MAC and the window', async () => {
		const fetchMock = vi.fn(async () => reply(200, DHCP_TIMELINE));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getDhcpTimeline(opts)).resolves.toEqual(DHCP_TIMELINE);
		const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
		expect(url.pathname).toBe('/api/dhcp/timeline');
		expect(Object.fromEntries(url.searchParams)).toEqual(opts);
	});

	it('takes no transactions as an empty list', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, DHCP_TIMELINE_EMPTY)));
		await expect(getDhcpTimeline(opts)).resolves.toEqual(DHCP_TIMELINE_EMPTY);
	});

	it.each([
		[400, { error: 'Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff.' }, 'Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff.'],
		[503, { error: 'Working this out took too long. Try a shorter time range.' }, 'Working this out took too long. Try a shorter time range.'],
		[500, {}, 'DHCP timeline failed: HTTP 500'],
	])("throws the daemon's reason on HTTP %s", async (status, body, message) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(status, body)));
		await expect(getDhcpTimeline(opts)).rejects.toThrow(message);
	});

	const first = DHCP_TIMELINE.transactions[0];
	it.each([
		['no transactions list', { ...DHCP_TIMELINE, transactions: undefined }],
		['no truncated flag', { ...DHCP_TIMELINE, truncated: undefined }],
		['an unknown outcome', { ...DHCP_TIMELINE, transactions: [{ ...first, outcome: 'maybe' }] }],
		['messages as a list', { ...DHCP_TIMELINE, transactions: [{ ...first, messages: ['ACK'] }] }],
		['a count that is not a number', { ...DHCP_TIMELINE, transactions: [{ ...first, messages: { ACK: '1' } }] }],
		['endpoints missing', { ...DHCP_TIMELINE, transactions: [{ ...first, server_endpoints: undefined }] }],
		['an address that is not text', { ...DHCP_TIMELINE, transactions: [{ ...first, assigned_ip: 7 }] }],
		['no completeness flag', { ...DHCP_TIMELINE, transactions: [{ ...first, endpoints_complete: undefined }] }],
	])('throws on a malformed reply (%s) instead of showing a blank', async (_, body) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getDhcpTimeline(opts)).rejects.toThrow('malformed');
	});

	it('takes a transaction with every optional field missing', async () => {
		const bare = { ...first, duration: null, requested_ip: null, assigned_ip: null, client_ip: null, lease_time: null, host_name: null, client_software: null, zeek_server: null, server_message: null };
		const body = { ...DHCP_TIMELINE, transactions: [bare] };
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getDhcpTimeline(opts)).resolves.toEqual(body);
	});
});
