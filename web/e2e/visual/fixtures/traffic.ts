import type {
	BandwidthPoint,
	BandwidthResponse,
	CategoriesResponse,
	CategoryBandwidthResponse,
	CategoryDetailResponse,
	ConnectionStatsResponse,
	ConnectionTimelineResponse,
	ConnectionsResponse,
	ProtocolsResponse,
	RelatedConnectionsResponse,
	SankeyResponse,
	TopTalkersResponse,
	TrafficCategory,
	TrafficSummary,
} from '../../../src/lib/api/traffic.ts';
import type { FixtureRoute } from './types.ts';
import { CONN_TEMPLATES, connections } from './net-connections.ts';
import {
	FLOWS,
	LAN_DEVICES,
	MB,
	PEERS,
	WINDOW,
	asnFull,
	hourBucket,
	hourly,
	lanDevice,
	peer,
	sum,
	totalBytes,
	totalsBy,
} from './net-world.ts';

const TOTAL_ORIG = sum(LAN_DEVICES.map((d) => d.origBytes));
const TOTAL_RESP = sum(LAN_DEVICES.map((d) => d.respBytes));
const TOTAL = TOTAL_ORIG + TOTAL_RESP;
const SESSIONS = sum(LAN_DEVICES.map((d) => d.connections));

const summary = {
	...WINDOW,
	total_bytes: TOTAL,
	orig_bytes: TOTAL_ORIG,
	resp_bytes: TOTAL_RESP,
	// NET-226: every flow in this world runs from a LAN device to the internet
	upload_bytes: TOTAL_ORIG,
	download_bytes: TOTAL_RESP,
	local_bytes: 0,
	packet_count: Math.round(TOTAL / 820),
	connection_count: SESSIONS,
	top_protocol: 'tcp',
	excluded_ips: [],
} satisfies TrafficSummary;

const emptySummary = {
	...WINDOW,
	total_bytes: 0,
	orig_bytes: 0,
	resp_bytes: 0,
	upload_bytes: 0,
	download_bytes: 0,
	local_bytes: 0,
	packet_count: 0,
	connection_count: 0,
	top_protocol: 'unknown',
	excluded_ips: [],
} satisfies TrafficSummary;

const bandwidthSeries: BandwidthPoint[] = hourly((i, share) => {
	const total = Math.round(TOTAL * share);
	const orig = Math.round((total * TOTAL_ORIG) / TOTAL);
	return {
		timestamp: hourBucket(i),
		orig_bytes: orig,
		resp_bytes: total - orig,
		upload_bytes: orig,
		download_bytes: total - orig,
		local_bytes: 0,
		total_bytes: total,
		connections: Math.round(SESSIONS * share),
	};
});

// Counts add up to SESSIONS.
const SERVICES = [
	{ name: 'ssl', count: 10900 },
	{ name: 'dns', count: 5400 },
	{ name: 'quic', count: 2950 },
	{ name: 'http', count: 1980 },
	{ name: 'ntp', count: 420 },
	{ name: 'ssh', count: 310 },
	{ name: 'dhcp', count: 56 },
	{ name: 'unknown', count: 1804 },
];
const TRANSPORTS = [
	{ name: 'tcp', count: 17900 },
	{ name: 'udp', count: 5800 },
	{ name: 'icmp', count: 120 },
];

// ---- categories: built from the external hosts so every page agrees on the numbers ----------

interface CategoryDef {
	name: string;
	label: string;
	peers: string[];
	/** traffic the hosts above do not account for (local chatter, DNS) */
	extraBytes: number;
	extraConnections: number;
}

const CATEGORY_DEFS: readonly CategoryDef[] = [
	{ name: 'streaming', label: 'Streaming', peers: ['198.51.100.10', '198.51.100.20'], extraBytes: 0, extraConnections: 0 },
	{ name: 'cloud', label: 'Cloud Services', peers: ['203.0.113.15'], extraBytes: 0, extraConnections: 0 },
	{ name: 'web', label: 'Web Browsing', peers: ['198.51.100.77'], extraBytes: 0, extraConnections: 0 },
	{ name: 'social', label: 'Social Media', peers: ['192.0.2.50'], extraBytes: 0, extraConnections: 0 },
	{ name: 'updates', label: 'Updates & Downloads', peers: ['203.0.113.40'], extraBytes: 0, extraConnections: 0 },
	{ name: 'iot', label: 'IoT & Smart Home', peers: ['192.0.2.80'], extraBytes: 0, extraConnections: 0 },
	{ name: 'communication', label: 'Communication', peers: ['203.0.113.99'], extraBytes: 0, extraConnections: 0 },
	{ name: 'dns', label: 'DNS', peers: [], extraBytes: 210 * MB, extraConnections: 5400 },
	{ name: 'other', label: 'Other', peers: [], extraBytes: 2220 * MB, extraConnections: 1710 },
];

