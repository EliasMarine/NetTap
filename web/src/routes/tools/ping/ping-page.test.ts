import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';

const search = vi.hoisted(() => ({ value: '' }));
// Each subscriber reads the query string the current test set
vi.mock('$app/stores', () => ({
	page: {
		subscribe(run: (value: unknown) => void) {
			run({ url: new URL(`http://localhost/tools/ping${search.value}`), params: {} });
			return () => {};
		},
	},
}));

const PING = {
	target: '1.1.1.1',
	raw: '',
	packets_sent: 2,
	packets_received: 2,
	packet_loss_pct: 0,
	rtt_min: 11.2,
	rtt_avg: 12.6,
	rtt_max: 14.0,
	rtt_mdev: 1.4,
	replies: [
		{ bytes: 64, from: '1.1.1.1', seq: 1, ttl: 57, time_ms: 14.0 },
		{ bytes: 64, from: '1.1.1.1', seq: 2, ttl: 57, time_ms: 11.2 },
	],
};

const TRACE = {
	target: '1.1.1.1',
	total_hops: 3,
	raw: '',
	hops: [
		{ hop: 1, host: 'router.lan', ip: '192.168.1.1', rtts: [0.512, 0.498, 0.502] },
		{ hop: 2, host: '* * *', ip: '', rtts: [] },
		{ hop: 3, host: 'one.one.one.one', ip: '1.1.1.1', rtts: [9.1, 9.4, 0] },
	],
};

function stubFetch(body: unknown, ok = true) {
	const fetch = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok, status: ok ? 200 : 500, json: async () => body }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

async function enterTarget(value = '1.1.1.1') {
	await fireEvent.input(screen.getByLabelText('Target'), { target: { value } });
}

describe('Ping and traceroute page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		search.value = '';
	});

	it('starts empty, with both actions disabled until there is a target', async () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'Ping and traceroute' })).toBeInTheDocument();
		expect(screen.getByText('No results yet')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Ping' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Traceroute' })).toBeDisabled();
		await enterTarget();
		expect(screen.getByRole('button', { name: 'Ping' })).toBeEnabled();
	});

	it('shows the loading state while a ping runs', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		await enterTarget();
		await fireEvent.click(screen.getByRole('button', { name: 'Ping' }));
		expect(screen.getByRole('status')).toHaveTextContent('Pinging 1.1.1.1');
	});

	it('sends the target and count, then shows the KPIs, the RTT bars and the replies table', async () => {
		const fetch = stubFetch(PING);
		render(Page);
		await enterTarget();
		await fireEvent.input(screen.getByLabelText('Count'), { target: { value: '2' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Ping' }));

		expect(await screen.findByText('Packet loss')).toBeInTheDocument();
		expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({ target: '1.1.1.1', count: 2 });
		expect(screen.getByText('12.6')).toBeInTheDocument();
		expect(screen.getByText('#1')).toBeInTheDocument();
		const table = screen.getByRole('table', { name: 'Ping replies' });
		expect(within(table).getAllByRole('row')).toHaveLength(3);
		expect(within(table).getAllByRole('columnheader').every((th) => th.hasAttribute('aria-sort'))).toBe(true);
	});

	it('shows no round-trip time, not 0.0 ms, when every packet was lost (S12)', async () => {
		stubFetch({ ...PING, packets_received: 0, packet_loss_pct: 100, rtt_min: null, rtt_avg: null, rtt_max: null, rtt_mdev: null, replies: [] });
		render(Page);
		await enterTarget();
		await fireEvent.click(screen.getByRole('button', { name: 'Ping' }));

		expect(await screen.findByText('Average RTT')).toBeInTheDocument();
		expect(screen.getAllByText('—')).toHaveLength(3);
		expect(screen.queryByText('0.0')).not.toBeInTheDocument();
	});

	it('shows the error state with the daemon message when the ping fails', async () => {
		stubFetch({ error: 'Invalid target' }, false);
		render(Page);
		await enterTarget('bad host');
		await fireEvent.click(screen.getByRole('button', { name: 'Ping' }));
		expect(await screen.findByText('Ping failed')).toBeInTheDocument();
		expect(screen.getByText('Invalid target')).toBeInTheDocument();
	});

	it('NET-169: a 200 reply carrying an error shows the error, never the default figures', async () => {
		// ping printed a header and one reply, then failed: the daemon returns its error with the
		// API's defaults (0 sent, 100% loss, no round trips)
		stubFetch({
			...PING,
			packets_sent: 0,
			packets_received: 0,
			packet_loss_pct: 100,
			rtt_min: null,
			rtt_avg: null,
			rtt_max: null,
			rtt_mdev: null,
			replies: [PING.replies[0]],
			error: 'ping: sendmsg: Network is unreachable',
		});
		render(Page);
		await enterTarget();
		await fireEvent.click(screen.getByRole('button', { name: 'Ping' }));
		expect(await screen.findByText('Ping failed')).toBeInTheDocument();
		expect(screen.getByText('ping: sendmsg: Network is unreachable')).toBeInTheDocument();
		for (const label of ['Packet loss', 'Average RTT', 'Minimum RTT', 'Maximum RTT']) {
			expect(screen.queryByText(label)).not.toBeInTheDocument();
		}
		expect(screen.queryByRole('table', { name: 'Ping replies' })).not.toBeInTheDocument();
		expect(screen.queryByText('100')).not.toBeInTheDocument();
	});

	it('runs a traceroute in its own tab, with timeouts shown as stars', async () => {
		stubFetch(TRACE);
		render(Page);
		await enterTarget();
		await fireEvent.click(screen.getByRole('button', { name: 'Traceroute' }));

		expect(await screen.findByRole('tab', { name: 'Traceroute' })).toHaveAttribute('aria-selected', 'true');
		const table = screen.getByRole('table', { name: 'Traceroute hops' });
		const rows = within(table).getAllByRole('row');
		expect(rows).toHaveLength(4);
		expect(within(rows[2]).getByText('* * *')).toBeInTheDocument();
		expect(within(rows[3]).getByText('9.100 ms')).toBeInTheDocument();
		expect(within(rows[3]).getByText('*')).toBeInTheDocument();
		expect(screen.getByText('NetTap')).toBeInTheDocument();
		expect(document.getElementById('ping-panel-ping')).not.toBeVisible();
		expect(document.getElementById('ping-panel-traceroute')).toBeVisible();
	});

	it('reads ?target and ?tab=traceroute on load', () => {
		search.value = '?target=8.8.8.8&tab=traceroute';
		render(Page);
		expect(screen.getByLabelText('Target')).toHaveValue('8.8.8.8');
		expect(screen.getByRole('tab', { name: 'Traceroute' })).toHaveAttribute('aria-selected', 'true');
		expect(screen.getByText('No traceroute results')).toBeInTheDocument();
	});
});
