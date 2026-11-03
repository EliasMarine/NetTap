import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// #96: getSmartAlerts turned an HTTP error into an empty list, so the Alert Summary card
// said "No actionable alerts detected" when the request had failed.

function stubDaemon(replies: Record<string, unknown>): void {
	// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
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

describe('Home — Alert Summary', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the alert summary failed instead of "No actionable alerts detected"', async () => {
		stubDaemon({});
		render(HomePage);
		expect(await screen.findByText("Couldn't load the alert summary: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No actionable alerts detected.')).not.toBeInTheDocument();
		expect(screen.queryByText(/0 to review/)).not.toBeInTheDocument();
	});

	it('still says none were detected when the request succeeds empty', async () => {
		stubDaemon({ '/api/alerts/smart': { from: '', to: '', device_ip: null, alerts: [], total: 0 } });
		render(HomePage);
		expect(await screen.findByText('No actionable alerts detected.')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load the alert summary/)).not.toBeInTheDocument();
	});
});
