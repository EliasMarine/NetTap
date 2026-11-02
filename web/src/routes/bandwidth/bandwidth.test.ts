import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Page from './+page.svelte';

describe('Bandwidth', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// #96: a failed request read as "0.0 GB" this month and an all-zero heatmap
const MONTHLY = {
	year: 2026,
	month: 11,
	total_bytes: 3 * 1024 ** 3,
	orig_bytes: 1024 ** 3,
	resp_bytes: 2 * 1024 ** 3,
	projection: {
		year: 2026, month: 11, current_bytes: 3 * 1024 ** 3, projected_bytes: 45 * 1024 ** 3,
		days_elapsed: 2, days_in_month: 30, daily_rate_bytes: 1.5 * 1024 ** 3,
		cap_bytes: 0, usage_percent: 0, projected_percent: 0, exceeds_cap: false,
	},
};

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

describe('Bandwidth — failed requests', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says each section failed instead of 0.0 GB or an empty heatmap', async () => {
		stubDaemon({});
		render(Page);
		expect(await screen.findByText("Couldn't load this month's usage: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the time-of-day heatmap: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load daily usage: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load per-device usage: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('0.0 GB')).not.toBeInTheDocument();
		expect(screen.queryByText(/Time-of-Day Heatmap/)).not.toBeInTheDocument();
	});

	it('shows the sections that loaded when others fail', async () => {
		stubDaemon({ '/api/bandwidth/monthly': MONTHLY });
		render(Page);
		expect(await screen.findByText('3.0 GB')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load this month's usage/)).not.toBeInTheDocument();
		expect(screen.getByText("Couldn't load the time-of-day heatmap: the request failed.")).toBeInTheDocument();
	});
});
