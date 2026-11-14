import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { writable } from 'svelte/store';
import type { NavigationType } from '@sveltejs/kit';
import Page from './+page.svelte';
import * as api from '$lib/api/packets';
import type { PacketSearchResult } from '$lib/api/packets';
import { refreshPage } from '$lib/stores/pageRefresh';
import { packetsUrl, readUrlState } from '$lib/utils/packet-query';
import { packetStats } from '$lib/utils/packet-stats';
import { LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import { CAPTURES, CDN_NAME, FIELDS, PACKET_DETAIL, ROWS, SEARCH_FROM, SEARCH_QUERY, SEARCH_RESULT, SEARCH_TO, TV } from '../../../e2e/visual/fixtures/packets';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';
import { clockTime } from './packets-view';

// NET-188: a search's answer. Every figure is counted over the rows returned and says so; a
// partial, failed or changed read is never shown as complete.

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/packets') });
	return { page: pageStore.value };
});
// OLD CODE: vi.mock('$app/navigation', () => ({ goto: vi.fn() })); (NET-276: the page loads from afterNavigate)
// A stand-in for SvelteKit's router: afterNavigate callbacks register on mount and run once for the arrival
// (`router.arrival`), then after each navigate(), which moves the page first, as the router does
const router = vi.hoisted(() => ({ arrival: 'link' as NavigationType, callbacks: new Set<(nav: { type: NavigationType }) => void>() }));
vi.mock('$app/navigation', async () => {
	const { onMount } = await import('svelte');
	return {
		goto: vi.fn((href: string) => navigate('goto', href)),
		afterNavigate: (callback: (nav: { type: NavigationType }) => void) =>
			onMount(() => {
				router.callbacks.add(callback);
				callback({ type: router.arrival });
				return () => router.callbacks.delete(callback);
			}),
	};
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

function stubOthers(): void {
	const all: Record<string, unknown> = { '/api/devices/registry': REGISTRY, '/api/network/lan': LAN_POLICY };
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const body = all[String(url).split('?')[0]];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 503, json: async () => ({}) };
		}),
	);
}

const open = (query = SEARCH_QUERY) => pageStore.value.set({ url: new URL(`http://localhost/packets?${query}`) });
/** An in-app navigation: the page moves, then the afterNavigate callbacks run. */
async function navigate(type: NavigationType, href: string): Promise<void> {
	pageStore.value.set({ url: new URL(href, 'http://localhost') });
	await tick();
	for (const callback of [...router.callbacks]) callback({ type });
}
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const result = (over: Partial<PacketSearchResult>): PacketSearchResult => ({ ...SEARCH_RESULT, ...over });

