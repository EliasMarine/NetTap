import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import { RECORDS_CHANGE, windowWords } from '$lib/utils/drilldown';
import { MOMENT_DEVICES, MOMENT_DEVICES_EMPTY } from '../../../e2e/visual/fixtures/moment';
import { LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-249: the moment page opens the exact window a chart point or range carried, and every
// figure on it links to the list that holds it over that window

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/moment') });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const FROM = '2026-11-12T14:05:00.000Z';
const TO = '2026-11-12T14:09:59.999Z';
const MIN = 60_000;
const CHART_FROM = '2026-11-11T14:05:00.000Z';
const CHART_TO = '2026-11-12T14:05:00.000Z';
const EXCLUDED = ['192.168.1.199'];

const echo = (u: URL) => ({ from: u.searchParams.get('from'), to: u.searchParams.get('to') });
const SUMMARY = (u: URL) => ({
	...echo(u), total_bytes: 2_800_000_000, orig_bytes: 0, resp_bytes: 0, download_bytes: 2_400_000_000, upload_bytes: 380_000_000, local_bytes: 20_000_000,
	packet_count: 0, connection_count: 321, top_protocol: 'tcp', excluded_ips: EXCLUDED,
});
const point = (k: number) => ({
	timestamp: new Date(Date.parse(FROM) + k * MIN).toISOString(), orig_bytes: 0, resp_bytes: 0,
	download_bytes: 100 * (k + 1), upload_bytes: 10 * (k + 1), local_bytes: k, total_bytes: 111 * (k + 1), connections: k + 1,
});
const ALERT = (id: string, rule: { name?: string }, severity: number, signature?: string) => ({
	_id: id, _index: 'x', timestamp: FROM, alert: { signature, severity }, rule, acknowledged: false,
});

type Reply = unknown | ((u: URL) => unknown);
const FULL: Record<string, Reply> = {
	'/api/network/lan': LAN_POLICY,
	'/api/traffic/summary': SUMMARY,
	'/api/alerts/count': (u: URL) => ({ ...echo(u), counts: { total: 12, high: 1, medium: 2, low: 9 } }),
	'/api/devices/count': (u: URL) => ({ ...echo(u), count: 7 }),
	'/api/traffic/bandwidth': (u: URL) => ({ ...echo(u), interval: u.searchParams.get('interval'), series: [0, 1, 2, 3, 4].map(point) }),
	'/api/moment/devices': MOMENT_DEVICES,
	'/api/traffic/protocols': (u: URL) => ({
		...echo(u), protocols: [], excluded_ips: EXCLUDED,
		services: [{ name: 'dns', count: 5 }, { name: 'ssl', count: 10 }, { name: 'unknown', count: 2 }, { name: 'ntp', count: 0 }],
	}),
	'/api/traffic/categories': (u: URL) => ({ ...echo(u), categories: [{ name: 'streaming', label: 'Streaming', total_bytes: 1_000_000_000, connection_count: 3, top_services: [] }] }),
	'/api/alerts': (u: URL) => ({
		...echo(u), page: 1, size: 10, total: 12, total_pages: 2,
		alerts: [ALERT('a1', { name: 'ET SCAN raw rule' }, 1, 'ET SCAN Nmap'), ALERT('a2', {}, 3, 'A rule with no name')],
	}),
	'/api/changelog': {
		count: 2,
		events: [
			{ _id: 'e1', '@timestamp': FROM, event_type: 'device_joined', title: 'New device', description: '', metadata: { mac: '02:00:5e:10:00:80', ip: '192.168.1.80' } },
			{ _id: 'e2', '@timestamp': FROM, event_type: 'device_joined', title: 'New device', description: '', metadata: { mac: '02:00:5e:10:00:81', ip: null } },
		],
	},
};
const EMPTY: Record<string, Reply> = {
	...FULL,
	'/api/traffic/summary': (u: URL) => ({ ...SUMMARY(u), total_bytes: 0, download_bytes: 0, upload_bytes: 0, local_bytes: 0, connection_count: 0 }),
	'/api/alerts/count': (u: URL) => ({ ...echo(u), counts: { total: 0, high: 0, medium: 0, low: 0 } }),
	'/api/devices/count': (u: URL) => ({ ...echo(u), count: 0 }),
	'/api/traffic/bandwidth': (u: URL) => ({ ...echo(u), interval: '1m', series: [] }),
	'/api/moment/devices': MOMENT_DEVICES_EMPTY,
	'/api/traffic/protocols': (u: URL) => ({ ...echo(u), protocols: [], services: [], excluded_ips: [] }),
	'/api/traffic/categories': (u: URL) => ({ ...echo(u), categories: [] }),
	'/api/alerts': (u: URL) => ({ ...echo(u), page: 1, size: 10, total: 0, total_pages: 0, alerts: [] }),
	'/api/changelog': { count: 0, events: [] },
};

let calls: URL[] = [];
const BUSY = 'Two other look-ups are being worked out right now; try again in a minute.';
/** Answers by pathname; a missing reply is a 503 with the daemon's reason. */
function stubDaemon(replies: Record<string, Reply>) {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			const reply = replies[url.pathname];
			const body = typeof reply === 'function' ? (reply as (u: URL) => unknown)(url) : reply;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({ error: BUSY }) };
		}),
	);
}