function toCategory(def: CategoryDef): TrafficCategory {
	const hosts = def.peers.map(peer);
	return {
		name: def.name,
		label: def.label,
		total_bytes: sum(hosts.map((p) => p.bytes)) + def.extraBytes,
		connection_count: sum(hosts.map((p) => p.connections)) + def.extraConnections,
		top_services: hosts.map((p) => ({ name: p.org, bytes: p.bytes, connections: p.connections })),
	};
}

const CATEGORIES = CATEGORY_DEFS.map(toCategory).sort((a, b) => b.total_bytes - a.total_bytes);
const STREAMING_DEF = CATEGORY_DEFS[0];
const STREAMING = toCategory(STREAMING_DEF);

const streamingDetail = (): CategoryDetailResponse => {
	const perDevice = totalsBy(
		FLOWS.filter((f) => STREAMING_DEF.peers.includes(f.dst)),
		(f) => f.src,
		(f) => f.mb * MB,
	);
	return {
		category: STREAMING.name,
		label: STREAMING.label,
		device_count: perDevice.length,
		total_bytes: STREAMING.total_bytes,
		connection_count: STREAMING.connection_count,
		devices: perDevice.map(([ip, bytes]) => {
			const upload = Math.round(bytes * 0.04);
			return {
				ip,
				hostname: lanDevice(ip).hostname,
				total_bytes: bytes,
				download_bytes: bytes - upload,
				upload_bytes: upload,
				connections: Math.round((STREAMING.connection_count * bytes) / STREAMING.total_bytes),
				percent: Math.round((bytes / STREAMING.total_bytes) * 1000) / 10,
			};
		}),
		services: STREAMING.top_services,
	};
};

const streamingBandwidth = (): CategoryBandwidthResponse => ({
	category: STREAMING.name,
	...WINDOW,
	interval: '1h',
	series: hourly((i, share) => {
		const total = Math.round(STREAMING.total_bytes * share);
		const upload = Math.round(total * 0.04);
		return {
			timestamp: hourBucket(i),
			download_bytes: total - upload,
			upload_bytes: upload,
			total_bytes: total,
			connections: Math.round(STREAMING.connection_count * share),
		};
	}),
});

// ---- connections ----------------------------------------------------------------------------

const PAGE_SIZE = 50;
const connectionPage = (): ConnectionsResponse => ({
	...WINDOW,
	page: 1,
	size: PAGE_SIZE,
	total: SESSIONS,
	total_pages: Math.ceil(SESSIONS / PAGE_SIZE),
	connections: connections(CONN_TEMPLATES, PAGE_SIZE),
});

const connectionStats = (): ConnectionStatsResponse => ({
	...WINDOW,
	total_sessions: SESSIONS,
	bytes_in: TOTAL_RESP,
	bytes_out: TOTAL_ORIG,
	alert_sessions: 14,
	protocols: SERVICES.slice(0, 5),
	top_sources: [...LAN_DEVICES]
		.sort((a, b) => totalBytes(b) - totalBytes(a))
		.map((d) => ({ ip: d.ip, total_bytes: totalBytes(d), connections: d.connections })),
	top_destinations: [...PEERS]
		.sort((a, b) => b.bytes - a.bytes)
		.map((p) => ({ ip: p.ip, total_bytes: p.bytes, connections: p.connections, asn: asnFull(p), country: p.countryCode })),
});

// OLD CODE START — NET-151: services as protocols and complete flows, so the Network flow chart
// never met transports, an Other destinations node, unnamed devices or crowded labels
// const sankey = (): SankeyResponse => {
// 	const bytes = (mb: number) => mb * MB;
// 	const toProtocol = totalsBy(FLOWS, (f) => `${f.src}→${peer(f.dst).service}`, (f) => bytes(f.mb));
// 	const toDestination = totalsBy(FLOWS, (f) => `${peer(f.dst).service}→${asnFull(peer(f.dst))}`, (f) => bytes(f.mb));
// 	const link = ([key, value]: [string, number]) => {
// 		const [source, target] = key.split('→');
// 		return { source, target, value };
// 	};
// 	return {
// 		...WINDOW,
// 		nodes: {
// 			sources: totalsBy(FLOWS, (f) => f.src, (f) => bytes(f.mb)).map(([ip, value]) => ({ id: ip, label: ip, value })),
// 			protocols: totalsBy(FLOWS, (f) => peer(f.dst).service, (f) => bytes(f.mb)).map(([name, value]) => ({
// 				id: name,
// 				label: name.toUpperCase(),
// 				value,
// 			})),
// 			destinations: totalsBy(FLOWS, (f) => f.dst, (f) => bytes(f.mb)).map(([ip, value]) => ({
// 				id: asnFull(peer(ip)),
// 				label: peer(ip).org,
// 				value,
// 				country: peer(ip).countryCode,
// 			})),
// 		},
// 		links: [...toProtocol, ...toDestination].map(link),
// 	};
// };
// OLD CODE END

