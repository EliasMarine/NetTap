import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getConnections } from '$api/traffic';
import { getLiveDashboard } from '$api/live';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/connections') }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/traffic', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/traffic')>()),
	getConnections: vi.fn(),
	getConnectionStats: vi.fn().mockRejectedValue(new Error('not under test')),
	getConnectionSankey: vi.fn().mockRejectedValue(new Error('not under test')),
	getConnectionTimeline: vi.fn().mockRejectedValue(new Error('not under test')),
}));
vi.mock('$api/live', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/live')>()),
	getLiveConnections: vi.fn().mockResolvedValue({ connections: [{}], count: 1, filters: {} }),
	getLiveDashboard: vi.fn(),
}));

describe('Connections v3 page', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Rendered page tests
// ---------------------------------------------------------------------------

function connectionsPage(page: number, totalPages = 5) {
	return { from: '', to: '', page, size: 50, total: totalPages * 50, total_pages: totalPages, connections: [] };
}

function dashboard(activeDevices: number) {
	return {
		connections: [],
		count: 1,
		stats: { connections_per_second: 3.2, bandwidth_bytes_per_second: 1000, active_devices: activeDevices, top_country: 'US' },
		protocols: {},
		top_talkers: [],
		geo_arcs: [],
	};
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

// jsdom has no ResizeObserver; the timeline/Sankey charts need one to mount
vi.stubGlobal(
	'ResizeObserver',
	class {
		observe() {}
		unobserve() {}
		disconnect() {}
	},
);

describe('Connections — Active Devices card', () => {
	beforeEach(() => {
		vi.mocked(getConnections).mockImplementation(async (opts = {}) => connectionsPage(opts.page ?? 1));
		vi.mocked(getLiveDashboard).mockResolvedValue(dashboard(17));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it('shows active devices from the live dashboard stats, not a 1-item list length', async () => {
		render(Page);
		await flush();

		const card = screen.getByText('Active Devices').closest('.stat-card');
		expect(card).toHaveTextContent('17');
		expect(getLiveDashboard).toHaveBeenCalledWith({ limit: 1 });
	});
});
