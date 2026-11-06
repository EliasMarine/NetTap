import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { refreshPage } from '$lib/stores/pageRefresh';
import type { AddressSummary } from '$lib/api/drilldown';
import { ADDRESS, ADDRESS_EMPTY, ADDRESS_QUIET, LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

// NET-160: every figure is exact for the window, or says it is partial, not measured or not checked

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/address/198.51.100.10'), params: { ip: '198.51.100.10' } });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const REGISTRY = {
	devices: [{ mac: 'aa', display_name: 'Living room TV', ips: ['192.168.1.22'], last_seen: '2026-11-05T00:00:00Z' }],
	total: 1,
};
const CONNECTIONS = (total: number) => ({
	from: 'a',
	to: 'b',
	ip: '198.51.100.10',
	page: 1,
	size: 25,
	total,
	total_pages: Math.min(Math.ceil(total / 25), 400),
	connections: total
		? [
				{ _id: 'c1', _index: 'x', '@timestamp': '2026-11-06T08:00:00Z', direction: 'in', source: { ip: '192.168.1.22', port: 50000, bytes: 1024 }, destination: { ip: '198.51.100.10', port: 443 }, network: { transport: 'tcp', protocol: 'ssl' } },
			]
		: [],
});

type Reply = unknown | ((url: URL) => unknown);
let calls: URL[] = [];

/** Answers by pathname; a missing reply is a 503 with the daemon's reason. */
function stubDaemon(replies: Record<string, Reply>, reason = 'The daemon is busy with other drill-downs; try again in a minute.') {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			const key = Object.keys(replies).find((k) => url.pathname === k || (k.endsWith('*') && url.pathname.startsWith(k.slice(0, -1))));
			const reply = key ? replies[key] : undefined;
			const body = typeof reply === 'function' ? (reply as (u: URL) => unknown)(url) : reply;
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({ error: reason }) };
		}),
	);
}

const baseReplies = (summary: AddressSummary | undefined, total = 1): Record<string, Reply> => ({
	'/api/network/lan': LAN_POLICY,
	'/api/addresses/*': summary,
	'/api/geoip/*': { ip: summary?.ip ?? '', country: 'United States', country_code: 'US', city: 'Ashburn', latitude: 1, longitude: 1, asn: 64501, organization: 'Example Streaming CDN', is_private: false },
	'/api/lookup/dns/*': { ip: summary?.ip ?? '', hostname: 'stream.example.net', aliases: [], addresses: [], error: null },
	'/api/devices/registry': REGISTRY,
	'/api/devices/*': CONNECTIONS(total),
	'/api/lookup/whois/*': { ip: '198.51.100.10', raw: 'x', parsed: { orgname: 'Example Streaming CDN', cidr: '198.51.100.0/24' }, error: null },
});

const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;

function goTo(ip: string) {
	pageStore.value.set({ url: new URL(`http://localhost/address/${encodeURIComponent(ip)}`), params: { ip } });
}

