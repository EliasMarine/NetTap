import type {
	LogProtocolBreakdownResponse,
	LogStatsResponse,
	LogTimelineResponse,
	LogTopDestinationsResponse,
	LogTopDnsResponse,
	LogTopTalkersResponse,
} from '../../../src/lib/api/logs.ts';
import type { FixtureRoute } from './types.ts';
import { CONN_TEMPLATES, connection } from './net-connections.ts';
import { LAN_DEVICES, PEERS, WINDOW, hourBucket, hourly, sum, totalBytes } from './net-world.ts';

// logs/+page.svelte and the drawers read these two with local types, so mirror what the daemon
// sends (daemon/api/logs.py handle_log_search / handle_log_fields).
interface LogSearchResponse {
	hits: Array<{ _id: string; _index: string; _source: Record<string, unknown> }>;
	total: number;
	search_after: unknown[] | null;
	size: number;
	log_type: string;
}
interface LogFieldsResponse {
	log_type: string;
	fields: Array<{ name: string; type: string; description: string; example: string }>;
}

/** 24 h event counts per Zeek/Suricata log type. */
const LOG_COUNTS = { conn: 23820, dns: 5400, http: 1980, ssl: 10900, files: 210, dhcp: 56, smtp: 40, alert: 14 };
const LABELS: Record<keyof typeof LOG_COUNTS, string> = {
	conn: 'Connections',
	dns: 'DNS',
	http: 'HTTP',
	ssl: 'TLS',
	files: 'Files',
	dhcp: 'DHCP',
	smtp: 'SMTP',
	alert: 'IDS Alerts',
};
const TOTAL_EVENTS = sum(Object.values(LOG_COUNTS));

const stats = (): LogStatsResponse => ({
	...WINDOW,
	total_events: TOTAL_EVENTS,
	unique_sources: LAN_DEVICES.length,
	protocol_count: Object.keys(LOG_COUNTS).length,
	total_bytes: sum(LAN_DEVICES.map(totalBytes)),
});

const timeline = (): LogTimelineResponse => ({
	...WINDOW,
	interval: '1h',
	buckets: hourly((i, share) => {
		const counts = {
			conn: Math.round(LOG_COUNTS.conn * share),
			dns: Math.round(LOG_COUNTS.dns * share),
			http: Math.round(LOG_COUNTS.http * share),
			ssl: Math.round(LOG_COUNTS.ssl * share),
			files: Math.round(LOG_COUNTS.files * share),
			dhcp: Math.round(LOG_COUNTS.dhcp * share),
			smtp: Math.round(LOG_COUNTS.smtp * share),
			alert: Math.round(LOG_COUNTS.alert * share),
		};
		return { timestamp: hourBucket(i), total: sum(Object.values(counts)), ...counts };
	}),
});

// ---- the explorer's table: conn, dns and tls rows in rotation, newest first -------------------

const RESOLVER = '192.168.1.1';
const HIT_COUNT = 30;

function hit(i: number): LogSearchResponse['hits'][number] {
	const c = connection(CONN_TEMPLATES, i);
	const kind = (['conn', 'dns', 'conn', 'tls'] as const)[i % 4];
	const host = PEERS.find((p) => p.ip === c.destination?.ip)?.host ?? 'unknown.example.com';
	const base = { '@timestamp': c['@timestamp'], event: { dataset: kind, provider: 'zeek' } };
	const source =
		kind === 'conn'
			? { ...base, source: c.source, destination: c.destination, network: c.network, zeek: c.zeek }
			: kind === 'dns'
				? {
						...base,
						source: { ip: c.source?.ip, port: c.source?.port },
						destination: { ip: RESOLVER, port: 53 },
						network: { transport: 'udp', protocol: 'dns' },
						zeek: { dns: { query: host, qtype_name: 'A', rcode_name: 'NOERROR', answers: [c.destination?.ip] } },
					}
				: {
						...base,
						source: { ip: c.source?.ip, port: c.source?.port },
						destination: { ip: c.destination?.ip, port: 443 },
						network: { transport: 'tcp', protocol: 'ssl' },
						zeek: { tls: { server_name: host, version: 'TLSv13', cipher: 'TLS_AES_256_GCM_SHA384', established: true } },
					};
	return { _id: `log-${String(i + 1).padStart(4, '0')}`, _index: 'arkime_sessions3-fixture', _source: source };
}

