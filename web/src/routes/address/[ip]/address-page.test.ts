import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
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
				{ _id: 'c1', _index: 'x', '@timestamp': '2026-11-06T08:00:00Z', direction: 'in', source: { ip: '192.168.1.22', port: 50000, bytes: 1000 }, destination: { ip: '198.51.100.10', port: 443 }, network: { transport: 'tcp', protocol: 'ssl' } },
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
const params = (el: Element) => Object.fromEntries(new URL(el.getAttribute('href')!, 'http://x').searchParams);
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
		// NET-160 section D: no figure yet, so the Alerts card links by range alone and carries no count
		expect(kpi('Alerts').closest('a')).toHaveAttribute('href', '/alerts?ip=198.51.100.10&range=24h');
	});

	it('shows the exact figures, with partial byte totals as lower bounds', async () => {
		stubDaemon(baseReplies(ADDRESS));
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		expect(kpi('Data to it')).toHaveTextContent('at least 200.0 MB');
		// OLD CODE: 'From it: at least 17.8 GB' (18,200 MiB in 1024-based units; NET-166)
		expect(kpi('Data to it')).toHaveTextContent('From it: at least 18.2 GB');
		expect(kpi('Data to it')).toHaveTextContent('To it: 1,970 of 1,980 connections measured · from it: 1,970 of 1,980 connections measured');
		expect(kpi('Devices that talked to it')).toHaveTextContent('3');
		expect(kpi('Devices that talked to it')).toHaveTextContent('on your network, of 3 addresses in all');
		// OLD CODE START: expect(kpi('Alerts').closest('a')).toHaveAttribute('href', '/alerts?ip=198.51.100.10'); OLD CODE END
		// the alerts page opens on this page's window, so its list matches the count
		// OLD CODE: expect(kpi('Alerts').closest('a')).toHaveAttribute('href', '/alerts?ip=198.51.100.10&range=24h'); (section D: the figures' own window, and the figure)
		const asked = calls.find((u) => u.pathname === '/api/addresses/198.51.100.10')!.searchParams;
		expect(params(kpi('Alerts').closest('a')!)).toEqual({ ip: '198.51.100.10', from: asked.get('from'), to: asked.get('to'), range: '24h', count: String(ADDRESS.alerts) });
		expect(screen.getByText('Not on a threat list')).toBeInTheDocument();
		expect(screen.getByText("Checked this window's alerts and 5,400 cached indicators")).toBeInTheDocument();
		// a port lists every service Zeek saw on it, each connection counted once
		const quic = within(card('Ports on this address')).getByText('quic, ssl').closest('tr')!;
		expect(quic).toHaveTextContent('250');
		// the daemon buckets a 24-hour window by the hour
		expect(screen.getByText('Connections per hour · last 24 hours')).toBeInTheDocument();
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
		// every TLS session counts here; Certificates counts only those that showed a certificate
		expect(within(tls).getByText(/so its figures can be lower/)).toBeInTheDocument();
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
		// a peer whose sessions carried no byte count: Not measured, never "at least 0 B"
		const quietPeer = within(card('Devices that talked to it')).getByRole('link', { name: '192.168.1.50' }).closest('tr')!;
		expect(quietPeer).toHaveTextContent('Not measured');
		expect(quietPeer).not.toHaveTextContent('0 B');
		// OLD CODE START: expect(screen.getByText(/On a threat list: Example blocklist/)).toBeInTheDocument(); OLD CODE END
		// a listing-rule alert in the window named it, with no indicator cache loaded
		expect(screen.getByText(/On a threat list: ET Compromised IPs/)).toBeInTheDocument();
		expect(screen.getByText('No name (SNI)')).toBeInTheDocument();
		expect(screen.getByText(/Too many addresses to list them all/)).toBeInTheDocument();
		expect(screen.getByText(/Too many ports to list them all/)).toBeInTheDocument();
		expect(screen.getByText(/Too many names to list them all/)).toBeInTheDocument();
		// a list cut at its cap says so in its subtitle too
		expect(card('Devices that talked to it')).toHaveTextContent('First 2 addresses · your devices first');
		// the no-name row has no certificates link: without a site it would open every certificate on the server
		const tls = card('Names it served (TLS)');
		expect(within(screen.getByText('No name (SNI)').closest('tr')!).queryByRole('link')).toBeNull();
		expect(within(tls).getByRole('link', { name: 'Certificates seen for telemetry.example.org' })).toBeInTheDocument();
		// connections with no port or transport recorded keep a row, so the rows add up
		const unknown = within(card('Ports on this address')).getByText('Unknown port').closest('tr')!;
		expect(unknown).toHaveTextContent('—');
		expect(unknown).toHaveTextContent('90');
		expectNoNestedInteractive(container);
	});

	// OLD CODE START — null meant "no indicators loaded"; with no cache the daemon still checks the window's alerts
	// it('says the address was not checked against threat lists when none are loaded, and shows empty states', async () => {
	// 	stubDaemon(baseReplies(ADDRESS_EMPTY, 0));
	// 	render(Page);
	// 	await screen.findByText('Not checked: no threat indicators loaded yet');
	// OLD CODE END
	it('says what it checked with no indicator cache, and shows empty states', async () => {
		stubDaemon(baseReplies(ADDRESS_EMPTY, 0));
		render(Page);
		await screen.findByText('Not on a threat list');
		// zero cached indicators is still a check of the window's alerts, not "not checked"
		expect(screen.getByText("Checked this window's alerts")).toBeInTheDocument();
		expect(screen.queryByText('Not checked')).toBeNull();
		expect(kpi('Connections')).toHaveTextContent('0');
		expect(kpi('Data to it')).toHaveTextContent('0 B');
		expect(screen.getAllByText('No connections in the last 24 hours').length).toBe(2);
		expect(screen.getByText('Nothing talked to it in the last 24 hours')).toBeInTheDocument();
	});

	it('carries the loaded window to the alerts page and Log Explorer', async () => {
		stubDaemon(baseReplies(ADDRESS, 25_000));
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		await fireEvent.click(screen.getByRole('button', { name: '30d' }));
		// OLD CODE: await vi.waitFor(() => expect(kpi('Alerts').closest('a')).toHaveAttribute('href', '/alerts?ip=198.51.100.10&range=30d')); (section D)
		await vi.waitFor(() => expect(params(kpi('Alerts').closest('a')!)).toMatchObject({ range: '30d', count: String(ADDRESS.alerts) }));
		const asked = calls.filter((u) => u.pathname === '/api/addresses/198.51.100.10').at(-1)!.searchParams;
		expect(Date.parse(asked.get('to')!) - Date.parse(asked.get('from')!)).toBe(720 * 3_600_000);
		// NET-160 section D: the 30-day figures' own window, and the figure, so the list can say if it differs
		expect(params(kpi('Alerts').closest('a')!)).toEqual({ ip: '198.51.100.10', from: asked.get('from'), to: asked.get('to'), range: '30d', count: String(ADDRESS.alerts) });
		const logs = await screen.findByRole('link', { name: 'search them all in Log Explorer' });
		expect(new URL(logs.getAttribute('href')!, 'http://x').searchParams.get('range')).toBe('30d');
	});

	it('says Not checked only when the daemon could not check every alert and nothing matched', async () => {
		stubDaemon(baseReplies({ ...ADDRESS, threat_intel: null }));
		render(Page);
		expect(await screen.findByText('Not checked')).toBeInTheDocument();
		expect(screen.getByText("This window's alerts couldn't all be checked")).toBeInTheDocument();
		expect(screen.queryByText('Not on a threat list')).toBeNull();
	});

	it.each([
		[503, 'Working this out took too long. Try a shorter time range.'],
		[500, 'Something went wrong working this out; the daemon log has the details.'],
	])("shows the daemon's HTTP %s text as it is", async (status, reason) => {
		stubDaemon(baseReplies(ADDRESS));
		const fetchStub = vi.mocked(globalThis.fetch as (input: string) => Promise<unknown>);
		const answer = fetchStub.getMockImplementation()!;
		fetchStub.mockImplementation(async (input: string) =>
			input.startsWith('/api/addresses/') ? { ok: false, status, json: async () => ({ error: reason }) } : answer(input),
		);
		render(Page);
		await vi.waitFor(() => expect(screen.getAllByText(reason).length).toBeGreaterThan(0));
		expect(kpi('Connections')).toHaveTextContent('—');
	});

	it("shows the daemon's reason when the summary fails, never zeros", async () => {
		stubDaemon({ ...baseReplies(undefined), '/api/addresses/*': undefined });
		render(Page);
		await vi.waitFor(() => expect(screen.getAllByText("Couldn't load connections over time: the request failed.").length).toBe(1));
		expect(screen.getAllByText('The daemon is busy with other drill-downs; try again in a minute.').length).toBeGreaterThan(0);
		expect(kpi('Connections')).toHaveTextContent('—');
		expect(kpi('Alerts')).toHaveTextContent('—');
	});

	// OLD CODE START — reverse DNS ran on every visit, and the card failed when both lookups did
	// it('says who it is could not be looked up when both lookups fail', async () => {
	// 	stubDaemon({ ...baseReplies(ADDRESS), '/api/geoip/*': undefined, '/api/lookup/dns/*': undefined });
	// 	render(Page);
	// 	expect(await screen.findByText("Couldn't load who this address is: the request failed.")).toBeInTheDocument();
	// 	expect(kpi('Connections')).toHaveTextContent('1,980');
	// });
	// OLD CODE END
	it('says where it is could not be looked up, and keeps the name and WHOIS look-ups a click away', async () => {
		stubDaemon({ ...baseReplies(ADDRESS), '/api/geoip/*': undefined });
		render(Page);
		const who = card('Who it is');
		await vi.waitFor(() => expect(within(who).getByText("Couldn't look it up")).toBeInTheDocument());
		expect(within(who).getByRole('button', { name: 'Look up its name' })).toBeEnabled();
		expect(within(who).getByRole('button', { name: 'Look it up' })).toBeEnabled();
		expect(kpi('Connections')).toHaveTextContent('1,980');
	});

	it('looks up reverse DNS only when asked, since the lookup reaches whoever runs the address', async () => {
		stubDaemon(baseReplies(ADDRESS));
		render(Page);
		const button = await screen.findByRole('button', { name: 'Look up its name' });
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		expect(calls.some((u) => u.pathname.startsWith('/api/lookup/dns'))).toBe(false);
		await fireEvent.click(button);
		expect(await within(card('Who it is')).findByText('stream.example.net')).toBeInTheDocument();
	});

	// NET-192 PR 3: the daemon gives the resolver 6 s, then answers 200 with no name
	it('says the reverse lookup timed out, instead of "None"', async () => {
		stubDaemon({
			...baseReplies(ADDRESS),
			'/api/lookup/dns/*': { ip: ADDRESS.ip, hostname: null, aliases: [], addresses: [], error: null, timed_out: true },
		});
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Look up its name' }));
		const who = card('Who it is');
		expect(await within(who).findByText('Reverse DNS lookup timed out')).toBeInTheDocument();
		expect(within(who).queryByText('None')).not.toBeInTheDocument();
	});

	it('shows the figures as soon as they land, without waiting for the location lookup', async () => {
		stubDaemon({ ...baseReplies(ADDRESS), '/api/geoip/*': () => new Promise(() => {}) });
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		expect(within(card('Who it is')).getByText('Looking up this address')).toBeInTheDocument();
	});

	it('ties each look-up to its address: another address gets its own button, and a late reply is dropped', async () => {
		stubDaemon(baseReplies(ADDRESS));
		const fetchStub = vi.mocked(globalThis.fetch as (input: string) => Promise<unknown>);
		const answer = fetchStub.getMockImplementation()!;
		const late: ((v: unknown) => void)[] = [];
		fetchStub.mockImplementation(async (input: string) =>
			input.startsWith('/api/lookup/') ? new Promise((r) => late.push(r)) : answer(input),
		);
		render(Page);
		const who = card('Who it is');
		await fireEvent.click(await within(who).findByRole('button', { name: 'Look it up' }));
		await fireEvent.click(within(who).getByRole('button', { name: 'Look up its name' }));
		expect(within(who).getAllByRole('button', { name: 'Looking up…' })).toHaveLength(2);
		goTo('192.0.2.80');
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1, name: '192.0.2.80' })).toBeInTheDocument());
		const whoNow = card('Who it is');
		await vi.waitFor(() => expect(within(whoNow).getByRole('button', { name: 'Look it up' })).toBeEnabled());
		expect(within(whoNow).getByRole('button', { name: 'Look up its name' })).toBeEnabled();
		// the first address's replies land late
		for (const r of late) r({ ok: true, status: 200, json: async () => ({ ip: '198.51.100.10', hostname: 'stream.example.net', raw: 'x', parsed: { orgname: 'Example Streaming CDN' }, aliases: [], addresses: [], error: null }) });
		await new Promise((r) => setTimeout(r, 0));
		expect(within(whoNow).queryByText('stream.example.net')).toBeNull();
		expect(within(whoNow).getByRole('button', { name: 'Look it up' })).toBeEnabled();
	});

	it('shows each session\'s bytes by direction, and "—" for a count that is missing or not a number', async () => {
		const row = (id: string, direction: string, source: object, destination: object) => ({
			_id: id, _index: 'x', '@timestamp': '2026-11-06T08:00:00Z', direction, source, destination, network: { transport: 'tcp', protocol: 'ssl' },
		});
		stubDaemon({
			...baseReplies(ADDRESS),
			'/api/devices/*': {
				...CONNECTIONS(3),
				connections: [
					// it opened this one: what the source sent came from it
					// decimal units (NET-166): 2,000 bytes is 2.0 KB
					row('out', 'out', { ip: '198.51.100.10', port: 443, bytes: 2000 }, { ip: '192.168.1.22', port: 50000, bytes: 'n/a' }),
					row('none', 'in', { ip: '192.168.1.22', port: 50001 }, { ip: '198.51.100.10', port: 443 }),
					row('in', 'in', { ip: '192.168.1.20', port: 50002, bytes: 1000 }, { ip: '198.51.100.10', port: 443, bytes: 4000 }),
				],
			},
		});
		render(Page);
		const table = await within(card('Connections')).findByRole('table');
		const rows = within(table).getAllByRole('row').slice(1);
		const cells = (i: number) => [...rows[i].querySelectorAll('td')].map((td) => td.textContent?.trim());
		// the other side's port shows, numbers included; the last two columns are Data to it, Data from it
		expect(cells(0)).toContain('192.168.1.22:50000');
		expect(cells(0).slice(-2)).toEqual(['—', '2.0 KB']);
		expect(cells(1).slice(-2)).toEqual(['—', '—']);
		expect(cells(2).slice(-2)).toEqual(['1.0 KB', '4.0 KB']);
	});

	it('keeps TLS rows apart when a client sends the literal name "(no name)"', async () => {
		stubDaemon(baseReplies({ ...ADDRESS, tls_names: [
			{ name: null, sessions: 3, statuses: { unchecked: 3 } },
			{ name: '(no name)', sessions: 2, statuses: { ok: 2 } },
			{ name: 'null', sessions: 1, statuses: { ok: 1 } },
		] }));
		render(Page);
		const tls = await vi.waitFor(() => card('Names it served (TLS)'));
		await vi.waitFor(() => expect(within(tls).getAllByRole('row')).toHaveLength(4));
		expect(within(tls).getByText('No name (SNI)')).toBeInTheDocument();
		// OLD CODE START: expect(within(tls).getByRole('link', { name: '(no name)' })).toBeInTheDocument(); OLD CODE END
		// not a host name: shown as sent, with no domain page or certificates link to fail on
		expect(within(tls).getByText('(no name)').closest('a')).toBeNull();
		expect(within(within(tls).getByText('(no name)').closest('tr')!).queryByRole('link')).toBeNull();
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
		// the daemon answers with the page it was asked for
		stubDaemon({ ...baseReplies(ADDRESS), '/api/devices/*': (u: URL) => ({ ...CONNECTIONS(25_000), page: Number(u.searchParams.get('page')) }) });
		render(Page);
		const notice = await screen.findByText(/Showing the newest 10,000 of 25,000\./);
		const link = within(notice.closest('p')!).getByRole('link', { name: 'search them all in Log Explorer' });
		// OLD CODE START: expect(decodeURIComponent(link.getAttribute('href')!)).toBe('/logs?query=(source.ip:"198.51.100.10" OR destination.ip:"198.51.100.10")'); OLD CODE END
		// OLD CODE: expect(decodeURIComponent(link.getAttribute('href')!)).toBe('/logs?query=(source.ip:"198.51.100.10" OR destination.ip:"198.51.100.10")&range=24h'); (slice 2a: the count's own window too)
		const conn = calls.find((u) => u.pathname.endsWith('/connections'))!;
		// OLD CODE START (section D: every log type, while 25,000 counts conn records; no figure carried)
		// expect(decodeURIComponent(link.getAttribute('href')!)).toBe(
		// 	`/logs?query=(source.ip:"198.51.100.10" OR destination.ip:"198.51.100.10")&range=24h&from=${conn.searchParams.get('from')}&to=${conn.searchParams.get('to')}`,
		// );
		// OLD CODE END
		expect(decodeURIComponent(link.getAttribute('href')!)).toBe(
			`/logs?query=(source.ip:"198.51.100.10" OR destination.ip:"198.51.100.10")&range=24h&type=zeek.conn&from=${conn.searchParams.get('from')}&to=${conn.searchParams.get('to')}&count=25000`,
		);
		expect(screen.getByText('Showing 1 to 25 of 10,000')).toBeInTheDocument();
		// a refresh of the same view stays on the page the user is reading
		await fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
		await vi.waitFor(() => expect(calls.at(-1)?.searchParams.get('page')).toBe('2'));
		await refreshPage();
		const pages = calls.filter((u) => u.pathname.endsWith('/connections')).map((u) => u.searchParams.get('page'));
		expect(pages.at(-1)).toBe('2');
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
		// the first address's connections are on screen
		await vi.waitFor(() => expect(within(card('Connections')).getAllByRole('row').length).toBeGreaterThan(1));
		fetchStub.mockImplementation(async (input: string) =>
			input.startsWith('/api/addresses/')
				? { ok: true, status: 200, json: async () => ADDRESS_QUIET }
				: input.startsWith('/api/devices/192.0.2.80/')
					? new Promise(() => {}) // the new address's connections are still on their way
					: answer(input),
		);
		goTo('192.0.2.80');
		await vi.waitFor(() => expect(kpi('Data to it')).toHaveTextContent('Not measured'));
		// never the old address's rows under the new one's figures
		expect(within(card('Connections')).queryByRole('table')).toBeNull();
		expect(within(card('Connections')).getByText('Loading connections')).toBeInTheDocument();
		releaseOld(undefined);
		await new Promise((r) => setTimeout(r, 0));
		expect(kpi('Data to it')).toHaveTextContent('Not measured');
		expect(screen.getByRole('heading', { level: 1, name: '192.0.2.80' })).toBeInTheDocument();
	});

	it("asks for a zone id once encoded and shows the daemon's 400 as an error", async () => {
		// SvelteKit hands the page the decoded param; decoding it again threw on the "%"
		goTo('fe80::1%eth0');
		stubDaemon({ ...baseReplies(undefined), '/api/addresses/*': undefined }, 'That is not an IP address.');
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'fe80::1%eth0' })).toBeInTheDocument();
		await vi.waitFor(() => expect(screen.getAllByText('That is not an IP address.').length).toBeGreaterThan(0));
		expect(calls.some((u) => u.pathname === '/api/addresses/fe80%3A%3A1%25eth0')).toBe(true);
		expect(kpi('Connections')).toHaveTextContent('—');
	});
});

