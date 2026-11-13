import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { goto } from '$app/navigation';
import { getDeviceCategories, getDeviceConnections, getDeviceDetail, getDevicePorts, getDeviceRiskScore } from '$api/devices';
import { getSmartAlerts } from '$api/alerts';
import { DEVICE_IPV6_NOTE } from '$lib/utils/narrow-page';
import Page from './+page.svelte';

// NET-249 slice 2 (T12, plan §1a): the device's bandwidth chart asks for the owner's buckets
// through the new `interval`, a pick narrows this page to the picked window (Custom) with the
// bytes picked, and the page says when its own chart's total differs, with the IPv6 note.

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));
const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const at = (query: string) => ({ url: new URL(`http://localhost/devices/${IP}${query}`), params: { ip: IP } });
	const page = writable(at(''));
	nav.set = (query) => page.set(at(query));
	return { page };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));
vi.mock('$lib/stores/captureMode', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/stores/captureMode')>()),
	initCaptureMode: vi.fn(async () => {}),
}));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(),
	getDeviceCategories: vi.fn(async () => ({ categories: [] })),
	getDevicePorts: vi.fn(async () => ({ ports: [] })),
	getDeviceRiskScore: vi.fn(async () => ({ score: 0, level: 'low', factors: [] })),
	getDeviceConnections: vi.fn(async () => ({ connections: [], page: 1, total_pages: 0, total: 0 })),
}));
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getSystemHealth: vi.fn(async () => ({ uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true })),
}));
vi.mock('$api/alerts', () => ({ getSmartAlerts: vi.fn(async () => ({ alerts: [], total: 0 })), suppressAlert: vi.fn() }));
vi.mock('$api/live-bandwidth', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live-bandwidth')>()),
	getLiveBandwidth: vi.fn(() => new Promise<never>(() => {})),
}));

const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:04:59.999Z';

/** The device over the request's own window, one minute slot per byte figure */
function detail(bytes: number[], opts: { from?: string; to?: string; interval?: string } = {}) {
	return async (_ip: string, q: { from?: string; to?: string; interval?: string } = {}) => ({
		device: {
			ip: IP, hostname: 'laptop', connection_count: 3, alert_count: 0, first_seen: F, last_seen: F,
			top_destinations: [], dns_queries: [], protocols: [],
			bandwidth_series: bytes.map((b, i) => ({ timestamp: new Date(Date.parse(F) + i * 60_000).toISOString(), bytes: b, download_bytes: b, upload_bytes: 0 })),
		},
		from: opts.from ?? q.from,
		to: opts.to ?? q.to,
		bandwidth_interval: 'interval' in opts ? opts.interval : '1m',
	});
}

const detailCalls = () => vi.mocked(getDeviceDetail).mock.calls.map(([, q]) => q!);
const chart = () => screen.getByRole('group', { name: /^Busiest at/ });
const loaded = () => vi.waitFor(() => expect(chart()).toBeInTheDocument());
const target = (n = 0) => new URL(String(vi.mocked(goto).mock.calls[n][0]), 'http://localhost');

beforeEach(() => {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.clearAllMocks();
	vi.mocked(getDeviceDetail).mockImplementation(detail([1000, 3000]) as never);
	vi.mocked(goto).mockImplementation(async () => {});
	nav.set('');
});
afterEach(() => vi.unstubAllGlobals());

describe('Device detail — the bandwidth chart drills into a window (NET-249)', () => {
	it("asks for each range's bucket from the owner's table", async () => {
		// the daemon echoes the bucket asked for
		vi.mocked(getDeviceDetail).mockImplementation(((ip: string, q: { interval?: string } = {}) => detail([1000, 3000], { interval: q.interval })(ip, q)) as never);
		render(Page);
		await loaded();
		expect(detailCalls().at(-1)!.interval).toBe('5m');
		expect(screen.getByText(/^Bytes per 5 minutes · last 24 hours/)).toBeInTheDocument();
		for (const [range, bucket, words] of [['1h', '1m', 'minute'], ['6h', '5m', '5 minutes'], ['7d', '1h', 'hour'], ['30d', '3h', '3 hours']]) {
			await fireEvent.click(screen.getByRole('button', { name: range }));
			await vi.waitFor(() => expect(detailCalls().at(-1)!.interval, range).toBe(bucket));
			expect(await screen.findByText(new RegExp(`^Bytes per ${words} · `))).toBeInTheDocument();
		}
	});

	it('a pick opens this page over the picked slots, with the bytes they drew', async () => {
		vi.mocked(getDeviceDetail).mockImplementation(detail([1000, 3000], { from: '2026-11-13T10:00:15.000Z', to: '2026-11-13T10:01:30.000Z' }) as never);
		render(Page);
		await loaded();
		expect(screen.getByText('Click a point or drag across the chart to see this page for that time.')).toBeInTheDocument();
		await fireEvent.keyDown(chart(), { key: 'Home' });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(target(0).pathname).toBe(`/devices/${IP}`);
		expect(Object.fromEntries(target(0).searchParams)).toEqual({ from: '2026-11-13T10:00:15.000Z', to: '2026-11-13T10:00:59.999Z', range: '24h', bytes: '1000' });
		await fireEvent.keyDown(chart(), { key: 'End', shiftKey: true });
		await fireEvent.keyDown(chart(), { key: 'Enter' });
		expect(Object.fromEntries(target(1).searchParams)).toEqual({ from: '2026-11-13T10:00:15.000Z', to: '2026-11-13T10:01:30.000Z', range: '24h', bytes: '4000' });
	});

	it('names the bucket the reply says it used', async () => {
		vi.mocked(getDeviceDetail).mockImplementation(detail([1000, 3000], { interval: '1h' }) as never);
		render(Page);
		await loaded();
		expect(detailCalls().at(-1)!.interval).toBe('5m');
		expect(screen.getByText(/^Bytes per hour · last 24 hours/)).toBeInTheDocument();
	});

	it('a reply that names no bucket (an older daemon) stays a picture', async () => {
		vi.mocked(getDeviceDetail).mockImplementation(detail([1000], { interval: undefined }) as never);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('img', { name: /^Busiest at/ })).toBeInTheDocument());
		expect(screen.queryByText(/see this page for that time/)).not.toBeInTheDocument();
	});
});

