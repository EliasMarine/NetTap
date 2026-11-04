import type {
	DnsPolicy,
	UnifiDevice,
	UnifiFirewall,
	UnifiNetwork,
	UnifiStatus,
	UnifiVpnTunnel,
	UnifiWan,
	UnifiWifi,
} from '../../../src/lib/api/unifi.ts';
import { NOW, type FixtureRoute } from './types.ts';

const NOT_CONFIGURED = {
	configured: false,
	controller_url: null,
	site_id: null,
	connected: false,
	last_poll_time: 0,
	last_error: null,
	cache_counts: {},
} satisfies UnifiStatus;

const CONNECTED = {
	configured: true,
	controller_url: 'https://unifi.example.net',
	site_id: '00000000-0000-4000-8000-000000000001',
	connected: true,
	last_poll_time: Math.floor((NOW - 45_000) / 1000),
	last_error: null,
	cache_counts: { clients: 31, devices: 4, networks: 3, wifi: 2 },
} satisfies UnifiStatus;

function device(id: string, name: string, model: string, ip: string, features: string[], interfaces: string[]) {
	return {
		id,
		macAddress: `02:00:5e:10:00:${id.slice(-2)}`,
		ipAddress: ip,
		name,
		model,
		state: 'ONLINE',
		firmwareVersion: '7.1.0',
		firmwareUpdatable: false,
		features,
		interfaces,
	} satisfies UnifiDevice;
}

// Everything below is only fetched once the status says `configured`.
const DEVICES = {
	devices: [
		device('dev-a1', 'Example Gateway', 'GW-EXAMPLE', '192.168.1.1', [], ['ports']),
		device('dev-a2', 'Example Switch', 'SW-EXAMPLE-8', '192.168.1.2', ['switching'], ['ports']),
		device('dev-a3', 'Example AP Hall', 'AP-EXAMPLE', '192.168.1.3', ['accessPoint'], ['radios']),
		device('dev-a4', 'Example AP Garden', 'AP-EXAMPLE', '192.168.1.4', ['accessPoint'], ['radios']),
	],
} satisfies { devices: UnifiDevice[] };

const NETWORKS = {
	networks: [
		{ id: 'net-1', name: 'Default', vlanId: 1, subnet: '192.168.1.0/24', purpose: 'corporate', management: 'GATEWAY' },
		{ id: 'net-2', name: 'IoT', vlanId: 20, subnet: '192.168.20.0/24', purpose: 'corporate', management: 'GATEWAY' },
		{ id: 'net-3', name: 'Guest', vlanId: 30, subnet: '192.168.30.0/24', purpose: 'guest', management: 'GATEWAY' },
	],
} satisfies { networks: UnifiNetwork[] };

const WIFI = {
	wifi: [
		{ id: 'wifi-1', name: 'Example-Home', band: '5 GHz', security: 'WPA2', enabled: true },
		{ id: 'wifi-2', name: 'Example-IoT', band: '2.4 GHz', security: 'WPA2', enabled: true },
	],
} satisfies { wifi: UnifiWifi[] };

const FIREWALL = {
	policies: [
		{ id: 'fw-1', name: 'Allow return traffic', enabled: true, action: { type: 'ALLOW' } },
		{ id: 'fw-2', name: 'Block IoT to LAN', enabled: true, action: { type: 'BLOCK' } },
	],
	zones: [
		{ id: 'zone-1', name: 'Internal' },
		{ id: 'zone-2', name: 'External' },
		{ id: 'zone-3', name: 'Gateway' },
	],
} satisfies UnifiFirewall;

const DNS_POLICIES = {
	policies: [{ id: 'dns-1', name: 'Block ads and trackers', enabled: true }],
} satisfies { policies: DnsPolicy[] };

const WANS = {
	wans: [{ id: 'wan-1', name: 'WAN1', type: 'DHCP', status: 'connected' }],
} satisfies { wans: UnifiWan[] };

const VPN = {
	tunnels: [{ id: 'vpn-1', name: 'Remote access', type: 'WireGuard', status: 'connected' }],
} satisfies { tunnels: UnifiVpnTunnel[] };

const BASE = '/api/integrations/unifi';

export const UNIFI_ROUTES: FixtureRoute[] = [
	{ path: `${BASE}/status`, empty: NOT_CONFIGURED, populated: CONNECTED },
	{ path: `${BASE}/devices`, empty: { devices: [] }, populated: DEVICES },
	{ path: `${BASE}/networks`, empty: { networks: [] }, populated: NETWORKS },
	{ path: `${BASE}/wifi`, empty: { wifi: [] }, populated: WIFI },
	{ path: `${BASE}/firewall`, empty: { policies: [], zones: [] }, populated: FIREWALL },
	{ path: `${BASE}/dns-policies`, empty: { policies: [] }, populated: DNS_POLICIES },
	{ path: `${BASE}/wans`, empty: { wans: [] }, populated: WANS },
	{ path: `${BASE}/vpn`, empty: { tunnels: [] }, populated: VPN },
];
