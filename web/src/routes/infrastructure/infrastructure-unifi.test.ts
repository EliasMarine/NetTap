import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import InfrastructurePage from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';

// #96: a failed UniFi status read showed "Connect your UniFi controller", and failed lists read
// "No UniFi devices found" / 0 firewall policies

const UNIFI = '/api/integrations/unifi';
const CONFIGURED = {
	configured: true,
	controller_url: 'https://192.168.1.1',
	site_id: 'default',
	connected: true,
	last_poll_time: 1793300000,
	last_error: null,
	cache_counts: {},
};
const EMPTY_LISTS: Record<string, unknown> = {
	[`${UNIFI}/devices`]: { devices: [] },
	[`${UNIFI}/networks`]: { networks: [] },
	[`${UNIFI}/wifi`]: { wifi: [] },
	[`${UNIFI}/firewall`]: { policies: [], zones: [] },
	[`${UNIFI}/dns-policies`]: { policies: [] },
	[`${UNIFI}/wans`]: { wans: [] },
	[`${UNIFI}/vpn`]: { tunnels: [] },
};

// the page's other readings, all answering, so only UniFi decides whether a "Couldn't load" shows
const SYSTEM_READINGS: Record<string, unknown> = {
	'/api/capture/mode': { mode: 'bridge', interface: '' },
	'/api/capture/stats': { capture_interface: 'br0', drop_rate_pct: 0, rx_packets: 1, tx_packets: 1, rx_dropped: 0, rx_missed_errors: 0, link_speed_mbps: 1000 },
	'/api/capture/health': { mode: 'bridge', status: 'normal', capture_interface: 'br0', link_up: true, promisc_enabled: true, issues: [] },
	'/api/bridge/health': { bridge_state: 'up', wan_link: true, lan_link: true, bypass_active: false, latency_us: 100, uptime_seconds: 60, issues: [] },
	'/api/system/health': { uptime: 60, healthy: true, opensearch_reachable: true },
	'/api/storage/status': { disk_usage_percent: 10 },
	'/api/opensearch/cluster': { status: 'green', number_of_nodes: 1 },
	'/api/opensearch/indices': { indices: [], count: 0 },
	'/api/opensearch/templates': { templates: [], count: 0 },
	'/api/logstash/stats': { events_in: 0 },
	'/api/logstash/pipelines': { pipelines: [] },
};

/** Stub fetch: URLs in `routes` get their body, everything else a 503. */
function stubFetch(routes: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) =>
			url in routes
				? { ok: true, status: 200, json: async () => routes[url] }
				: { ok: false, status: 503, json: async () => ({}) },
		),
	);
}

describe('Infrastructure — UniFi reads that failed', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says the UniFi status failed instead of "Connect your UniFi controller"', async () => {
		stubFetch({});
		render(InfrastructurePage);
		expect(await screen.findByText("Couldn't load the UniFi status: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/Connect your UniFi controller/)).not.toBeInTheDocument();
	});

	it('says which lists failed while the ones that loaded still show', async () => {
		const down = ['devices', 'firewall', 'wans'].map((p) => `${UNIFI}/${p}`);
		const lists = Object.fromEntries(Object.entries(EMPTY_LISTS).filter(([url]) => !down.includes(url)));
		stubFetch({ ...lists, [`${UNIFI}/status`]: CONFIGURED });
		render(InfrastructurePage);

		expect(await screen.findByText("Couldn't load UniFi devices: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No UniFi devices found')).not.toBeInTheDocument();
		expect(screen.getByText('— devices')).toBeInTheDocument();
		expect(screen.getByText("Couldn't load firewall policies: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load WAN interfaces: the request failed.")).toBeInTheDocument();
		// the reads that worked keep their real empty answer
		expect(screen.getByText('No networks found')).toBeInTheDocument();
		expect(screen.getByText('No WiFi networks found')).toBeInTheDocument();
	});

	it('keeps the real answers when UniFi is configured and everything is empty', async () => {
		stubFetch({ ...SYSTEM_READINGS, ...EMPTY_LISTS, [`${UNIFI}/status`]: CONFIGURED });
		render(InfrastructurePage);

		expect(await screen.findByText('No UniFi devices found')).toBeInTheDocument();
		expect(screen.getByText('0 devices')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load/)).not.toBeInTheDocument();
	});

	it('still offers to connect UniFi when it really is not configured', async () => {
		stubFetch({ [`${UNIFI}/status`]: { ...CONFIGURED, configured: false } });
		render(InfrastructurePage);

		expect(await screen.findByText(/Connect your UniFi controller/)).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load the UniFi status/)).not.toBeInTheDocument();
	});
});