/**
 * The Network flow in production's shape, crowded on purpose (NET-151): 10 sources (the 6 LAN
 * devices, which the registry names, and 4 addresses it doesn't know), one source with ~60 % of
 * the bytes and some under 0.5 %, transports as protocols, and 10 destinations (two with long
 * names) that cover ~80 % of the bytes, so the chart draws Other destinations.
 */
export const UNNAMED_SOURCES = ['192.168.1.60', '192.168.1.61', '192.168.1.62', '192.168.1.63'] as const;
const FLOW_SOURCES: [ip: string, mb: Record<string, number>][] = [
	['192.168.1.22', { tcp: 3000, udp: 9000 }],
	['192.168.1.20', { tcp: 2400, udp: 600 }],
	['192.168.1.30', { tcp: 1800, udp: 200 }],
	['192.168.1.21', { tcp: 900, udp: 600 }],
	['192.168.1.50', { tcp: 800, udp: 100, icmp: 2 }],
	['192.168.1.60', { tcp: 300, udp: 120 }],
	['192.168.1.61', { tcp: 100, icmp: 1 }],
	['192.168.1.31', { tcp: 40, udp: 20 }],
	['192.168.1.62', { tcp: 12, udp: 3 }],
	['192.168.1.63', { tcp: 2 }],
];
// The first seven peers' bytes by transport, in MB
const PEER_FLOWS: Record<string, number>[] = [
	{ udp: 6000, tcp: 1000 },
	{ tcp: 1500, udp: 400 },
	{ tcp: 1400 },
	{ tcp: 1200 },
	{ tcp: 900, udp: 100 },
	{ tcp: 200, udp: 50 },
	{ tcp: 150, udp: 40 },
];
const longName = (asn: number, org: string, country: string, mb: Record<string, number>) => ({ id: `AS${asn} ${org}`, label: org, country, mb });
const FLOW_DESTINATIONS: { id: string; label: string; country: string; mb: Record<string, number> }[] = [
	...PEER_FLOWS.map((mb, i) => ({ id: asnFull(PEERS[i]), label: PEERS[i].org, country: PEERS[i].countryCode, mb })),
	{ id: 'Unknown', label: 'Unknown', country: '', mb: { udp: 2000, tcp: 600 } },
	longName(64510, 'Example International Aeronautical Telecommunications Society SC', 'CH', { tcp: 400, icmp: 2 }),
	longName(64511, 'Example Regional Broadband and Fibre Communications Cooperative Ltd', 'GB', { udp: 300, tcp: 50 }),
];

export const networkFlow = (): SankeyResponse => {
	const total = (by: Record<string, number>) => sum(Object.values(by)) * MB;
	const protocolTotals = totalsBy(FLOW_SOURCES.flatMap(([, by]) => Object.entries(by)), ([p]) => p, ([, mb]) => mb * MB);
	return {
		...WINDOW,
		nodes: {
			sources: FLOW_SOURCES.map(([ip, by]) => ({ id: ip, label: ip, value: total(by) })),
			protocols: protocolTotals.map(([id, value]) => ({ id, label: id.toUpperCase(), value })),
			destinations: FLOW_DESTINATIONS.map((d) => ({ id: d.id, label: d.label, value: total(d.mb), country: d.country })),
		},
		links: [
			...FLOW_SOURCES.flatMap(([ip, by]) => Object.entries(by).map(([p, mb]) => ({ source: ip, target: p, value: mb * MB }))),
			...FLOW_DESTINATIONS.flatMap((d) => Object.entries(d.mb).map(([p, mb]) => ({ source: p, target: d.id, value: mb * MB }))),
		],
	};
};

const connectionTimeline = (): ConnectionTimelineResponse => ({
	...WINDOW,
	interval: '1h',
	buckets: hourly((i, share) => {
		const total = Math.round(SESSIONS * share);
		const tcp = Math.round((total * 17900) / SESSIONS);
		const icmp = Math.round((total * 120) / SESSIONS);
		return { timestamp: hourBucket(i), total, protocols: { tcp, udp: total - tcp - icmp, icmp } };
	}),
});

