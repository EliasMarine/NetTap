import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

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
});
