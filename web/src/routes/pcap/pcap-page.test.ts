import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';
import * as api from '$lib/api/pcap';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-189: "Download filtered" takes its own window, because one download reads a few busy
// minutes at most and the page's shortest range is an hour.

vi.mock('$lib/api/pcap', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/pcap')>()),
	getPcapFiles: vi.fn(),
	searchPcaps: vi.fn(),
	previewPcap: vi.fn(),
}));
vi.mock('$lib/api/capture', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/capture')>()),
	fetchCaptureStatus: vi.fn(async () => ({ enabled: true, maxFileSizeMB: 256, rotateMinutes: 10, containerRunning: true, containerStatus: 'running' })),
}));

let open: ReturnType<typeof vi.fn>;

beforeEach(() => {
	vi.mocked(api.getPcapFiles).mockResolvedValue({ count: 0, files: [] });
	open = vi.fn();
	vi.stubGlobal('open', open);
});
afterEach(() => {
	vi.unstubAllGlobals();
	vi.clearAllMocks();
});

/** The query of the one download the page opened. */
function opened(): URLSearchParams {
	expect(open).toHaveBeenCalledTimes(1);
	const url = new URL(open.mock.calls[0][0] as string, 'http://localhost');
	expect(url.pathname).toBe('/api/pcap/download');
	return url.searchParams;
}

async function setUp(filter = 'tcp') {
	render(Page);
	await fireEvent.input(screen.getByLabelText('Wireshark display filter'), { target: { value: filter } });
}

const download = () => fireEvent.click(screen.getByRole('button', { name: /Download filtered/ }));
const from = () => screen.getByLabelText('Download from') as HTMLInputElement;
const to = () => screen.getByLabelText('to', { exact: true }) as HTMLInputElement;

describe('PCAP Search: Download filtered window', () => {
	it('downloads the page range when no window is set', async () => {
		await setUp();
		const before = Date.now();
		await download();
		const q = opened();
		expect(q.get('filter')).toBe('tcp');
		const span = Date.parse(q.get('to')!) - Date.parse(q.get('from')!);
		expect(span).toBe(60 * 60 * 1000); // the default range, last hour
		expect(Date.parse(q.get('to')!)).toBeGreaterThanOrEqual(before - 1000);
	});

	it('downloads exactly the window set, in UTC, and keeps the search on the page range', async () => {
		vi.mocked(api.searchPcaps).mockResolvedValue({ filter: 'tcp', count: 0, results: [], complete: true } as never);
		await setUp();
		await fireEvent.input(from(), { target: { value: '2026-11-12T17:00:00' } });
		await fireEvent.input(to(), { target: { value: '2026-11-12T17:00:20' } });
		await download();
		const q = opened();
		expect(q.get('from')).toBe(new Date('2026-11-12T17:00:00').toISOString());
		expect(q.get('to')).toBe(new Date('2026-11-12T17:00:20').toISOString());
		expect(q.get('from')).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/); // what the daemon reads
		expect(screen.queryByRole('alert')).toBeNull();

		await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
		const [, range] = vi.mocked(api.searchPcaps).mock.calls[0];
		expect(Date.parse(range!.to!) - Date.parse(range!.from!)).toBe(60 * 60 * 1000);
	});

	it('asks for both ends when only one is set, and opens nothing', async () => {
		await setUp();
		await fireEvent.input(from(), { target: { value: '2026-11-12T17:00:00' } });
		await download();
		expect(screen.getByRole('alert').textContent).toContain('Set both a start and an end for the download, or clear both.');
		expect(open).not.toHaveBeenCalled();
	});

	it('refuses an end before the start, and opens nothing', async () => {
		await setUp();
		await fireEvent.input(from(), { target: { value: '2026-11-12T17:00:20' } });
		await fireEvent.input(to(), { target: { value: '2026-11-12T17:00:20' } });
		await download();
		expect(screen.getByRole('alert').textContent).toContain('The download’s end has to be after its start.');
		expect(open).not.toHaveBeenCalled();
	});

	it('says what the window is for, and nests no control in another', async () => {
		await setUp();
		expect(from().type).toBe('datetime-local');
		expect(to().type).toBe('datetime-local');
		expect(screen.getByText(/Download filtered saves the last hour unless you set a start and an end here/)).toBeTruthy();
		expectNoNestedInteractive(document.body);
	});
});
