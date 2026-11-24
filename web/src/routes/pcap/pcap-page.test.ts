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
	checkPcapFilter: vi.fn(),
}));
vi.mock('$lib/api/capture', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/capture')>()),
	fetchCaptureStatus: vi.fn(async () => ({ enabled: true, maxFileSizeMB: 256, rotateMinutes: 10, containerRunning: true, containerStatus: 'running' })),
}));

let open: ReturnType<typeof vi.fn>;
/** The download's tab: window.open returns it, and only it may report a refusal (NET-373) */
let tab: { close: ReturnType<typeof vi.fn> };

beforeEach(() => {
	vi.mocked(api.getPcapFiles).mockResolvedValue({ count: 0, files: [] });
	vi.mocked(api.checkPcapFilter).mockImplementation(async (filter) => ({ ok: true, filter }));
	tab = { close: vi.fn() };
	// OLD CODE: open = vi.fn(); (NET-373: a null return now means the browser blocked the tab)
	open = vi.fn(() => tab);
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
	// NET-347: Download filtered turns on once TShark has accepted the filter (500 ms after typing)
	await vi.waitFor(() => expect(screen.getByRole('button', { name: /Download filtered/ })).toBeEnabled());
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
		expect(screen.getByText(/a window that holds too many says how many here/)).toBeTruthy();
		expectNoNestedInteractive(document.body);
	});
});

// NET-373: a refused download opened its raw JSON in the new tab, away from the dates
describe('PCAP Search: a refused download says why beside its dates', () => {
	const EMPTY = 'No capture file holds packets from this window.';

	/** What lib/server/download-error-page.ts posts from the download's tab. */
	function refusal(message: string, opts: { source?: unknown; origin?: string; type?: string } = {}) {
		const event = new MessageEvent('message', {
			data: { type: opts.type ?? api.DOWNLOAD_ERROR_MESSAGE, message },
			origin: opts.origin ?? window.location.origin,
		});
		// jsdom's MessageEvent takes only a real window as its source
		Object.defineProperty(event, 'source', { value: 'source' in opts ? opts.source : tab });
		window.dispatchEvent(event);
	}

	async function downloadWindow2001() {
		await setUp('ip.addr == 192.0.2.123');
		await fireEvent.input(from(), { target: { value: '2001-01-01T00:00:00' } });
		await fireEvent.input(to(), { target: { value: '2001-01-01T00:01:00' } });
		await download();
	}

	it('asks for the refusal as a page, and shows it beside the dates, keeping the filter and dates', async () => {
		await downloadWindow2001();
		expect(opened().get('reply')).toBe('page');
		refusal(EMPTY);
		const alert = await screen.findByRole('alert');
		expect(alert).toHaveTextContent(EMPTY);
		expect(alert.id).toBe('pcap-download-error');
		expect(from()).toHaveAttribute('aria-describedby', 'pcap-download-error');
		expect(tab.close).toHaveBeenCalledTimes(1);
		// jsdom writes a whole minute without its seconds
		expect(from().value).toMatch(/^2001-01-01T00:00(:00)?$/);
		expect(to().value).toMatch(/^2001-01-01T00:01(:00)?$/);
		expect((screen.getByLabelText('Wireshark display filter') as HTMLInputElement).value).toBe('ip.addr == 192.0.2.123');
	});

	it('ignores a message from another window, another origin or of another kind', async () => {
		await downloadWindow2001();
		refusal(EMPTY, { source: {} });
		refusal(EMPTY, { origin: 'https://elsewhere.example' });
		refusal(EMPTY, { type: 'something-else' });
		await Promise.resolve();
		expect(screen.queryByText(EMPTY)).toBeNull();
		expect(tab.close).not.toHaveBeenCalled();
	});

	it('ignores the answer once the dates have changed, and leaves its tab open', async () => {
		await downloadWindow2001();
		await fireEvent.input(to(), { target: { value: '2001-01-01T00:02:00' } });
		refusal(EMPTY);
		await Promise.resolve();
		expect(screen.queryByText(EMPTY)).toBeNull();
		expect(tab.close).not.toHaveBeenCalled();
	});

	it('clears the last refusal when the same download is tried again', async () => {
		await downloadWindow2001();
		refusal('Another download is running; try again when it finishes.');
		expect(await screen.findByText('Another download is running; try again when it finishes.')).toBeTruthy();
		await download();
		expect(screen.queryByRole('alert')).toBeNull();
		expect(open).toHaveBeenCalledTimes(2);
	});

	it('offers a plain link when the browser blocks the tab, and clears it once used', async () => {
		open.mockReturnValueOnce(null);
		await downloadWindow2001();
		expect(screen.getByRole('alert')).toHaveTextContent('Your browser blocked the download tab.');
		const link = screen.getByRole('link', { name: 'Start the download' });
		expect(link.getAttribute('href')).toBe(open.mock.calls[0][0]);
		link.addEventListener('click', (e) => e.preventDefault()); // jsdom can't navigate
		await fireEvent.click(link);
		expect(screen.queryByRole('alert')).toBeNull();
		expect(from().value).toMatch(/^2001-01-01T00:00(:00)?$/);
	});
});
