import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import * as devices from '$api/devices';
import Page from './+page.svelte';

// #96: one failed request blanked the device page as "Device not found"; a failed risk score read
// "0 LOW" and failed ports read "No port data."

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

const DEVICE = {
	ip: IP,
	hostname: 'laptop',
	connection_count: 3,
	alert_count: 0,
	first_seen: '2026-10-29T00:00:00Z',
	last_seen: '2026-10-29T01:00:00Z',
	top_destinations: [],
	dns_queries: [],
	bandwidth_series: [],
	protocols: [],
};
const failed = (what: string) => new Error(`${what} failed: HTTP 503`);

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

describe('Device detail — failed requests', () => {
	beforeEach(() => {
		vi.mocked(devices.getDeviceDetail).mockResolvedValue({ device: DEVICE } as never);
		vi.mocked(devices.getDeviceCategories).mockResolvedValue({ categories: [] } as never);
		vi.mocked(devices.getDevicePorts).mockResolvedValue({ ports: [] } as never);
		vi.mocked(devices.getDeviceRiskScore).mockResolvedValue({ score: 12, level: 'low', factors: [] } as never);
		vi.mocked(devices.getDeviceConnections).mockResolvedValue({ connections: [], page: 1, total_pages: 0, total: 0 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it('says the device failed to load instead of "Device not found"', async () => {
		vi.mocked(devices.getDeviceDetail).mockRejectedValue(failed('Device detail'));
		render(Page);
		await flush();

		expect(screen.getByText(`Couldn't load device ${IP}: the request failed.`)).toBeInTheDocument();
		expect(screen.queryByText(/Device not found/)).not.toBeInTheDocument();
	});

	it('says the risk score failed while the rest of the page renders', async () => {
		vi.mocked(devices.getDeviceRiskScore).mockRejectedValue(failed('Device risk score'));
		render(Page);
		await flush();

		expect(screen.getAllByText('laptop').length).toBeGreaterThan(0);
		expect(screen.getByText("Couldn't load the risk score: the request failed.")).toBeInTheDocument();
		// OLD CODE START — 2026-11-03 UI redesign: the gauge's UNKNOWN badge became the card's error state
		// expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
		// expect(screen.queryByText('LOW')).not.toBeInTheDocument();
		// OLD CODE END
		expect(screen.queryByRole('img', { name: /^Risk score/ })).not.toBeInTheDocument();
		expect(screen.queryByText('Low')).not.toBeInTheDocument();
	});

	it('says ports and categories failed instead of "No port data" / "No category data"', async () => {
		vi.mocked(devices.getDevicePorts).mockRejectedValue(failed('Device ports'));
		vi.mocked(devices.getDeviceCategories).mockRejectedValue(failed('Device categories'));
		render(Page);
		await flush();

		expect(screen.getByText("Couldn't load ports: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No port data.')).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load traffic categories: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No category data available.')).not.toBeInTheDocument();
	});

	it('still says "No port data." and shows the score when everything loads empty', async () => {
		render(Page);
		await flush();

		expect(screen.getByText('No port data.')).toBeInTheDocument();
		// OLD CODE START — 2026-11-03 UI redesign: the LOW badge and "12 / 100" became a severity pill and the Ring
		// expect(screen.getByText('LOW')).toBeInTheDocument();
		// expect(screen.getByText('12 / 100')).toBeInTheDocument();
		// OLD CODE END
		expect(screen.getByText('Low')).toBeInTheDocument();
		expect(screen.getByRole('img', { name: 'Risk score 12 of 100, low' })).toBeInTheDocument();
	});
});
