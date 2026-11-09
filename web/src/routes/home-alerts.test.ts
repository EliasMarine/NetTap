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

	it('O9: with the summary failed, "to review" is left out, not filled with every alert', async () => {
		stubDaemon({ '/api/alerts/count': { from: '', to: '', counts: { total: 57, high: 1, medium: 6, low: 50 } } });
		render(HomePage);
		expect(await screen.findByText("Couldn't load the alert summary: the request failed.")).toBeInTheDocument();
		await screen.findByRole('img', { name: /^57 alerts in the/ });
		expect(screen.queryByText(/to review/)).not.toBeInTheDocument();
	});

	// OLD CODE START — NET-228: "No actionable alerts detected." never said whether data was arriving
	// it('still says none were detected when the request succeeds empty', async () => {
	// 	stubDaemon({ '/api/alerts/smart': { from: '', to: '', device_ip: null, alerts: [], total: 0 } });
	// 	render(HomePage);
	// 	expect(await screen.findByText('No actionable alerts detected.')).toBeInTheDocument();
	// 	expect(screen.queryByText(/Couldn't load the alert summary/)).not.toBeInTheDocument();
	// });
	// OLD CODE END
	const FRESH = {
		status: 'healthy', healthy: true, opensearch_reachable: true,
		pipeline: { state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' },
	};
	const EMPTY_SMART = { from: '', to: '', device_ip: null, alerts: [], total: 0 };

	it('an empty summary says nothing needs review, beside the pipeline state, while data is fresh', async () => {
		stubDaemon({
			'/api/alerts/smart': EMPTY_SMART,
			'/api/alerts/count': { from: '', to: '', counts: { total: 57, high: 1, medium: 6, low: 50 } },
			'/api/system/health': FRESH,
		});
		render(HomePage);
		expect((await screen.findByText('No alert groups to review in this period · Data pipeline now: Newest record 40 s ago')).closest('p')).toHaveClass('dim');
		expect(screen.queryByText(/Couldn't load the alert summary/)).not.toBeInTheDocument();
	});

	it("an empty summary can't tell, as a warning, when the pipeline isn't fresh", async () => {
		stubDaemon({
			'/api/alerts/smart': EMPTY_SMART,
			'/api/alerts/count': { from: '', to: '', counts: { total: 57, high: 1, medium: 6, low: 50 } },
			'/api/system/health': { ...FRESH, pipeline: { ...FRESH.pipeline, state: 'stale', age_seconds: 47 * 60 } },
		});
		render(HomePage);
		const line = await screen.findByText("Can't tell if anything needs review · Data pipeline now: No new records for 47 min");
		expect(line.closest('p')).toHaveClass('notice', 'is-warn');
	});
});
