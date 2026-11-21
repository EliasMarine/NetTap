import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import type { FailedLookups } from '$lib/api/threats';
import { LAN_POLICY } from '../../../../../e2e/visual/fixtures/drilldown';
import { FAILED_LOOKUPS, FAILED_LOOKUPS_EMPTY } from '../../../../../e2e/visual/fixtures/threats';
import { expectNoNestedInteractive } from '../../../../tests/nested-interactive';

// One device's failed lookups: what was read, what usually causes each kind, and the names, each
// opening the domain page in finding mode over this reply's exact window

const IP = FAILED_LOOKUPS.ip;
const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
// kit 3: $app/stores → $app/state; the store mock below now backs a $app/state page (NET-315)
vi.mock('$app/state', async () => (await import('../../../../tests/app-navigation.svelte')).stateFromStores(async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/threats/failed-lookups/x'), params: { ip: 'x' } });
	return { page: pageStore.value };
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const goTo = (query = '?range=24h') => pageStore.value.set({ url: new URL(`http://localhost/threats/failed-lookups/${IP}${query}`), params: { ip: IP } });

let calls: URL[] = [];
function stubDaemon(figures: FailedLookups | undefined, reason = 'Invalid IP address: x') {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			const body = url.pathname === '/api/network/lan' ? LAN_POLICY : url.pathname.startsWith('/api/threats/failed-lookups/') ? figures : undefined;
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 400, json: async () => ({ error: reason }) };
		}),
	);
}
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;

describe('Failed lookups page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo();
	});

	it('shows loading, not zeros, before the first answer', () => {
		goTo();
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(kpi('Failed')).toHaveTextContent('—');
	});

	it('shows the figures and explains them from what was read', async () => {
		goTo();
		stubDaemon(FAILED_LOOKUPS);
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Failed')).toHaveTextContent('410'));
		const call = calls.find((u) => u.pathname.startsWith('/api/threats/failed-lookups/'))!;
		expect(call.pathname).toBe('/api/threats/failed-lookups/192.168.1.80');
		expect(call.searchParams.get('interval')).toBe('5m');
		expect(screen.getByRole('heading', { level: 1, name: 'Failed lookups from 192.168.1.80' })).toBeInTheDocument();
		expect(kpi('Lookups')).toHaveTextContent('640');
		expect(kpi('Share failed')).toHaveTextContent('64%');
		expect(kpi('Names that failed')).toHaveTextContent('4');
		const why = card('Why NetTap lists this device');
		expect(why).toHaveTextContent('192.168.1.80 made 640 lookups in the last 24 hours; 410 of them (64%) came back as “no such name”');
		expect(why).toHaveTextContent('All 4 names that failed were read. The busiest, lb._dns-sd._udp.0.1.168.192.in-addr.arpa, was 300 of the 410 failures.');
		expect(why).toHaveTextContent('Service discovery: devices asking the network for printers');
		expect(why).toHaveTextContent('1 of the names that failed looks generated.');
		expect(within(why).getByText('What to do').closest('.todo')).toHaveTextContent('check the device for malware');
		expect(within(card('Response codes')).getByText('NXDOMAIN')).toBeInTheDocument();
		expectNoNestedInteractive(container);
	});

	it('links host names to the domain page in finding mode over the same window, sortably', async () => {
		goTo();
		// Zeek logs whatever was asked, so a failed "name" can be no host name at all
		stubDaemon({ ...FAILED_LOOKUPS, failed_names: [...FAILED_LOOKUPS.failed_names, { name: 'not a name', lookups: 1, last_seen: null, kind: 'other' }], failed_names_read: 5 });
		render(Page);
		const table = await vi.waitFor(() => screen.getByRole('table', { name: 'Names that failed' }));
		const link = within(table).getByRole('link', { name: 'wpad.lan' });
		const href = new URL(link.getAttribute('href')!, 'http://x');
		expect(href.pathname).toBe('/domain/wpad.lan');
		expect(Object.fromEntries(href.searchParams)).toEqual({ from: FAILED_LOOKUPS.from, to: FAILED_LOOKUPS.to, range: '24h', finding: 'wpad.lan' });
		// a service-discovery name is a host name (labels may start with "_"); "not a name" stays plain text
		expect(within(table).getByRole('link', { name: 'lb._dns-sd._udp.0.1.168.192.in-addr.arpa' })).toBeInTheDocument();
		expect(within(table).queryByRole('link', { name: 'not a name' })).not.toBeInTheDocument();
		expect(within(table).getByText('not a name')).toBeInTheDocument();
		expect(card('Names that failed')).toHaveTextContent('All 5 names, by failed lookups');
		const lookups = within(table).getByRole('columnheader', { name: /Failed lookups/ });
		expect(lookups).toHaveAttribute('aria-sort', 'descending');
		await fireEvent.click(within(lookups).getByRole('button'));
		expect(lookups).toHaveAttribute('aria-sort', 'ascending');
		expect(within(table).getAllByRole('row')[1]).toHaveTextContent('not a name');
	});

	it('says a capped read covers only the names read, in name order', async () => {
		goTo();
		stubDaemon({ ...FAILED_LOOKUPS, failed_names_complete: false, failed_names_read: 5000 });
		render(Page);
		await vi.waitFor(() => expect(kpi('Names that failed')).toHaveTextContent('at least 5,000'));
		const names = card('Names that failed');
		expect(names).toHaveTextContent('The 4 busiest of the first 5,000 names read, in name order');
		expect(names).toHaveTextContent('A busier name may be missing.');
		expect(card('Why NetTap lists this device')).not.toHaveTextContent('Service discovery');
		stubDaemon({ ...FAILED_LOOKUPS, failed_names_read: 140 });
		goTo('?range=6h');
		await vi.waitFor(() => expect(card('Names that failed')).toHaveTextContent('The 4 busiest of the 140 names'));
	});

	it('shows an empty window and a failure for what they are', async () => {
		goTo();
		stubDaemon(FAILED_LOOKUPS_EMPTY);
		render(Page);
		await vi.waitFor(() => expect(kpi('Lookups')).toHaveTextContent('0'));
		expect(within(card('Lookups over time')).getByText('No lookups from 192.168.1.80 in the last 24 hours')).toBeInTheDocument();
		expect(within(card('Names that failed')).getByText('No failed lookups from 192.168.1.80 in the last 24 hours')).toBeInTheDocument();
		// no lookups: an empty state, not "All 0 names that failed were read."
		const why = card('Why NetTap lists this device');
		expect(within(why).getByText('No lookups from 192.168.1.80 in the last 24 hours')).toBeInTheDocument();
		expect(why).not.toHaveTextContent('names that failed were read');
		expect(within(why).queryByText('What to do')).not.toBeInTheDocument();
		vi.unstubAllGlobals();
		stubDaemon(undefined);
		goTo('?range=7d');
		await vi.waitFor(() => expect(screen.getAllByText('Invalid IP address: x').length).toBeGreaterThan(0));
	});

	it("says when the page's window doesn't meet the check's rule", async () => {
		goTo();
		stubDaemon({ ...FAILED_LOOKUPS, lookups: 40, failed: 30, timeline: [], meets_rule: false });
		render(Page);
		await vi.waitFor(() => expect(card('Why NetTap lists this device')).toHaveTextContent("In this window that isn't met, so the check wouldn't list this device for it."));
	});

	it('says when the device is excluded in Settings', async () => {
		goTo();
		stubDaemon({ ...FAILED_LOOKUPS, excluded: true });
		render(Page);
		await vi.waitFor(() => expect(screen.getByText(/This device is excluded in Settings/)).toBeInTheDocument());
	});
});