// The streaming TV's sessions with its CDN, the pair the drawer's "related" view opens for.
const related = (): RelatedConnectionsResponse => {
	const rows = connections(CONN_TEMPLATES, PAGE_SIZE).filter(
		(c) => c.source?.ip === '192.168.1.22' && c.destination?.ip === '198.51.100.10',
	);
	return {
		...WINDOW,
		src_ip: '192.168.1.22',
		dst_ip: '198.51.100.10',
		total_connections: rows.length,
		total_bytes: sum(rows.map((c) => (c.source?.bytes ?? 0) + (c.destination?.bytes ?? 0))),
		protocols: [...new Set(rows.map((c) => c.network?.protocol ?? 'unknown'))],
		first_seen: rows.at(-1)?.['@timestamp'] ?? null,
		last_seen: rows[0]?.['@timestamp'] ?? null,
		connections: rows,
	};
};

export const TRAFFIC_ROUTES: FixtureRoute[] = [
	{
		path: '/api/traffic/summary',
		empty: emptySummary,
		populated: summary,
	},
	{
		path: '/api/traffic/bandwidth',
		empty: { ...WINDOW, interval: '1h', series: [] } satisfies BandwidthResponse,
		populated: { ...WINDOW, interval: '1h', series: bandwidthSeries } satisfies BandwidthResponse,
	},
	{
		path: '/api/traffic/protocols',
		empty: {
			...WINDOW,
			protocols: [],
			services: [],
			encryption: { eligible: 0, encrypted: 0 },
			dns: { plain: 0, over_tls: 0 },
			unidentified: { conversations: 0, one_way: 0, icmp: 0 },
		} satisfies ProtocolsResponse,
		populated: {
			...WINDOW,
			protocols: TRANSPORTS,
			services: SERVICES,
			encryption: { eligible: 21300, encrypted: 19800 },
			dns: { plain: 5400, over_tls: 60 },
			// adds up to the unknown service (1,804); icmp matches the ICMP transport count
			unidentified: { conversations: 644, one_way: 1040, icmp: 120 },
		} satisfies ProtocolsResponse,
	},
	{
		path: '/api/traffic/top-talkers',
		empty: { ...WINDOW, limit: 10, top_talkers: [] } satisfies TopTalkersResponse,
		populated: {
			...WINDOW,
			limit: 10,
			top_talkers: [...LAN_DEVICES]
				.sort((a, b) => totalBytes(b) - totalBytes(a))
				.map((d) => ({ ip: d.ip, total_bytes: totalBytes(d), connection_count: d.connections })),
		} satisfies TopTalkersResponse,
	},
	{
		path: '/api/traffic/categories',
		empty: { ...WINDOW, categories: [] } satisfies CategoriesResponse,
		populated: { ...WINDOW, categories: CATEGORIES } satisfies CategoriesResponse,
	},
	{
		// Same record for any category name: the fixtures only model "streaming" in detail.
		path: /^\/api\/traffic\/categories\/[^/]+$/,
		empty: {
			category: 'streaming',
			label: 'Streaming',
			device_count: 0,
			total_bytes: 0,
			connection_count: 0,
			devices: [],
			services: [],
		} satisfies CategoryDetailResponse,
		populated: streamingDetail(),
	},
	{
		path: /^\/api\/traffic\/categories\/[^/]+\/bandwidth$/,
		empty: { category: 'streaming', ...WINDOW, interval: '1h', series: [] } satisfies CategoryBandwidthResponse,
		populated: streamingBandwidth(),
	},
	{
		path: '/api/traffic/connections',
		empty: {
			...WINDOW,
			page: 1,
			size: PAGE_SIZE,
			total: 0,
			total_pages: 0,
			connections: [],
		} satisfies ConnectionsResponse,
		populated: connectionPage(),
	},
	{
		path: '/api/traffic/connections/stats',
		empty: {
			...WINDOW,
			total_sessions: 0,
			bytes_in: 0,
			bytes_out: 0,
			alert_sessions: 0,
			protocols: [],
			top_sources: [],
			top_destinations: [],
		} satisfies ConnectionStatsResponse,
		populated: connectionStats(),
	},
	{
		path: '/api/traffic/connections/sankey',
		empty: {
			...WINDOW,
			nodes: { sources: [], protocols: [], destinations: [] },
			links: [],
		} satisfies SankeyResponse,
		populated: networkFlow(),
	},
	{
		path: '/api/traffic/connections/timeline',
		empty: { ...WINDOW, interval: '1h', buckets: [] } satisfies ConnectionTimelineResponse,
		populated: connectionTimeline(),
	},
	{
		path: '/api/traffic/connections/related',
		empty: {
			...WINDOW,
			src_ip: '192.168.1.22',
			dst_ip: '198.51.100.10',
			total_connections: 0,
			total_bytes: 0,
			protocols: [],
			first_seen: null,
			last_seen: null,
			connections: [],
		} satisfies RelatedConnectionsResponse,
		populated: related(),
	},
];
