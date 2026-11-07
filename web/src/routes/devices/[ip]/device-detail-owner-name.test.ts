import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import * as devices from '$api/devices';
import Page from './+page.svelte';

// NET-200: the owner's name heads the IP device page, outranks the UniFi name (and its chip),
// and the Hostname row keeps the name the network gives the device.

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/${IP}`), params: { ip: IP } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(),
	getDeviceCategories: vi.fn(),
	getDevicePorts: vi.fn(),
	getDeviceRiskScore: vi.fn(),
	getDeviceConnections: vi.fn(),
}));
vi.mock('$api/alerts', () => ({
	getSmartAlerts: vi.fn(async () => ({ alerts: [], total: 0 })),
	suppressAlert: vi.fn(),
}));

const detail = (over: Record<string, unknown>) => ({
	device: {
		ip: IP, mac: 'D0:21:F9:5E:35:32', hostname: 'laptop', connection_count: 3, alert_count: 0, total_bytes: 2048,
		first_seen: '2026-10-29T00:00:00Z', last_seen: '2026-10-29T01:00:00Z',
		top_destinations: [], dns_queries: [], bandwidth_series: [], protocols: [],
		...over,
	},
});

describe('Device detail — the owner name', () => {
	beforeEach(() => {
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 12, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [], page: 1, total_pages: 0, total: 0 } as never);
	});
	afterEach(() => vi.clearAllMocks());

	it("heads the page with the owner's name, hides the UniFi chip and keeps the real hostname", async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(
			detail({ hostname: 'Work laptop', custom_name: 'Work laptop', discovered_name: 'eli-mbp.local', unifi_name: 'MacBook' }) as never,
		);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Work laptop'));
		expect(screen.queryByText('UniFi')).not.toBeInTheDocument();
		expect(screen.getByText('Hostname').nextElementSibling).toHaveTextContent('eli-mbp.local');
	});

	it('still shows the UniFi name and chip when the owner has not named it', async () => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue(detail({ unifi_name: 'MacBook' }) as never);
		render(Page);
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('MacBook'));
		expect(screen.getByText('UniFi')).toBeInTheDocument();
		expect(screen.getByText('Hostname').nextElementSibling).toHaveTextContent('laptop');
	});
});
