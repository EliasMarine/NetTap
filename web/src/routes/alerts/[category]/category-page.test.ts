import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/alerts/scan'), params: { category: 'scan' } }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

// #96: a failed request read as "No alerts in <category>" (the client returned zero stats, and
// one failed request blanked the page) and the alert table said "No alerts found".

const DETAIL = {
	category: { id: 'scan', label: 'Scanning', description: '', color: 'amber', icon: 'radar' },
	stats: { total: 4, unique_sources: 1, unique_targets: 2, affected_devices: 2 },
	severity_breakdown: { critical: 0, high: 1, medium: 3, low: 0, info: 0 },
	sub_categories: [],
	affected_devices: [],
	top_signatures: [],
	mitre_techniques: [],
	from: '',
	to: '',
};

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

describe('Alert category page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the category could not be loaded instead of "No alerts in"', async () => {
		stubDaemon({});
		render(Page);
		await vi.waitFor(() => expect(screen.getByText(/Couldn't load/)).toBeInTheDocument());
		expect(screen.queryByText(/No alerts in/)).not.toBeInTheDocument();
	});

	it('says the alert list failed while the rest of the category still shows', async () => {
		stubDaemon({ '/api/alerts/categories/scan': DETAIL });
		render(Page);
		await vi.waitFor(() => expect(screen.getByText("Couldn't load alerts: the request failed.")).toBeInTheDocument());
		expect(screen.queryByText('No alerts found in this time range.')).not.toBeInTheDocument();
		expect(screen.getByText(/Couldn't load the alert volume over time/)).toBeInTheDocument();
		expect(screen.getByText('4 alerts')).toBeInTheDocument();
	});

	it('still says "No alerts in" when the category has none', async () => {
		stubDaemon({ '/api/alerts/categories/scan': { ...DETAIL, stats: { ...DETAIL.stats, total: 0 } } });
		render(Page);
		await vi.waitFor(() => expect(screen.getByText(/No alerts in/)).toBeInTheDocument());
	});
});
