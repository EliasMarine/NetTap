// ---------------------------------------------------------------------------
// TShark display filter construction utilities
// ---------------------------------------------------------------------------

export type Connection = Record<string, unknown>;

/** Traverse a nested object by dot-separated path (e.g. "source.ip"). */
export function getField(obj: Record<string, unknown>, path: string): unknown {
	const parts = path.split('.');
	let current: unknown = obj;
	for (const part of parts) {
		if (current == null || typeof current !== 'object') return undefined;
		current = (current as Record<string, unknown>)[part];
	}
	return current;
}

/** Safely extract a string from a value that may be an array (OpenSearch ECS). */
export function asString(val: unknown): string {
	if (Array.isArray(val)) return val[0] ?? '';
	if (typeof val === 'string') return val;
	return '';
}

/**
 * Build a Wireshark/TShark display filter for a connection record.
 *
 * Uses both IPs + destination (service) port only. The ephemeral source port
 * is intentionally excluded — it makes the filter too specific to match across
 * Arkime's rotating PCAP files. The combination of both IPs + service port
 * (e.g. 443) is unique enough.
 *
 * Handles edge cases:
 * - IPv6 addresses use `ipv6.addr` instead of `ip.addr`
 * - ICMP has no ports — uses bare protocol name instead
 * - Missing fields are gracefully skipped
 */
export function buildTSharkFilter(conn: Connection): string {
	const srcIp = asString(getField(conn, 'source.ip'));
	const dstIp = asString(getField(conn, 'destination.ip'));
	const dstPort = getField(conn, 'destination.port');
	const proto = asString(getField(conn, 'network.transport')).toLowerCase();

	const parts: string[] = [];

	// IPv6 addresses require ipv6.addr; IPv4 uses ip.addr
	const ipField = (ip: string) => ip.includes(':') ? 'ipv6.addr' : 'ip.addr';
	if (srcIp) parts.push(`${ipField(srcIp)} == ${srcIp}`);
	if (dstIp) parts.push(`${ipField(dstIp)} == ${dstIp}`);

	// ICMP has no ports — icmp.port is not a valid TShark field.
	// For ICMP, filter by protocol name instead.
	const isIcmp = proto === 'icmp' || proto === 'icmpv6';
	if (isIcmp) {
		parts.push(proto);
	} else if (proto && dstPort) {
		parts.push(`${proto}.port == ${dstPort}`);
	}

	return parts.join(' && ');
}