describe('Infrastructure — UniFi tables', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('lists every UniFi list in its own sortable table', async () => {
		stubFetch({
			...SYSTEM_READINGS,
			[`${UNIFI}/status`]: CONFIGURED,
			[`${UNIFI}/devices`]: {
				devices: [{ id: 'd1', name: 'Dream Machine', model: 'UDM-Pro', ipAddress: '192.168.1.1', state: 'ONLINE', firmwareVersion: '4.0.6', firmwareUpdatable: true, features: [] }],
			},
			[`${UNIFI}/networks`]: { networks: [{ id: 'n1', name: 'Default', vlanId: 1, management: 'gateway', enabled: true }] },
			[`${UNIFI}/wifi`]: { wifi: [{ id: 'w1', name: 'Home', broadcastingFrequenciesGHz: [5, 2.4], securityConfiguration: { type: 'WPA2_PERSONAL' }, enabled: true }] },
			[`${UNIFI}/firewall`]: { policies: [{ id: 'p1', name: 'Block IoT', enabled: true, action: { type: 'BLOCK' } }], zones: [] },
			[`${UNIFI}/dns-policies`]: { policies: [] },
			[`${UNIFI}/wans`]: { wans: [{ id: 'wan1', name: 'WAN', type: 'dhcp', status: 'connected' }] },
			[`${UNIFI}/vpn`]: { tunnels: [{ id: 'v1', name: 'Office', type: 'wireguard', status: 'down' }] },
		});
		render(InfrastructurePage);

		const devices = await screen.findByRole('table', { name: 'UniFi devices' });
		expect(within(devices).getByText('Gateway')).toBeInTheDocument();
		expect(within(devices).getByText('Update')).toBeInTheDocument();
		const wifi = within(screen.getByRole('table', { name: 'WiFi networks' }));
		expect(wifi.getByText('2.4 / 5 GHz')).toBeInTheDocument();
		expect(wifi.getByText('WPA2 PERSONAL')).toBeInTheDocument();
		expect(within(screen.getByRole('table', { name: 'Firewall policies' })).getByText('BLOCK')).toBeInTheDocument();
		expect(within(screen.getByRole('table', { name: 'WAN interfaces' })).getByText('connected')).toBeInTheDocument();
		expect(within(screen.getByRole('table', { name: 'VPN tunnels' })).getByText('down')).toBeInTheDocument();
		// every column sorts (repo rule), including the ones the old tables left unsorted
		for (const name of ['UniFi devices', 'Networks', 'WiFi networks', 'Firewall policies', 'WAN interfaces', 'VPN tunnels']) {
			for (const th of within(screen.getByRole('table', { name })).getAllByRole('columnheader')) {
				expect(within(th).getByRole('button')).toBeInTheDocument();
			}
		}
	});
});

describe('Infrastructure — a refresh while the UniFi lists load', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('does not leave the cards loading when the next status read fails', async () => {
		let statusUp = true;
		vi.stubGlobal(
			'fetch',
			vi.fn((url: string) => {
				if (url === `${UNIFI}/status`) {
					return Promise.resolve(statusUp ? { ok: true, status: 200, json: async () => CONFIGURED } : { ok: false, status: 503, json: async () => ({}) });
				}
				if (url.startsWith(UNIFI)) return new Promise(() => {}); // the lists never answer
				return Promise.resolve(url in SYSTEM_READINGS ? { ok: true, status: 200, json: async () => SYSTEM_READINGS[url] } : { ok: false, status: 503, json: async () => ({}) });
			}),
		);
		render(InfrastructurePage);
		expect(await screen.findByText('Loading UniFi devices')).toBeInTheDocument();

		statusUp = false;
		void refreshPage();

		expect(await screen.findByText(/Couldn't (load|refresh) the UniFi status/)).toBeInTheDocument();
		expect(screen.queryByText('Loading UniFi devices')).not.toBeInTheDocument();
	});
});