describe('Packet analysis: a search', () => {
	beforeEach(() => {
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES);
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_RESULT);
		stubOthers();
		open();
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
		pageStore.value.set({ url: new URL('http://localhost/packets') });
	});

	it('searches exactly what the URL holds and shows that it is working', async () => {
		vi.mocked(api.searchPackets).mockReturnValue(new Promise(() => {}));
		render(Page);
		expect(api.searchPackets).toHaveBeenCalledWith({ filter: SEARCH_RESULT.filter, from: SEARCH_RESULT.window.requested.from, to: SEARCH_RESULT.window.requested.to, limit: 250 });
		expect(screen.getByText(/Searching… 0 s so far\. A search reads every packet/)).toBeInTheDocument();
		expect(screen.queryByText('Packets', { selector: '.kpi-top span' })).not.toBeInTheDocument();
	});

	it('counts the packets shown and says "All of them" only for a complete read', async () => {
		const { container } = render(Page);
		await vi.waitFor(() => expect(kpi('Packets')).toHaveTextContent('9'));
		expect(kpi('Packets')).toHaveTextContent('All of them');
		expect(kpi('Packets')).toHaveTextContent('5 from Living-room TV · 4 to it');
		expect(kpi('Data')).toHaveTextContent(/sent by Living-room TV/);
		expect(kpi('TShark noticed')).toHaveTextContent('1');
		expect(kpi('Lasted')).toHaveTextContent('34.0');
		expect(screen.getByText(/Read/).closest('.line')).toHaveTextContent('1 capture file');
		expectNoNestedInteractive(container);
	});

	it.each([
		['a provisional complete read', { complete: true, provisional: true }, 'All saved so far'],
		['the row limit', { complete: false, termination: 'limit' as const }, 'First 9'],
		['the deadline', { complete: false, termination: 'deadline' as const, message: 'The search stopped after 40 s. These are the matches it returned before stopping; more may exist in this window.' }, 'Search stopped early'],
	])('never calls %s complete', async (_, over, chip) => {
		vi.mocked(api.searchPackets).mockResolvedValue(result(over));
		render(Page);
		await vi.waitFor(() => expect(kpi('Packets')).toHaveTextContent(chip));
		expect(kpi('Packets')).not.toHaveTextContent('All of them');
		if ('message' in over) expect(screen.getByText(over.message!)).toBeInTheDocument();
	});

	it('names files it could not read and calls the read incomplete', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(
			result({ complete: false, skipped_files: [{ id: 'broken.pcap', error: 'cut short in the middle of a packet', modified: '' }] }),
		);
		render(Page);
		await screen.findByText(/cut short in the middle of a packet/);
		expect(kpi('Packets')).toHaveTextContent('Some files not read');
	});

	it('says a deadline with no match found nothing yet, not that nothing matches', async () => {
		const message = 'The search stopped after 40 s before finding a match; matches may still exist in this window.';
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [], complete: false, termination: 'deadline', message }));
		render(Page);
		await screen.findByText('No match found before the search stopped');
		expect(screen.getAllByText(message).length).toBeGreaterThan(0);
		expect(screen.queryByText('No packets match')).not.toBeInTheDocument();
	});

	it('says nothing matches only after a complete read', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [] }));
		render(Page);
		await screen.findByText('No packets match');
		// What was searched, word for word, so a miss never reads as "no traffic"
		expect(screen.getByText(`No packet in this window matches ${SEARCH_RESULT.filter}. Try a longer stretch of time or a wider filter.`)).toBeInTheDocument();
	});

	it('says a site name has to match exactly when a site search finds nothing', async () => {
		const filter = 'tls.handshake.extensions_server_name == "example.com" || dns.qry.name == "example.com" || http.host == "example.com"';
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [], filter }));
		render(Page);
		expect(await screen.findByText(/www\.example\.com is a different name from example\.com/)).toHaveTextContent(filter);
	});

	it('offers to run the search again when the captures changed (409)', async () => {
		vi.mocked(api.searchPackets).mockRejectedValueOnce(new api.PacketApiError('The capture files behind this search have changed (old captures are deleted to free space). Run the search again.', 409));
		render(Page);
		await screen.findByText('The capture files behind this search have changed');
		await fireEvent.click(screen.getByRole('button', { name: 'Run the search again' }));
		await vi.waitFor(() => expect(kpi('Packets')).toHaveTextContent('All of them'));
		expect(api.searchPackets).toHaveBeenCalledTimes(2);
	});

	it.each([
		[503, 'NetTap is still indexing capture files (12 left).', 'NetTap is still indexing capture files'],
		[503, 'The packet reader is busy; try again in a moment.', 'The packet reader is busy'],
		[507, 'TShark ran out of memory reading this window.', 'The search ran out of memory'],
		[502, 'TShark failed: mergecap exited 2.', "Couldn't search the saved captures"],
	])("shows a %s with the daemon's own reason", async (status, message, title) => {
		vi.mocked(api.searchPackets).mockRejectedValue(new api.PacketApiError(message, status));
		render(Page);
		await screen.findByText(title);
		expect(screen.getByText(message, { exact: false })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
	});

	it('lists the packets with who sent them, by device name or the site the connection asked for', async () => {
		render(Page);
		const table = await screen.findByRole('table', { name: 'Packets' });
		const rows = within(table).getAllByRole('row').slice(1);
		expect(rows).toHaveLength(ROWS.length);
		// Names arrive with the device registry
		await vi.waitFor(() => expect(within(screen.getByRole('table', { name: 'Packets' })).getAllByRole('row')[1]).toHaveTextContent('Living-room TV'));
		expect(rows[0]).toHaveTextContent('start');
		expect(rows[1]).toHaveTextContent(CDN_NAME);
		expect(rows[1]).toHaveTextContent('+19 ms');
		expect(rows[3]).toHaveTextContent(`Client Hello (SNI=${CDN_NAME})`);
		// The plain-English line names the server by its site too, not only the Sent by column
		expect(rows[4]).toHaveTextContent(`${CDN_NAME} agreed`);
		expect(rows[4]).not.toHaveTextContent('203.0.113.45 agreed');
	});

	it('shows device-chosen text as text, never as markup', async () => {
		const hostile = '<img src=x onerror="window.hacked=1">';
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [{ ...ROWS[5], info: hostile, protocol: '<b>x</b>' }] }));
		const { container } = render(Page);
		await screen.findByText(hostile);
		expect(container.querySelector('img')).toBeNull();
	});

	it('filters the rows already shown by what TShark noticed', async () => {
		render(Page);
		await screen.findByRole('table', { name: 'Packets' });
		// The warning comes before the routine notes, which have their own "Show it"
		await fireEvent.click(screen.getAllByRole('button', { name: 'Show it' })[0]);
		const table = screen.getByRole('table', { name: 'Packets' });
		expect(within(table).getAllByRole('row')).toHaveLength(2);
		expect(screen.getByText(/Showing the 1 packet TShark marked/)).toBeInTheDocument();
		expect(api.searchPackets).toHaveBeenCalledTimes(1);
		await fireEvent.click(screen.getAllByRole('button', { name: 'Show all' })[0]);
		expect(within(screen.getByRole('table', { name: 'Packets' })).getAllByRole('row')).toHaveLength(ROWS.length + 1);
	});

	it('posts the manifest exactly as returned to download the packets', async () => {
		const { container } = render(Page);
		await screen.findByRole('table', { name: 'Packets' });
		const form = container.querySelector('form[action="/api/packets/download"]') as HTMLFormElement;
		expect(form.getAttribute('method')).toBe('POST');
		expect((form.querySelector('input[name="manifest"]') as HTMLInputElement).value).toBe(JSON.stringify(SEARCH_RESULT.manifest));
		expect(within(form).getByRole('button', { name: 'Download these 9 packets' })).toBeInTheDocument();
	});

	it('opens one packet: its layers, field names and bytes, marking only proven bytes', async () => {
		vi.mocked(api.getPacket).mockResolvedValue(PACKET_DETAIL);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Open packet 101' }));
		expect(api.getPacket).toHaveBeenCalledWith(SEARCH_RESULT.manifest, 101);
		const drawer = await screen.findByRole('complementary', { name: 'Packet 1 of 9' });
		await within(drawer).findByText('Destination Address: 203.0.113.45');
		expect(within(drawer).getByText('ip.dst · bytes 30 to 33')).toBeInTheDocument();
		expect(within(drawer).getByText("NetTap couldn't line up this layer's fields with the raw bytes, so they aren't marked here.")).toBeInTheDocument();
		// tcp's layer isn't markable, so its field is plain text
		expect(within(drawer).queryByRole('button', { name: /Source Port: 51834/ })).not.toBeInTheDocument();
		expect(drawer.querySelector('mark')).toBeNull();

		await fireEvent.click(within(drawer).getByRole('button', { name: /Destination Address/ }));
		// Bytes 30–33 straddle two rows of 16
		const marked = [...drawer.querySelectorAll('.hex .hexrun mark')].map((m) => m.textContent).join(' ');
		expect(marked).toBe('cb 00 71 2d');
		expect(within(drawer).getByRole('img', { name: /marked at bytes 30 to 33/ })).toBeInTheDocument();
		expect(within(drawer).getByRole('link', { name: 'Living-room TV' })).toHaveAttribute('href', `/devices/${TV}`);

		// Its whole TCP conversation: the stream number, over this same window
		const href = within(drawer).getByRole('link', { name: 'Show its whole conversation' }).getAttribute('href')!;
		expect(readUrlState(new URL(href, 'http://localhost').searchParams)).toEqual({
			filter: 'tcp.stream == 7', from: SEARCH_FROM, to: SEARCH_TO, limit: 1000, device: TV, conn: null,
		});
	});

	it('says so when no bytes can be marked for a packet', async () => {
		vi.mocked(api.getPacket).mockResolvedValue({ ...PACKET_DETAIL, marking: 'none' });
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Open packet 101' }));
		await screen.findByText(/No bytes are marked for this packet/);
	});

	it('offers a fresh search when the captures changed under an open packet', async () => {
		vi.mocked(api.getPacket).mockRejectedValue(new api.PacketApiError('The capture files behind this search have changed.', 409));
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Open packet 104' }));
		const drawer = await screen.findByRole('complementary', { name: 'Packet 4 of 9' });
		await fireEvent.click(await within(drawer).findByRole('button', { name: 'Run the search again' }));
		await vi.waitFor(() => expect(api.searchPackets).toHaveBeenCalledTimes(2));
	});

	it('runs the search again on Refresh', async () => {
		render(Page);
		await screen.findByRole('table', { name: 'Packets' });
		await refreshPage();
		expect(api.searchPackets).toHaveBeenCalledTimes(2);
	});

	it('keeps the open packet and the noticed filter through a refresh that brings new row objects', async () => {
		vi.mocked(api.getPacket).mockResolvedValue(PACKET_DETAIL);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Open packet 101' }));
		await screen.findByRole('complementary', { name: 'Packet 1 of 9' });
		// The first "Show it" is the problem TShark noticed (the resent packet)
		await fireEvent.click(screen.getAllByRole('button', { name: 'Show it' })[0]);
		expect(screen.getByText(/Showing the 1 packet TShark marked “This frame is a \(suspected\) retransmission”/)).toBeInTheDocument();

		vi.mocked(api.searchPackets).mockResolvedValue(structuredClone(SEARCH_RESULT));
		await refreshPage();
		expect(await screen.findByRole('complementary', { name: 'Packet 1 of 9' })).toBeInTheDocument();
		expect(screen.getByText(/Showing the 1 packet TShark marked “This frame is a \(suspected\) retransmission”/)).toBeInTheDocument();
	});

	it('closes the drawer when a refresh no longer holds the open packet', async () => {
		vi.mocked(api.getPacket).mockResolvedValue(PACKET_DETAIL);
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Open packet 101' }));
		await screen.findByRole('complementary', { name: 'Packet 1 of 9' });

		// Same frame number, different packet (old captures were deleted): matched by checksum too
		const moved = { ...ROWS[0], md5: 'f'.repeat(32) };
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [moved, ...ROWS.slice(1)] }));
		await refreshPage();
		await screen.findByRole('table', { name: 'Packets' });
		expect(screen.queryByRole('complementary', { name: /^Packet \d+ of/ })).not.toBeInTheDocument();
	});

	it('steps through a long connection opened from Connections, segment by segment', async () => {
		const base = { filter: SEARCH_RESULT.filter, from: '1794061926.412', to: '1794063726.412', limit: 1000 as const, device: TV };
		open(packetsUrl({ ...base, conn: { start: '1794061927.412', duration: 8040, segment: 0, exact: true } }).split('?')[1]);
		render(Page);
		expect(screen.getByText(/Opened from a connection on Connections/)).toBeInTheDocument();
		expect(screen.getByText(/Segment 1 of 5: minutes 0 to 30 of a 2 h 14 min connection/)).toBeInTheDocument();
		expect(screen.queryByRole('link', { name: /Previous segment/ })).not.toBeInTheDocument();
		const next = new URL(screen.getByRole('link', { name: /Next segment/ }).getAttribute('href')!, 'http://localhost');
		expect(next.searchParams.get('seg')).toBe('1');
		expect(next.searchParams.get('from')).toBe('1794063726.412');
		expect(next.searchParams.get('filter')).toBe(SEARCH_RESULT.filter);
		expect(screen.queryByText(/no exact connection/)).not.toBeInTheDocument();
	});

	it('says when a connection had no ports, so the search is all traffic between the two addresses', () => {
		const base = { filter: SEARCH_RESULT.filter, from: '1794061926.412', to: '1794061986.412', limit: 1000 as const, device: TV };
		open(packetsUrl({ ...base, conn: { start: '1794061927.412', duration: null, segment: 0, exact: false } }).split('?')[1]);
		render(Page);
		expect(screen.getByText(/all traffic between these two addresses \(no exact connection\)/)).toBeInTheDocument();
		expect(screen.getByText(/the first minute \(the connection's length isn't recorded\)/)).toBeInTheDocument();
	});
});