describe('Device detail — a Custom window from the URL (NET-249 §1a)', () => {
	it("loads every card over the link's window, shown as Custom", async () => {
		nav.set(`?from=${F}&to=${T}&range=7d&bytes=4000`);
		render(Page);
		await loaded();
		const sent = (fn: unknown) => (vi.mocked(fn as typeof getDevicePorts).mock.calls.at(-1)!.at(-1) as { from: string; to: string });
		for (const [name, fn] of [['detail', getDeviceDetail], ['categories', getDeviceCategories], ['ports', getDevicePorts], ['risk', getDeviceRiskScore], ['connections', getDeviceConnections]] as const) {
			expect([sent(fn).from, sent(fn).to], name).toEqual([F, T]);
		}
		const smart = vi.mocked(getSmartAlerts).mock.calls.at(-1)![0] as { from: string; to: string };
		expect([smart.from, smart.to]).toEqual([F, T]);
		expect(detailCalls().at(-1)!.interval).toBe('1m');
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText(/^Bytes per minute · window /)).toBeInTheDocument();
		expect(screen.getByText('Traffic').closest('.kpi')).toHaveTextContent(/Window /);
	});

	it('choosing a range clears the window', async () => {
		vi.mocked(goto).mockImplementation(async (h) => nav.set(String(h).replace(`/devices/${IP}`, '')));
		nav.set(`?from=${F}&to=${T}&bytes=4000`);
		render(Page);
		await loaded();
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		expect(String(vi.mocked(goto).mock.calls[0][0])).toBe(`/devices/${IP}`);
		await vi.waitFor(() => expect(detailCalls().at(-1)!.interval).toBe('1h'));
		const q = detailCalls().at(-1)!;
		expect((Date.parse(q.to!) - Date.parse(q.from!)) / 86_400_000).toBeCloseTo(7);
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
	});

	it('an invalid window falls back to the default range', async () => {
		nav.set(`?to=${T}&bytes=4000`);
		render(Page);
		await loaded();
		const q = detailCalls().at(-1)!;
		expect((Date.parse(q.to!) - Date.parse(q.from!)) / 3_600_000).toBeCloseTo(24);
		expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute('aria-pressed', 'true');
	});
});

describe('Device detail — the shared receiver (NET-249)', () => {
	it('says nothing when the totals agree', async () => {
		nav.set(`?from=${F}&to=${T}&bytes=4000`);
		render(Page);
		await loaded();
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		expect(screen.queryByText(new RegExp(DEVICE_IPV6_NOTE.slice(0, 40)))).not.toBeInTheDocument();
	});

	it('the parent window counted IPv6 traffic the narrow window does not: the line says so, with the note', async () => {
		// the 24-hour chart gave this device an IPv6 address (6,000 B in the slot); over the picked slot it doesn't qualify
		nav.set(`?from=${F}&to=${T}&bytes=6000`);
		render(Page);
		const line = await screen.findByText(/^You clicked 6\.0 KB\. This window now shows 4\.0 KB \(2\.0 KB less\)\./);
		expect(line).toHaveTextContent(DEVICE_IPV6_NOTE);
	});

	it('says nothing when the device request failed', async () => {
		vi.mocked(getDeviceDetail).mockRejectedValue(new Error('Device detail failed: HTTP 502'));
		nav.set(`?from=${F}&to=${T}&bytes=6000`);
		render(Page);
		await screen.findByText(/Couldn't load device/);
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
	});

	it("never compares with a superseded window's reply", async () => {
		const W2 = { from: '2026-11-13T11:00:00.000Z', to: '2026-11-13T11:04:59.999Z' };
		let releaseFirst: (body: unknown) => void = () => {};
		const second = detail([1000, 3000]);
		vi.mocked(getDeviceDetail).mockImplementation(((ip: string, q: { from?: string } = {}) =>
			q.from === F ? new Promise((resolve) => (releaseFirst = resolve)) : second(ip, q)) as never);
		nav.set(`?from=${F}&to=${T}&bytes=4000`);
		render(Page);
		await vi.waitFor(() => expect(detailCalls()).toHaveLength(1));
		nav.set(`?from=${W2.from}&to=${W2.to}&bytes=4000`);
		await vi.waitFor(() => expect(detailCalls()).toHaveLength(2));
		await loaded();
		// the first window's reply lands last, with another total; the page compares with the second's only
		releaseFirst(await detail([99_000])(IP, { from: F, to: T }));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText(/You clicked/)).not.toBeInTheDocument();
		expect(chart()).toHaveAccessibleName(/with 3\.0 KB transferred/);
	});
});
