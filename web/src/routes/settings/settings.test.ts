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
