import type { GeoIPBatchResponse, GeoIPResult } from '../../../src/lib/api/geoip.ts';
import type { FixtureRoute } from './types.ts';
import { PEERS, type Peer } from './net-world.ts';

const geoip = (p: Peer): GeoIPResult => ({
	ip: p.ip,
	country: p.country,
	country_code: p.countryCode,
	city: p.city,
	latitude: p.latitude,
	longitude: p.longitude,
	asn: p.asn,
	organization: p.org,
	is_private: false,
});

export const GEOIP_ROUTES: FixtureRoute[] = [
	{
		// exact path, so "batch" is never taken for an IP
		path: '/api/geoip/batch',
		empty: { results: [] } satisfies GeoIPBatchResponse,
		populated: { results: PEERS.map(geoip) } satisfies GeoIPBatchResponse,
	},
	{
		// the same host for any IP the page asks about
		path: /^\/api\/geoip\/[^/]+$/,
		empty: {
			ip: PEERS[0].ip,
			country: 'Unknown',
			country_code: '',
			city: null,
			latitude: null,
			longitude: null,
			asn: null,
			organization: null,
			is_private: false,
		} satisfies GeoIPResult,
		populated: geoip(PEERS[0]),
	},
];
