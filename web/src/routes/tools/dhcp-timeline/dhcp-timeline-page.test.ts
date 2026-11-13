import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { goto } from '$app/navigation';
import type { DhcpTimeline } from '$lib/api/dhcp-timeline';
import { LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import { DHCP_MAC, DHCP_TIMELINE, DHCP_TIMELINE_EMPTY } from '../../../../e2e/visual/fixtures/dhcp';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

// NET-263: one device's DHCP transactions, by ?mac= over the range pills

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/tools/dhcp-timeline'), params: {} });
	return { page: pageStore.value };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const { default: Page } = await import('./+page.svelte');

const REGISTRY = {
	total: 1,
	devices: [{ mac: DHCP_MAC.toUpperCase(), ips: ['192.168.1.138'], hostnames: [], display_name: 'Office AP', manufacturer: null, friendly_name: null, category: 'infrastructure', first_seen: '', last_seen: '', is_new: false }],
};

let calls: URL[] = [];
/** The daemon: the LAN policy, the registry, and the timeline (or an error with its reason). */
function stubDaemon(timeline: DhcpTimeline | Promise<never> | undefined, opts: { registry?: boolean; error?: string } = {}) {
	calls = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			if (url.pathname === '/api/network/lan') return { ok: true, status: 200, json: async () => LAN_POLICY };
			if (url.pathname === '/api/devices/registry') return opts.registry === false ? { ok: false, status: 500, json: async () => ({}) } : { ok: true, status: 200, json: async () => REGISTRY };
			if (timeline instanceof Promise) return timeline;
			if (url.pathname === '/api/dhcp/timeline' && timeline) return { ok: true, status: 200, json: async () => timeline };
			return { ok: false, status: 400, json: async () => ({ error: opts.error ?? 'Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff.' }) };
		}),
	);
}

const goTo = (query = '') => pageStore.value.set({ url: new URL(`http://localhost/tools/dhcp-timeline${query}`), params: {} });
const timelineCall = () => calls.find((u) => u.pathname === '/api/dhcp/timeline');
const table = () => screen.getByRole('table', { name: /DHCP transactions for/ });

