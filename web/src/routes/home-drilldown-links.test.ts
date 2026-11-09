import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import HomePage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';
import { _configure } from '$lib/stores/alertSnapshot';
import type { SmartAlert, SmartAlertKey } from '$api/alerts';

// NET-160 slice 2b-1: Home's figures open the list that holds them, over the window of the
// response on screen: a smart alert's ×N, and the Alerts, Connections and Bandwidth cards.

const REQUESTS = 15;
const KEY: SmartAlertKey = { rule_name: 'ET SCAN The raw rule', source_ip: '192.168.1.20', destination_ip: '93.184.216.34' };

interface Call {
	path: string;
	url: URL;
	reply: (body?: unknown) => void;
	fail: () => void;
}
let calls: Call[] = [];
/** Per-path reply bodies for this test, over the defaults below. */
let overrides: Record<string, (from: string, to: string) => unknown> = {};

function group(key: SmartAlertKey, signature = 'A friendlier shown name'): SmartAlert {
	return {
		signature_id: 0, signature, suricata_category: '', severity: 3, severity_label: 'MEDIUM', category: 'recon',
		category_label: 'Reconnaissance', source_ip: key.source_ip ?? '', destination_ip: key.destination_ip ?? '', count: 7,
		first_seen: '', last_seen: '', trend: 'stable', assessment: '', key,
	};
}

function body(url: URL): unknown {
	const from = url.searchParams.get('from') ?? '';
	const to = url.searchParams.get('to') ?? '';
	if (overrides[url.pathname]) return overrides[url.pathname](from, to);
	switch (url.pathname) {
		case '/api/traffic/summary':
			return { from, to, total_bytes: 5_000_000, orig_bytes: 1_000_000, resp_bytes: 4_000_000, upload_bytes: 1_000_000, download_bytes: 4_000_000, local_bytes: 0, packet_count: 0, connection_count: 321, top_protocol: 'tcp', excluded_ips: ['192.168.1.199', '2001:db8::199'] };
		case '/api/traffic/bandwidth':
			return { from, to, interval: '1h', series: [] };
		case '/api/traffic/protocols':
			return { from, to, protocols: [], services: [] };
		case '/api/traffic/categories':
			return { from, to, categories: [] };
		case '/api/devices/count':
			return { from, to, count: 3 };
		case '/api/devices/registry/new-count':
			return { count: 0, since: url.searchParams.get('since') };
		case '/api/alerts/count':
			return { from, to, counts: { total: 12, high: 1, medium: 2, low: 9 } };
		case '/api/system/health':
			return { uptime: 60, timestamp: '', storage: null, smart: null, healthy: true, opensearch_reachable: true };
		case '/api/alerts/smart':
			return { from, to, device_ip: null, alerts: [group(KEY)], total: 1 };
		case '/api/alerts/smart/summary':
			return { from, to, threat_score: 0, threat_level: 'none', total_groups: 1, total_events: 7, categories: {}, top_threats: [] };
		case '/api/devices':
			return { from, to, limit: 5, devices: [] };
		case '/api/capture/health':
			return { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] };
		case '/api/capture/stats':
			return { capture_interface: 'br0', rx_bytes: 0, tx_bytes: 0, rx_packets: 10, tx_packets: 0, rx_dropped: 0, rx_missed_errors: 0, link_speed_mbps: 1000, drop_rate_pct: 0 };
		default:
			throw new Error(`unexpected request ${url.pathname}`);
	}
}

/** Every request waits until the test replies to it or fails it. */
function stubDaemon(): void {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(
			(input: string) =>
				new Promise((resolve) => {
					const url = new URL(input, 'http://x');
					calls.push({
						path: url.pathname,
						url,
						reply: (b = body(url)) => resolve({ ok: true, status: 200, json: async () => b }),
						fail: () => resolve({ ok: false, status: 503, json: async () => ({}) }),
					});
				}),
		),
	);
}

const settle = () => new Promise((r) => setTimeout(r, 0));
const sent = (batch: Call[], path: string) => batch.find((c) => c.path === path)!.url.searchParams;
/** A KPI card's link, by its label. */
const kpi = (label: string) => screen.getByText(label, { selector: '.kpi-top > span' }).closest('.kpi') as HTMLElement;
const params = (el: Element) => Object.fromEntries(new URL(el.getAttribute('href')!, 'http://x').searchParams);
/** The Alert summary card's row for a smart alert, by its shown signature. */
const row = (signature: string) => screen.getByText(signature, { selector: '.sig' }).closest('.top-cat') as HTMLElement;

