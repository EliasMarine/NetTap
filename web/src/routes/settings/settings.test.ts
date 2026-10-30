import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { previewCleanup, executeCleanup } from '$lib/api/storage';
import Page from './+page.svelte';

vi.mock('$lib/api/storage', () => ({
	previewCleanup: vi.fn(),
	executeCleanup: vi.fn(),
}));

describe('Settings', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Rendered page tests
// ---------------------------------------------------------------------------

type FetchRoute = (init?: RequestInit) => { status?: number; body: unknown };

/** Stub fetch: URLs in `routes` get their body, everything else a 500. */
function stubFetch(routes: Record<string, FetchRoute> = {}) {
	const fn = vi.fn(async (url: string, init?: RequestInit) => {
		const route = routes[url.split('?')[0]];
		if (!route) return { ok: false, status: 500, json: async () => ({}) };
		const { status = 200, body } = route(init);
		return { ok: status < 400, status, json: async () => body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const PREVIEW = {
	cutoff_date: '2026-09-01T00:00:00Z',
	older_than_days: 30,
	indices: [],
	pcap_files: [],
	total_indices: 3,
	total_pcap_files: 2,
	estimated_freed_bytes: 1024,
};

describe('Settings — manual cleanup', () => {
	beforeEach(() => {
		stubFetch();
		vi.mocked(previewCleanup).mockResolvedValue(PREVIEW as never);
		vi.mocked(executeCleanup).mockResolvedValue({
			deleted_indices: 3,
			deleted_pcap_files: 2,
			freed_bytes_estimate: 1024,
			errors: [],
		} as never);
	});

	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	async function openPreview(days: string) {
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Retention' }));
		const input = screen.getByLabelText('Delete data older than (days)');
		await fireEvent.input(input, { target: { value: days } });
		await fireEvent.click(screen.getByRole('button', { name: 'Preview Cleanup' }));
		await flush();
		return input;
	}

	it('deletes with the days that were previewed', async () => {
		await openPreview('30');
		expect(previewCleanup).toHaveBeenCalledWith(30);

		await fireEvent.click(screen.getByRole('button', { name: 'Delete Data' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Confirm Delete' }));
		await flush();

		expect(executeCleanup).toHaveBeenCalledWith(30);
	});

	it('drops the preview and its delete button when the days change', async () => {
		const input = await openPreview('30');
		expect(screen.getByRole('button', { name: 'Delete Data' })).toBeInTheDocument();

		await fireEvent.input(input, { target: { value: '5' } });

		expect(screen.queryByRole('button', { name: 'Delete Data' })).not.toBeInTheDocument();
		expect(screen.queryByText('Cleanup Preview')).not.toBeInTheDocument();
		expect(executeCleanup).not.toHaveBeenCalled();
	});
});

describe('Settings — retention save', () => {
	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	async function saveWith(status: number, body: unknown) {
		stubFetch({ '/api/setup/storage': (init) => (init?.method === 'POST' ? { status, body } : { body: {} }) });
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Retention' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Save Retention Config' }));
		await flush();
	}

	it('says "Not saved" when the daemon is unreachable', async () => {
		await saveWith(502, { saved: false, error: 'Daemon unreachable: ECONNREFUSED' });

		expect(screen.getByText('Not saved: Daemon unreachable: ECONNREFUSED')).toBeInTheDocument();
		expect(screen.queryByText(/settings saved/i)).not.toBeInTheDocument();
	});

	it('says the outcome is unknown when the daemon timed out', async () => {
		await saveWith(504, { saved: false, outcome_unknown: true, error: 'The daemon did not answer in time.' });

		expect(screen.getByText(/^Outcome unknown — check again\./)).toBeInTheDocument();
		expect(screen.queryByText(/settings saved/i)).not.toBeInTheDocument();
	});
});

describe('Settings — capture status label', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('does not claim "capturing packets" while the container is stopped', async () => {
		stubFetch({
			'/api/capture/status': () => ({
				body: { enabled: true, maxFileSizeMB: 100, containerRunning: false, containerStatus: 'exited' },
			}),
		});
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Capture' }));

		expect(screen.getByText('Enabled — capture container not running')).toBeInTheDocument();
		expect(screen.queryByText('Enabled — capturing packets')).not.toBeInTheDocument();
	});
});

describe('Settings — UniFi integration', () => {
	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	function status(overrides: Record<string, unknown> = {}) {
		return {
			configured: true,
			controller_url: 'https://192.168.1.1',
			site_id: null,
			connected: true,
			last_poll_time: Date.now() / 1000 - 30,
			cache_counts: { clients: 4, devices: 2 },
			last_error: null,
			...overrides,
		};
	}

	async function openIntegrations() {
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Integrations' }));
	}

	it('shows connected state and last poll from the daemon status fields', async () => {
		stubFetch({ '/api/integrations/unifi/status': () => ({ body: status({ site_id: 'site-a' }) }) });

		await openIntegrations();

		expect(screen.getByText('Connected')).toBeInTheDocument();
		expect(screen.getByText('Last Poll')).toBeInTheDocument();
		expect(screen.getByText(/^\d+s ago$/)).toBeInTheDocument();
		expect(screen.getByLabelText('Site')).toHaveValue('site-a');
	});

	it('shows disconnected and no last poll before the first successful poll', async () => {
		stubFetch({
			'/api/integrations/unifi/status': () => ({ body: status({ connected: false, last_poll_time: 0 }) }),
		});

		await openIntegrations();

		expect(screen.getByText('Disconnected')).toBeInTheDocument();
		expect(screen.queryByText('Last Poll')).not.toBeInTheDocument();
	});

	it('does not post a blank site_id', async () => {
		const fetchMock = stubFetch({
			'/api/integrations/unifi/status': () => ({ body: status() }),
			'/api/integrations/unifi/configure': () => ({ body: { status: 'configured' } }),
			'/api/integrations/unifi/test': () => ({ body: { success: true, status: status() } }),
		});

		await openIntegrations();
		await fireEvent.input(screen.getByLabelText('Site'), { target: { value: '   ' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Save Configuration' }));
		await flush();

		const call = fetchMock.mock.calls.find(([url]) => url === '/api/integrations/unifi/configure');
		expect(call).toBeDefined();
		const body = JSON.parse(String(call?.[1]?.body));
		expect(body).toEqual({ controller_url: 'https://192.168.1.1' });
	});
});