describe('DHCP lease timeline page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.mocked(goto).mockClear();
		goTo();
	});

	it('asks for a device first, and reads nothing without one', async () => {
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'DHCP lease timeline' })).toBeInTheDocument();
		expect(await screen.findByRole('heading', { name: 'Pick a device' })).toBeInTheDocument();
		expect(timelineCall()).toBeUndefined();
	});

	it('shows loading, not an empty list, before the answer', () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(new Promise(() => {}) as Promise<never>);
		render(Page);
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
		expect(screen.queryByRole('table')).not.toBeInTheDocument();
	});

	it('lists the transactions over the URL window, named from the registry, each with its line', async () => {
		goTo(`?mac=${DHCP_MAC}&range=7d`);
		stubDaemon(DHCP_TIMELINE);
		const { container } = render(Page);
		expect(await screen.findByRole('heading', { name: 'Office AP' })).toBeInTheDocument();
		const sent = timelineCall()!;
		expect(sent.searchParams.get('mac')).toBe(DHCP_MAC);
		expect((Date.parse(sent.searchParams.get('to')!) - Date.parse(sent.searchParams.get('from')!)) / 3_600_000).toBe(168);
		expect(within(table()).getAllByRole('row')).toHaveLength(DHCP_TIMELINE.transactions.length + 1);
		expect(screen.getByText('ACK observed from 192.168.1.1 for 192.168.1.138. OFFER also observed.')).toBeInTheDocument();
		expect(screen.getByText('NAK observed from 192.168.1.1 for 192.168.1.139. Server message: “lease not found”.')).toBeInTheDocument();
		expect(screen.getByText('ACK, DISCOVER, OFFER, REQUEST')).toBeInTheDocument();
		// Zeek's server is shown as what it recorded only when it isn't the one endpoint
		expect(screen.queryByText('Zeek recorded 192.168.1.1')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
		expectNoNestedInteractive(container);
	});

	it('links the packets where two servers took part, and names neither as the sender', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		expect(await screen.findByText('NAK observed. Server endpoints in this transaction: 192.168.1.1 and 192.168.1.5.')).toBeInTheDocument();
		const links = screen.getAllByRole('link', { name: 'See the captured packets' });
		expect(links).toHaveLength(2); // two endpoints, and a connection not recorded yet
		const q = new URL(links[0].getAttribute('href')!, 'http://x').searchParams;
		expect(q.get('filter')).toBe(`dhcp && dhcp.hw.mac_addr == ${DHCP_MAC}`);
	});

	it('says why a device can have no DHCP messages', async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon(DHCP_TIMELINE_EMPTY);
		render(Page);
		expect(await screen.findByRole('heading', { name: /^No DHCP messages from this device in the last/ })).toBeInTheDocument();
		expect(screen.getByText(/only reaches NetTap if it crosses the mirrored link\. Phones with a private Wi-Fi address/)).toBeInTheDocument();
		expect(screen.queryByRole('table')).not.toBeInTheDocument();
	});

	it("says when only the newest 200 are shown", async () => {
		goTo(`?mac=${DHCP_MAC}`);
		stubDaemon({ ...DHCP_TIMELINE, truncated: true });
		render(Page);
		expect(await screen.findByText(/Showing the newest 200 transactions\./)).toBeInTheDocument();
	});

	it("shows the daemon's reason and a retry on an error", async () => {
		goTo('?mac=nonsense');
		stubDaemon(undefined);
		render(Page);
		expect(await screen.findByRole('heading', { name: "Couldn't load the DHCP history: the request failed." })).toBeInTheDocument();
		expect(screen.getByText('Enter a six-byte MAC address, such as aa:bb:cc:dd:ee:ff.')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
	});

	it("picks a device by name from the suggestions' list, keeping the range", async () => {
		goTo('?range=6h');
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		await vi.waitFor(() => expect(calls.some((u) => u.pathname === '/api/devices/registry')).toBe(true));
		const field = screen.getByLabelText('Device');
		await vi.waitFor(() => expect(document.querySelector('#dhcp-devices option')).toHaveAttribute('value', DHCP_MAC));
		await fireEvent.input(field, { target: { value: 'office ap' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Show history' }));
		expect(goto).toHaveBeenCalledWith(`/tools/dhcp-timeline?mac=${encodeURIComponent(DHCP_MAC)}&range=6h`, expect.anything());
	});

	it('still takes a typed MAC when the device list fails, and says so', async () => {
		stubDaemon(DHCP_TIMELINE, { registry: false });
		render(Page);
		expect(await screen.findByText(/Couldn't load your devices for suggestions/)).toBeInTheDocument();
		await fireEvent.input(screen.getByLabelText('Device'), { target: { value: 'AA-BB-CC-DD-EE-FF' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Show history' }));
		expect(goto).toHaveBeenCalledWith('/tools/dhcp-timeline?mac=AA-BB-CC-DD-EE-FF&range=24h', expect.anything());
	});

	it('a range pill keeps the device and drops a link’s exact window', async () => {
		goTo(`?mac=${DHCP_MAC}&from=2026-11-12T00:00:00.000Z&to=2026-11-12T06:00:00.000Z`);
		stubDaemon(DHCP_TIMELINE);
		render(Page);
		await screen.findByRole('heading', { name: 'Office AP' });
		expect(timelineCall()!.searchParams.get('from')).toBe('2026-11-12T00:00:00.000Z');
		await fireEvent.click(screen.getByRole('button', { name: '7d' }));
		expect(goto).toHaveBeenCalledWith(`/tools/dhcp-timeline?mac=${encodeURIComponent(DHCP_MAC)}&range=7d`, expect.anything());
	});
});
