import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import * as devices from '$api/devices';
import Page from './+page.svelte';
import { resetNavigation, traverse } from '../../../tests/app-navigation.svelte';

// NET-357: the device page reads its range from the URL, and Back to a view clears what another
// view left on screen, even when that view's device reply had failed; the connections total waits
// for its own window's reply.

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));

vi.mock('$app/state', () => import('../../../tests/app-navigation.svelte'));
vi.mock('$app/navigation', () => import('../../../tests/app-navigation.svelte'));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(),
	getDeviceCategories: vi.fn(async () => ({ categories: [] })),
	getDevicePorts: vi.fn(),
	getDeviceRiskScore: vi.fn(async () => ({ score: 12, level: 'low', factors: [] })),
	getDeviceConnections: vi.fn(),
}));
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getSystemHealth: vi.fn(async () => ({
		uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
		pipeline: { state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' },
	})),
}));
vi.mock('$api/alerts', () => ({ getSmartAlerts: vi.fn(async () => ({ alerts: [], total: 0 })), suppressAlert: vi.fn() }));

/** A: a 1 h Custom window */
const F = '2026-11-13T10:00:00.000Z';
const T = '2026-11-13T10:59:59.999Z';
type Span = { from?: string; to?: string };
const hoursOf = (q?: Span) => Math.round((Date.parse(q!.to!) - Date.parse(q!.from!)) / 3_600_000);
/** The requests that fail: 'detail', 'ports' or 'connections' */
let failing = new Set<string>();
const answer = (name: string, body: unknown) => (failing.has(name) ? Promise.reject(new Error('HTTP 503')) : Promise.resolve(body));

const detailCalls = () => vi.mocked(devices.getDeviceDetail).mock.calls.map(([, q]) => q as Span);
const pill = (name: string) => screen.getByRole('button', { name });
async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

beforeEach(() => {
	failing = new Set();
	vi.clearAllMocks();
	vi.mocked(devices.getDeviceDetail).mockImplementation((() =>
		answer('detail', {
			device: {
				ip: IP, hostname: 'laptop', connection_count: 3, alert_count: 0, total_bytes: 2048,
				first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
				top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
			},
		})) as never);
	// a 6 h window used port 8443, any other 443
	vi.mocked(devices.getDevicePorts).mockImplementation(((_ip: string, q: Span) =>
		answer('ports', { ports: [{ port: hoursOf(q) === 6 ? 8443 : 443, service: 'https', connections: 3, suspicious: false }] })) as never);
	// 11 connections an hour
	vi.mocked(devices.getDeviceConnections).mockImplementation(((_ip: string, q: Span) =>
		answer('connections', { connections: [], page: 1, total_pages: 0, total: hoursOf(q) * 11 })) as never);
});
afterEach(() => vi.clearAllMocks());

describe('Device detail — the range lives in the URL (NET-357)', () => {
	it('opens on the URL range', async () => {
		resetNavigation(`http://localhost/devices/${IP}?range=6h`, { ip: IP });
		render(Page);
		await vi.waitFor(() => expect(detailCalls()).toHaveLength(1));
		expect(hoursOf(detailCalls()[0])).toBe(6);
		expect(pill('6h')).toHaveAttribute('aria-pressed', 'true');
	});

	it("Back to a window after a range whose device failed leaves none of that range's ports", async () => {
		resetNavigation(`http://localhost/devices/${IP}?from=${F}&to=${T}`, { ip: IP });
		render(Page);
		expect(await screen.findByText('443')).toBeInTheDocument();

		failing = new Set(['detail']);
		await fireEvent.click(pill('6h'));
		await vi.waitFor(() => expect(vi.mocked(devices.getDevicePorts).mock.calls.some(([, q]) => hoursOf(q) === 6)).toBe(true));
		await flush();

		failing = new Set(['ports']);
		traverse(-1);
		expect(await screen.findByText("Couldn't load ports: the request failed.")).toBeInTheDocument();
		expect(detailCalls().at(-1)!.from).toBe(F);
		expect(screen.queryByText('8443')).not.toBeInTheDocument();
	});

	it("Back to a window shows no total until that window's connections answer", async () => {
		resetNavigation(`http://localhost/devices/${IP}?from=${F}&to=${T}`, { ip: IP });
		render(Page);
		expect(await screen.findByText('11 total')).toBeInTheDocument();
		await fireEvent.click(pill('6h'));
		expect(await screen.findByText('66 total')).toBeInTheDocument();

		let release: () => void = () => {};
		vi.mocked(devices.getDeviceConnections).mockImplementationOnce(((_ip: string, q: Span) =>
			new Promise((resolve) => (release = () => resolve({ connections: [], page: 1, total_pages: 0, total: hoursOf(q) * 11 })))) as never);
		traverse(-1);
		await vi.waitFor(() => expect(detailCalls().at(-1)!.from).toBe(F));
		await flush();
		expect(screen.getByText('Loading connections')).toBeInTheDocument();
		expect(screen.queryByText(/ total$/)).not.toBeInTheDocument();

		release();
		expect(await screen.findByText('11 total')).toBeInTheDocument();
	});
});
