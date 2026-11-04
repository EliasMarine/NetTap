/**
 * The synthetic home network behind the traffic, device, bandwidth, DNS, IoT, GeoIP and log
 * fixtures: six LAN devices and eight external hosts, so every page tells the same story.
 * Addresses are RFC 1918 (LAN) and RFC 5737 (external); names are *.example.*; ASNs are the
 * RFC 5398 documentation range.
 */
import { DAY, HOUR, NOW, iso } from './types.ts';

export const MB = 1024 ** 2;
export const GB = 1024 ** 3;

/** The 24 h window a list endpoint reports when the request names no range. */
export const WINDOW = { from: iso(DAY), to: iso(0) };

export const sum = (xs: readonly number[]): number => xs.reduce((a, b) => a + b, 0);

export type DeviceKind = 'computer' | 'phone' | 'iot' | 'infrastructure' | 'unknown';

export interface LanDevice {
	ip: string;
	mac: string;
	hostname: string;
	vendor: string;
	os: string | null;
	kind: DeviceKind;
	/** 24 h bytes the device sent / received */
	origBytes: number;
	respBytes: number;
	connections: number;
	protocols: string[];
	alerts: number;
	/** ms since the registry first saw it, and since its last record */
	knownFor: number;
	lastSeenAgo: number;
}

/** The IP's last octet is the MAC's last byte, so `192.168.1.20` is `02:00:5e:10:00:20`. */
export const LAN_DEVICES: readonly LanDevice[] = [
	{ ip: '192.168.1.22', mac: '02:00:5e:10:00:22', hostname: 'tv-livingroom.example.com', vendor: 'Example Electronics', os: null, kind: 'iot', origBytes: 610 * MB, respBytes: 24100 * MB, connections: 1860, protocols: ['ssl', 'quic', 'dns'], alerts: 0, knownFor: 120 * DAY, lastSeenAgo: 40_000 },
	{ ip: '192.168.1.20', mac: '02:00:5e:10:00:20', hostname: 'laptop-01.example.com', vendor: 'Example Corp', os: 'Linux', kind: 'computer', origBytes: 1640 * MB, respBytes: 17200 * MB, connections: 9240, protocols: ['ssl', 'dns', 'quic', 'ssh', 'http'], alerts: 0, knownFor: 200 * DAY, lastSeenAgo: 12_000 },
	{ ip: '192.168.1.30', mac: '02:00:5e:10:00:30', hostname: 'desktop-02.example.com', vendor: 'Example Corp', os: 'Windows', kind: 'computer', origBytes: 1230 * MB, respBytes: 8700 * MB, connections: 6420, protocols: ['ssl', 'dns', 'http', 'ssh'], alerts: 0, knownFor: 200 * DAY, lastSeenAgo: 25_000 },
	{ ip: '192.168.1.21', mac: '02:00:5e:10:00:21', hostname: 'phone-01.example.com', vendor: 'Example Mobile Inc', os: 'Android', kind: 'phone', origBytes: 520 * MB, respBytes: 3890 * MB, connections: 5110, protocols: ['ssl', 'quic', 'dns'], alerts: 0, knownFor: 90 * DAY, lastSeenAgo: 8_000 },
	{ ip: '192.168.1.50', mac: '02:00:5e:10:00:50', hostname: 'camera-01.example.com', vendor: 'Example Cameras Inc', os: null, kind: 'iot', origBytes: 2150 * MB, respBytes: 105 * MB, connections: 880, protocols: ['ssl', 'dns', 'http'], alerts: 2, knownFor: 6 * HOUR, lastSeenAgo: 5_000 },
	{ ip: '192.168.1.31', mac: '02:00:5e:10:00:31', hostname: 'thermostat-01.example.com', vendor: 'Example Home Systems', os: null, kind: 'iot', origBytes: 38 * MB, respBytes: 47 * MB, connections: 310, protocols: ['ssl', 'dns', 'ntp'], alerts: 0, knownFor: 300 * DAY, lastSeenAgo: 90_000 },
];

export const totalBytes = (d: { origBytes: number; respBytes: number }): number => d.origBytes + d.respBytes;

export function lanDevice(ip: string): LanDevice {
	const found = LAN_DEVICES.find((d) => d.ip === ip);
	if (!found) throw new Error(`fixture world has no LAN device ${ip}`);
	return found;
}

export interface Peer {
	ip: string;
	host: string;
	org: string;
	asn: number;
	countryCode: string;
	country: string;
	city: string;
	latitude: number;
	longitude: number;
	/** 24 h traffic to this host, and the Zeek service carrying most of it */
	bytes: number;
	connections: number;
	service: string;
}

export const asnFull = (p: Peer): string => `AS${p.asn} ${p.org}`;

