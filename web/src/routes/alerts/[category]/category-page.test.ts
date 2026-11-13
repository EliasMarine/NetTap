import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
// OLD CODE: import { readable } from 'svelte/store'; (NET-185: the page store is writable)
import { goto } from '$app/navigation';
import { refreshPage } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

// OLD CODE START — NET-185: the page reads its window from the URL, so tests move it
// vi.mock('$app/stores', () => ({
// 	page: readable({ url: new URL('http://localhost/alerts/scan'), params: { category: 'scan' } }),
// }));
// OLD CODE END
const nav = vi.hoisted(() => ({ set: (_query: string) => {} }));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const page = writable({ url: new URL('http://localhost/alerts/scan'), params: { category: 'scan' } });
	nav.set = (query) => page.set({ url: new URL(`http://localhost/alerts/scan${query}`), params: { category: 'scan' } });
	return { page };
});
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
		// NET-160 section D: the bar carries its figure; the table row's link counts nothing, so carries none
		expect(new URL(screen.getByRole('link', { name: 'ET SCAN Nmap' }).getAttribute('href')!, 'http://localhost').searchParams.get('count')).toBe('3');
		expect(new URL(screen.getByRole('link', { name: 'Sig a' }).getAttribute('href')!, 'http://localhost').searchParams.has('count')).toBe(false);
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

	// OLD CODE START — NET-185: the daemon kept "Unknown" and no rule name in one bucket, so neither linked
	// // NET-160 section D: "Unknown" is the daemon's bucket for alerts with no rule name, and the list
	// // matches the literal name only; an empty name makes the list drop the filter. Neither can list its figure.
	// it('the "Unknown" and empty-name bars are plain rows, with no link and no count', async () => {
	// 	const detail = {
	// 		...DETAIL,
	// 		top_signatures: [
	// 			{ signature: 'ET SCAN Nmap', count: 3, last_seen: '2026-11-06T10:00:00Z' },
	// 			{ signature: 'Unknown', count: 5, last_seen: '2026-11-06T10:00:00Z' },
	// 			{ signature: '', count: 2, last_seen: '2026-11-06T10:00:00Z' },
	// 		],
	// 	};
	// 	stubDaemon({ '/api/alerts/categories/scan': detail });
	// 	const { container } = render(Page);
	// 	const card = await vi.waitFor(() => screen.getByRole('heading', { name: 'Top signatures' }).closest('.card') as HTMLElement);
	// 	const rows = [...card.querySelectorAll('.bar-row')];
	// 	expect(rows).toHaveLength(3);
	// 	const links = within(card).getAllByRole('link');
	// 	expect(links.map((a) => a.textContent)).toEqual(['ET SCAN Nmap']);
	// 	for (const row of rows.slice(1)) {
	// 		expect(row.querySelector('a, button, [href]')).toBeNull();
	// 	}
	// 	expect(rows[1]).toHaveTextContent('Unknown');
	// 	expect(rows[1]).toHaveTextContent('5');
	// 	expectNoNestedInteractive(container);
	// });
	// OLD CODE END
	// NET-185: "Unknown" is a rule's name and null is no rule name, each its own exact list; an
	// empty name still makes the list drop the filter, so that bar stays plain
	it('the "Unknown" and "No rule name" bars each open their own list with their figure; an empty name stays plain', async () => {
		const detail = {
			...DETAIL,
			top_signatures: [
				{ signature: 'ET SCAN Nmap', count: 3, last_seen: '2026-11-06T10:00:00Z' },
				{ signature: 'Unknown', count: 5, last_seen: '2026-11-06T10:00:00Z' },
				{ signature: null, count: 4, last_seen: '2026-11-06T10:00:00Z' },
				{ signature: '', count: 2, last_seen: '2026-11-06T10:00:00Z' },
			],
		};
		stubDaemon({ '/api/alerts/categories/scan': detail });
		const { container } = render(Page);
		const card = await vi.waitFor(() => screen.getByRole('heading', { name: 'Top signatures' }).closest('.card') as HTMLElement);
		const rows = [...card.querySelectorAll('.bar-row')];
		expect(rows).toHaveLength(4);
		const params = (name: string) => Object.fromEntries(new URL(within(card).getByRole('link', { name: new RegExp(name) }).getAttribute('href')!, 'http://localhost').searchParams);
		const shown = new URLSearchParams(vi.mocked(fetch).mock.calls.map(([u]) => String(u)).find((u) => u.startsWith('/api/alerts/categories/scan?'))!.split('?')[1]);
		const win = { from: shown.get('from'), to: shown.get('to'), range: '24h' };
		expect(params('Unknown')).toEqual({ signature: 'Unknown', ...win, count: '5' });
		expect(params('No rule name')).toEqual({ no_rule_name: 'true', ...win, count: '4' });
		expect(within(card).getAllByRole('link')).toHaveLength(3);
		expect(rows[3].querySelector('a, button, [href]')).toBeNull();
		expectNoNestedInteractive(container);
	});
});

// NET-185: a link from another page's window opens the category over that window, so its figures
// are the ones that were clicked
describe('Alert category page — the window in its URL', () => {
	const asked = (path: string) =>
		vi.mocked(fetch).mock.calls.map(([u]) => new URL(String(u), 'http://localhost')).filter((u) => u.pathname === path);
	afterEach(() => {
		nav.set('');
		vi.mocked(goto).mockClear();
		vi.unstubAllGlobals();
	});

	it("loads every figure over a link's exact window, shown as Custom", async () => {
		const from = '2026-11-01T08:00:00.000Z';
		const to = '2026-11-01T20:00:00.000Z';
		nav.set(`?from=${from}&to=${to}&range=7d`);
		stubDaemon({ '/api/alerts/categories/scan': { ...DETAIL, top_signatures: [{ signature: 'ET SCAN Nmap', count: 3, last_seen: '' }] } });
		render(Page);
		await vi.waitFor(() => expect(asked('/api/alerts')).toHaveLength(1));
		for (const path of ['/api/alerts/categories/scan', '/api/alerts/categories/scan/timeline', '/api/alerts']) {
			const [u] = asked(path);
			expect([u.searchParams.get('from'), u.searchParams.get('to')], path).toEqual([from, to]);
		}
		// 12 hours: the 24h range's hourly slots
		expect(asked('/api/alerts/categories/scan/timeline')[0].searchParams.get('interval')).toBe('1h');
		expect(screen.getByRole('button', { name: 'Custom' })).toHaveAttribute('aria-pressed', 'true');
		const bar = new URL((await screen.findByRole('link', { name: /ET SCAN Nmap/ })).getAttribute('href')!, 'http://localhost');
		expect([bar.searchParams.get('from'), bar.searchParams.get('to'), bar.searchParams.get('range')]).toEqual([from, to, '7d']);
	});

	it('loads ?range=7d over the last 7 days, and a pill writes its range to the URL', async () => {
		nav.set('?range=7d');
		stubDaemon({ '/api/alerts/categories/scan': DETAIL });
		render(Page);
		await vi.waitFor(() => expect(asked('/api/alerts/categories/scan')).toHaveLength(1));
		const [u] = asked('/api/alerts/categories/scan');
		expect((Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000).toBe(168);
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.queryByRole('button', { name: 'Custom' })).not.toBeInTheDocument();
		screen.getByRole('button', { name: '1h' }).click();
		expect(goto).toHaveBeenCalledWith('/alerts/scan?range=1h', { replaceState: true, keepFocus: true, noScroll: true });
	});
});
