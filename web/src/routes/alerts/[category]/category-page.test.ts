import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

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

describe('Alert category page — sorting (#146)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("asks the daemon for the category's most severe alerts first, across every page", async () => {
		const alerts = {
			from: '', to: '', page: 1, size: 25, total: 400, total_pages: 16,
			alerts: [{ _id: 'a', _index: 'x', timestamp: '2026-10-29T10:00:00Z', alert: { signature: 'Sig a', signature_id: 1, severity: 2, category: 'misc' }, src_ip: '10.0.0.9', dest_ip: '8.8.8.8', acknowledged: false }],
		};
		stubDaemon({ '/api/alerts/categories/scan': DETAIL, '/api/alerts': alerts });
		const { container } = render(Page);
		await vi.waitFor(() => expect(screen.getByText('Sig a')).toBeInTheDocument());
		const severity = [...container.querySelectorAll('th')].find((th) => th.textContent?.trim().startsWith('Severity'))!;
		// OLD CODE START — the shared DataTable sorts from the header's button, not the th
		// severity.dispatchEvent(new MouseEvent('click', { bubbles: true }));
		// OLD CODE END
		severity.querySelector('button')!.click();
		await vi.waitFor(() => {
			const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url)).filter((u) => u.startsWith('/api/alerts?'));
			const last = new URLSearchParams(urls.at(-1)!.split('?')[1]);
			expect([last.get('category'), last.get('page'), last.get('sort'), last.get('order')]).toEqual(['scan', '1', 'severity', 'desc']);
		});
	});
});

describe('Alert category page — sub-category filter (#147)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('really filters the alert table when a sub-category is picked, and clears back', async () => {
		const detail = { ...DETAIL, sub_categories: [{ id: 'port_scan', label: 'Port Scan', count: 3 }] };
		const alerts = { from: '', to: '', page: 1, size: 25, total: 3, total_pages: 1, alerts: [] };
		stubDaemon({ '/api/alerts/categories/scan': detail, '/api/alerts': alerts });
		render(Page);
		const listCalls = () => vi.mocked(fetch).mock.calls.map(([u]) => String(u)).filter((u) => u.startsWith('/api/alerts?'));
		const lastParams = () => new URLSearchParams(listCalls().at(-1)!.split('?')[1]);
		await vi.waitFor(() => expect(screen.getByText('Port Scan')).toBeInTheDocument());
		const before = listCalls().length;

		screen.getByText('Port Scan').closest('button')!.click();
		await vi.waitFor(() => expect(lastParams().get('sub')).toBe('port_scan'));
		expect(lastParams().get('category')).toBe('scan');
		expect(listCalls().length).toBe(before + 1); // the list only, not the whole page again

		screen.getByText('Clear filter').click();
		await vi.waitFor(() => expect(lastParams().get('sub')).toBeNull());
	});
});

// NET-160 slice 2a: a signature opens the alerts list for it over the window of the figures on screen
describe('Alert category page — signature links', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("the top-signature bars and the table's signatures carry the shown window and range", async () => {
		const detail = { ...DETAIL, top_signatures: [{ signature: 'ET SCAN Nmap', count: 3, last_seen: '2026-11-06T10:00:00Z' }] };
		const alerts = {
			from: '', to: '', page: 1, size: 25, total: 1, total_pages: 1,
			alerts: [{ _id: 'a', _index: 'x', timestamp: '2026-10-29T10:00:00Z', alert: { signature: 'Sig a', signature_id: 1, severity: 2, category: 'misc' }, src_ip: '10.0.0.9', dest_ip: '8.8.8.8', acknowledged: false }],
		};
		stubDaemon({ '/api/alerts/categories/scan': detail, '/api/alerts': alerts });
		const { container } = render(Page);
		await vi.waitFor(() => expect(screen.getByRole('link', { name: 'Sig a' })).toBeInTheDocument());
		const detailUrl = vi.mocked(fetch).mock.calls.map(([u]) => String(u)).find((u) => u.startsWith('/api/alerts/categories/scan?'))!;
		const shown = new URLSearchParams(detailUrl.split('?')[1]);
		for (const name of ['ET SCAN Nmap', 'Sig a']) {
			const q = new URL(screen.getByRole('link', { name }).getAttribute('href')!, 'http://localhost');
			expect(q.pathname).toBe('/alerts');
			expect([q.searchParams.get('signature'), q.searchParams.get('from'), q.searchParams.get('to'), q.searchParams.get('range')]).toEqual([
				name, shown.get('from'), shown.get('to'), '24h',
			]);
		}
		expectNoNestedInteractive(container);

		// a refresh still in flight (minutes later) leaves the links on the figures on screen
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(Date.now() + 5 * 60_000);
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		void refreshPage();
		await new Promise((r) => setTimeout(r, 0));
		const bar = new URL(screen.getByRole('link', { name: 'ET SCAN Nmap' }).getAttribute('href')!, 'http://localhost');
		expect(bar.searchParams.get('to')).toBe(shown.get('to'));
		vi.useRealTimers();
	});
});
