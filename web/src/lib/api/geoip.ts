/**
 * Client-side API helpers for GeoIP lookup endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Result of a single GeoIP lookup. */
export interface GeoIPResult {
	ip: string;
	country: string;
	country_code: string;
	city: string | null;
	latitude: number | null;
	longitude: number | null;
	asn: number | null;
	organization: string | null;
	is_private: boolean;
	/** NET-237 (GEO-3): where the answer came from */
	source: GeoSource;
	/** For a "traffic" answer: when the session it was read from was seen */
	seen_at: string | null;
	/** An anycast service: answered from many places, so there is no city or point */
	anycast: boolean;
}

/**
 * traffic: Malcolm's GeoLite2 lookup, stored with a session · maxmind: a local GeoLite2 file ·
 * builtin: NetTap's list of well-known services · private: not looked up · none: no answer yet
 */
export type GeoSource = 'traffic' | 'maxmind' | 'builtin' | 'private' | 'none';

/**
 * What a GeoIP answer can honestly place (NET-237, GEO-2). GeoLite2 gives a city's centre, or only
 * a country's when it knows no city, with no accuracy radius. A country centre says nothing local,
 * and an anycast address has no one place, so both get no coordinates. A city centre is shown to
 * one decimal (about 11 km) and called an estimate.
 */
export function geoEstimate(
	lat: number | null | undefined,
	lon: number | null | undefined,
	city: string | null | undefined,
	anycast = false,
): { coordinates: string | null; note: string } {
	if (anycast) return { coordinates: null, note: 'Anycast: location varies' };
	if (lat == null || lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) {
		return { coordinates: null, note: '—' };
	}
	if (!city) return { coordinates: null, note: 'Country-level estimate, no local position' };
	return { coordinates: `${lat.toFixed(1)}, ${lon.toFixed(1)}`, note: 'city estimate, accuracy unknown' };
}

/** Response from the batch GeoIP lookup endpoint. */
export interface GeoIPBatchResponse {
	results: GeoIPResult[];
	invalid?: string[];
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Look up GeoIP data for a single IP address.
 *
 * Returns a GeoIPResult on success; throws on a non-ok HTTP response (#96: the old
 * country="Unknown" fallback read as a real answer).
 */
export async function lookupGeoIP(ip: string): Promise<GeoIPResult> {
	const encodedIP = encodeURIComponent(ip);
	const res = await fetch(`/api/geoip/${encodedIP}`);

	// OLD CODE START — #96: a failed lookup read as country "Unknown", not a private address
	// if (!res.ok) {
	// 	return {
	// 		ip,
	// 		country: 'Unknown',
	// 		country_code: 'XX',
	// 		city: null,
	// 		latitude: null,
	// 		longitude: null,
	// 		asn: null,
	// 		organization: null,
	// 		is_private: false,
	// 	};
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`GeoIP lookup failed: HTTP ${res.status}`);

	return res.json();
}

/**
 * Look up GeoIP data for multiple IP addresses in a single request.
 *
 * Caps at 50 IPs (excess IPs are silently dropped by the daemon).
 * Returns a GeoIPBatchResponse on success; throws on a non-ok HTTP response.
 */
export async function lookupGeoIPBatch(ips: string[]): Promise<GeoIPBatchResponse> {
	if (ips.length === 0) {
		return { results: [] };
	}

	// Cap at 50 on the client side as well
	const capped = ips.slice(0, 50);
	const ipsParam = capped.map((ip) => encodeURIComponent(ip)).join(',');
	const res = await fetch(`/api/geoip/batch?ips=${ipsParam}`);

	// OLD CODE START — #96: a failed lookup read as no results
	// if (!res.ok) {
	// 	return { results: [] };
	// }
	// OLD CODE END
	if (!res.ok) throw new Error(`GeoIP batch lookup failed: HTTP ${res.status}`);

	return res.json();
}
