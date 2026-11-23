/**
 * NET-355: the alert drawer's Evidence block. On open only the Zeek lookup runs; packets load on
 * a click; every empty or failed result says what it means and never claims more than it read.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import type { Alert } from '$api/alerts';
import * as api from '$lib/api/packets';
import { PacketApiError, type PacketSearchResult } from '$lib/api/packets';
import { LAN_POLICY } from '../../../e2e/visual/fixtures/drilldown';
import { CAPTURES, CAPTURES_EMPTY, SEARCH_RESULT, SEARCH_EMPTY } from '../../../e2e/visual/fixtures/packets';
import AlertEvidence from './AlertEvidence.svelte';

vi.mock('$lib/api/packets', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/packets')>()),
	searchPackets: vi.fn(),
	getCaptures: vi.fn(),
	downloadPackets: vi.fn(),
}));

const T = Date.UTC(2026, 10, 23, 1, 40, 44);
const ID = '1:BHcgw+xc46L4m7IOXm9O5K6Vg8o=';
const ALERT = {
	_id: 'a1',
	_index: 'arkime_sessions3-261123',
	timestamp: new Date(T).toISOString(),
	acknowledged: false,
	alert: { signature: 'ET EXPLOIT x', signature_id: 2033967, severity: 1 },
	src_ip: '192.168.1.208',
	src_port: 49232,
	dest_ip: '149.154.166.110',
	dest_port: 443,
	proto: 'TCP',
	network: { community_id: ID, application: 'tls' },
	suricata: { tls: { sni: 'example.org' } },
} as unknown as Alert;

const ZEEK = {
	hits: [
		{ _id: 'z1', _source: { '@timestamp': new Date(T - 5000).toISOString(), event: { dataset: 'conn' }, zeek: { uid: 'CAAA1', conn: { conn_state: 'SF' } } } },
		{ _id: 'z2', _source: { '@timestamp': new Date(T - 4000).toISOString(), event: { dataset: 'ssl' }, zeek: { uid: 'CBBB2', ssl: { server_name: 'example.org' } } } },
	],
	total: 2,
};

let logReply: { ok: boolean; status: number; body: unknown } = { ok: true, status: 200, body: ZEEK };
const fetchMock = vi.fn(async (url: string) => {
	if (String(url).startsWith('/api/network/lan')) return { ok: true, status: 200, json: async () => LAN_POLICY };
	if (String(url).startsWith('/api/logs/search')) return { ok: logReply.ok, status: logReply.status, json: async () => logReply.body };
	return { ok: false, status: 503, json: async () => ({}) };
});

const result = (over: Partial<PacketSearchResult>): PacketSearchResult => ({ ...SEARCH_RESULT, ...over });
const showPackets = () => fireEvent.click(screen.getByRole('button', { name: /Show packets/ }));
const logCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).startsWith('/api/logs/search'));

beforeEach(() => {
	logReply = { ok: true, status: 200, body: ZEEK };
	vi.stubGlobal('fetch', fetchMock);
	vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES);
});
afterEach(() => {
	vi.unstubAllGlobals();
	vi.clearAllMocks();
});

describe('on open', () => {
	it('shows what Suricata saw and recorded, and looks up Zeek records only', async () => {
		render(AlertEvidence, { alert: ALERT });
		expect(screen.getByText(/Suricata saw TLS traffic from/)).toBeTruthy();
		expect(screen.getByText(/Suricata saw TLS traffic from/).textContent?.replace(/\s+/g, ' ')).toContain('192.168.1.208 port 49232 to 149.154.166.110 port 443.');
		expect(screen.getByText('Server name')).toBeTruthy();
		expect(await screen.findByText('CAAA1')).toBeTruthy();
		expect(screen.getByText('CBBB2')).toBeTruthy();
		expect(screen.queryByText(/\d{4}-\d{2}-\d{2}T/)).toBeNull(); // times are formatted, not raw ISO
		expect(screen.getByText(/Showing 2 of 2 records/)).toBeTruthy();
		expect(screen.getByText(/these may include other connections/)).toBeTruthy();
		expect(api.searchPackets).not.toHaveBeenCalled();
		const params = new URL(String(logCalls()[0][0]), 'http://x').searchParams;
		expect(params.get('query')).toBe(`network.community_id:"${ID}" AND event.provider:zeek`);
		expect(params.get('size')).toBe('10');
		expect(params.get('sort')).toBe('@timestamp:desc');
		expect(screen.getByRole('link', { name: /Open all in Log Explorer/ }).getAttribute('href')).toContain('/logs?');
	});

	it('says so when the alert has no community ID, and searches nothing', () => {
		render(AlertEvidence, { alert: { ...ALERT, network: {} } as unknown as Alert });
		expect(screen.getByText('This alert has no community ID to look up.')).toBeTruthy();
		expect(logCalls()).toHaveLength(0);
	});

	it('keeps a failed Zeek lookup to its own message', async () => {
		logReply = { ok: false, status: 502, body: {} };
		render(AlertEvidence, { alert: ALERT });
		expect(await screen.findByText(/couldn't search the Zeek records \(HTTP 502\)/)).toBeTruthy();
		expect(screen.getByRole('button', { name: /Show packets/ })).toBeTruthy();
	});

	it('explains the gap when no protocol field was recorded', () => {
		render(AlertEvidence, { alert: { ...ALERT, suricata: {} } as unknown as Alert });
		expect(screen.getByText(/None of the protocol fields shown here are in this alert/)).toBeTruthy();
	});
});

describe('Show packets', () => {
	it('runs one search with the alert’s tuple, a minute either side', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_RESULT);
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		await screen.findByRole('table', { name: 'Packets near the alert time' });
		expect(api.searchPackets).toHaveBeenCalledTimes(1);
		const body = vi.mocked(api.searchPackets).mock.calls[0][0];
		expect(body).toMatchObject({ from: String((T - 60_000) / 1000), to: String((T + 60_000) / 1000), limit: 100 });
		expect(body.filter).toContain('149.154.166.110');
		expect(screen.getByText(/All of them \(the window holds no more\)/)).toBeTruthy();
		expect(screen.getByRole('button', { name: /Download these/ })).toBeTruthy();
	});

	it('uses the effective window for the shown interval and Open in Packets', async () => {
		const effective = { from: '1795400000', to: '1795400030.5' };
		vi.mocked(api.searchPackets).mockResolvedValue(result({ window: { ...SEARCH_RESULT.window, effective } }));
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		const href = (await screen.findByRole('link', { name: /Open in Packets/ })).getAttribute('href') ?? '';
		const params = new URL(href, 'http://x').searchParams;
		expect(params.get('from')).toBe(effective.from);
		expect(params.get('to')).toBe(effective.to);
		expect(params.get('limit')).toBe('1000');
	});

	it('never says "no match" after a deadline or skipped files', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [], complete: false, termination: 'deadline' }));
		const { unmount } = render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText(/stopped before it finished/)).toBeTruthy();
		expect(screen.queryByText(/No matching packets/)).toBeNull();
		unmount();

		vi.mocked(api.searchPackets).mockResolvedValue(result({ rows: [], complete: false, files: [], skipped_files: [SEARCH_RESULT.files[0]] as never }));
		vi.mocked(api.getCaptures).mockRejectedValue(new Error('down'));
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText(/Some capture files couldn't be read, so packets may still be there/)).toBeTruthy();
		expect(screen.queryByText(/No capture was available/)).toBeNull();
	});

	it('says no capture was available when nothing was read; an unindexed file makes coverage unknown, never expired', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue({ ...SEARCH_EMPTY, files: [] });
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES); // holds a pending (unindexed) live file
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText(/No capture was available for this window/)).toBeTruthy();
		expect(await screen.findByText(/coverage is unknown/)).toBeTruthy();
		expect(screen.queryByText(/No saved capture covers/)).toBeNull();
		expect(screen.queryByRole('button', { name: /Download/ })).toBeNull();
	});

	it('says no saved capture covers the window when the index has none, without inventing a date', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue({ ...SEARCH_EMPTY, files: [] });
		vi.mocked(api.getCaptures).mockResolvedValue(CAPTURES_EMPTY);
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText('No saved capture covers this window.')).toBeTruthy();
		expect(screen.queryByText(/earliest indexed packet/)).toBeNull();
	});

	it('says "no match" only after reading a file', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_EMPTY);
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText(/No matching packets in the captures searched\./)).toBeTruthy();
	});

	it('offers the 11 minutes before, with or without rows', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_EMPTY);
		render(AlertEvidence, { alert: ALERT });
		const before = () => new URL(screen.getByRole('link', { name: 'search the 11 minutes before' }).getAttribute('href') ?? '', 'http://x').searchParams;
		expect(before().get('from')).toBe(String((T - 660_000) / 1000));
		expect(before().get('to')).toBe(String(T / 1000));
		await showPackets();
		await screen.findByText(/No matching packets/);
		expect(before().get('to')).toBe(String(T / 1000));
	});

	it('offers Try again when the reader is busy', async () => {
		vi.mocked(api.searchPackets).mockRejectedValueOnce(new PacketApiError('Two searches are already running.', 503)).mockResolvedValue(SEARCH_RESULT);
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText('Two searches are already running.')).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		await screen.findByRole('table', { name: 'Packets near the alert time' });
		expect(api.searchPackets).toHaveBeenCalledTimes(2);
	});

	it('sends a refusal to the blank Packets builder, with no retry', async () => {
		vi.mocked(api.searchPackets).mockRejectedValue(new PacketApiError('These files are over the read budget: pick a shorter window.', 422));
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		expect(await screen.findByText(/over the read budget/)).toBeTruthy();
		expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
		expect(screen.getByRole('link', { name: 'Choose a shorter window on Packets' }).getAttribute('href')).toBe('/packets');
	});

	it('downloads the manifest, and re-arms Show packets when the files changed', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_RESULT);
		vi.mocked(api.downloadPackets).mockRejectedValue(new PacketApiError('Changed.', 409));
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		await fireEvent.click(await screen.findByRole('button', { name: /Download these/ }));
		expect(api.downloadPackets).toHaveBeenCalledWith(SEARCH_RESULT.manifest);
		expect(await screen.findByText('The capture files changed since the search. Show the packets again.')).toBeTruthy();
		expect(screen.getByRole('button', { name: /Show packets/ })).toBeTruthy();
	});

	it('saves the download under the alert’s name', async () => {
		vi.mocked(api.searchPackets).mockResolvedValue(SEARCH_RESULT);
		vi.mocked(api.downloadPackets).mockResolvedValue(new Blob(['pcap']));
		const create = vi.fn(() => 'blob:x');
		vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
		const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
		render(AlertEvidence, { alert: ALERT });
		await showPackets();
		await fireEvent.click(await screen.findByRole('button', { name: /Download these/ }));
		await waitFor(() => expect(click).toHaveBeenCalled());
		expect((click.mock.instances[0] as unknown as HTMLAnchorElement).download).toBe('alert-2033967-20261123-014044.pcap');
		click.mockRestore();
	});

	it('shows why instead of the button when the alert can’t be searched', () => {
		render(AlertEvidence, { alert: { ...ALERT, dest_ip: undefined } as unknown as Alert });
		expect(screen.getByText("This alert doesn't carry two IP addresses to look for.")).toBeTruthy();
		expect(screen.queryByRole('button', { name: /Show packets/ })).toBeNull();
	});
});
