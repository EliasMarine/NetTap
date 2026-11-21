import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';
import * as api from '$lib/api/pcap';
import { PcapRequestError } from '$lib/api/pcap';

// NET-347: a filter TShark refuses starts nothing, the results follow the search that was sent
// (not the text in the box), and a finished search says how much of the window it covered.

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

const REFUSED = 'tshark: "nettapqa_invalid_filter" is neither a field nor a protocol name.';
const FILE = { file: '/data/pcap/a.pcap', name: 'a.pcap', size_bytes: 2048, modified: '2026-11-20T00:00:00Z', relative_path: 'a.pcap' };

function done(over: Partial<api.PcapSearchResponse> = {}): api.PcapSearchResponse {
	return {
		filter: 'dns', count: 0, results: [], files_checked: 1, files_total: 1, complete: true,
		timed_out: 0, failed: 0, files_full: 1, files_truncated: 0, ...over,
	};
}

beforeEach(() => {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	vi.mocked(api.getPcapFiles).mockResolvedValue({ count: 0, files: [] });
	vi.mocked(api.checkPcapFilter).mockImplementation(async (filter) => ({ ok: true, filter }));
	vi.mocked(api.previewPcap).mockResolvedValue({ file: FILE.file, filter: null, count: 0, packets: [] });
});
afterEach(() => {
	vi.unstubAllGlobals();
	vi.clearAllMocks();
});

const field = () => screen.getByLabelText('Wireshark display filter') as HTMLInputElement;
const type = (value: string) => fireEvent.input(field(), { target: { value } });
const search = () => fireEvent.click(screen.getByRole('button', { name: 'Search' }));
const downloadButton = () => screen.getByRole('button', { name: /Download filtered/ });

async function searchFor(filter: string) {
	render(Page);
	await type(filter);
	await search();
}

describe('PCAP search: a refused filter (NET-347)', () => {
	it("shows TShark's message under the field, with no results card and no polling", async () => {
		vi.mocked(api.searchPcaps).mockRejectedValue(new PcapRequestError(REFUSED, 400));
		await searchFor('nettapqa_invalid_filter');

		const message = await screen.findByText(REFUSED);
		expect(message).toHaveAttribute('id', 'pcap-filter-error');
		expect(field()).toHaveAttribute('aria-invalid', 'true');
		expect(field()).toHaveAttribute('aria-describedby', 'pcap-filter-error');
		expect(screen.queryByText('Search results')).not.toBeInTheDocument();
		expect(screen.queryByText(/files? match/)).not.toBeInTheDocument();
		expect(api.searchPcaps).toHaveBeenCalledTimes(1);
	});

	it('drops the inline message once the field holds different text', async () => {
		vi.mocked(api.searchPcaps).mockRejectedValue(new PcapRequestError(REFUSED, 400));
		await searchFor('nettapqa_invalid_filter');
		await screen.findByText(REFUSED);

		await type('dns');
		expect(screen.queryByText(REFUSED)).not.toBeInTheDocument();
		expect(field()).not.toHaveAttribute('aria-invalid');
	});

	it('names the filter in a page notice when the field was edited before the refusal came back', async () => {
		let refuse!: (e: Error) => void;
		vi.mocked(api.searchPcaps).mockReturnValue(new Promise((_, reject) => (refuse = reject)));
		await searchFor('nettapqa_invalid_filter');
		await type('dns');
		refuse(new PcapRequestError(REFUSED, 400));

		expect(await screen.findByText(`The filter "nettapqa_invalid_filter" was refused: ${REFUSED}`)).toBeInTheDocument();
		expect(field()).not.toHaveAttribute('aria-invalid');
	});
});

describe('PCAP search: a start that failed for another reason', () => {
	it('offers Try again, which resends the same filter and window', async () => {
		vi.mocked(api.searchPcaps)
			.mockRejectedValueOnce(new PcapRequestError('The packet reader is busy; try again in a moment.', 503))
			.mockResolvedValue(done());
		await searchFor('dns');
		await screen.findByText('The packet reader is busy; try again in a moment.');
		await type('http'); // the retry is the search that failed, not the new text

		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await screen.findByText('Search results');
		const [first, second] = vi.mocked(api.searchPcaps).mock.calls;
		expect(second).toEqual(first);
		expect(second[0]).toBe('dns');
	});
});

