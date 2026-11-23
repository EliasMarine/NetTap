import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import HomePage from './+page.svelte';
import { goto } from '$app/navigation';
import { _configure } from '$lib/stores/alertSnapshot';
import { historyState, resetNavigation, traverse } from '../tests/app-navigation.svelte';

// NET-357: Home's range lives in the URL (?range=), so Back, Forward and a reload keep it. A pill
// replaces the history entry it is on, and each Traffic categories bar opens the window it was counted over.

vi.mock('$app/state', () => import('../tests/app-navigation.svelte'));
vi.mock('$app/navigation', () => import('../tests/app-navigation.svelte'));

const REQUESTS = 15;
const HOUR = 3_600_000;
const CATEGORIES_WINDOW = { from: '2026-11-06T11:00:00.123Z', to: '2026-11-06T12:00:00.456Z' };

interface Call {
	path: string;
	url: URL;
	reply: () => void;
}
let calls: Call[] = [];

/** Each reply over the request's own window; the summary counts 111 connections per hour of window. */
function body(url: URL): unknown {
	const from = url.searchParams.get('from') ?? '';
	const to = url.searchParams.get('to') ?? '';
	switch (url.pathname) {
		case '/api/traffic/summary':
			return { from, to, total_bytes: 1, orig_bytes: 0, resp_bytes: 0, upload_bytes: 0, download_bytes: 0, local_bytes: 0, packet_count: 0, connection_count: Math.round((Date.parse(to) - Date.parse(from)) / HOUR) * 111, top_protocol: 'tcp', excluded_ips: [] };
		case '/api/traffic/bandwidth':
			return { from, to, interval: '1h', series: [] };
		case '/api/traffic/protocols':
			return { from, to, protocols: [], services: [] };
		case '/api/traffic/categories':
			return { ...CATEGORIES_WINDOW, categories: [{ name: 'streaming', label: 'Streaming', total_bytes: 5000, connection_count: 2, top_services: [] }] };
		case '/api/devices/count':
			return { from, to, count: 3 };
		case '/api/devices/registry/new-count':
			return { count: 0, since: url.searchParams.get('since') };
		case '/api/alerts/timeline':
			return { from, to, interval: '1h', buckets: [] };
		case '/api/alerts/count':
			return { from, to, counts: { total: 0, high: 0, medium: 0, low: 0 } };
		case '/api/system/health':
			return { uptime: 60, timestamp: '', storage: null, smart: null, healthy: true, opensearch_reachable: true };
		case '/api/alerts/smart':
			return { from, to, device_ip: null, alerts: [], total: 0 };
		case '/api/alerts/smart/summary':
			return { from, to, threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [] };
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

/** Every request waits until the test replies to it. */
function stubDaemon(): void {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(
			(input: string) =>
				new Promise((resolve) => {
					const url = new URL(input, 'http://x');
					calls.push({ path: url.pathname, url, reply: () => resolve({ ok: true, status: 200, json: async () => body(url) }) });
				}),
		),
	);
}

const settle = () => new Promise((r) => setTimeout(r, 0));
/** The next load's requests, once they have all gone out. */
async function nextLoad(before: number): Promise<Call[]> {
	await vi.waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(before + REQUESTS));
	return calls.slice(before);
}
const hoursOf = (batch: Call[]) => {
	const q = batch.find((c) => c.path === '/api/traffic/summary')!.url.searchParams;
	return (Date.parse(q.get('to')!) - Date.parse(q.get('from')!)) / HOUR;
};
const kpi = (label: string) => screen.getByText(label, { selector: '.kpi-top > span' }).closest('.kpi') as HTMLElement;
const pill = (name: string) => screen.getByRole('button', { name });

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(new Date('2026-11-06T12:00:30Z'));
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	_configure({ now: () => Date.now() });
	stubDaemon();
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	_configure({ now: Date.now });
});

describe('Home — the range lives in the URL (NET-357)', () => {
	it('opens on the URL range', async () => {
		resetNavigation('http://localhost/?range=1h');
		render(HomePage);
		expect(hoursOf(await nextLoad(0))).toBe(1);
		expect(pill('1h')).toHaveAttribute('aria-pressed', 'true');
	});

	it('an unknown range falls back to the default 24h', async () => {
		resetNavigation('http://localhost/?range=x');
		render(HomePage);
		expect(hoursOf(await nextLoad(0))).toBe(24);
		expect(pill('24h')).toHaveAttribute('aria-pressed', 'true');
	});

	it('a pill replaces the entry it is on, and loads that range', async () => {
		resetNavigation('http://localhost/?range=1h');
		render(HomePage);
		(await nextLoad(0)).forEach((c) => c.reply());
		await settle();

		await fireEvent.click(pill('6h'));
		expect(historyState()).toEqual({ entries: ['/?range=6h'], index: 0 });
		expect(hoursOf(await nextLoad(REQUESTS))).toBe(6);
		expect(pill('6h')).toHaveAttribute('aria-pressed', 'true');
	});

	it("Back to an earlier 1h entry reloads at 1h, and 6h's figures don't stand in meanwhile", async () => {
		// an earlier Home entry at 1h behind the one the page opens on
		resetNavigation('http://localhost/?range=1h');
		await goto('/?range=1h');
		render(HomePage);
		(await nextLoad(0)).forEach((c) => c.reply());
		await settle();
		await fireEvent.click(pill('6h'));
		(await nextLoad(REQUESTS)).forEach((c) => c.reply());
		await settle();
		expect(kpi('Connections')).toHaveTextContent('666');
		expect(historyState()).toEqual({ entries: ['/?range=1h', '/?range=6h'], index: 1 });

		traverse(-1);
		const back = await nextLoad(REQUESTS * 2);
		expect(hoursOf(back)).toBe(1);
		expect(pill('1h')).toHaveAttribute('aria-pressed', 'true');
		expect(kpi('Connections')).not.toHaveTextContent('666');

		back.forEach((c) => c.reply());
		await settle();
		expect(kpi('Connections')).toHaveTextContent('111');
	});

	it("a Traffic categories bar opens the category over the reply's own window, with Home's range", async () => {
		resetNavigation('http://localhost/?range=1h');
		render(HomePage);
		(await nextLoad(0)).forEach((c) => c.reply());
		await settle();
		const href = screen.getByRole('link', { name: 'Streaming' }).getAttribute('href')!;
		expect(href.split('?')[0]).toBe('/traffic/streaming');
		expect(Object.fromEntries(new URL(href, 'http://x').searchParams)).toEqual({ ...CATEGORIES_WINDOW, range: '1h' });
	});
});