// NET-160 slice 2a: each port opens its connections in Log Explorer, with the count's own filters
// (this address as the destination, no source) over the window the count came from
describe('Address page — port links', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:00Z'));
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		goTo('198.51.100.10');
	});

	const conn = (port: number, transport: string) =>
		`event.provider:zeek AND event.dataset:conn AND destination.ip:"198.51.100.10" AND destination.port:${port} AND network.transport:${transport}`;

	it("links each port over its count's window, not a newer refresh's", async () => {
		stubDaemon(baseReplies(ADDRESS));
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('1,980'));
		const sent = calls.find((u) => u.pathname === '/api/addresses/198.51.100.10')!;

		// ten minutes on, a refresh whose figures haven't arrived must not move the links
		vi.setSystemTime(new Date('2026-11-06T12:10:00Z'));
		stubDaemon({ ...baseReplies(ADDRESS), '/api/addresses/*': () => new Promise(() => {}) });
		void refreshPage();
		await vi.waitFor(() => expect(calls.some((u) => u.pathname === '/api/addresses/198.51.100.10')).toBe(true));

		const links = within(card('Ports on this address')).getAllByRole('link').map((a) => new URL(a.getAttribute('href')!, 'http://x'));
		expect(links.map((u) => u.searchParams.get('query'))).toEqual([conn(443, 'tcp'), conn(443, 'udp'), conn(80, 'tcp')]);
		// NET-160 section D: each carries the row's connection count, the figure clicked
		expect(links.map((u) => u.searchParams.get('count'))).toEqual(['1700', '250', '30']);
		for (const u of links) {
			expect(u.pathname).toBe('/logs');
			expect(u.searchParams.get('query')).not.toContain('source.ip');
			expect(['from', 'to', 'range'].map((k) => u.searchParams.get(k))).toEqual([sent.searchParams.get('from'), sent.searchParams.get('to'), '24h']);
		}
	});

	it('leaves a port without a number or a transport as text', async () => {
		const ports = [
			{ port: 8883, transport: null, services: [], connections: 5 },
			{ port: null, transport: 'tcp', services: [], connections: 3 },
		];
		stubDaemon(baseReplies({ ...ADDRESS, ports }));
		render(Page);
		const port = await vi.waitFor(() => within(card('Ports on this address')).getByText('8883'));
		expect(port.closest('a')).toBeNull();
		expect(within(card('Ports on this address')).queryAllByRole('link')).toHaveLength(0);
	});
});
