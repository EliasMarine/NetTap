import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ConnectionDrawer from './ConnectionDrawer.svelte';
import ConnectionDrawerContent from './drawer/content/ConnectionDrawerContent.svelte';
import { readUrlState } from '$lib/utils/packet-query';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

// NET-188: both connection drawers open the connection's exact packets on /packets, over its
// own padded window, in place of the old TShark tool link

const CONNECTION = {
	_id: 'c1',
	'@timestamp': '2026-11-06T14:32:07.412Z',
	event: { start: '1794061927412' },
	length: 34_250,
	source: { ip: '192.168.1.42', port: 51834 },
	destination: { ip: '203.0.113.45', port: 443 },
	network: { transport: 'tcp' },
};

function stubFetch() {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) =>
			String(input).startsWith('/api/tshark/status')
				? new Response(JSON.stringify({ available: true, version: '4.0.17', container_running: true, container_name: 'nettap-tshark' }), { status: 200 })
				: new Response('{}', { status: 500 }),
		),
	);
}

function expectExactConnection(link: HTMLElement) {
	const url = new URL(link.getAttribute('href')!, 'http://localhost');
	expect(url.pathname).toBe('/packets');
	const state = readUrlState(url.searchParams)!;
	expect(state.filter).toBe(
		'(ip.src == 192.168.1.42 && tcp.srcport == 51834 && ip.dst == 203.0.113.45 && tcp.dstport == 443) || (ip.src == 203.0.113.45 && tcp.srcport == 443 && ip.dst == 192.168.1.42 && tcp.dstport == 51834)',
	);
	expect(state).toMatchObject({ from: '1794061926.412', to: '1794061962.662', limit: 1000 });
	expect(state.conn).toEqual({ start: '1794061927.412', duration: 34.25, segment: 0, exact: true });
}

describe('Open these packets', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('links from the Connections drawer', async () => {
		stubFetch();
		render(ConnectionDrawerContent, { props: { connection: CONNECTION, activeTab: 'tshark' } });
		expectExactConnection(await screen.findByRole('link', { name: 'Open these packets' }));
		expect(screen.queryByRole('link', { name: 'Open in TShark tool' })).not.toBeInTheDocument();
	});

	it("links from a device page's connection drawer", async () => {
		stubFetch();
		render(ConnectionDrawer, { props: { connection: CONNECTION, deviceIp: '192.168.1.42', onclose: () => {} } });
		await fireEvent.click(screen.getByRole('button', { name: 'TShark analysis' }));
		expectExactConnection(await screen.findByRole('link', { name: 'Open these packets' }));
	});

	it('offers no link for a record without both addresses', async () => {
		stubFetch();
		render(ConnectionDrawerContent, { props: { connection: { ...CONNECTION, destination: {} }, activeTab: 'tshark' } });
		await screen.findByText(/Display filter/);
		expect(screen.queryByRole('link', { name: 'Open these packets' })).not.toBeInTheDocument();
	});
});
