import { describe, it, expect, vi, afterEach } from 'vitest';
import { getAddressSummary, getDomainSummary } from './drilldown';
import { ADDRESS, ADDRESS_EMPTY, ADDRESS_QUIET, DOMAIN, DOMAIN_EMPTY, DOMAIN_QUIET } from '../../../e2e/visual/fixtures/drilldown';

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

	const without = <T extends object>(o: T, path: string): unknown => {
		const [head, ...rest] = path.split('.');
		const copy: Record<string, unknown> = { ...(o as Record<string, unknown>) };
		if (rest.length) copy[head] = without(copy[head] as object, rest.join('.'));
		else delete copy[head];
		return copy;
	};

	// A field the page reads as a figure or a flag that is missing must reach the error state:
	// no "partial" would show an exact total, no "*_complete" a whole list, no threat_intel "Not checked"
	it.each(['bytes_to.partial', 'bytes_from.partial', 'threat_intel', 'peers_complete', 'ports_complete', 'tls_complete', 'alerts', 'lan'])(
		'rejects an address reply without %s',
		async (path) => {
			vi.stubGlobal('fetch', vi.fn(async () => reply(200, without(ADDRESS, path))));
			await expect(getAddressSummary('x', 'a', 'b')).rejects.toThrow('malformed');
		},
	);

	it.each([
		'dns.askers_complete',
		'dns.answers_complete',
		'dns.addresses',
		'tls.sessions',
		'tls.statuses',
		'tls.servers_complete',
		'tls.clients_complete',
		'http.requests',
		'alerts.tagged',
		'alerts.alerts_in_window',
		'alerts.with_host_field',
	])('rejects a domain reply without %s', async (path) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, without(DOMAIN, path))));
		await expect(getDomainSummary('x', 'a', 'b')).rejects.toThrow('malformed');
	});

	it('accepts every well-formed fixture, including the null cases', async () => {
		for (const body of [ADDRESS, ADDRESS_QUIET, ADDRESS_EMPTY]) {
			vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
			await expect(getAddressSummary('x', 'a', 'b')).resolves.toEqual(body);
		}
		for (const body of [DOMAIN, DOMAIN_QUIET, DOMAIN_EMPTY]) {
			vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
			await expect(getDomainSummary('x', 'a', 'b')).resolves.toEqual(body);
		}
	});
});
