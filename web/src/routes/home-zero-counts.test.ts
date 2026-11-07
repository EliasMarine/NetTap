import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';
import { _configure } from '$lib/stores/alertSnapshot';
import { refreshPage } from '$lib/stores/pageRefresh';

// Home showed '--' for a real 0 alerts or 0 devices, and a failed alert count cleared the card.

function stubDaemon(replies: Record<string, unknown>): void {
	vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
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

/** A KPI card's number, found by its label (the stat cards became KpiCards). */
function cardValue(label: string): string | undefined {
	return screen.getByText(label, { selector: '.kpi-top > span' }).closest('.kpi')?.querySelector('.kpi-num')?.textContent?.trim();
}

describe('Home — real zeros and failed counts', () => {
	// the shared alert snapshot store outlives each render; start every test empty
	beforeEach(() => _configure({}));
	afterEach(() => vi.unstubAllGlobals());

	it('shows 0 alerts and 0 devices as 0, not "--"', async () => {
		stubDaemon({
			'/api/alerts/count': { from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } },
			'/api/devices/count': { from: '', to: '', count: 0 },
		});
		render(HomePage);
		await screen.findByText('0 high, 0 med, 0 low');
		expect(cardValue('Alerts')?.startsWith('0')).toBe(true);
		await vi.waitFor(() => expect(cardValue('Devices')).toBe('0'));
	});

	// NET-192 PR 4: the KPI read "214.0K" over "9000 high, 47000 med, 158000 low"
	it('writes a large alert count compactly, and its breakdown with separators', async () => {
		stubDaemon({
			'/api/alerts/count': { from: '', to: '', counts: { total: 214_000, high: 9000, medium: 47_000, low: 158_000 } },
			'/api/traffic/summary': { from: '', to: '', total_bytes: 10, packets_total: 1, connection_count: 1, top_protocols: [] },
		});
		render(HomePage);
		await screen.findByText('9,000 high, 47,000 med, 158,000 low');
		expect(cardValue('Alerts')).toBe('214K');
	});

	it("says the alert count failed and shows '—' instead of a blank '--'", async () => {
		// the traffic summary answers, so the page isn't the whole-daemon-down screen
		stubDaemon({
			'/api/devices/count': { from: '', to: '', count: 3 },
			'/api/traffic/summary': { from: '', to: '', total_bytes: 10, packets_total: 1, connection_count: 1, top_protocols: [] },
		});
		render(HomePage);
		expect(await screen.findByText("Couldn't load the alert count: the request failed.")).toBeInTheDocument();
		expect(cardValue('Alerts')?.startsWith('—')).toBe(true);
	});

	it('keeps the last alert count on a failed refresh and says it is stale (#96)', async () => {
		const summary = { from: '', to: '', total_bytes: 10, packets_total: 1, connection_count: 1, top_protocols: [] };
		stubDaemon({
			'/api/alerts/count': { from: '', to: '', counts: { total: 37, high: 1, medium: 6, low: 30 } },
			'/api/traffic/summary': summary,
		});
		render(HomePage);
		await screen.findByText('1 high, 6 med, 30 low');

		stubDaemon({ '/api/traffic/summary': summary });
		await refreshPage();

		expect(await screen.findByText("Couldn't refresh the alert count; showing the last figures loaded.")).toBeInTheDocument();
		expect(cardValue('Alerts')?.startsWith('37')).toBe(true);
		expect(screen.getByText("Couldn't refresh the severity summary; showing the last figures loaded.")).toBeInTheDocument();
	});
});
