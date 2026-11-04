import type { DnsResult, WhoisResult } from '../../../src/lib/api/lookup.ts';
import type { FixtureRoute } from './types.ts';
import { PEERS } from './net-world.ts';

const HOST = PEERS[0];

const WHOIS_RAW = [
	'NetRange:       198.51.100.0 - 198.51.100.255',
	'CIDR:           198.51.100.0/24',
	'NetName:        EXAMPLE-STREAMING-CDN',
	`OrgName:        ${HOST.org}`,
	`Country:        ${HOST.countryCode}`,
	'RegDate:        2015-03-12',
	'Updated:        2024-06-30',
	'Ref:            https://rdap.example.net/ip/198.51.100.0',
].join('\n');

export const LOOKUP_ROUTES: FixtureRoute[] = [
	{
		// the same record for any IP the page asks about
		path: /^\/api\/lookup\/whois\/[^/]+$/,
		empty: { ip: HOST.ip, raw: '', parsed: {}, error: null } satisfies WhoisResult,
		populated: {
			ip: HOST.ip,
			raw: WHOIS_RAW,
			parsed: {
				netrange: '198.51.100.0 - 198.51.100.255',
				cidr: '198.51.100.0/24',
				netname: 'EXAMPLE-STREAMING-CDN',
				orgname: HOST.org,
				country: HOST.countryCode,
				regdate: '2015-03-12',
				updated: '2024-06-30',
				ref: 'https://rdap.example.net/ip/198.51.100.0',
			},
			error: null,
		} satisfies WhoisResult,
	},
	{
		path: /^\/api\/lookup\/dns\/[^/]+$/,
		empty: { ip: HOST.ip, hostname: null, aliases: [], addresses: [], error: null } satisfies DnsResult,
		populated: {
			ip: HOST.ip,
			hostname: HOST.host,
			aliases: ['edge.example.net'],
			addresses: [HOST.ip],
			error: null,
		} satisfies DnsResult,
	},
];
