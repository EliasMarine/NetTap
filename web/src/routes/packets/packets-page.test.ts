import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import type { writable } from 'svelte/store';
import Page from './+page.svelte';
import * as api from '$lib/api/packets';
import { epochNs, readUrlState } from '$lib/utils/packet-query';
import { LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import { CAPTURES, CAPTURES_EMPTY, FIELDS, TV } from '../../../e2e/visual/fixtures/packets';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-188: the first visit. Packet analysis reads its search from the URL; with none it starts
// from a question, and shows the capture files and what a search would read.

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/packets') });
	return { page: pageStore.value };
});
const goto = vi.hoisted(() => vi.fn());
// OLD CODE: vi.mock('$app/navigation', () => ({ goto })); (NET-276: the page loads from afterNavigate)
// SvelteKit runs afterNavigate once the page mounts; a test render is a full load. This stand-in never
// fires again, so a URL change after mount loads nothing here: use packets-results.test.ts's router for that
vi.mock('$app/navigation', async () => {
	const { onMount } = await import('svelte');
	return { goto, afterNavigate: (callback: (nav: { type: 'enter' }) => void) => onMount(() => callback({ type: 'enter' })) };
});
vi.mock('$lib/api/packets', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/packets')>()),
	getCaptures: vi.fn(),
	searchPackets: vi.fn(),
	getPacket: vi.fn(),
	checkFilter: vi.fn(),
	suggestFields: vi.fn(),
}));

const REGISTRY = {
	devices: [{ mac: '02:00:5e:10:00:22', display_name: 'Living-room TV', manufacturer: 'Example', ips: [TV], last_seen: '2026-11-05T00:00:00Z' }],
	total: 1,
};

/** The page's other reads; a path set to null fails with 503. */
function stubOthers(replies: Record<string, unknown> = {}): void {
	const all: Record<string, unknown> = {
		'/api/capture/status': { enabled: true, maxFileSizeMB: 256, rotateMinutes: 10, containerRunning: true, containerStatus: 'running' },
		'/api/tshark/status': { available: true, version: 'TShark (Wireshark) 4.0.17 (Git v4.0.17)', container_running: true, container_name: 'nettap-tshark' },
		'/api/devices/registry': REGISTRY,
		'/api/network/lan': LAN_POLICY,
		...replies,
	};
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = all[String(url).split('?')[0]];
			return body
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({ error: 'Unavailable in this test.' }) };
		}),
	);
}

const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const builder = () => screen.getByRole('heading', { name: 'What do you want to see?' }).closest('.card') as HTMLElement;

