import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// #96: a failed traffic request read as "0 B", an empty chart and "No category data yet".

const STREAMING = { name: 'streaming', label: 'Streaming', total_bytes: 5_000_000, connection_count: 4, device_count: 1 };

/** Replies by path; any path not listed answers 503. */
function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = replies[url.split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

describe('Home — failed traffic requests (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubCharts(): void {
		// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
	}

	it('says each traffic section failed instead of showing zeros or "no data"', async () => {
		stubCharts();
		stubDaemon({});
		render(HomePage);

		expect(await screen.findByText("Couldn't load traffic categories: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load traffic totals: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load bandwidth over time: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load network protocols: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No category data yet/)).not.toBeInTheDocument();
		expect(screen.queryByText('No service data available.')).not.toBeInTheDocument();
		expect(screen.queryByText(/0 B/)).not.toBeInTheDocument();
		// devices (#96): not "No device data available."
		expect(await screen.findByText("Couldn't load top devices: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the device count: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No device data available.')).not.toBeInTheDocument();
	});

	it('says the mirror-mode device list failed instead of "No devices detected yet"', async () => {
		stubCharts();
		stubDaemon({ '/api/capture/mode': { mode: 'mirror', interface: 'eth1' } });
		render(HomePage);

		expect(await screen.findByText("Couldn't load devices: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No devices detected yet')).not.toBeInTheDocument();
	});

	it('still says there is no category data when the request succeeds with none', async () => {
		stubCharts();
		stubDaemon({ '/api/traffic/categories': { from: '', to: '', categories: [] } });
		render(HomePage);

		expect(await screen.findByText(/No category data yet/)).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load traffic categories/)).not.toBeInTheDocument();
	});

	it('keeps the last categories on a failed refresh and says they are stale', async () => {
		stubCharts();
		stubDaemon({ '/api/traffic/categories': { from: '', to: '', categories: [STREAMING] } });
		render(HomePage);
		expect(await screen.findByText('Streaming')).toBeInTheDocument();

		stubDaemon({});
		await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));

		expect(await screen.findByText("Couldn't refresh traffic categories; showing the last figures loaded.")).toBeInTheDocument();
		expect(screen.getByText('Streaming')).toBeInTheDocument();
	});
});
