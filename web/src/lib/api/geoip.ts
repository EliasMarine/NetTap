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
 * Returns a GeoIPResult on success. On failure (non-ok HTTP response),
 * returns a fallback result with country="Unknown".
 */
export async function lookupGeoIP(ip: string): Promise<GeoIPResult> {
	const encodedIP = encodeURIComponent(ip);
	const res = await fetch(`/api/geoip/${encodedIP}`);

	if (!res.ok) {
		return {
			ip,
			country: 'Unknown',
			country_code: 'XX',
			city: null,
			latitude: null,
			longitude: null,
			asn: null,
			organization: null,
			is_private: false,
		};
	}

	return res.json();
}

/**
 * Look up GeoIP data for multiple IP addresses in a single request.
 *
 * Caps at 50 IPs (excess IPs are silently dropped by the daemon).
 * Returns a GeoIPBatchResponse on success. On failure, returns an
 * empty results array.
 */
export async function lookupGeoIPBatch(ips: string[]): Promise<GeoIPBatchResponse> {
	if (ips.length === 0) {
		return { results: [] };
	}

	// Cap at 50 on the client side as well
	const capped = ips.slice(0, 50);
	const ipsParam = capped.map((ip) => encodeURIComponent(ip)).join(',');
	const res = await fetch(`/api/geoip/batch?ips=${ipsParam}`);

	if (!res.ok) {
		return { results: [] };
	}

	return res.json();
}
