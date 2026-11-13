/** Fixtures for /api/local-services (daemon/api/local_services.py, NET-264), shaped like the G11's rows. */
import type { LocalServiceRow, LocalServicesResponse } from '../../../src/lib/api/local-services.ts';
import { HOUR, MIN, iso, type FixtureRoute } from './types.ts';
import { WINDOW } from './net-world.ts';

const ROUTER_MAC = '02:00:5e:10:00:01';
const sender = (ip: string, mac: string | null, name: string | null, vlan: string | null, joined = true): LocalServiceRow['sender'] => ({
	ip,
	mac,
	name,
	vlan,
	vlan_state: !joined ? 'unknown' : vlan === null ? 'untagged' : 'tagged',
});
const mdns = (id: string, service_type: string, instance: string, s: LocalServiceRow['sender'], last_seen: string): LocalServiceRow => ({
	id,
	protocol: 'mdns',
	service_type,
	instance,
	sender: s,
	last_seen,
});

export const LOCAL_SERVICES = {
	...WINDOW,
	truncated: false,
	rows: [
		// an announcement whose flow has no conn record yet: MAC and VLAN not known
		mdns('0a01', '_airplay._tcp', 'living room', sender('192.168.1.147', null, null, null, false), iso(MIN)),
		mdns('0a02', '_airplay._tcp', 'living room', sender('192.168.1.147', '02:00:5e:10:00:47', 'Living room TV', null), iso(2 * MIN)),
		// the router re-sends it on VLAN 2: its own row
		mdns('0a03', '_airplay._tcp', 'living room', sender('10.10.0.1', ROUTER_MAC, 'Router', '2'), iso(2 * MIN)),
		mdns('0a04', '_hue._tcp', 'hue bridge - 0a0b0c', sender('192.168.1.154', '02:00:5e:10:00:54', 'Hue bridge', null), iso(3 * MIN)),
		mdns('0a05', '_googlecast._tcp', 'google-nest-mini-0a0b', sender('fe80::200:5eff:fe10:12', '02:00:5e:10:00:12', null, null), iso(8 * MIN)),
		// a type the page has no name for shows as itself
		mdns('0a06', '_asquic._udp', 'studio mac', sender('192.168.1.188', '02:00:5e:10:00:88', 'Studio Mac', null), iso(25 * MIN)),
		{ id: '0a07', protocol: 'ssdp', service_type: null, instance: null, sender: sender('192.168.1.44', '02:00:5e:10:00:44', null, null), last_seen: iso(2 * HOUR) },
	],
} satisfies LocalServicesResponse;

export const LOCAL_SERVICES_EMPTY = { ...WINDOW, truncated: false, rows: [] } satisfies LocalServicesResponse;

export const LOCAL_SERVICES_ROUTES: FixtureRoute[] = [{ path: '/api/local-services', empty: LOCAL_SERVICES_EMPTY, populated: LOCAL_SERVICES }];
