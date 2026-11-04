import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import AnalysisPanel from './AnalysisPanel.svelte';

// tests can point the page at another URL (auto-analyze reads ?filter=&auto=1)
const nav = vi.hoisted(() => ({ url: 'http://localhost/tools/tshark' }));
vi.mock('$app/stores', () => ({
	page: { subscribe: (fn: (v: { url: URL }) => void) => readable({ url: new URL(nav.url) }).subscribe(fn) },
}));

/** Answer each URL prefix with its body, or HTTP 500 when it has none. */
function stubFetch(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			const key = Object.keys(replies).find((prefix) => url.startsWith(prefix));
			if (!key) return new Response('{}', { status: 500 });
			return new Response(JSON.stringify(replies[key]), { status: 200 });
		}),
	);
}

const STATUS = { available: true, version: '4.2.5', container_running: true, container_name: 'tshark' };

describe('AnalysisPanel when a request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the TShark status is unknown instead of "TShark Unavailable"', async () => {
		stubFetch({});

		render(AnalysisPanel);

		expect(await screen.findByText(/TShark status unknown/)).toBeInTheDocument();
		expect(screen.queryByText(/TShark unavailable/)).not.toBeInTheDocument();
	});

	it('says the PCAP list failed instead of "No PCAP files found"', async () => {
		stubFetch({ '/api/tshark/status': STATUS });

		render(AnalysisPanel);
		await fireEvent.click(screen.getByRole('button', { name: /Browse/ }));

		expect(await screen.findByText("Couldn't load the PCAP file list: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No PCAP files found/)).not.toBeInTheDocument();
	});

	it("names TShark once when the version line already starts with it", async () => {
		const version = 'TShark (Wireshark) 4.2.5 (Git v4.2.5 packaged as 4.2.5-1)';
		stubFetch({ '/api/tshark/status': { ...STATUS, version }, '/api/tshark/pcaps': { pcaps: [], count: 0 } });

		render(AnalysisPanel);
		expect(await screen.findByText(version)).toBeInTheDocument();
		expect(screen.queryByText(/TShark TShark/)).not.toBeInTheDocument();
	});

	it('still shows the version and an empty list when both requests succeed', async () => {
		stubFetch({ '/api/tshark/status': STATUS, '/api/tshark/pcaps': { pcaps: [], count: 0 } });

		render(AnalysisPanel);
		expect(await screen.findByText(/TShark 4\.2\.5/)).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /Browse/ }));

		expect(await screen.findByText(/No PCAP files found/)).toBeInTheDocument();
	});
});

const CUT_SHORT = { packets: [], packet_count: 0, truncated: true, tshark_version: '4.0.17' };
const PCAPS = {
	pcaps: [1, 2].map((n) => ({ name: `f${n}.pcap`, path: `/opt/nettap/pcap/f${n}.pcap`, size_bytes: 9e7, modified: 1793667138 - n })),
	count: 2,
};

describe('AnalysisPanel when TShark stopped before the end of the file', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		nav.url = 'http://localhost/tools/tshark';
	});

	it('says matches may be further in, not "more packets available", when none were found', async () => {
		stubFetch({ '/api/tshark/status': STATUS, '/api/tshark/analyze': CUT_SHORT });

		render(AnalysisPanel);
		await fireEvent.input(screen.getByLabelText('PCAP file path'), { target: { value: '/opt/nettap/pcap/f1.pcap' } });
		await fireEvent.click(screen.getByRole('button', { name: /Analyse/ }));

		expect(await screen.findByText(/Stopped before the end of the file/)).toBeInTheDocument();
		expect(screen.queryByText(/more packets available/)).not.toBeInTheDocument();
	});

	it('does not call cut-short searches "no packets matching" across the files it tried', async () => {
		nav.url = 'http://localhost/tools/tshark?filter=dns&auto=1';
		stubFetch({ '/api/tshark/status': STATUS, '/api/tshark/pcaps': PCAPS, '/api/tshark/analyze': CUT_SHORT });

		render(AnalysisPanel);

		expect(await screen.findByText(/stopped before the end of 2 of them/)).toBeInTheDocument();
		expect(screen.queryByText(/found across 2 PCAP file/)).not.toBeInTheDocument();
	});
});
