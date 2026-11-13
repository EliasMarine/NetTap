import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';

const RESULT = {
	peer: '192.168.1.20',
	resolved_ip: '192.168.1.20',
	port: 5201,
	duration: 10,
	path: { interface: 'eno1', source_ip: '192.168.1.199', wifi: false, speed_mbps: 1000, mtu: 1500 },
	capture: { mode: 'mirror', interface: 'enp4s0', has_ip: false },
	error: null,
};
const UPLOAD = { ...RESULT, direction: 'upload', bits_per_second: 941_000_000, retransmits: 12 };
const DOWNLOAD = { ...RESULT, direction: 'download', bits_per_second: 937_000_000, retransmits: null };

type Reply = { body: unknown; status?: number } | Promise<never>;

function stubFetch(...replies: Reply[]) {
	const fetch = vi.fn(async (_url: string, _init?: RequestInit) => {
		const next = replies.shift()!;
		if (next instanceof Promise) return next;
		const status = next.status ?? 200;
		return { ok: status < 400, status, json: async () => next.body };
	});
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

async function run(peer = '192.168.1.20') {
	await fireEvent.input(screen.getByLabelText('Peer'), { target: { value: peer } });
	await fireEvent.click(screen.getByRole('button', { name: 'Run test' }));
}

describe('LAN throughput test page (NET-266)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('starts empty, with Run test disabled until there is a peer', async () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'LAN throughput test' })).toBeInTheDocument();
		expect(screen.getByText('No results yet')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Run test' })).toBeDisabled();
		expect(screen.getByText(/can appear in NetTap's own traffic figures/)).toBeInTheDocument();
	});

	it('shows the loading state while the upload runs', async () => {
		stubFetch(new Promise<never>(() => {}));
		render(Page);
		await run();
		expect(screen.getByRole('status')).toHaveTextContent('Testing upload for 10 seconds');
		expect(screen.getByRole('button', { name: 'Testing…' })).toBeDisabled();
	});

	it('runs upload then download, shows the interface first, then both rates and a history row', async () => {
		const fetch = stubFetch({ body: UPLOAD }, { body: DOWNLOAD });
		render(Page);
		await fireEvent.input(screen.getByLabelText('Port'), { target: { value: '5299' } });
		await fireEvent.input(screen.getByLabelText('Duration (seconds)'), { target: { value: '5' } });
		await run();

		expect(await screen.findAllByText('937 Mbit/s')).toHaveLength(2); // the download card and the history row
		const bodies = fetch.mock.calls.map((c) => JSON.parse(String(c[1]?.body)));
		expect(bodies).toEqual([
			{ host: '192.168.1.20', port: 5299, duration: 5, direction: 'upload' },
			{ host: '192.168.1.20', port: 5299, duration: 5, direction: 'download' },
		]);
		expect(screen.getByText('This test runs over eno1 (192.168.1.199, wired, 1 Gbit/s).')).toBeInTheDocument();
		expect(screen.getByText(/The capture port enp4s0 has no IP address/)).toBeInTheDocument();
		expect(screen.getByText('NetTap to the peer · 12 retransmits')).toBeInTheDocument();

		const table = screen.getByRole('table', { name: 'Earlier throughput runs' });
		const rows = within(table).getAllByRole('row');
		expect(rows).toHaveLength(2);
		expect(within(rows[1]).getByText('941 Mbit/s')).toBeInTheDocument();
		expect(within(table).getAllByRole('columnheader').every((th) => th.hasAttribute('aria-sort'))).toBe(true);
	});

	it('shows an iperf3 failure as the error state and skips the download', async () => {
		const fetch = stubFetch({
			body: { ...UPLOAD, bits_per_second: null, retransmits: null, error: 'No iperf3 server on 192.168.1.20:5201. Start one there with iperf3 -s.' },
		});
		render(Page);
		await run();

		expect(await screen.findByText('Upload test failed')).toBeInTheDocument();
		expect(screen.getByText('No iperf3 server on 192.168.1.20:5201. Start one there with iperf3 -s.')).toBeInTheDocument();
		expect(screen.getByText('Not run')).toBeInTheDocument();
		expect(fetch).toHaveBeenCalledTimes(1);
		const rows = within(screen.getByRole('table', { name: 'Earlier throughput runs' })).getAllByRole('row');
		expect(within(rows[1]).getAllByText('—').length).toBeGreaterThanOrEqual(2);
	});

	it("shows the daemon's sentence when the request is refused", async () => {
		stubFetch({ status: 400, body: { error: 'The LAN throughput test only runs against local addresses: private, CGNAT/VPN or ULA ranges.' } });
		render(Page);
		await run('9.9.9.9');

		expect(await screen.findByText('Upload test failed')).toBeInTheDocument();
		expect(screen.getByText(/only runs against local addresses/)).toBeInTheDocument();
		expect(screen.queryByText(/This test runs over/)).not.toBeInTheDocument();
	});
});
