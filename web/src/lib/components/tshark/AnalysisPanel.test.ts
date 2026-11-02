import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import AnalysisPanel from './AnalysisPanel.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/tools/tshark') }),
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
		expect(screen.queryByText(/TShark Unavailable/)).not.toBeInTheDocument();
	});

	it('says the PCAP list failed instead of "No PCAP files found"', async () => {
		stubFetch({ '/api/tshark/status': STATUS });

		render(AnalysisPanel);
		await fireEvent.click(screen.getByRole('button', { name: /Browse/ }));

		expect(await screen.findByText("Couldn't load the PCAP file list: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No PCAP files found/)).not.toBeInTheDocument();
	});

	it('still shows the version and an empty list when both requests succeed', async () => {
		stubFetch({ '/api/tshark/status': STATUS, '/api/tshark/pcaps': { pcaps: [], count: 0 } });

		render(AnalysisPanel);
		expect(await screen.findByText(/TShark 4\.2\.5/)).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /Browse/ }));

		expect(await screen.findByText(/No PCAP files found/)).toBeInTheDocument();
	});
});