export const PEERS: readonly Peer[] = [
	{ ip: '198.51.100.10', host: 'stream.example.net', org: 'Example Streaming CDN', asn: 64501, countryCode: 'US', country: 'United States', city: 'Ashburn', latitude: 39.04, longitude: -77.49, bytes: 18200 * MB, connections: 1980, service: 'ssl' },
	{ ip: '198.51.100.20', host: 'video.example.com', org: 'Example Video Inc', asn: 64502, countryCode: 'US', country: 'United States', city: 'Seattle', latitude: 47.61, longitude: -122.33, bytes: 8200 * MB, connections: 920, service: 'quic' },
	{ ip: '203.0.113.15', host: 'api.example.org', org: 'Example Cloud Services', asn: 64503, countryCode: 'DE', country: 'Germany', city: 'Frankfurt', latitude: 50.11, longitude: 8.68, bytes: 8300 * MB, connections: 3300, service: 'ssl' },
	{ ip: '198.51.100.77', host: 'cdn.example.net', org: 'Example CDN', asn: 64507, countryCode: 'NL', country: 'Netherlands', city: 'Amsterdam', latitude: 52.37, longitude: 4.9, bytes: 7600 * MB, connections: 4600, service: 'ssl' },
	{ ip: '192.0.2.50', host: 'social.example.net', org: 'Example Social', asn: 64505, countryCode: 'IE', country: 'Ireland', city: 'Dublin', latitude: 53.35, longitude: -6.26, bytes: 5800 * MB, connections: 2600, service: 'ssl' },
	{ ip: '203.0.113.40', host: 'updates.example.com', org: 'Example Software Updates', asn: 64504, countryCode: 'GB', country: 'United Kingdom', city: 'London', latitude: 51.51, longitude: -0.13, bytes: 4900 * MB, connections: 640, service: 'http' },
	{ ip: '192.0.2.80', host: 'telemetry.example.org', org: 'Example IoT Cloud', asn: 64506, countryCode: 'SG', country: 'Singapore', city: 'Singapore', latitude: 1.35, longitude: 103.82, bytes: 2650 * MB, connections: 1190, service: 'ssl' },
	{ ip: '203.0.113.99', host: 'mail.example.com', org: 'Example Mail', asn: 64508, countryCode: 'CA', country: 'Canada', city: 'Toronto', latitude: 43.65, longitude: -79.38, bytes: 2150 * MB, connections: 1480, service: 'ssl' },
];

export function peer(ip: string): Peer {
	const found = PEERS.find((p) => p.ip === ip);
	if (!found) throw new Error(`fixture world has no external host ${ip}`);
	return found;
}

/** Who talked to whom in the 24 h: the Sankey, category and device breakdowns all derive from these. */
export interface Flow {
	src: string;
	dst: string;
	mb: number;
}

/** Per-peer sums match `PEERS[].bytes` (streaming 18200 + 8200, cloud 8300, ...). */
export const FLOWS: readonly Flow[] = [
	{ src: '192.168.1.22', dst: '198.51.100.10', mb: 15800 },
	{ src: '192.168.1.22', dst: '198.51.100.20', mb: 8200 },
	{ src: '192.168.1.20', dst: '198.51.100.10', mb: 2400 },
	{ src: '192.168.1.20', dst: '203.0.113.15', mb: 6200 },
	{ src: '192.168.1.30', dst: '203.0.113.15', mb: 2100 },
	{ src: '192.168.1.20', dst: '198.51.100.77', mb: 4100 },
	{ src: '192.168.1.30', dst: '198.51.100.77', mb: 3500 },
	{ src: '192.168.1.21', dst: '192.0.2.50', mb: 3800 },
	{ src: '192.168.1.30', dst: '192.0.2.50', mb: 2000 },
	{ src: '192.168.1.20', dst: '203.0.113.40', mb: 1800 },
	{ src: '192.168.1.30', dst: '203.0.113.40', mb: 3100 },
	{ src: '192.168.1.50', dst: '192.0.2.80', mb: 2150 },
	{ src: '192.168.1.31', dst: '192.0.2.80', mb: 85 },
	{ src: '192.168.1.22', dst: '192.0.2.80', mb: 415 },
	{ src: '192.168.1.21', dst: '203.0.113.99', mb: 600 },
	{ src: '192.168.1.20', dst: '203.0.113.99', mb: 1550 },
];

/** Sum `value` per `key`, largest first. */
export function totalsBy<T>(rows: readonly T[], key: (row: T) => string, value: (row: T) => number): Array<[string, number]> {
	const totals = new Map<string, number>();
	for (const row of rows) totals.set(key(row), (totals.get(key(row)) ?? 0) + value(row));
	return [...totals].sort((a, b) => b[1] - a[1]);
}

/**
 * Relative weight of each of 24 hourly buckets, oldest first (also read as hour of day 0..23):
 * quiet night, evening peak. Indexed by position, so the chart shape never depends on the clock.
 */
export const HOURLY_WEIGHTS: readonly number[] = [2, 1, 1, 1, 1, 2, 3, 4, 4, 4, 5, 5, 6, 5, 5, 5, 6, 7, 8, 10, 11, 10, 7, 4];
const WEIGHT_SUM = sum(HOURLY_WEIGHTS);

/** ISO start of hourly bucket `i` (0 oldest, 23 the current hour), aligned to the clock hour as a date histogram is. */
export const hourBucket = (i: number): string => iso((NOW % HOUR) + (HOURLY_WEIGHTS.length - 1 - i) * HOUR);

/** One entry per hourly bucket; `share` is that bucket's fraction of the day (the shares sum to 1). */
export function hourly<T>(build: (i: number, share: number) => T): T[] {
	return HOURLY_WEIGHTS.map((w, i) => build(i, w / WEIGHT_SUM));
}