async function firstLoad(): Promise<Call[]> {
	render(HomePage);
	await vi.waitFor(() => expect(calls).toHaveLength(REQUESTS));
	return calls.slice();
}

/** A Refresh: its requests, once they have all gone out. */
async function refresh(): Promise<{ batch: Call[]; done: Promise<unknown> }> {
	const before = calls.length;
	const done = refreshPage();
	await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(before + REQUESTS - 1));
	await settle();
	return { batch: calls.slice(before), done };
}

describe('Home — drill-down links carry the window on screen (NET-160 slice 2b-1)', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		_configure({ now: () => Date.now() });
		overrides = {};
		stubDaemon();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		_configure({ now: Date.now });
	});

	it("a smart alert's row opens its exact list over the response's own window, even while a refresh is out", async () => {
		const first = await firstLoad();
		first.forEach((c) => c.reply());
		await settle();
		const asked = sent(first, '/api/alerts/smart');
		const link = row('A friendlier shown name');
		expect(link.tagName).toBe('A');
		// OLD CODE: …toEqual({ signature, src, dst, from, to, range: '24h' }) (section D: the link carries the ×N)
		expect(params(link)).toEqual({
			signature: KEY.rule_name, src: KEY.source_ip, dst: KEY.destination_ip,
			from: asked.get('from'), to: asked.get('to'), range: '24h', count: '7',
		});

		vi.setSystemTime(new Date('2026-11-06T12:10:30Z'));
		const { batch, done } = await refresh();
		batch.filter((c) => c.path !== '/api/alerts/smart').forEach((c) => c.reply());
		await settle();
		expect(params(row('A friendlier shown name')).from).toBe(asked.get('from'));

		batch.find((c) => c.path === '/api/alerts/smart')!.reply();
		await done;
		expect(params(row('A friendlier shown name')).from).toBe(sent(batch, '/api/alerts/smart').get('from'));
	});

	it('an activity group opens the activity list, which is the only list holding it (NET-191)', async () => {
		overrides['/api/alerts/smart'] = (from, to) => ({
			from, to, device_ip: null, total: 2,
			alerts: [{ ...group(KEY, 'Activity group'), severity: 5, activity: true }, group(KEY, 'Counted group')],
		});
		(await firstLoad()).forEach((c) => c.reply());
		await settle();
		expect(params(row('Activity group'))).toMatchObject({ signature: KEY.rule_name, activity: 'true', count: '7' });
		expect(params(row('Counted group'))).not.toHaveProperty('activity');
	});

	it('a smart alert with a missing or empty key part is a plain row, not a link', async () => {
		overrides['/api/alerts/smart'] = (from, to) => ({
			from, to, device_ip: null, total: 2,
			alerts: [group({ ...KEY, destination_ip: null }, 'No destination'), group({ ...KEY, rule_name: '' }, 'Empty rule')],
		});
		(await firstLoad()).forEach((c) => c.reply());
		await settle();
		for (const name of ['No destination', 'Empty rule']) {
			expect(row(name).tagName).toBe('DIV');
			expect(row(name)).not.toHaveAttribute('href');
			expect(row(name)).toHaveAttribute('title', "This group has no signature, source or destination recorded, so it can't be listed exactly");
		}
		expect(screen.getByRole('link', { name: 'View threat intelligence' })).toHaveAttribute('href', '/threats');
	});

	it("the Alerts card opens the count response's own window, with Home's range", async () => {
		(await firstLoad()).forEach((c) => c.reply());
		await settle();
		await fireEvent.click(screen.getByRole('button', { name: '6h' }));
		await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(REQUESTS * 2));
		const sixHours = calls.slice(REQUESTS);
		sixHours.forEach((c) => c.reply());
		await settle();
		const count = sent(sixHours, '/api/alerts/count');
		expect(kpi('Alerts')).toHaveTextContent('12');
		// OLD CODE: expect(params(kpi('Alerts'))).toEqual({ from: count.get('from'), to: count.get('to'), range: '6h' }); (section D)
		expect(params(kpi('Alerts'))).toEqual({ from: count.get('from'), to: count.get('to'), range: '6h', count: '12' });
	});

	it('Connections and Bandwidth open the conn records the summary counted, leaving out its excluded sources', async () => {
		const first = await firstLoad();
		first.forEach((c) => c.reply());
		await settle();
		const asked = sent(first, '/api/traffic/summary');
		const expected = { type: 'zeek.conn', exclude_src: '192.168.1.199,2001:db8::199', from: asked.get('from'), to: asked.get('to'), range: '24h' };
		// OLD CODE: expect(params(kpi('Connections'))).toEqual(expected); (section D: Connections carries its figure; Bandwidth, a byte sum, does not)
		expect(params(kpi('Connections'))).toEqual({ ...expected, count: '321' });
		expect(params(kpi('Bandwidth'))).toEqual(expected);
		expect(kpi('Bandwidth')).toHaveAttribute('title', 'Opens the connections this total is summed from');
	});

	it('with nothing excluded, the traffic links carry no exclude_src', async () => {
		overrides['/api/traffic/summary'] = (from, to) => ({
			from, to, total_bytes: 0, orig_bytes: 0, resp_bytes: 0, upload_bytes: 0, download_bytes: 0, local_bytes: 0, packet_count: 0, connection_count: 5, top_protocol: 'tcp', excluded_ips: [],
		});
		(await firstLoad()).forEach((c) => c.reply());
		await settle();
		expect(params(kpi('Connections'))).not.toHaveProperty('exclude_src');
		expect(params(kpi('Connections')).type).toBe('zeek.conn');
	});

	it("after a failed refresh, the cards keep their figures and their links keep those figures' window", async () => {
		const first = await firstLoad();
		first.forEach((c) => c.reply());
		await settle();
		const summary = sent(first, '/api/traffic/summary');
		const count = sent(first, '/api/alerts/count');

		vi.setSystemTime(new Date('2026-11-06T12:10:30Z'));
		const { batch, done } = await refresh();
		batch.forEach((c) => (c.path === '/api/traffic/summary' || c.path === '/api/alerts/count' ? c.fail() : c.reply()));
		await done;
		await settle();
		expect(sent(batch, '/api/traffic/summary').get('from')).not.toBe(summary.get('from'));

		expect(kpi('Connections')).toHaveTextContent('321');
		// OLD CODE: …toMatchObject({ from, to, exclude_src }) and Alerts …toEqual({ from, to, range: '24h' }) (section D: the kept figures too)
		expect(params(kpi('Connections'))).toMatchObject({ from: summary.get('from'), to: summary.get('to'), exclude_src: '192.168.1.199,2001:db8::199', count: '321' });
		expect(kpi('Alerts')).toHaveTextContent('12');
		expect(params(kpi('Alerts'))).toEqual({ from: count.get('from'), to: count.get('to'), range: '24h', count: '12' });
	});

	// NET-160 slice 2b-3: the Devices card opened /iot, which counts something else
	it("the Devices card opens All devices over the count reply's own window, and by range alone before it", async () => {
		const REPLY = { from: '2026-11-05T12:00:00.123Z', to: '2026-11-06T12:00:00.123Z' };
		overrides['/api/devices/count'] = () => ({ ...REPLY, count: 3 });
		const first = await firstLoad();
		const href = () => new URL(kpi('Devices').getAttribute('href')!, 'http://x');
		expect(href().pathname).toBe('/devices');
		expect(params(kpi('Devices'))).toEqual({ view: 'all', range: '24h' });

		first.forEach((c) => c.reply());
		await settle();
		expect(kpi('Devices')).toHaveTextContent('3');
		expect(href().pathname).toBe('/devices');
		// OLD CODE: expect(params(kpi('Devices'))).toEqual({ view: 'all', ...REPLY, range: '24h' }); (section D: the figure too)
		expect(params(kpi('Devices'))).toEqual({ view: 'all', ...REPLY, range: '24h', count: '3' });
	});

	it("after 24h loads, choosing 7d links the Devices card by range alone while 7d loads and after its count fails", async () => {
		(await firstLoad()).forEach((c) => c.reply());
		await settle();
		expect(params(kpi('Devices'))).toHaveProperty('from');

		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(REQUESTS * 2));
		expect(params(kpi('Devices'))).toEqual({ view: 'all', range: '7d' });

		calls.slice(REQUESTS).forEach((c) => (c.path === '/api/devices/count' ? c.fail() : c.reply()));
		await settle();
		expect(kpi('Devices')).toHaveTextContent('—');
		expect(params(kpi('Devices'))).toEqual({ view: 'all', range: '7d' });
	});

	it('a card with no number links by range alone', async () => {
		const first = await firstLoad();
		first.forEach((c) => (c.path === '/api/traffic/summary' || c.path === '/api/alerts/count' ? c.fail() : c.reply()));
		await settle();
		expect(kpi('Connections')).toHaveTextContent('—');
		expect(kpi('Connections')).toHaveAttribute('href', '/logs?range=24h');
		expect(kpi('Bandwidth')).toHaveAttribute('href', '/logs?range=24h');
		expect(kpi('Bandwidth')).not.toHaveAttribute('title');
		expect(kpi('Alerts')).toHaveAttribute('href', '/alerts?range=24h');
	});
});