// NET-249 slice 2: a pick on "The conversation over time" shows exactly the packets in the picked
// buckets (the chart's own assignment), apart from the noticed filter, and both can apply at once
describe('Packet analysis: picking on the chart', () => {
	beforeEach(() => {
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES);
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_RESULT);
		stubOthers();
		open();
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
		pageStore.value.set({ url: new URL('http://localhost/packets') });
	});

	const timeline = packetStats(ROWS, TV).timeline;
	const tableRows = () => within(screen.getByRole('table', { name: 'Packets' })).getAllByRole('row').length - 1;
	async function chart() {
		render(Page);
		await screen.findByRole('table', { name: 'Packets' });
		return screen.getByRole('group', { name: /^Busiest at / });
	}

	it('a click on a bucket shows only its packets, and Show all brings every row back', async () => {
		const c = await chart();
		expect(screen.getByText('Click a point or drag across the chart to show only those packets.')).toBeInTheDocument();
		await fireEvent.keyDown(c, { key: 'Home' });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(tableRows()).toBe(timeline[0].packets);
		expect(screen.getByText(new RegExp(`^Showing the ${timeline[0].packets} packets? sent (at|from) `))).toBeInTheDocument();
		expect(api.searchPackets).toHaveBeenCalledTimes(1);
		await fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
		expect(tableRows()).toBe(ROWS.length);
	});

	it('the last bucket holds the last packet, and a range holds every bucket in it', async () => {
		const c = await chart();
		await fireEvent.keyDown(c, { key: 'End' });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(tableRows()).toBe(timeline.at(-1)!.packets);
		expect(timeline.at(-1)!.rows).toContain(ROWS.length - 1);
		await fireEvent.keyDown(c, { key: 'Home', shiftKey: true });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(tableRows()).toBe(ROWS.length);
	});

	it('combines with the noticed filter, and each clears on its own', async () => {
		const c = await chart();
		await fireEvent.click(screen.getAllByRole('button', { name: 'Show it' })[0]);
		const noted = tableRows();
		expect(noted).toBe(1);
		// the bucket that holds the noted packet, then one that doesn't
		const notedRow = ROWS.findIndex((r) => within(screen.getByRole('table', { name: 'Packets' })).queryByRole('button', { name: `Open packet ${r.n}` }));
		const holds = timeline.findIndex((b) => b.rows.includes(notedRow));
		const lacks = timeline.findIndex((b) => b.packets > 0 && !b.rows.includes(notedRow));
		await fireEvent.keyDown(c, { key: 'Home' });
		for (let i = 0; i < holds; i++) await fireEvent.keyDown(c, { key: 'ArrowRight' });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(tableRows()).toBe(1);
		expect(screen.getByText(/^Showing the 1 packet TShark marked “.*” and sent (at|from) /)).toBeInTheDocument();
		await fireEvent.keyDown(c, { key: 'Home' });
		for (let i = 0; i < lacks; i++) await fireEvent.keyDown(c, { key: 'ArrowRight' });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(screen.queryByRole('table', { name: 'Packets' }) && tableRows()).toBe(0);
		await fireEvent.click(screen.getByRole('button', { name: 'Clear the note filter' }));
		expect(tableRows()).toBe(timeline[lacks].packets);
		await fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
		expect(tableRows()).toBe(ROWS.length);
	});

	it('says the picked packets\' earliest and latest times when the rows are out of time order', async () => {
		// TShark lists frames in file order, which a reordered capture need not keep: bucket 0 holds rows 0 and 1
		const rows = [
			{ ...ROWS[0], n: 1, t: '1794026197.020' },
			{ ...ROWS[1], n: 2, t: '1794026197.001' },
			{ ...ROWS[2], n: 3, t: '1794026199.000' },
		];
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows }));
		const c = await chart();
		await fireEvent.keyDown(c, { key: 'Home' });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(tableRows()).toBe(2);
		expect(screen.getByText(`Showing the 2 packets sent from ${clockTime('1794026197.001')} to ${clockTime('1794026197.020')}`, { exact: false })).toBeInTheDocument();
	});

	it('a refresh that brings new rows drops the pick, as the buckets are worked out again', async () => {
		const c = await chart();
		await fireEvent.keyDown(c, { key: 'Home' });
		await fireEvent.keyDown(c, { key: 'Enter' });
		expect(tableRows()).toBe(timeline[0].packets);
		vi.mocked(api.searchPackets).mockResolvedValue(structuredClone(SEARCH_RESULT));
		await refreshPage();
		await vi.waitFor(() => expect(tableRows()).toBe(ROWS.length));
		expect(screen.queryByText(/^Showing the /)).not.toBeInTheDocument();
	});
});

