import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { getPcapFiles, searchPcaps, previewPcap, getDownloadUrl, formatBytes } from '$lib/api/pcap';
import PcapPage from './+page.svelte';

/**
 * Page-level tests for the PCAP search page.
 * Tests the API integration functions used by the page.
 */

function mockFetchSuccess(body: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve(body),
		}),
	);
}

describe('PCAP search page integration', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('loads available PCAP files', async () => {
		mockFetchSuccess({
			count: 1,
			files: [
				{
					file: '/data/pcap/test.pcap',
					name: 'test.pcap',
					size_bytes: 1024,
					modified: '2026-03-08T00:00:00Z',
					relative_path: 'test.pcap',
				},
			],
		});

		const result = await getPcapFiles();
		expect(result.files).toHaveLength(1);
		expect(result.files[0].name).toBe('test.pcap');
	});

	it('searches PCAPs with BPF filter', async () => {
		mockFetchSuccess({
			filter: 'tcp port 80',
			count: 1,
			files_checked: 1,
			files_total: 1,
			complete: true,
			timed_out: 0,
			results: [
				{
					file: '/data/pcap/test.pcap',
					name: 'test.pcap',
					size_bytes: 1024,
					modified: '2026-03-08T00:00:00Z',
					relative_path: 'test.pcap',
					matching_packets: 42,
				},
			],
		});

		const result = await searchPcaps('tcp port 80');
		expect(result.results[0].matching_packets).toBe(42);
	});

	it('previews packets from a PCAP file', async () => {
		mockFetchSuccess({
			file: '/data/pcap/test.pcap',
			filter: null,
			count: 1,
			packets: [
				{
					frame_number: '1',
					timestamp: '2026-03-08T00:00:00',
					source: '192.168.1.1',
					destination: '8.8.8.8',
					protocol: 'DNS',
					length: '74',
					info: 'Standard query A google.com',
				},
			],
		});

		const result = await previewPcap('/data/pcap/test.pcap');
		expect(result.packets).toHaveLength(1);
		expect(result.packets[0].protocol).toBe('DNS');
	});

	it('generates correct download URL', () => {
		const url = getDownloadUrl('tcp port 80', {
			from: '2026-03-01T00:00:00Z',
			to: '2026-03-08T00:00:00Z',
		});
		expect(url).toContain('/api/pcap/download');
		expect(url).toContain('filter=');
	});

	it('formats bytes correctly', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(1024)).toBe('1.0 KB');
		expect(formatBytes(1048576)).toBe('1.0 MB');
	});
});

// ---------------------------------------------------------------------------
// Rendered page: capture status header
// ---------------------------------------------------------------------------

describe('PCAP page — capture status', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	/** /api/capture/status gets `status` (or a network error when null); everything else 500s. */
	async function renderWithCaptureStatus(status: Record<string, unknown> | null) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/capture/status')) {
					if (!status) throw new Error('network error');
					return { ok: true, status: 200, json: async () => status };
				}
				return { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(PcapPage);
		for (let i = 0; i < 5; i++) await Promise.resolve();
		await new Promise((r) => setTimeout(r, 0));
	}

	it('says Active when enabled and the container is running', async () => {
		await renderWithCaptureStatus({ enabled: true, maxFileSizeMB: 100, containerRunning: true, containerStatus: 'running' });

		expect(screen.getByText('Capture Active')).toBeInTheDocument();
	});

	it('does not say Active when enabled but the container is down', async () => {
		await renderWithCaptureStatus({ enabled: true, maxFileSizeMB: 100, containerRunning: false, containerStatus: 'exited' });

		expect(screen.getByText('Capture Stopped')).toBeInTheDocument();
		expect(screen.queryByText('Capture Active')).not.toBeInTheDocument();
	});

	it('says the status is unknown when it cannot be read', async () => {
		await renderWithCaptureStatus(null);

		expect(screen.getByText('Capture Status Unknown')).toBeInTheDocument();
		expect(screen.queryByText('Capture Active')).not.toBeInTheDocument();
	});
});

