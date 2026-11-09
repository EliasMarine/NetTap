import type {
	Device,
	DeviceCategoriesResponse,
	DeviceConnectionsResponse,
	DeviceCountResponse,
	DeviceDetailResponse,
	DeviceAlertsResponse,
	DeviceListResponse,
	DevicePortsResponse,
} from '../../../src/lib/api/devices.ts';
import type {
	DeviceTraffic,
	RegistryDevice,
	RegistryListResponse,
	getNewDeviceCount,
} from '../../../src/lib/api/devices-registry.ts';
import type { CaptureMode } from '../../../src/lib/api/capture.ts';
import { DAY, MIN, iso, type FixtureRoute } from './types.ts';
import { CONN_TEMPLATES, connections } from './net-connections.ts';
import {
	FLOWS,
	LAN_DEVICES,
	MB,
	WINDOW,
	hourBucket,
	hourly,
	lanDevice,
	peer,
	totalBytes,
	totalsBy,
	type LanDevice,
} from './net-world.ts';

/** The device the id-carrying routes answer for, whatever id the page asks about. */
const FOCUS = lanDevice('192.168.1.20');
const CONNECTIONS_PAGE_SIZE = 25;

const deviceRow = (d: LanDevice): Device => ({
	ip: d.ip,
	mac: d.mac,
	hostname: d.hostname,
	manufacturer: d.vendor,
	os_hint: d.os,
	// The list's first_seen is the first record in its window, not the device's first sighting.
	first_seen: iso(DAY - 10 * MIN),
	last_seen: iso(d.lastSeenAgo),
	total_bytes: totalBytes(d),
	// OLD CODE: orig_bytes: d.origBytes, resp_bytes: d.respBytes, (NET-226: both sides, from the device's side)
	upload_bytes: d.origBytes,
	download_bytes: d.respBytes,
	connection_count: d.connections,
	ipv6_connections: 0,
	ipv6_left_out: 0,
	ipv6_left_out_reason: null,
	protocols: d.protocols,
	alert_count: d.alerts,
	category: d.kind,
	category_basis: d.kind === 'unknown' ? null : 'name',
	os_basis: d.os ? 'web traffic' : null,
});

/** NET-160 slice 2b-3: the list reply is one reading: its rows, the devices before the cut, and the online count by its own clock. */
const reading = (devices: Device[]): Pick<DeviceListResponse, 'devices' | 'total' | 'as_of' | 'online_since' | 'online_total'> => ({
	devices,
	total: devices.length,
	as_of: iso(0),
	online_since: iso(5 * MIN),
	online_total: devices.filter((d) => Date.parse(d.last_seen) >= Date.parse(iso(5 * MIN))).length,
});

const deviceList = (): DeviceListResponse => ({
	...WINDOW,
	limit: 200,
	...reading([...LAN_DEVICES].sort((a, b) => totalBytes(b) - totalBytes(a)).map(deviceRow)),
});

const registryRow = (d: LanDevice): RegistryDevice => ({
	mac: d.mac,
	ips: [d.ip],
	hostnames: [d.hostname],
	manufacturer: d.vendor,
	friendly_name: null,
	display_name: d.hostname,
	category: d.kind,
	first_seen: iso(d.knownFor),
	last_seen: iso(d.lastSeenAgo),
	is_new: d.knownFor < DAY,
});

// ---- one device's detail ---------------------------------------------------------------------

const topDestinations = (ip: string) =>
	totalsBy(
		FLOWS.filter((f) => f.src === ip),
		(f) => f.dst,
		(f) => f.mb * MB,
	).map(([dst, bytes]) => ({
		ip: dst,
		bytes,
		connections: Math.round((peer(dst).connections * bytes) / peer(dst).bytes),
	}));

const DNS_QUERIES = [
	{ domain: 'api.example.org', count: 1420 },
	{ domain: 'cdn.example.net', count: 980 },
	{ domain: 'stream.example.net', count: 640 },
	{ domain: 'updates.example.com', count: 310 },
	{ domain: 'mail.example.com', count: 270 },
	{ domain: 'social.example.net', count: 190 },
];

const detail = (d: LanDevice): DeviceDetailResponse => {
	const destinations = topDestinations(d.ip);
	return {
		device: {
			...deviceRow(d),
			top_destinations: destinations,
			dns_queries: DNS_QUERIES,
			bandwidth_series: hourly((i, share) => {
				const bytes = Math.round(totalBytes(d) * share);
				const upload = Math.round((bytes * d.origBytes) / totalBytes(d));
				return { timestamp: hourBucket(i), bytes, download_bytes: bytes - upload, upload_bytes: upload };
			}),
			unique_destinations: 38,
			top_services: destinations.map((x) => ({ name: peer(x.ip).org, bytes: x.bytes, connections: x.connections })),
		},
	};
};