describe('Packet analysis: first visit', () => {
	beforeEach(() => {
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES);
		stubOthers();
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
		pageStore.value.set({ url: new URL('http://localhost/packets') });
	});

	it('has one page title and shows the capture files, capture state and reader', async () => {
		const { container } = render(Page);
		expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
		expect(screen.getByRole('heading', { level: 1, name: 'Packet analysis' })).toBeInTheDocument();
		await vi.waitFor(() => expect(kpi('Capture files')).toHaveTextContent('5'));
		expect(kpi('Capture files')).toHaveTextContent('1.2 GB on disk');
		expect(kpi('Packets kept')).toHaveTextContent('still being indexed');
		await vi.waitFor(() => expect(kpi('Capture')).toHaveTextContent('On'));
		await vi.waitFor(() => expect(kpi('Packet reader')).toHaveTextContent('TShark 4.0.17'));
		expect(kpi('Packet reader')).toHaveTextContent('Reads up to 1,000 packets per search');
		expect(api.searchPackets).not.toHaveBeenCalled();
		expectNoNestedInteractive(container);
	});

	it('lists every capture file, the one being written and the ones not yet indexed', async () => {
		render(Page);
		const table = await screen.findByRole('table', { name: 'Capture files' });
		const rows = within(table).getAllByRole('row').slice(1);
		expect(rows).toHaveLength(5);
		const live = rows.find((r) => r.textContent?.includes('mnetsniff-enp4s0_live.pcap'))!;
		// Newest first: the file being written has no first packet yet, but it is the newest
		expect(rows[0]).toBe(live);
		expect(live).toHaveTextContent('Indexing…');
		expect(live).toHaveTextContent('Being written');
		// No time span to search until the file is indexed, but it can still be downloaded
		expect(within(live).queryByRole('link', { name: "Search this file's time span" })).not.toBeInTheDocument();
		expect(within(live).getByRole('link', { name: 'Download' })).toHaveAttribute('href', api.captureFileUrl('mnetsniff-enp4s0_live.pcap'));

		const indexed = rows.find((r) => r.textContent?.includes('mnetsniff-enp4s0_2.pcap'))!;
		const file = CAPTURES.files.find((f) => f.id === 'mnetsniff-enp4s0_2.pcap')!;
		const href = within(indexed).getByRole('link', { name: "Search this file's time span" }).getAttribute('href')!;
		const state = readUrlState(new URL(href, 'http://localhost').searchParams)!;
		// Compared as exact times: the URL drops trailing zeros (…828.660 is …828.66)
		expect(epochNs(state.from)).toBe(epochNs(file.first!));
		expect(BigInt(state.to.replace('.', '')) > 0n).toBe(true);
	});

	it("says a file longer than one search is searched for its first 30 minutes", async () => {
		const long = { ...CAPTURES.files[1], id: 'long.pcap', name: 'long.pcap', first: '1794000000', last: '1794003600' };
		vi.mocked(api.getCaptures).mockResolvedValue({ ...CAPTURES, files: [long], count: 1 });
		render(Page);
		const table = await screen.findByRole('table', { name: 'Capture files' });
		const href = within(table).getByRole('link', { name: "Search this file's first 30 minutes" }).getAttribute('href')!;
		const state = readUrlState(new URL(href, 'http://localhost').searchParams)!;
		expect([state.from, state.to]).toEqual(['1794000000', '1794001800']);
		expect(within(table).queryByRole('link', { name: "Search this file's time span" })).not.toBeInTheDocument();
	});

	it('sorts the file being written as the newest by its last packet too', async () => {
		render(Page);
		const table = await screen.findByRole('table', { name: 'Capture files' });
		const header = within(table).getByRole('button', { name: /Last packet/ });
		const live = () => within(table).getAllByRole('row').slice(1).findIndex((r) => r.textContent?.includes('mnetsniff-enp4s0_live.pcap'));
		for (let i = 0; i < 2; i++) {
			await fireEvent.click(header);
			const dir = header.closest('th')!.getAttribute('aria-sort');
			// '~' as text sorted before digits, so this file landed at the wrong end
			expect(live()).toBe(dir === 'descending' ? 0 : 4);
		}
	});

	it('shows loading, not zeros, while the capture index loads', () => {
		vi.mocked(api.getCaptures).mockReturnValue(new Promise(() => {}));
		render(Page);
		expect(kpi('Capture files')).toHaveTextContent('…');
		expect(screen.getByRole('status', { name: '' , busy: true })).toBeInTheDocument();
	});

	it("says the capture index failed with the daemon's reason, never zero files", async () => {
		vi.mocked(api.getCaptures).mockRejectedValue(new api.PacketApiError('The capture index is unreadable.', 500));
		render(Page);
		await screen.findByText('The capture index is unreadable.');
		expect(screen.getByText("Couldn't load the capture files: the request failed.")).toBeInTheDocument();
		expect(kpi('Capture files')).toHaveTextContent('—');
		expect(screen.queryByText('No capture files yet')).not.toBeInTheDocument();
	});

	it('says there are no capture files only when the index loaded empty', async () => {
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES_EMPTY);
		render(Page);
		await screen.findByText('No capture files yet');
		expect(kpi('Capture files')).toHaveTextContent('0');
	});

	it('writes the filter from the choices and shows the files it will read before searching', async () => {
		render(Page);
		// Only the indexed file that overlaps the last 15 minutes is counted; the one being written is "up to"
		await vi.waitFor(() =>
			expect(within(builder()).getByText(/NetTap will read/)).toHaveTextContent(
				/NetTap will read 1 capture file \(.*, 268.4 MB\) and up to 1 more not indexed yet, if it holds packets from this window, with no filter/,
			),
		);
		expect(within(builder()).getByText(/with no filter, so every packet/)).toBeInTheDocument();

		await fireEvent.click(within(builder()).getByRole('button', { name: 'Name lookups' }));
		expect(within(builder()).getByRole('button', { name: 'Name lookups' })).toHaveAttribute('aria-pressed', 'true');
		expect(within(builder()).getByRole('button', { name: 'All traffic' })).toHaveAttribute('aria-pressed', 'false');
		expect(builder().querySelector('code.filter')).toHaveTextContent('dns && dns.flags.response == 0');

		await vi.waitFor(() => expect(within(builder()).getByRole('option', { name: `Living-room TV · ${TV}` })).toBeInTheDocument());
		await fireEvent.change(within(builder()).getByLabelText('Device'), { target: { value: TV } });
		expect(builder().querySelector('code.filter')).toHaveTextContent(`ip.addr == ${TV} && dns && dns.flags.response == 0`);

		await fireEvent.click(within(builder()).getByRole('button', { name: 'Find packets' }));
		expect(goto).toHaveBeenCalledTimes(1);
		const state = readUrlState(new URL(goto.mock.calls[0][0], 'http://localhost').searchParams)!;
		expect(state).toMatchObject({ filter: `ip.addr == ${TV} && dns && dns.flags.response == 0`, limit: 100, device: TV, conn: null });
		expect(Number(state.to) - Number(state.from)).toBe(900);
	});

	it("explains a choice it can't write instead of searching", async () => {
		render(Page);
		await fireEvent.change(within(builder()).getByLabelText('Port'), { target: { value: '99999' } });
		await fireEvent.input(within(builder()).getByLabelText('Port'), { target: { value: '99999' } });
		expect(within(builder()).getByText('A port is a whole number from 1 to 65535.')).toBeInTheDocument();
		await fireEvent.click(within(builder()).getByRole('button', { name: 'Find packets' }));
		expect(goto).not.toHaveBeenCalled();
	});

	it('refuses a time range over 30 minutes', async () => {
		render(Page);
		await fireEvent.click(within(builder()).getByRole('button', { name: 'From… to…' }));
		expect(within(builder()).getByText('At most 30 minutes, the longest stretch one search reads')).toBeInTheDocument();
		await fireEvent.input(within(builder()).getByLabelText('from'), { target: { value: '2026-11-06T10:00:00' } });
		await fireEvent.change(within(builder()).getByLabelText('from'));
		await fireEvent.input(within(builder()).getByLabelText('to'), { target: { value: '2026-11-06T11:00:00' } });
		await fireEvent.change(within(builder()).getByLabelText('to'));
		expect(within(builder()).getByText('A search covers at most 30 minutes. Pick a shorter stretch.')).toBeInTheDocument();
	});

	it('puts a library filter or a common question into the builder', async () => {
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Use Lookups that failed' }));
		expect(builder().querySelector('code.filter')).toHaveTextContent('dns.flags.rcode != 0');
		expect(within(builder()).getByRole('button', { name: 'Remove Lookups that failed' })).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: /Which sites did a device open/ }));
		expect(builder().querySelector('code.filter')).toHaveTextContent('tls.handshake.type == 1');
	});

	it('says a site name matches exactly', async () => {
		render(Page);
		await fireEvent.change(within(builder()).getByLabelText('Other side'), { target: { value: 'address' } });
		expect(within(builder()).getByLabelText('Address or site')).toHaveAccessibleDescription('A site name matches exactly; www.example.com is a different name');
	});

	it('never runs a library filter with its example value', async () => {
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Use Lookups that skip your router' }));
		expect(within(builder()).getByText(/Enter your router's address/)).toBeInTheDocument();
		expect(builder().querySelector('code.filter')).toBeNull();
		await fireEvent.click(within(builder()).getByRole('button', { name: 'Find packets' }));
		expect(goto).not.toHaveBeenCalled();

		await fireEvent.input(within(builder()).getByLabelText("Your router's address"), { target: { value: '10.0.0.1' } });
		expect(builder().querySelector('code.filter')).toHaveTextContent('dns && !(ip.addr == 10.0.0.1)');
		await fireEvent.click(within(builder()).getByRole('button', { name: 'Find packets' }));
		expect(readUrlState(new URL(goto.mock.calls[0][0], 'http://localhost').searchParams)!.filter).toBe('dns && !(ip.addr == 10.0.0.1)');

		// A stream number only means something inside one search, so it comes from a packet's drawer
		const library = screen.getByRole('heading', { name: 'Filter library' }).closest('section') as HTMLElement;
		expect(within(library).queryByRole('button', { name: 'Use One conversation' })).not.toBeInTheDocument();
		expect(within(library).getByText('Open a packet, then choose Show its whole conversation')).toBeInTheDocument();
		// The library shows a slot for the router, not an address that could be run
		const router = within(library).getByText('Lookups that skip your router').closest('li') as HTMLElement;
		expect(router.querySelector('code')).toHaveTextContent('dns && !(ip.addr == router address)');
		expect(router).not.toHaveTextContent('192.168.1.1');
	});

	it('finds library filters by words and by group', async () => {
		render(Page);
		const library = screen.getByRole('heading', { name: 'Filter library' }).closest('section') as HTMLElement;
		// 37 filters; "One conversation" is offered from a packet instead
		expect(within(library).getAllByRole('button', { name: /^Use / })).toHaveLength(36);
		await fireEvent.click(within(library).getByRole('button', { name: 'Logins and remote access 5' }));
		expect(within(library).getAllByRole('button', { name: /^Use / })).toHaveLength(5);
		await fireEvent.click(within(library).getByRole('button', { name: 'All 37' }));
		await fireEvent.input(within(library).getByRole('searchbox', { name: 'Search the library' }), { target: { value: 'wireguard' } });
		expect(within(library).getAllByRole('button', { name: /^Use / }).map((b) => b.getAttribute('aria-label'))).toEqual(['Use VPN tunnels']);
	});

	it('lets you write your own filter, with field suggestions and a check once typing pauses', async () => {
		vi.mocked(api.suggestFields).mockResolvedValue(FIELDS);
		vi.mocked(api.checkFilter).mockRejectedValue(new api.PacketApiError('"tls.handshake.extensions_s" is neither a field nor a protocol name.', 400));
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Write my own filter' }));
		const input = screen.getByRole('combobox', { name: 'Display filter' });
		await fireEvent.input(input, { target: { value: 'tls.handshake.extensions_s' } });

		await screen.findByRole('option', { name: /tls\.handshake\.extensions_server_name Server Name/ }, { timeout: 2000 });
		expect(api.suggestFields).toHaveBeenCalledWith('tls.handshake.extensions_s', expect.any(AbortSignal));
		await screen.findByText('"tls.handshake.extensions_s" is neither a field nor a protocol name.', {}, { timeout: 2000 });
		expect(input).toHaveAttribute('aria-invalid', 'true');

		await fireEvent.keyDown(input, { key: 'Enter' });
		expect(input).toHaveValue('tls.handshake.extensions_server_name');
		// The builder now uses the written filter
		expect(builder().querySelector('code.filter')).toHaveTextContent('tls.handshake.extensions_server_name');
	});

	it('aborts a suggestion request when the word changes', async () => {
		const signals: AbortSignal[] = [];
		vi.mocked(api.suggestFields).mockImplementation((_prefix, signal) => {
			signals.push(signal!);
			return new Promise(() => {});
		});
		vi.mocked(api.checkFilter).mockResolvedValue({ ok: true, filter: '' });
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Write my own filter' }));
		const input = screen.getByRole('combobox', { name: 'Display filter' });
		await fireEvent.input(input, { target: { value: 'dns.q' } });
		await vi.waitFor(() => expect(signals).toHaveLength(1), { timeout: 2000 });
		await fireEvent.input(input, { target: { value: 'dns.qr' } });
		expect(signals[0].aborted).toBe(true);
	});

	it("says when a link's search can't be read, and searches nothing", async () => {
		pageStore.value.set({ url: new URL('http://localhost/packets?filter=tcp&from=x&to=1&limit=250') });
		render(Page);
		expect(screen.getByText(/This link's search couldn't be read/)).toBeInTheDocument();
		expect(api.searchPackets).not.toHaveBeenCalled();
	});
});