// The toggle read "on" when the state couldn't be read, so a click turned capture off on a guess.
describe('PCAP page — capture toggle', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const RUNNING = { enabled: true, maxFileSizeMB: 100, containerRunning: true, containerStatus: 'running' };

	/** Status replies `status` (HTTP 503 when null); the toggle replies `toggle` (HTTP 500 when null). */
	function stubCapture(status: Record<string, unknown> | null, toggle: Record<string, unknown> | null = null) {
		const fetchMock = vi.fn(async (url: string) => {
			if (url.startsWith('/api/capture/status')) {
				return status
					? { ok: true, status: 200, json: async () => status }
					: { ok: false, status: 503, json: async () => ({}) };
			}
			if (url.startsWith('/api/capture/toggle')) {
				return toggle
					? { ok: true, status: 200, json: async () => toggle }
					: { ok: false, status: 500, json: async () => ({ error: 'docker did not answer' }) };
			}
			return { ok: false, status: 500, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fetchMock);
		return fetchMock;
	}

	const toggleCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => String(u).startsWith('/api/capture/toggle'));

	it('is not shown on and cannot be clicked while the state is unknown', async () => {
		const fetchMock = stubCapture(null);
		render(PcapPage);

		const toggle = await screen.findByRole('button', { name: "PCAP capture state unknown: can't change it" });
		expect(toggle).toBeDisabled();
		expect(toggle).not.toHaveClass('on');
		await fireEvent.click(toggle);
		expect(toggleCalls(fetchMock)).toHaveLength(0);
	});

	it('turns capture off when it is known to be on', async () => {
		const fetchMock = stubCapture(RUNNING, { enabled: false, containerRunning: false, containerStatus: 'exited' });
		render(PcapPage);

		const toggle = await screen.findByRole('button', { name: 'Disable PCAP capture' });
		expect(toggle).toHaveClass('on');
		await fireEvent.click(toggle);

		expect(await screen.findByText('Capture Stopped')).toBeInTheDocument();
		expect(toggleCalls(fetchMock)[0][1]).toMatchObject({ body: JSON.stringify({ enabled: false }) });
	});

	it('says so when the toggle fails', async () => {
		stubCapture(RUNNING);
		render(PcapPage);

		await fireEvent.click(await screen.findByRole('button', { name: 'Disable PCAP capture' }));

		expect(await screen.findByText("Couldn't turn capture off: docker did not answer")).toBeInTheDocument();
		expect(screen.getByText('Capture Active')).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Rendered page: background search polling
// ---------------------------------------------------------------------------

const MATCH = {
	file: '/data/pcap/a.pcap',
	name: 'a.pcap',
	size_bytes: 2048,
	modified: '2026-03-08T00:00:00Z',
	relative_path: 'a.pcap',
	matching_packets: 7,
};

function searchBody(over: Record<string, unknown> = {}) {
	return {
		filter: 'dns',
		count: 0,
		results: [],
		files_checked: 0,
		files_total: 53,
		complete: false,
		timed_out: 0,
		...over,
	};
}

describe('PCAP page — search polling', () => {
	/** Each /api/pcap/search call takes the next queued step (the last one repeats); the rest 500. */
	function stubSearch(steps: Array<Record<string, unknown> | Error>) {
		const searchUrls: string[] = [];
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (!url.startsWith('/api/pcap/search')) return { ok: false, status: 500, json: async () => ({}) };
				const step = steps[Math.min(searchUrls.length, steps.length - 1)];
				searchUrls.push(url);
				if (step instanceof Error) return { ok: false, status: 400, json: async () => ({ error: step.message }) };
				return { ok: true, status: 200, json: async () => step };
			}),
		);
		return searchUrls;
	}

	async function startSearch() {
		render(PcapPage);
		await vi.advanceTimersByTimeAsync(0);
		await fireEvent.input(screen.getByPlaceholderText(/display filter/i), { target: { value: 'dns' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
		await vi.advanceTimersByTimeAsync(0);
	}

	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('polls with the same range until complete, showing progress then results', async () => {
		const urls = stubSearch([
			searchBody({ files_checked: 5, results: [], count: 0 }),
			searchBody({ files_checked: 53, complete: true, count: 1, results: [MATCH] }),
		]);

		await startSearch();

		expect(screen.getByText(/Checked 5 of 53 files, newest first/)).toBeInTheDocument();
		expect(screen.queryByText('a.pcap')).not.toBeInTheDocument();
		expect(screen.queryByText(/No matching packets/)).not.toBeInTheDocument();

		await vi.advanceTimersByTimeAsync(3000);

		expect(screen.getByText('a.pcap')).toBeInTheDocument();
		expect(screen.getByText('Search Results (1 files match)')).toBeInTheDocument();
		expect(screen.queryByText(/Checked \d+ of/)).not.toBeInTheDocument();
		expect(urls).toHaveLength(2);
		expect(urls[1]).toBe(urls[0]); // identical filter/from/to or the daemon restarts the job

		await vi.advanceTimersByTimeAsync(10_000);
		expect(urls).toHaveLength(2); // stopped polling once complete
	});

	it('a new search replaces a running one', async () => {
		const urls = stubSearch([searchBody({ files_checked: 1 })]);

		await startSearch();
		await fireEvent.input(screen.getByPlaceholderText(/display filter/i), { target: { value: 'http' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Searching...' }));
		await vi.advanceTimersByTimeAsync(0);
		const startedAt = urls.length;
		await vi.advanceTimersByTimeAsync(9000);

		const later = urls.slice(startedAt - 1);
		expect(later.length).toBeGreaterThan(1);
		expect(later.every((u) => u.includes('filter=http'))).toBe(true); // the dns loop stopped
	});

	it('stops polling and shows the error when a poll fails', async () => {
		const urls = stubSearch([searchBody({ files_checked: 1 }), new Error('Daemon unreachable: boom')]);

		await startSearch();
		await vi.advanceTimersByTimeAsync(3000);

		expect(screen.getByText('Daemon unreachable: boom')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Search' })).toBeEnabled();

		await vi.advanceTimersByTimeAsync(10_000);
		expect(urls).toHaveLength(2);
	});

	it('stops polling when the page is destroyed', async () => {
		const urls = stubSearch([searchBody({ files_checked: 1 })]);

		const { unmount } = render(PcapPage);
		await vi.advanceTimersByTimeAsync(0);
		await fireEvent.input(screen.getByPlaceholderText(/display filter/i), { target: { value: 'dns' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Search' }));
		await vi.advanceTimersByTimeAsync(0);
		expect(urls).toHaveLength(1);

		unmount();
		await vi.advanceTimersByTimeAsync(10_000);
		expect(urls).toHaveLength(1);
	});

	it('explains files skipped for taking too long', async () => {
		stubSearch([searchBody({ files_checked: 53, complete: true, timed_out: 2, count: 1, results: [MATCH] })]);

		await startSearch();

		expect(
			screen.getByText(
				'2 large files took longer than 5 minutes each and were skipped \u2014 pick a shorter time range to search them.',
			),
		).toBeInTheDocument();
		expect(screen.getByText('a.pcap')).toBeInTheDocument();
	});

	it('does not show the skipped-files note when nothing timed out', async () => {
		stubSearch([searchBody({ files_checked: 53, complete: true, timed_out: 0 })]);

		await startSearch();

		expect(screen.getByText(/No matching packets found/)).toBeInTheDocument();
		expect(screen.queryByText(/were skipped/)).not.toBeInTheDocument();
		expect(screen.queryByText(/couldn't be searched/)).not.toBeInTheDocument();
	});

	it('says files tshark could not read were not searched, instead of "no match" (#96)', async () => {
		stubSearch([searchBody({ files_checked: 53, complete: true, failed: 2, error: 'docker not found in PATH' })]);

		await startSearch();

		expect(screen.getByText("2 files couldn't be searched: docker not found in PATH")).toBeInTheDocument();
		expect(screen.getByText('No matching packets in the files that could be searched.')).toBeInTheDocument();
		expect(screen.queryByText('No matching packets found in any PCAP file.')).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Rendered page: preview that ran out of time (#52)
// ---------------------------------------------------------------------------

describe('PCAP page — preview time limit', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	async function previewWith(body: Record<string, unknown>) {
		// jsdom has no ResizeObserver; the traffic chart beside the file list needs one to mount
		vi.stubGlobal(
			'ResizeObserver',
			class {
				observe() {}
				unobserve() {}
				disconnect() {}
			},
		);
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/pcap/files')) {
					return { ok: true, status: 200, json: async () => ({ count: 1, files: [MATCH] }) };
				}
				if (url.startsWith('/api/pcap/preview')) {
					return { ok: true, status: 200, json: async () => ({ file: MATCH.file, filter: 'dns', count: 0, ...body }) };
				}
				return { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(PcapPage);
		await fireEvent.click(await screen.findByText('a.pcap'));
		for (let i = 0; i < 5; i++) await Promise.resolve();
		await new Promise((r) => setTimeout(r, 0));
	}

	it('says the read stopped early instead of "No packets to display"', async () => {
		await previewWith({ packets: [], timed_out: true });

		expect(screen.getByText(/No matching packets in the part of this file read within 45 seconds/)).toBeInTheDocument();
		expect(screen.queryByText(/No packets to display/)).not.toBeInTheDocument();
	});

	it('keeps "No packets to display" when the whole file was read', async () => {
		await previewWith({ packets: [], timed_out: false });

		expect(screen.getByText(/No packets to display/)).toBeInTheDocument();
		expect(screen.queryByText(/within 45 seconds/)).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Rendered page: a failed file listing is not "No PCAP files" (#96)
// ---------------------------------------------------------------------------

describe('PCAP page — file list', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubFiles(reply: { ok: boolean; status: number; json: () => Promise<unknown> }) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) =>
				url.startsWith('/api/pcap/files') ? reply : { ok: false, status: 500, json: async () => ({}) },
			),
		);
	}

	it('says the list could not be loaded instead of "No PCAP files"', async () => {
		stubFiles({ ok: false, status: 500, json: async () => ({ error: 'boom' }) });

		render(PcapPage);

		expect((await screen.findAllByText("Couldn't load the PCAP file list: the request failed.")).length).toBe(2);
		expect(screen.queryByText(/No PCAP files/)).not.toBeInTheDocument();
	});

	it('still says there are no PCAP files when the list really is empty', async () => {
		stubFiles({ ok: true, status: 200, json: async () => ({ count: 0, files: [] }) });

		render(PcapPage);

		expect(await screen.findByText('No PCAP files in this time range.')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load the PCAP file list/)).not.toBeInTheDocument();
	});
});
