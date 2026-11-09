/**
 * Live Monitor (/api/live/dashboard). Populated has destinations with lat/lon on three
 * continents, and an alerting connection to NL, so DotMap draws hotspots on each.
 */
import type { GeoArc, LiveConnection, LiveDashboardResponse } from '../../../src/lib/api/live.ts';
import { iso, type FixtureRoute } from './types.ts';

const ARCS: GeoArc[] = [
	{ city: 'Amsterdam', country: 'Netherlands', country_code: 'NL', lat: 52.37, lon: 4.9, count: 42, bytes: 18_000_000 },
	{ city: 'Frankfurt', country: 'Germany', country_code: 'DE', lat: 50.11, lon: 8.68, count: 30, bytes: 9_500_000 },
	{ city: 'Tokyo', country: 'Japan', country_code: 'JP', lat: 35.68, lon: 139.69, count: 12, bytes: 4_200_000 },
	{ city: 'Sao Paulo', country: 'Brazil', country_code: 'BR', lat: -23.55, lon: -46.63, count: 8, bytes: 2_100_000 },
	{ city: 'Seattle', country: 'United States', country_code: 'US', lat: 47.61, lon: -122.33, count: 65, bytes: 31_000_000 },
	{ city: 'Sydney', country: 'Australia', country_code: 'AU', lat: -33.87, lon: 151.21, count: 5, bytes: 900_000 },
];

function conn(i: number, arc: GeoArc, dest: string, hasAlert: boolean): LiveConnection {
	return {
		timestamp: iso(i * 4_000 + 1_500 + i * 1_000),
		// NET-237: the feed shows and sorts by the end; the start is duration earlier
		ended_at: iso(i * 4_000),
		source_ip: `192.168.1.${20 + (i % 4)}`,
		source_port: 50_000 + i,
		dest_ip: dest,
		dest_port: 443,
		protocol: 'tcp',
		service: 'ssl',
		bytes: 40_000 + i * 1_500,
		duration: 1.5 + i,
		country: arc.country_code,
		country_name: arc.country,
		device_name: `device-${20 + (i % 4)}.example.com`,
		dest_lat: arc.lat,
		dest_lon: arc.lon,
		dest_city: arc.city,
		dest_asn: 64_496 + i,
		dest_org: 'Example Hosting',
		geo_ip: dest,
		has_alert: hasAlert,
		direction: 'out',
	};
}

/** An internet address reaching a LAN device (a port forward): the place is the source's. */
function inbound(i: number, arc: GeoArc, src: string): LiveConnection {
	return { ...conn(i, arc, '192.168.1.30', false), source_ip: src, source_port: 40_000 + i, dest_port: 22, geo_ip: src, direction: 'in', device_name: '' };
}

const CONNECTIONS = [
	conn(0, ARCS[0], '198.51.100.23', true),
	conn(1, ARCS[1], '203.0.113.5', false),
	conn(2, ARCS[2], '192.0.2.44', false),
	conn(3, ARCS[3], '198.51.100.80', false),
	conn(4, ARCS[4], '203.0.113.90', false),
	conn(5, ARCS[5], '192.0.2.10', false),
	inbound(6, ARCS[2], '198.51.100.140'),
];

export const LIVE_ROUTES: FixtureRoute[] = [
	{
		path: '/api/live/dashboard',
		empty: {
			connections: [],
			count: 0,
			stats: { connections_per_second: 0, bandwidth_bytes_per_second: 0, active_devices: 0, top_country: '', connections_in_window: 0 },
			protocols: {},
			top_talkers: [],
			geo_arcs: [],
		} satisfies LiveDashboardResponse,
		populated: {
			connections: CONNECTIONS,
			count: CONNECTIONS.length,
			stats: { connections_per_second: 3.2, bandwidth_bytes_per_second: 1_250_000, active_devices: 4, top_country: 'US', connections_in_window: 162 },
			protocols: { tcp: 120, udp: 38, icmp: 4 },
			top_talkers: [
				{ ip: '192.168.1.20', bytes: 31_000_000, connections: 70 },
				{ ip: '192.168.1.21', bytes: 18_000_000, connections: 44 },
				{ ip: '192.168.1.22', bytes: 9_500_000, connections: 30 },
			],
			geo_arcs: ARCS,
		} satisfies LiveDashboardResponse,
	},
];