describe('Address page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo('198.51.100.10');
	});

	it('shows loading, not zeros, before the first answer', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: '198.51.100.10' })).toBeInTheDocument();
		expect(kpi('Connections')).toHaveTextContent('—');
		expect(kpi('Data to it')).toHaveTextContent('—');
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
	});

	it('shows the exact figures, with partial byte totals as lower bounds', async () => {
		stubDaemon(baseReplies(ADDRESS));
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		expect(kpi('Data to it')).toHaveTextContent('at least 200.0 MB');
		expect(kpi('Data to it')).toHaveTextContent('From it: at least 17.8 GB');
		expect(kpi('Data to it')).toHaveTextContent('To it: 1,970 of 1,980 connections measured · from it: 1,970 of 1,980 connections measured');
		expect(kpi('Devices that talked to it')).toHaveTextContent('3');
		expect(kpi('Devices that talked to it')).toHaveTextContent('on your network, of 3 addresses in all');
		expect(kpi('Alerts').closest('a')).toHaveAttribute('href', '/alerts?ip=198.51.100.10');
		expect(screen.getByText('Not on a threat list')).toBeInTheDocument();
		// the window is the request's
		const req = calls.find((u) => u.pathname === '/api/addresses/198.51.100.10')!;
		expect(Date.parse(req.searchParams.get('to')!) - Date.parse(req.searchParams.get('from')!)).toBe(24 * 3_600_000);
		expectNoNestedInteractive(container);
	});

	it('links every peer, name and certificate where it drills down', async () => {
		stubDaemon(baseReplies(ADDRESS));
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		const peers = card('Devices that talked to it');
		await vi.waitFor(() => expect(within(peers).getByRole('link', { name: 'Living room TV' })).toHaveAttribute('href', '/devices/192.168.1.22'));
		// the laptop's sessions missed some byte counts
		const laptop = within(peers).getByRole('link', { name: '192.168.1.20' }).closest('tr')!;
		expect(laptop).toHaveTextContent('at least 60.0 MB');
		const tls = card('Names it served (TLS)');
		expect(within(tls).getByRole('link', { name: 'stream.example.net' })).toHaveAttribute('href', '/domain/stream.example.net');
		const certs = new URL(within(tls).getAllByRole('link', { name: /Certificates seen/ })[0].getAttribute('href')!, 'http://x');
		expect(certs.pathname).toBe('/certificates');
		expect(certs.searchParams.get('server')).toBe('198.51.100.10');
		expect(['stream.example.net', 'edge.example.net']).toContain(certs.searchParams.get('site'));
		const req = calls.find((u) => u.pathname === '/api/addresses/198.51.100.10')!;
		expect(certs.searchParams.get('from')).toBe(req.searchParams.get('from'));
		expect(certs.searchParams.get('to')).toBe(req.searchParams.get('to'));
	});

	it('says Not measured, too many to count and no name, and flags a threat-list match', async () => {
		goTo('192.0.2.80');
		stubDaemon(baseReplies(ADDRESS_QUIET));
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Data to it')).toHaveTextContent('Not measured'));
		expect(kpi('Data to it')).toHaveTextContent('From it: Not measured');
		expect(kpi('Data to it')).not.toHaveTextContent('0 B');
		expect(kpi('Devices that talked to it')).toHaveTextContent('—');
		expect(kpi('Devices that talked to it')).toHaveTextContent('too many to count');
		expect(screen.getByText(/On a threat list: Example blocklist/)).toBeInTheDocument();
		expect(screen.getByText('No name (SNI)')).toBeInTheDocument();
		expect(screen.getByText(/Too many addresses to list them all/)).toBeInTheDocument();
		expect(screen.getByText(/Too many ports to list them all/)).toBeInTheDocument();
		expect(screen.getByText(/Too many names to list them all/)).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('says the address was not checked against threat lists when none are loaded, and shows empty states', async () => {
		stubDaemon(baseReplies(ADDRESS_EMPTY, 0));
		render(Page);
		await screen.findByText('Not checked: no threat indicators loaded yet');
		expect(kpi('Connections')).toHaveTextContent('0');
		expect(kpi('Data to it')).toHaveTextContent('0 B');
		expect(screen.getAllByText('No connections in the last 24 hours').length).toBe(2);
		expect(screen.getByText('Nothing talked to it in the last 24 hours')).toBeInTheDocument();
	});

	it("shows the daemon's reason when the summary fails, never zeros", async () => {
		stubDaemon({ ...baseReplies(undefined), '/api/addresses/*': undefined });
		render(Page);
		await vi.waitFor(() => expect(screen.getAllByText("Couldn't load connections over time: the request failed.").length).toBe(1));
		expect(screen.getAllByText('The daemon is busy with other drill-downs; try again in a minute.').length).toBeGreaterThan(0);
		expect(kpi('Connections')).toHaveTextContent('—');
		expect(kpi('Alerts')).toHaveTextContent('—');
	});

	it('says who it is could not be looked up when both lookups fail', async () => {
		stubDaemon({ ...baseReplies(ADDRESS), '/api/geoip/*': undefined, '/api/lookup/dns/*': undefined });
		render(Page);
		expect(await screen.findByText("Couldn't load who this address is: the request failed.")).toBeInTheDocument();
		expect(kpi('Connections')).toHaveTextContent('1,980');
	});

	it('reports ok, partial and failed to the top bar, keeping the last figures', async () => {
		stubDaemon(baseReplies(ADDRESS));
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		expect(await refreshPage()).toBe('ok');
		stubDaemon({ ...baseReplies(ADDRESS), '/api/addresses/*': undefined });
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText(/Couldn't refresh this address; showing the last figures loaded/)).toBeInTheDocument();
		expect(kpi('Connections')).toHaveTextContent('1,980');
		stubDaemon({ '/api/network/lan': LAN_POLICY });
		expect(await refreshPage()).toBe('failed');
	});

	it('discloses the 10,000-row reach and links to Log Explorer', async () => {
		stubDaemon(baseReplies(ADDRESS, 25_000));
		render(Page);
		const notice = await screen.findByText(/Showing the newest 10,000 of 25,000\./);
		const link = within(notice.closest('p')!).getByRole('link', { name: 'search them all in Log Explorer' });
		expect(decodeURIComponent(link.getAttribute('href')!)).toBe('/logs?query=(source.ip:"198.51.100.10" OR destination.ip:"198.51.100.10")');
		expect(screen.getByText('Showing 1 to 25 of 10,000')).toBeInTheDocument();
	});

	it('looks up WHOIS only when asked', async () => {
		stubDaemon(baseReplies(ADDRESS));
		render(Page);
		const button = await screen.findByRole('button', { name: 'Look it up' });
		expect(calls.some((u) => u.pathname.startsWith('/api/lookup/whois'))).toBe(false);
		await fireEvent.click(button);
		expect(await screen.findByText('Example Streaming CDN', { selector: 'dd' })).toBeInTheDocument();
	});

	it('offers the device page for an address on your network', async () => {
		goTo('192.168.1.22');
		stubDaemon(baseReplies({ ...ADDRESS, ip: '192.168.1.22', lan: true }));
		render(Page);
		const link = await screen.findByRole('link', { name: 'Open its device page' });
		expect(link).toHaveAttribute('href', '/devices/192.168.1.22');
		expect(screen.getByText('On your network')).toBeInTheDocument();
	});

	it('reloads for another address and drops a late reply for the old one', async () => {
		let releaseOld: (v: unknown) => void = () => {};
		let askedOld = false;
		stubDaemon(baseReplies(ADDRESS));
		const fetchStub = vi.mocked(globalThis.fetch as (input: string) => Promise<unknown>);
		const answer = fetchStub.getMockImplementation()!;
		fetchStub.mockImplementation(async (input: string) =>
			input.startsWith('/api/addresses/198.51.100.10')
				? new Promise((r) => {
						askedOld = true;
						releaseOld = () => r({ ok: true, status: 200, json: async () => ADDRESS });
					})
				: answer(input),
		);
		render(Page);
		await vi.waitFor(() => expect(askedOld).toBe(true));
		fetchStub.mockImplementation(async (input: string) =>
			input.startsWith('/api/addresses/') ? { ok: true, status: 200, json: async () => ADDRESS_QUIET } : answer(input),
		);
		goTo('192.0.2.80');
		await vi.waitFor(() => expect(kpi('Data to it')).toHaveTextContent('Not measured'));
		releaseOld(undefined);
		await new Promise((r) => setTimeout(r, 0));
		expect(kpi('Data to it')).toHaveTextContent('Not measured');
		expect(screen.getByRole('heading', { level: 1, name: '192.0.2.80' })).toBeInTheDocument();
	});
});
