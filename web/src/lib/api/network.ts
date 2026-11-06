/**
 * The daemon's LAN policy (NET-160): which addresses are on your network. The browser follows
 * the same policy so a link never sends a device page an address the daemon calls internet.
 * Wraps GET /api/network/lan (daemon/api/network.py).
 */

export interface LanPolicy {
	/** Changes whenever the subnets change. */
	version: string;
	/** IPv4 CIDRs; empty means every RFC 1918 range. */
	subnets: string[];
	source: 'env' | 'detected' | 'rfc1918';
	/** The daemon treats every IPv6 address as not on the LAN. */
	ipv6: 'not-lan';
}

/** The policy, or an error when the daemon can't give one (the caller keeps links on the address page). */
export async function getLanPolicy(): Promise<LanPolicy> {
	const res = await fetch('/api/network/lan');
	if (!res.ok) throw new Error(`LAN policy failed: HTTP ${res.status}`);
	const body = (await res.json()) as Partial<LanPolicy> | null;
	const wellFormed =
		!!body &&
		typeof body.version === 'string' &&
		Array.isArray(body.subnets) &&
		body.subnets.every((s) => typeof s === 'string');
	if (!wellFormed) throw new Error('LAN policy failed: the reply was malformed');
	return body as LanPolicy;
}