describe('PCAP search: results follow the search that was sent', () => {
	it('keeps the submitted filter in the card and for a row preview after the field is edited', async () => {
		vi.mocked(api.searchPcaps).mockResolvedValue(
			done({ count: 1, results: [{ ...FILE, matching_packets: 7, outcome: 'full' }] }),
		);
		await searchFor('dns');
		expect(await screen.findByText('1 file matches dns')).toBeInTheDocument();

		await type('http');
		expect(screen.getByText('1 file matches dns')).toBeInTheDocument();
		const results = screen.getByRole('table', { name: /search results|matching/i });
		await fireEvent.click(within(results).getByText('a.pcap'));
		expect(api.previewPcap).toHaveBeenCalledWith(FILE.file, expect.objectContaining({ filter: 'dns' }));
	});

	it('shows the later preview when two answers come back in reverse order', async () => {
		vi.mocked(api.getPcapFiles).mockResolvedValue({ count: 2, files: [FILE, { ...FILE, file: '/data/pcap/b.pcap', name: 'b.pcap', relative_path: 'b.pcap' }] });
		let slow!: (v: api.PcapPreviewResponse) => void;
		const pkt = (info: string) => ({ frame_number: '1', timestamp: 't', source: 's', destination: 'd', protocol: 'DNS', length: '60', info });
		vi.mocked(api.previewPcap)
			.mockReturnValueOnce(new Promise((resolve) => (slow = resolve)))
			.mockResolvedValueOnce({ file: '/data/pcap/b.pcap', filter: null, count: 1, packets: [pkt('from b')] });
		render(Page);
		await fireEvent.click(await screen.findByText('a.pcap'));
		await fireEvent.click(screen.getByText('b.pcap'));
		expect(await screen.findByText('from b')).toBeInTheDocument();

		slow({ file: FILE.file, filter: null, count: 1, packets: [pkt('from a')] });
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('from a')).not.toBeInTheDocument();
		expect(screen.getByText('from b')).toBeInTheDocument();
	});
});

describe('PCAP search: what a finished search covered', () => {
	it('labels a search with unread files incomplete and says how much was read', async () => {
		vi.mocked(api.searchPcaps).mockResolvedValue(
			done({
				files_checked: 318, files_total: 318, files_full: 7, failed: 311,
				error: 'timeout: fork system call failed',
				count: 1, results: [{ ...FILE, matching_packets: 3, outcome: 'full' }],
			}),
		);
		await searchFor('dns');

		expect(await screen.findByText('1 file matches dns · incomplete')).toBeInTheDocument();
		expect(screen.getByText('Fully searched 7 of 318 files. Results are incomplete.')).toBeInTheDocument();
		expect(screen.getByText("311 files couldn't be searched: timeout: fork system call failed")).toBeInTheDocument();
	});

	it('marks a count from a read that stopped early as a minimum', async () => {
		vi.mocked(api.searchPcaps).mockResolvedValue(
			done({ files_full: 0, timed_out: 1, count: 1, results: [{ ...FILE, matching_packets: 2, outcome: 'timed_out' }] }),
		);
		await searchFor('dns');

		expect(await screen.findByText('at least 2')).toBeInTheDocument();
		expect(screen.getByText(/Reading stopped early in 1 file: its count is a minimum/)).toBeInTheDocument();
		expect(screen.queryByText(/took longer than 5 minutes/)).not.toBeInTheDocument(); // counted once, as a row
	});

	it('gives a file that ends mid-packet its own line without calling the search incomplete', async () => {
		vi.mocked(api.searchPcaps).mockResolvedValue(done({ files_full: 0, files_truncated: 1 }));
		await searchFor('dns');

		expect(await screen.findByText(/1 file ends mid-packet/)).toBeInTheDocument();
		expect(screen.getByText('0 files match dns')).toBeInTheDocument();
		expect(screen.queryByText(/incomplete/)).not.toBeInTheDocument();
		expect(screen.queryByText(/Fully searched/)).not.toBeInTheDocument(); // a file being written is not a missed file
	});

	it('says nothing about coverage when every file was read to the end', async () => {
		vi.mocked(api.searchPcaps).mockResolvedValue(done());
		await searchFor('dns');

		await screen.findByText('0 files match dns');
		expect(screen.queryByText(/Fully searched/)).not.toBeInTheDocument();
	});
});

describe('PCAP search: Download filtered waits for the filter check', () => {
	it('stays off with the message when TShark refuses the filter', async () => {
		vi.mocked(api.checkPcapFilter).mockRejectedValue(new PcapRequestError(REFUSED, 400));
		render(Page);
		await type('nettapqa_invalid_filter');

		expect(await screen.findByText(REFUSED)).toBeInTheDocument();
		expect(downloadButton()).toBeDisabled();
	});

	it("turns on with a note when the check couldn't run (the download checks again)", async () => {
		vi.mocked(api.checkPcapFilter).mockRejectedValue(new PcapRequestError('The packet reader is busy; try again in a moment.', 503));
		render(Page);
		await type('dns');

		expect(await screen.findByText(/Couldn't check the filter just now/)).toBeInTheDocument();
		expect(downloadButton()).toBeEnabled();
	});

	it('is off while the text in the field has not been checked', async () => {
		vi.mocked(api.checkPcapFilter).mockReturnValue(new Promise(() => {}));
		render(Page);
		await type('dns');

		expect(downloadButton()).toBeDisabled();
	});
});
