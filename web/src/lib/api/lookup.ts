/**
 * Client-side API helpers for WHOIS and DNS reverse lookups.
 * Wraps GET /api/lookup/whois/{ip} and GET /api/lookup/dns/{ip}.
 */

export interface WhoisResult {
	ip: string;
	raw: string;
	parsed: Record<string, string>;
	error: string | null;
}

export interface DnsResult {
	ip: string;
	hostname: string | null;
	aliases: string[];
	addresses: string[];
	error: string | null;
}

/**
 * Look up WHOIS data for an IP address.
 * Can take up to 15 seconds — the daemon has a 15s timeout on the whois binary.
 */
export async function getWhois(ip: string): Promise<WhoisResult> {
	try {
		const res = await fetch(`/api/lookup/whois/${encodeURIComponent(ip)}`);
		if (!res.ok) {
			return { ip, raw: '', parsed: {}, error: `HTTP ${res.status}` };
		}
		return res.json();
	} catch {
		return { ip, raw: '', parsed: {}, error: 'Network error' };
	}
}

/**
 * Reverse DNS lookup for an IP address.
 */
export async function getDnsReverse(ip: string): Promise<DnsResult> {
	try {
		const res = await fetch(`/api/lookup/dns/${encodeURIComponent(ip)}`);
		if (!res.ok) {
			return { ip, hostname: null, aliases: [], addresses: [], error: `HTTP ${res.status}` };
		}
		return res.json();
	} catch {
		return { ip, hostname: null, aliases: [], addresses: [], error: 'Network error' };
	}
}
