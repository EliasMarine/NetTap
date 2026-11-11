import type {
	DnsStats,
	NxdomainEntry,
	getDeviceDns,
	getDnsTimeline,
	getNxdomains,
	getQueryTypes,
	getSuspiciousDns,
	getTopDomains,
} from '../../../src/lib/api/dns.ts';
import type { FixtureRoute } from './types.ts';
import { WINDOW, hourBucket, hourly, sum } from './net-world.ts';

// dns.ts declares these response shapes inline on the fetch helpers, so take them from there.
type TopDomainsResponse = Awaited<ReturnType<typeof getTopDomains>>;
type NxdomainResponse = Awaited<ReturnType<typeof getNxdomains>>;
type QueryTypesResponse = Awaited<ReturnType<typeof getQueryTypes>>;
type DnsTimelineResponse = Awaited<ReturnType<typeof getDnsTimeline>>;
type SuspiciousResponse = Awaited<ReturnType<typeof getSuspiciousDns>>;
type DeviceDnsResponse = Awaited<ReturnType<typeof getDeviceDns>>;

const TOTAL_QUERIES = 5400;

const TOP_DOMAINS = [
	{ domain: 'api.example.org', count: 1420, unique_clients: 5 },
	{ domain: 'cdn.example.net', count: 980, unique_clients: 4 },
	{ domain: 'stream.example.net', count: 640, unique_clients: 2 },
	{ domain: 'telemetry.example.org', count: 520, unique_clients: 2 },
	{ domain: 'video.example.com', count: 410, unique_clients: 2 },
	{ domain: 'updates.example.com', count: 310, unique_clients: 3 },
	{ domain: 'mail.example.com', count: 270, unique_clients: 3 },
	{ domain: 'time.example.net', count: 260, unique_clients: 4 },
	{ domain: 'social.example.net', count: 190, unique_clients: 2 },
	{ domain: 'ads.example.net', count: 180, unique_clients: 3 },
	{ domain: 'tracker.example.org', count: 150, unique_clients: 2 },
];

const NXDOMAINS: NxdomainEntry[] = [
	{ domain: 'wpad.example.com', count: 184, clients: ['192.168.1.20', '192.168.1.30'] },
	{ domain: 'old-service.example.net', count: 96, clients: ['192.168.1.30'] },
	{ domain: 'typo.example.org', count: 22, clients: ['192.168.1.21'] },
];

const QUERY_TYPES = [
	{ type: 'A', count: 2900 },
	{ type: 'AAAA', count: 1480 },
	{ type: 'HTTPS', count: 520 },
	{ type: 'PTR', count: 280 },
	{ type: 'TXT', count: 90 },
	{ type: 'SRV', count: 70 },
	{ type: 'MX', count: 30 },
	{ type: 'NS', count: 15 },
	{ type: 'SOA', count: 15 },
];

const LONG_DOMAIN = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4.example.net';

const SUSPICIOUS = [
	{
		type: 'high_frequency',
		domain: 'telemetry.example.org',
		count: 520,
		unique_clients: 2,
		severity: 'medium',
		description: 'High-frequency queries (520) from few source addresses — possible beaconing. A router or resolver address can stand for several devices.',
	},
	{
		type: 'long_domain',
		domain: LONG_DOMAIN,
		length: LONG_DOMAIN.length,
		count: 12,
		severity: 'medium',
		description: `Unusually long domain name (${LONG_DOMAIN.length} chars) — potential data exfiltration or DGA`,
	},
	{
		type: 'txt_abuse',
		domain: 'txt.example.org',
		count: 64,
		severity: 'low',
		description: 'High TXT query volume (64) — TXT records can be used for data tunneling',
	},
];

export const DNS_ROUTES: FixtureRoute[] = [
	{
		path: '/api/dns/stats',
		// NET-225: nothing answered means nothing timed (null), never 0 ms
		empty: { total_queries: 0, unique_domains: 0, nxdomain_count: 0, avg_resolution_ms: null, median_resolution_ms: null } satisfies DnsStats,
		populated: {
			total_queries: TOTAL_QUERIES,
			unique_domains: 412,
			nxdomain_count: sum(NXDOMAINS.map((n) => n.count)),
			avg_resolution_ms: 18,
			median_resolution_ms: 6,
		} satisfies DnsStats,
	},
	{
		path: '/api/dns/top-domains',
		empty: { ...WINDOW, domains: [] } satisfies TopDomainsResponse,
		populated: { ...WINDOW, domains: TOP_DOMAINS } satisfies TopDomainsResponse,
	},
	{
		path: '/api/dns/nxdomain',
		empty: { ...WINDOW, nxdomains: [] } satisfies NxdomainResponse,
		populated: { ...WINDOW, nxdomains: NXDOMAINS } satisfies NxdomainResponse,
	},
	{
		path: '/api/dns/types',
		empty: { ...WINDOW, types: [] } satisfies QueryTypesResponse,
		populated: { ...WINDOW, types: QUERY_TYPES } satisfies QueryTypesResponse,
	},
	{
		path: '/api/dns/timeline',
		empty: { ...WINDOW, interval: '1h', series: [] } satisfies DnsTimelineResponse,
		populated: {
			...WINDOW,
			interval: '1h',
			series: hourly((i, share) => ({ timestamp: hourBucket(i), count: Math.round(TOTAL_QUERIES * share) })),
		} satisfies DnsTimelineResponse,
	},
	{
		path: '/api/dns/suspicious',
		// OLD CODE: empty: { ...WINDOW, suspicious: [] } satisfies SuspiciousResponse,
		// OLD CODE: populated: { ...WINDOW, suspicious: SUSPICIOUS } satisfies SuspiciousResponse, (NET-238: complete)
		empty: { ...WINDOW, suspicious: [], complete: true } satisfies SuspiciousResponse,
		populated: { ...WINDOW, suspicious: SUSPICIOUS, complete: true } satisfies SuspiciousResponse,
	},
	{
		// fires when a device is picked in the DNS page's device section
		path: /^\/api\/dns\/device\/[^/]+$/,
		empty: { device_ip: '192.168.1.20', ...WINDOW, domains: [] } satisfies DeviceDnsResponse,
		populated: {
			device_ip: '192.168.1.20',
			...WINDOW,
			domains: [
				{ domain: 'api.example.org', count: 820, query_types: [{ type: 'A', count: 430 }, { type: 'AAAA', count: 390 }] },
				{ domain: 'cdn.example.net', count: 540, query_types: [{ type: 'A', count: 300 }, { type: 'AAAA', count: 240 }] },
				{ domain: 'updates.example.com', count: 160, query_types: [{ type: 'A', count: 160 }] },
			],
		} satisfies DeviceDnsResponse,
	},
];