const emptyDetail = (d: LanDevice): DeviceDetailResponse => ({
	device: {
		...deviceRow(d),
		total_bytes: 0,
		upload_bytes: 0,
		download_bytes: 0,
		connection_count: 0,
		protocols: [],
		alert_count: 0,
		top_destinations: [],
		dns_queries: [],
		bandwidth_series: [],
		unique_destinations: 0,
		top_services: [],
	},
});

const categories = (): DeviceCategoriesResponse => ({
	ip: FOCUS.ip,
	...WINDOW,
	categories: [
		{ name: 'cloud', label: 'Cloud Services', total_bytes: 6200 * MB, connection_count: 3300 },
		{ name: 'web', label: 'Web Browsing', total_bytes: 4100 * MB, connection_count: 2700 },
		{ name: 'streaming', label: 'Streaming', total_bytes: 2400 * MB, connection_count: 410 },
		{ name: 'updates', label: 'Updates & Downloads', total_bytes: 1800 * MB, connection_count: 230 },
		{ name: 'communication', label: 'Communication', total_bytes: 1550 * MB, connection_count: 1040 },
		{ name: 'dns', label: 'DNS', total_bytes: 12 * MB, connection_count: 1560 },
	],
});

const ports = (): DevicePortsResponse => ({
	ip: FOCUS.ip,
	...WINDOW,
	ports: [
		{ port: 443, service: 'https', connections: 6100, suspicious: false },
		{ port: 53, service: 'dns', connections: 2100, suspicious: false },
		{ port: 80, service: 'http', connections: 520, suspicious: false },
		{ port: 993, service: 'imaps', connections: 330, suspicious: false },
		{ port: 22, service: 'ssh', connections: 140, suspicious: false },
		{ port: 123, service: 'ntp', connections: 50, suspicious: false },
	],
});

const deviceConnections = (): DeviceConnectionsResponse => ({
	...WINDOW,
	ip: FOCUS.ip,
	page: 1,
	size: CONNECTIONS_PAGE_SIZE,
	total: FOCUS.connections,
	total_pages: Math.ceil(FOCUS.connections / CONNECTIONS_PAGE_SIZE),
	connections: connections(
		CONN_TEMPLATES.filter((t) => t.src === FOCUS.ip),
		CONNECTIONS_PAGE_SIZE,
	),
});

// ---- the MAC-keyed registry ------------------------------------------------------------------

/** The daemon wraps the record; devices-registry.ts unwraps `device` and `traffic`. */
interface RegistryDeviceEnvelope {
	device: RegistryDevice;
}
interface RegistryTrafficEnvelope {
	from: string;
	to: string;
	traffic: DeviceTraffic;
}

const registryTraffic = (d: LanDevice): RegistryTrafficEnvelope => ({
	...WINDOW,
	traffic: {
		mac: d.mac,
		total_bytes: totalBytes(d),
		inbound_bytes: d.respBytes,
		outbound_bytes: d.origBytes,
		connection_count: d.connections,
		top_destinations: topDestinations(d.ip),
		top_protocols: [
			{ name: 'ssl', count: 5400 },
			{ name: 'dns', count: 2100 },
			{ name: 'quic', count: 1250 },
			{ name: 'http', count: 350 },
			{ name: 'ssh', count: 140 },
		],
	},
});

const emptyRegistryTraffic = (d: LanDevice): RegistryTrafficEnvelope => ({
	...WINDOW,
	traffic: {
		mac: d.mac,
		total_bytes: 0,
		inbound_bytes: 0,
		outbound_bytes: 0,
		connection_count: 0,
		top_destinations: [],
		top_protocols: [],
	},
});

type NewDeviceCount = Awaited<ReturnType<typeof getNewDeviceCount>>;

