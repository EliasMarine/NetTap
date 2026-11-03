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