// NET-276: a search held in the URL holds one of the daemon's two packet-reader slots for up to ~45 s,
// and a link from another site makes the owner's own page ask for it. Opened from outside NetTap (a full
// load) the page fills in the search and waits for Run; a search started inside NetTap runs straight away.
describe('Packet analysis: where the search came from', () => {
	const wanted = { filter: SEARCH_RESULT.filter, from: SEARCH_RESULT.window.requested.from, to: SEARCH_RESULT.window.requested.to, limit: 250 };
	const runButton = () => screen.queryByRole('button', { name: 'Run the search' });

	beforeEach(() => {
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES);
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_RESULT);
		vi.mocked(api.checkFilter).mockResolvedValue({ ok: true, filter: 'dns' });
		vi.mocked(api.suggestFields).mockResolvedValue({ ...FIELDS, prefix: 'dns', fields: [] });
		stubOthers();
		open();
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
		router.arrival = 'link';
		pageStore.value.set({ url: new URL('http://localhost/packets') });
	});

	it('opened from outside NetTap, shows the search and waits for Run, even on Refresh', async () => {
		router.arrival = 'enter';
		const { container } = render(Page);
		await vi.waitFor(() => expect(api.getCaptures).toHaveBeenCalled());
		expect(screen.getByText("This search hasn't run yet")).toBeInTheDocument();
		expect(runButton()).toBeInTheDocument();
		// The search exactly as the link holds it, ready to edit
		expect(container.querySelector('code.filter')).toHaveTextContent(SEARCH_RESULT.filter);
		expect(screen.getByRole('button', { name: 'Edit filter' })).toBeInTheDocument();
		expect(screen.queryByText(/Searching…/)).not.toBeInTheDocument();
		await refreshPage();
		expect(api.searchPackets).not.toHaveBeenCalled();
		expectNoNestedInteractive(container);
	});

	it('runs the waiting search when Run is clicked', async () => {
		router.arrival = 'enter';
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Run the search' }));
		expect(api.searchPackets).toHaveBeenCalledTimes(1);
		expect(api.searchPackets).toHaveBeenCalledWith(wanted);
		await vi.waitFor(() => expect(kpi('Packets')).toHaveTextContent('9'));
		expect(runButton()).not.toBeInTheDocument();
	});

	it('started inside NetTap, runs straight away', async () => {
		render(Page);
		expect(api.searchPackets).toHaveBeenCalledTimes(1);
		expect(api.searchPackets).toHaveBeenCalledWith(wanted);
		expect(runButton()).not.toBeInTheDocument();
		await screen.findByRole('table', { name: 'Packets' });
	});

	it('after waiting, an edited search runs once, with the new filter', async () => {
		router.arrival = 'enter';
		render(Page);
		await fireEvent.click(await screen.findByRole('button', { name: 'Edit filter' }));
		await fireEvent.input(screen.getByRole('combobox', { name: 'Display filter' }), { target: { value: 'dns' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Find packets' }));
		await vi.waitFor(() => expect(api.searchPackets).toHaveBeenCalledTimes(1));
		expect(api.searchPackets).toHaveBeenCalledWith({ ...wanted, filter: 'dns' });
		await screen.findByRole('table', { name: 'Packets' });
		expect(runButton()).not.toBeInTheDocument();
	});

	it('while open, a link to another search runs it and Back runs the first again; a hash or the same search runs nothing', async () => {
		render(Page);
		await screen.findByRole('table', { name: 'Packets' });
		await navigate('link', packetsUrl({ ...readUrlState(new URLSearchParams(SEARCH_QUERY))!, filter: 'dns' }));
		await vi.waitFor(() => expect(api.searchPackets).toHaveBeenCalledTimes(2));
		expect(api.searchPackets).toHaveBeenLastCalledWith({ ...wanted, filter: 'dns' });

		await navigate('popstate', `/packets?${SEARCH_QUERY}`);
		await vi.waitFor(() => expect(api.searchPackets).toHaveBeenCalledTimes(3));
		expect(api.searchPackets).toHaveBeenLastCalledWith(wanted);

		await navigate('link', `/packets?${SEARCH_QUERY}#top`);
		await navigate('goto', `/packets?${SEARCH_QUERY}`);
		await tick();
		expect(api.searchPackets).toHaveBeenCalledTimes(3);
	});
});
