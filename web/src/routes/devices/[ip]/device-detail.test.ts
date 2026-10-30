import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getSmartAlerts, suppressAlert } from '$api/alerts';
import Page from './+page.svelte';

const { IP } = vi.hoisted(() => ({ IP: '192.168.1.10' }));

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL(`http://localhost/devices/${IP}`), params: { ip: IP } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/devices', () => ({
	getDeviceDetail: vi.fn(async () => ({
		device: {
			ip: IP,
			hostname: 'laptop',
			connection_count: 3,
			alert_count: 1,
			first_seen: '2026-10-29T00:00:00Z',
			last_seen: '2026-10-29T01:00:00Z',
			top_destinations: [],
			dns_queries: [],
			bandwidth_series: [],
			protocols: [],
		},
	})),
	getDeviceCategories: vi.fn(async () => ({ categories: [] })),
	getDevicePorts: vi.fn(async () => ({ ports: [] })),
	getDeviceRiskScore: vi.fn(async () => ({ score: 0, level: 'low', factors: [] })),
	getDeviceConnections: vi.fn(async () => ({ connections: [], page: 1, total_pages: 0, total: 0 })),
}));
vi.mock('$api/alerts', () => ({
	getSmartAlerts: vi.fn(),
	suppressAlert: vi.fn(),
}));

const ALERT = {
	signature_id: 2010935,
	signature: 'ET SCAN Suspicious inbound to MSSQL port 1433',
	severity: 2,
	severity_label: 'High',
	category_label: 'Scan',
	count: 4,
	trend: 'stable',
	source_ip: IP,
	destination_ip: '10.0.0.5',
	destination_port: 1433,
	assessment: 'Someone probed a database port.',
};

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

describe('Device detail — suppress smart alert', () => {
	beforeEach(() => {
		vi.mocked(getSmartAlerts).mockResolvedValue({ alerts: [ALERT], total: 1 } as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	async function clickSuppress() {
		render(Page);
		await flush();
		await fireEvent.click(await screen.findByRole('button', { name: 'Suppress' }));
		await flush();
	}

	it('keeps the alert and shows an error when the suppress fails', async () => {
		vi.mocked(suppressAlert).mockRejectedValue(new Error('HTTP 500'));
		await clickSuppress();

		expect(suppressAlert).toHaveBeenCalledWith(ALERT.signature_id, IP);
		expect(screen.getByText(ALERT.signature)).toBeInTheDocument();
		expect(screen.getByText('Suppress failed. Try again.')).toBeInTheDocument();
	});

	it('removes the alert once the daemon confirms the suppress', async () => {
		vi.mocked(suppressAlert).mockResolvedValue({ status: 'ok' } as never);
		await clickSuppress();

		expect(screen.queryByText(ALERT.signature)).not.toBeInTheDocument();
		expect(screen.queryByText('Suppress failed. Try again.')).not.toBeInTheDocument();
	});
});