const search = (): LogSearchResponse => {
	const hits = Array.from({ length: HIT_COUNT }, (_, i) => hit(i));
	return {
		hits,
		total: TOTAL_EVENTS,
		search_after: [Date.parse(String(hits.at(-1)?._source['@timestamp']))],
		size: 100,
		log_type: 'all',
	};
};

export const LOGS_ROUTES: FixtureRoute[] = [
	{
		path: '/api/logs/stats',
		empty: {
			...WINDOW,
			total_events: 0,
			unique_sources: 0,
			protocol_count: 0,
			total_bytes: 0,
		} satisfies LogStatsResponse,
		populated: stats(),
	},
	{
		path: '/api/logs/timeline',
		empty: { ...WINDOW, interval: '1h', buckets: [] } satisfies LogTimelineResponse,
		populated: timeline(),
	},
	{
		path: '/api/logs/top-talkers',
		empty: { ...WINDOW, talkers: [] } satisfies LogTopTalkersResponse,
		populated: {
			...WINDOW,
			talkers: [...LAN_DEVICES]
				.sort((a, b) => b.connections - a.connections)
				.map((d) => ({ ip: d.ip, count: d.connections * 2 })),
		} satisfies LogTopTalkersResponse,
	},
	{
		path: '/api/logs/protocol-breakdown',
		empty: { ...WINDOW, protocols: [] } satisfies LogProtocolBreakdownResponse,
		populated: {
			...WINDOW,
			protocols: (Object.keys(LOG_COUNTS) as Array<keyof typeof LOG_COUNTS>).map((protocol) => ({
				protocol,
				label: LABELS[protocol],
				count: LOG_COUNTS[protocol],
			})),
		} satisfies LogProtocolBreakdownResponse,
	},
	{
		path: '/api/logs/top-destinations',
		empty: { ...WINDOW, destinations: [] } satisfies LogTopDestinationsResponse,
		populated: {
			...WINDOW,
			destinations: [...PEERS].sort((a, b) => b.connections - a.connections).map((p) => ({ ip: p.ip, count: p.connections })),
		} satisfies LogTopDestinationsResponse,
	},
	{
		path: '/api/logs/top-dns',
		empty: { ...WINDOW, queries: [] } satisfies LogTopDnsResponse,
		populated: {
			...WINDOW,
			queries: [...PEERS].sort((a, b) => b.connections - a.connections).map((p) => ({ domain: p.host, count: p.connections })),
		} satisfies LogTopDnsResponse,
	},
	{
		path: '/api/logs/search',
		empty: { hits: [], total: 0, search_after: null, size: 100, log_type: 'all' } satisfies LogSearchResponse,
		populated: search(),
	},
	{
		path: /^\/api\/logs\/fields\/[^/]+$/,
		empty: { log_type: 'zeek.conn', fields: [] } satisfies LogFieldsResponse,
		populated: {
			log_type: 'zeek.conn',
			fields: [
				{ name: '@timestamp', type: 'date', description: 'When the connection was observed', example: '2026-03-05T12:34:56Z' },
				{ name: 'source.ip', type: 'ip', description: 'IP address that initiated the connection', example: '192.168.1.100' },
				{ name: 'destination.ip', type: 'ip', description: 'IP address that received the connection', example: '203.0.113.15' },
				{ name: 'network.transport', type: 'keyword', description: 'Transport protocol (tcp, udp, icmp)', example: 'tcp' },
			],
		} satisfies LogFieldsResponse,
	},
];