export const DEVICES_ROUTES: FixtureRoute[] = [
	{
		path: '/api/devices',
		empty: { ...WINDOW, limit: 200, ...reading([]) } satisfies DeviceListResponse,
		populated: deviceList(),
	},
	{
		path: '/api/devices/count',
		empty: { ...WINDOW, count: 0 } satisfies DeviceCountResponse,
		populated: { ...WINDOW, count: LAN_DEVICES.length } satisfies DeviceCountResponse,
	},
	{
		path: '/api/devices/registry',
		empty: { devices: [], total: 0 } satisfies RegistryListResponse,
		populated: { devices: LAN_DEVICES.map(registryRow), total: LAN_DEVICES.length } satisfies RegistryListResponse,
	},
	{
		path: '/api/devices/registry/new-count',
		empty: { count: 0, since: iso(DAY) } satisfies NewDeviceCount,
		populated: { count: LAN_DEVICES.filter((d) => d.knownFor < DAY).length, since: iso(DAY) } satisfies NewDeviceCount,
	},
	{
		// the MAC arrives URL-encoded: /api/devices/registry/02%3A00%3A5e%3A10%3A00%3A20
		path: /^\/api\/devices\/registry\/[^/]+$/,
		empty: { device: registryRow(FOCUS) } satisfies RegistryDeviceEnvelope,
		populated: {
			device: { ...registryRow(FOCUS), total_bytes: totalBytes(FOCUS), connection_count: FOCUS.connections },
		} satisfies RegistryDeviceEnvelope,
	},
	{
		path: /^\/api\/devices\/registry\/[^/]+\/traffic$/,
		empty: emptyRegistryTraffic(FOCUS),
		populated: registryTraffic(FOCUS),
	},
	{
		path: /^\/api\/devices\/[^/]+$/,
		empty: emptyDetail(FOCUS),
		populated: detail(FOCUS),
	},
	{
		path: /^\/api\/devices\/[^/]+\/categories$/,
		empty: { ip: FOCUS.ip, ...WINDOW, categories: [] } satisfies DeviceCategoriesResponse,
		populated: categories(),
	},
	{
		path: /^\/api\/devices\/[^/]+\/connections$/,
		empty: {
			...WINDOW,
			ip: FOCUS.ip,
			page: 1,
			size: CONNECTIONS_PAGE_SIZE,
			total: 0,
			total_pages: 0,
			connections: [],
		} satisfies DeviceConnectionsResponse,
		populated: deviceConnections(),
	},
	{
		path: /^\/api\/devices\/[^/]+\/ports$/,
		empty: { ip: FOCUS.ip, ...WINDOW, ports: [] } satisfies DevicePortsResponse,
		populated: ports(),
	},
	{
		// No alerts in either mode: the focus device is a quiet laptop.
		path: /^\/api\/devices\/[^/]+\/alerts$/,
		empty: { ip: FOCUS.ip, ...WINDOW, total: 0, alerts: [] } satisfies DeviceAlertsResponse,
	},
];

// ---- By type in mirror mode: a band of cards that used to misalign (NET-180) -------------------

/**
 * devices-layout.visual.ts serves these in place of the registry and the device list (the
 * fixture's capture mode is bridge, so By type shows no cards otherwise). Four computers, seen
 * more recently than the fixture's own, so they fill the Computers group's first band: no maker,
 * an addresses note (2 of 3 listed), a long maker that wraps and a connection count that wraps,
 * and a short count beside it in the next band (or the same band at two cards a row).
 */
const BAND = [
	{ mac: '02:00:5e:10:00:40', ips: ['192.168.1.40'], name: 'DESKTOP-1H4Q4HV', maker: null, bytes: 640 * MB, connections: 812, ago: 2_000 },
	{ mac: '02:00:5e:10:00:41', ips: ['192.168.1.41', '192.168.1.141', '10.10.0.41'], name: 'work-laptop.example.com', maker: 'Example Corp', bytes: 2300 * MB, connections: 4100, ago: 3_000 },
	{ mac: '02:00:5e:10:00:42', ips: ['192.168.1.42'], name: 'build-server.example.com', maker: 'Example Very Long Manufacturer Name Holdings International', bytes: 9800 * MB, connections: 1_234_567_890_123, ago: 4_000 },
	{ mac: '02:00:5e:10:00:43', ips: ['192.168.1.43'], name: 'mac-mini.example.com', maker: 'Example Corp', bytes: 12 * MB, connections: 7, ago: 5_000 },
] as const;

const bandRegistryRow = (d: (typeof BAND)[number]): RegistryDevice => ({
	mac: d.mac,
	ips: [...d.ips],
	hostnames: [d.name],
	manufacturer: d.maker,
	friendly_name: null,
	display_name: d.name,
	category: 'computer',
	first_seen: iso(90 * DAY),
	last_seen: iso(d.ago),
	is_new: false,
});

/** One list row per listed address: the work laptop's third address isn't listed. */
const bandListRows = (d: (typeof BAND)[number]): Device[] =>
	d.ips.slice(0, 2).map((ip, i, listed) => ({
		ip,
		mac: d.mac,
		hostname: d.name,
		manufacturer: d.maker,
		os_hint: null,
		first_seen: iso(DAY - 10 * MIN),
		last_seen: iso(d.ago + i * MIN),
		total_bytes: Math.round(d.bytes / listed.length),
		connection_count: Math.round(d.connections / listed.length),
		protocols: ['ssl', 'dns'],
		alert_count: 0,
		category: 'computer',
	}));

/** Mirror mode, with the fixture's registry and list plus the band. */
export const BY_TYPE_LAYOUT = {
	mode: { mode: 'mirror', interface: 'enp1s0' } satisfies CaptureMode,
	registry: {
		devices: [...BAND.map(bandRegistryRow), ...LAN_DEVICES.map(registryRow)],
		total: BAND.length + LAN_DEVICES.length,
	} satisfies RegistryListResponse,
	list: { ...deviceList(), ...reading([...BAND.flatMap(bandListRows), ...deviceList().devices]) } satisfies DeviceListResponse,
};