function goTo(query: string) {
	pageStore.value.set({ url: new URL(`http://localhost/moment${query}`) });
}
const at = (from = FROM, to = TO, extra = '') => goTo(`?from=${from}&to=${to}&range=1h${extra}`);

const kpi = (label: string) => screen.getByText(label, { selector: '.kpi-top > span' }).closest('.kpi') as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;
const params = (el: Element) => Object.fromEntries(new URL(el.getAttribute('href')!, 'http://x').searchParams);
const link = (name: string | RegExp, scope: HTMLElement = document.body) => within(scope).getByRole('link', { name });
const loaded = () => vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('321'));

describe('Moment page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
		goTo('');
	});

	it('shows loading on every card, not zeros, before the first answer', () => {
		at();
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'What your network was doing' })).toBeInTheDocument();
		expect(screen.getByText(windowWords(FROM, TO), { selector: '.page-sub' })).toBeInTheDocument();
		for (const label of ['Bandwidth', 'Connections', 'Alerts', 'Active devices']) expect(kpi(label)).toHaveTextContent('—');
		const busy = screen.getAllByRole('status').filter((s) => s.getAttribute('aria-busy') === 'true');
		expect(busy).toHaveLength(6); // chart, protocols, devices, categories, alerts, new devices
	});

	it('asks every endpoint for exactly the link window, with the bucket that fits it', async () => {
		at();
		stubDaemon(FULL);
		render(Page);
		await loaded();
		const asked = calls.filter((u) => u.pathname !== '/api/network/lan');
		expect(new Set(asked.map((u) => u.pathname)).size).toBe(9);
		for (const u of asked) expect([u.pathname, u.searchParams.get('from'), u.searchParams.get('to')]).toEqual([u.pathname, FROM, TO]);
		expect(asked.find((u) => u.pathname === '/api/traffic/bandwidth')!.searchParams.get('interval')).toBe('1m');
		expect(Object.fromEntries(asked.find((u) => u.pathname === '/api/alerts')!.searchParams)).toMatchObject({ size: '10', sort: 'severity', order: 'desc' });
		expect(Object.fromEntries(asked.find((u) => u.pathname === '/api/changelog')!.searchParams)).toMatchObject({ type: 'device_joined', limit: '50' });
		expect(asked.find((u) => u.pathname === '/api/moment/devices')!.searchParams.get('limit')).toBe('10');
	});

	it('links every count to the list that holds it over this window, and byte figures to nothing', async () => {
		at();
		stubDaemon(FULL);
		const { container } = render(Page);
		await loaded();
		const conn = { type: 'zeek.conn', exclude_src: '192.168.1.199', from: FROM, to: TO, range: '1h' };
		// Bandwidth sums bytes, which no list totals: a plain figure, and a records link with no count
		expect(kpi('Bandwidth').tagName).toBe('ARTICLE');
		expect(kpi('Bandwidth')).toHaveTextContent('2.8GB');
		expect(kpi('Bandwidth')).toHaveTextContent('↓ 2.4 GB down · ↑ 380.0 MB up · 20.0 MB local');
		expect(params(link('View connection records', kpi('Bandwidth')))).toEqual(conn);
		expect(params(kpi('Connections'))).toEqual({ ...conn, count: '321' });
		expect(params(kpi('Alerts'))).toEqual({ from: FROM, to: TO, range: '1h', count: '12' });
		expect(new URL(kpi('Active devices').getAttribute('href')!, 'http://x').pathname).toBe('/devices');
		expect(params(kpi('Active devices'))).toEqual({ view: 'all', from: FROM, to: TO, range: '1h', count: '7' });

		// protocol bars: the endpoint's whole predicate, biggest first, empty services left out
		const protocols = card('Protocols');
		expect(within(protocols).getAllByRole('link').map((a) => a.textContent)).toEqual(['SSL', 'DNS', 'Unidentified']);
		expect(params(link('SSL', protocols))).toEqual({ ...conn, query: 'network.protocol:"ssl" AND NOT network.protocol:"quic"', count: '10' });
		expect(params(link('Unidentified', protocols))).toEqual({ ...conn, query: 'NOT _exists_:network.protocol', count: '2' });
		// a category page has no window yet: navigation, no count
		expect(link('Streaming', card('Traffic categories'))).toHaveAttribute('href', '/traffic/streaming');

		const alerts = card('Alerts');
		expect(params(link(/ET SCAN Nmap/, alerts))).toEqual({ signature: 'ET SCAN raw rule', from: FROM, to: TO, range: '1h' });
		expect(params(link(/A rule with no name/, alerts))).toEqual({ no_rule_name: 'true', from: FROM, to: TO, range: '1h' });
		expect(params(link('All 12 alerts', alerts))).toEqual({ from: FROM, to: TO, range: '1h', count: '12' });

		const joined = card('New devices');
		expect(link(/02:00:5e:10:00:80/, joined)).toHaveAttribute('href', '/devices/192.168.1.80');
		expect(link(/02:00:5e:10:00:81/, joined)).toHaveAttribute('href', '/devices/mac/02%3A00%3A5e%3A10%3A00%3A81');

		expect(params(link('Open in Log Explorer'))).toEqual(conn);
		expectNoNestedInteractive(container);
	});

	it("lists the top devices with what each talked to; their bytes are plain and their records link has no count", async () => {
		at();
		stubDaemon(FULL);
		render(Page);
		await loaded();
		const devices = card('Top devices');
		await vi.waitFor(() => expect(within(devices).getByRole('table')).toBeInTheDocument());
		const [top] = MOMENT_DEVICES.devices;
		expect(devices).toHaveTextContent(`top ${MOMENT_DEVICES.devices.length} of ${MOMENT_DEVICES.total_devices}`);
		const row = link(top.name!, devices).closest('tr')!;
		expect(link(top.name!, devices)).toHaveAttribute('href', `/devices/${top.ip}`);
		// the byte cells hold text only
		for (const cell of [...row.querySelectorAll('td')].slice(1)) expect(cell.querySelector('a')).toBeNull();
		expect(row).toHaveTextContent('24.1 GB');
		expect(params(link(`Connection records for ${top.ip}`, row))).toEqual({
			query: `(source.ip:"${top.ip}" OR destination.ip:"${top.ip}")`, range: '1h', type: 'zeek.conn', from: FROM, to: TO,
		});
		expect(link(top.destinations[0].ip, row)).toHaveAttribute('href', `/address/${top.destinations[0].ip}`);
		expect(link(top.domains[0].domain, row)).toHaveAttribute('href', `/domain/${top.domains[0].domain}`);
		expect(within(row).getByText(top.apps[0].protocol)).toBeInTheDocument();
		// IPv6 left out says how much and why; a device that started nothing says so
		expect(devices).toHaveTextContent('14 IPv6 connections left out of these totals.');
		expect(devices).toHaveTextContent('no internet traffic showed which device is the router');
		expect(within(devices).getByText('Started no connections in this window.')).toBeInTheDocument();
	});

	it('gives every card its own error, with the daemon reason where it has one', async () => {
		at();
		stubDaemon({ '/api/network/lan': LAN_POLICY });
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent("Couldn't load connection totals: the request failed."));
		expect(kpi('Bandwidth')).toHaveTextContent("Couldn't load traffic totals: the request failed.");
		expect(kpi('Alerts')).toHaveTextContent("Couldn't load the alert count: the request failed.");
		expect(kpi('Active devices')).toHaveTextContent("Couldn't load the device count: the request failed.");
		for (const what of ['bandwidth in this window', 'protocols', 'top devices', 'traffic categories', 'alerts', 'new devices']) {
			expect(screen.getByRole('heading', { name: `Couldn't load ${what}: the request failed.` })).toBeInTheDocument();
		}
		expect(within(card('Top devices')).getByText(BUSY)).toBeInTheDocument();
		// a count with no figure still opens the window, with nothing to compare
		expect(params(kpi('Alerts'))).toEqual({ from: FROM, to: TO, range: '1h' });
	});

	it('keeps the last figures on a failed refresh, and says so on every card', async () => {
		at();
		stubDaemon(FULL);
		render(Page);
		await loaded();
		await vi.waitFor(() => expect(within(card('Top devices')).getByRole('table')).toBeInTheDocument());
		stubDaemon({ '/api/network/lan': LAN_POLICY });
		await refreshPage();
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent("Couldn't refresh connection totals; showing the last figures loaded."));
		expect(kpi('Connections')).toHaveTextContent('321');
		expect(kpi('Bandwidth')).toHaveTextContent('2.8GB');
		for (const what of ['bandwidth in this window', 'protocols', 'top devices', 'traffic categories', 'alerts', 'new devices']) {
			expect(screen.getByText(`Couldn't refresh ${what}; showing the last figures loaded.`)).toBeInTheDocument();
		}
		expect(link('SSL', card('Protocols'))).toBeInTheDocument();
		expect(within(card('Top devices')).getByRole('table')).toBeInTheDocument();
	});

	it('gives every card its own empty state', async () => {
		at();
		stubDaemon(EMPTY);
		render(Page);
		await vi.waitFor(() => expect(kpi('Connections')).toHaveTextContent('0'));
		for (const title of [
			'No bandwidth data for this window',
			'No connections in this window',
			'No devices seen in this window',
			'No category data for this window',
			'No alerts in this window',
			'No new devices joined in this window',
		]) {
			expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
		}
	});

	it.each([
		['no window', ''],
		['an unreadable time', `?from=soon&to=${TO}`],
		['a start after the end', `?from=${TO}&to=${FROM}`],
	])('shows %s as an error, invents no window and asks for nothing', (_, query) => {
		goTo(query);
		stubDaemon(FULL);
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'What your network was doing' })).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: "There's no moment to show" })).toBeInTheDocument();
		expect(link('Go to the overview')).toHaveAttribute('href', '/');
		expect(calls).toEqual([]);
		expect(screen.queryByRole('link', { name: '±15 min' })).not.toBeInTheDocument();
	});

	it("opens a one-millisecond window (a chart's trailing slot) as that moment, with no packets link", async () => {
		at(FROM, FROM);
		stubDaemon(FULL);
		render(Page);
		await loaded();
		expect(screen.getByText(/^at \d\d:\d\d:\d\d, /, { selector: '.page-sub' })).toBeInTheDocument();
		expect(calls.find((u) => u.pathname === '/api/traffic/summary')!.searchParams.toString()).toBe(new URLSearchParams({ from: FROM, to: FROM }).toString());
		expect(screen.queryByRole('link', { name: 'Search packets in this window' })).not.toBeInTheDocument();
	});

	it('offers packets only for a window of 30 minutes or less', async () => {
		at();
		stubDaemon(FULL);
		const { unmount } = render(Page);
		await loaded();
		const href = new URL(link('Search packets in this window').getAttribute('href')!, 'http://x');
		expect(href.pathname).toBe('/packets');
		expect([href.searchParams.get('from'), href.searchParams.get('to')]).toEqual([String(Date.parse(FROM) / 1000), String(Date.parse(TO) / 1000)]);
		unmount();

		at(FROM, new Date(Date.parse(FROM) + 30 * MIN).toISOString());
		render(Page);
		await loaded();
		expect(link('Search packets in this window')).toBeInTheDocument();
		goTo(`?from=${FROM}&to=${new Date(Date.parse(FROM) + 31 * MIN).toISOString()}`);
		await vi.waitFor(() => expect(screen.queryByRole('link', { name: 'Search packets in this window' })).not.toBeInTheDocument());
	});

	it('widens by 15 minutes, an hour or to the whole chart, dropping the figures clicked', async () => {
		const clicked = '&down=2400000000&up=380000000&local=20000000&count=9';
		at(FROM, TO, `${clicked}&chart_from=${CHART_FROM}&chart_to=${CHART_TO}`);
		stubDaemon(FULL);
		render(Page);
		await loaded();
		const kept = { range: '1h', chart_from: CHART_FROM, chart_to: CHART_TO };
		const shift = (iso: string, ms: number) => new Date(Date.parse(iso) + ms).toISOString();
		expect(params(link('±15 min'))).toEqual({ from: shift(FROM, -15 * MIN), to: shift(TO, 15 * MIN), ...kept });
		expect(params(link('±1 h'))).toEqual({ from: shift(FROM, -60 * MIN), to: shift(TO, 60 * MIN), ...kept });
		expect(params(link('Whole chart'))).toEqual({ from: CHART_FROM, to: CHART_TO, ...kept });

		// a widened page compares nothing, and loads its own window
		goTo(link('Whole chart').getAttribute('href')!.replace('/moment', ''));
		await vi.waitFor(() => expect(calls.some((u) => u.pathname === '/api/traffic/summary' && u.searchParams.get('from') === CHART_FROM)).toBe(true));
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it('offers no Whole chart without the chart window', async () => {
		at();
		stubDaemon(FULL);
		render(Page);
		await loaded();
		expect(link('±15 min')).toBeInTheDocument();
		expect(screen.queryByRole('link', { name: 'Whole chart' })).not.toBeInTheDocument();
	});

	it('says nothing when the figures clicked match, and says per figure when data grew', async () => {
		at(FROM, TO, '&down=2400000000&up=380000000&local=20000000');
		stubDaemon(FULL);
		const { unmount } = render(Page);
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		unmount();

		at(FROM, TO, '&down=2300000000&up=380000000&local=10000000');
		render(Page);
		await loaded();
		const note = screen.getByText(/You clicked/);
		expect(note.textContent).toBe(
			'You clicked 2.3 GB downloaded. This window now shows 2.4 GB (100.0 MB more). ' +
				'You clicked 10.0 MB on your network. This window now shows 20.0 MB (10.0 MB more). ' +
				RECORDS_CHANGE,
		);
	});

	it('explains a different split when the total matches the chart, and ignores a figure that is not a whole number', async () => {
		at(FROM, TO, '&down=2500000000&up=280000000&local=20000000');
		stubDaemon(FULL);
		const { unmount } = render(Page);
		await loaded();
		const note = screen.getByText(/You clicked/).textContent!;
		expect(note).toContain('You clicked 2.5 GB downloaded. This window now shows 2.4 GB (100.0 MB less).');
		expect(note).toContain('You clicked 280.0 MB uploaded. This window now shows 380.0 MB (100.0 MB more).');
		expect(note).toMatch(/The total matches the chart\. Some IPv6 traffic is split between downloaded and uploaded differently/);
		expect(note).not.toContain(RECORDS_CHANGE);
		unmount();

		at(FROM, TO, '&down=-5&up=1.5&local=abc');
		render(Page);
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it("drills into a narrower moment from its own chart, passing the first chart's window on", async () => {
		at(FROM, TO, `&chart_from=${CHART_FROM}&chart_to=${CHART_TO}`);
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		stubDaemon(FULL);
		render(Page);
		await loaded();
		const chart = await screen.findByRole('group', { name: /^Bandwidth / });
		expect(screen.getByText('Click a point or drag across the chart to see that moment.')).toBeInTheDocument();
		await fireEvent.keyDown(chart, { key: 'Home' });
		await fireEvent.keyDown(chart, { key: 'ArrowRight', shiftKey: true });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		const href = new URL(String(vi.mocked(goto).mock.calls[0][0]), 'http://x');
		expect(href.pathname).toBe('/moment');
		expect(Object.fromEntries(href.searchParams)).toEqual({
			from: FROM, to: '2026-11-12T14:06:59.999Z', range: '1h', down: '300', up: '30', local: '1', chart_from: CHART_FROM, chart_to: CHART_TO,
		});
	});
});
