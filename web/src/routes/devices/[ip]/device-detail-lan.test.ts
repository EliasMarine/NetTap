import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import { goto } from '$app/navigation';
import * as devices from '$api/devices';
import { lanPolicy } from '$lib/stores/lan';
import type { LanPolicy } from '$lib/api/network';
import { LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import Page from './+page.svelte';

// NET-209: the daemon has no device page for an address off the LAN (404), so the page swaps
// its URL for the address page once the LAN policy says so, and waits while it is unknown.

const view = vi.hoisted(() => ({ ip: '' }));

vi.mock('$app/stores', async () => {
	const { readable } = await import('svelte/store');
	return {
		page: {
			subscribe: (run: (v: unknown) => void) =>
				readable({ url: new URL(`http://localhost/devices/${view.ip}`), params: { ip: view.ip } }).subscribe(run),
		},
	};
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
// the policy is set by each test; the rest of the store module is real
vi.mock('$lib/stores/lan', async (importOriginal) => {
	const { writable } = await import('svelte/store');
	return { ...(await importOriginal<typeof import('$lib/stores/lan')>()), lanPolicy: writable(null) };
});
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(),
	getDeviceCategories: vi.fn(),
	getDevicePorts: vi.fn(),
	getDeviceRiskScore: vi.fn(),
	getDeviceConnections: vi.fn(),
}));
// NET-228: the Smart alerts empty state reads the pipeline's state; fresh unless a test says not
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getSystemHealth: vi.fn(async () => ({
		uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
		pipeline: { state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' },
	})),
}));
vi.mock('$api/alerts', () => ({
	getSmartAlerts: vi.fn(async () => ({ alerts: [], total: 0 })),
	suppressAlert: vi.fn(),
}));

const policy = lanPolicy as Writable<LanPolicy | null>;

async function open(ip: string) {
	view.ip = ip;
	vi.mocked(devices.getDeviceDetail).mockResolvedValue({
		device: {
			ip, hostname: 'laptop', custom_name: 'laptop', connection_count: 3, alert_count: 0, total_bytes: 2048,
			first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
			top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
		},
	} as never);
	render(Page);
	await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('laptop'));
}

describe('Device detail — an address off the LAN', () => {
	beforeEach(() => {
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 0, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [], page: 1, total_pages: 0, total: 0 } as never);
	});
	afterEach(() => {
		policy.set(null);
		vi.clearAllMocks();
	});

	it('replaces the URL with the address page when the policy loads and says it is not on the LAN', async () => {
		await open('91.92.40.12');
		policy.set(LAN_POLICY);
		await vi.waitFor(() => expect(goto).toHaveBeenCalledWith('/address/91.92.40.12', { replaceState: true }));
	});

	it('stays on the device page for a LAN address', async () => {
		await open('192.168.1.10');
		policy.set(LAN_POLICY);
		await tick();
		expect(goto).not.toHaveBeenCalled();
	});

	it('stays while the policy is unknown', async () => {
		await open('91.92.40.12');
		await tick();
		expect(goto).not.toHaveBeenCalled();
	});
});

// NET-265: in this file for its device page set-up; the card has its own tests
describe('Device detail — compare periods', () => {
	beforeEach(() => {
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 0, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [], page: 1, total_pages: 0, total: 0 } as never);
	});
	afterEach(() => vi.clearAllMocks());

	it('Compare periods opens the compare card and closes it again', async () => {
		await open('192.168.1.10');
		const toggle = screen.getByRole('button', { name: 'Compare periods' });
		expect(screen.queryByRole('heading', { name: 'Compare periods' })).toBeNull();
		await fireEvent.click(toggle);
		expect(toggle).toHaveAttribute('aria-expanded', 'true');
		expect(screen.getByRole('heading', { name: 'Compare periods' })).toBeTruthy();
		await fireEvent.click(toggle);
		expect(screen.queryByRole('heading', { name: 'Compare periods' })).toBeNull();
	});
});
