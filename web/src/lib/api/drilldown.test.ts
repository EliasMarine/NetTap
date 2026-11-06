import { describe, it, expect, vi, afterEach } from 'vitest';
import { getAddressSummary, getDomainSummary } from './drilldown';
import { ADDRESS, DOMAIN } from '../../../e2e/visual/fixtures/drilldown';

const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });

describe('drill-down clients', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the address in the window, encoded', async () => {
		const fetchMock = vi.fn(async () => reply(200, ADDRESS));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getAddressSummary('2001:db8::1', '2026-11-05T00:00:00Z', '2026-11-06T00:00:00Z')).resolves.toEqual(ADDRESS);
		const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
		expect(url.pathname).toBe('/api/addresses/2001%3Adb8%3A%3A1');
		expect(url.searchParams.get('from')).toBe('2026-11-05T00:00:00Z');
		expect(url.searchParams.get('to')).toBe('2026-11-06T00:00:00Z');
	});

	it('asks for the domain in the window', async () => {
		const fetchMock = vi.fn(async () => reply(200, DOMAIN));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getDomainSummary('example.com', 'a', 'b')).resolves.toEqual(DOMAIN);
		expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe('/api/domains/example.com?from=a&to=b');
	});

	it.each([
		[400, { error: 'Invalid IP address: nope' }, 'Invalid IP address: nope'],
		[503, { error: 'busy' }, 'busy'],
		[502, {}, 'Address summary failed: HTTP 502'],
	])('throws the daemon reason on HTTP %s', async (status, body, message) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(status, body)));
		await expect(getAddressSummary('x', 'a', 'b')).rejects.toThrow(message);
	});

	it('throws on a malformed reply instead of showing an empty one', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, { ...ADDRESS, bytes_to: 5 })));
		await expect(getAddressSummary('x', 'a', 'b')).rejects.toThrow('malformed');
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, { ...DOMAIN, tls: null })));
		await expect(getDomainSummary('x', 'a', 'b')).rejects.toThrow('malformed');
		vi.stubGlobal('fetch', vi.fn(async () => reply(503, 'not json')));
		await expect(getDomainSummary('x', 'a', 'b')).rejects.toThrow('Domain summary failed: HTTP 503');
	});
});
