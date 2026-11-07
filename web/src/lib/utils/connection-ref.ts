/**
 * A connection record (Zeek conn via Malcolm, as Connections and a device's page list them) as
 * packet-query's ConnectionRef (NET-188), for "Open these packets". A field the record lacks
 * stays null: connectionFilter then falls back to all traffic between the two addresses and
 * says so, and connectionSegments opens one labelled minute. Nothing is invented.
 */
import { asString, getField, type Connection } from './tshark-filter';
import { connectionDurationMs, epochMs } from './connection-duration';
import type { LanPolicy } from '$lib/api/network';
import { connectionUrl, nsEpoch, type ConnectionRef } from './packet-query';

/** A port from a number, digit text or a one-item array; null for anything else. */
function port(value: unknown): number | null {
	const v = Array.isArray(value) ? value[0] : value;
	const n = typeof v === 'number' ? v : typeof v === 'string' && /^\d{1,5}$/.test(v.trim()) ? Number(v) : NaN;
	return Number.isInteger(n) && n >= 0 && n <= 65535 ? n : null;
}

/** The record's start in whole epoch ms (event.start, else @timestamp); null when neither reads. */
function startMs(conn: Connection): number | null {
	for (const path of ['event.start', '@timestamp']) {
		const raw = getField(conn, path);
		const ms = epochMs(Array.isArray(raw) ? raw[0] : raw);
		if (Number.isFinite(ms) && ms > 0) return Math.floor(ms);
	}
	return null;
}

/** The record as a ConnectionRef, or null without both addresses and a start time. */
export function connectionRef(conn: Connection): ConnectionRef | null {
	const srcIp = asString(getField(conn, 'source.ip')).trim();
	const dstIp = asString(getField(conn, 'destination.ip')).trim();
	const start = startMs(conn);
	if (!srcIp || !dstIp || start === null) return null;
	const ms = connectionDurationMs(conn);
	return {
		proto: asString(getField(conn, 'network.transport')).toLowerCase(),
		srcIp,
		srcPort: port(getField(conn, 'source.port')),
		dstIp,
		dstPort: port(getField(conn, 'destination.port')),
		start: nsEpoch(BigInt(start) * 1_000_000n),
		duration: ms === null ? null : ms / 1000,
	};
}

/**
 * "Open these packets": /packets for the connection's exact five-tuple over its own window (the
 * first 30-minute segment of a longer one), or null when the record can't give one (no
 * addresses, no start, or addresses packet-query refuses).
 */
export function packetsHrefFor(conn: Connection, lan: LanPolicy | null): string | null {
	const ref = connectionRef(conn);
	if (!ref) return null;
	try {
		return connectionUrl(ref, lan);
	} catch {
		return null;
	}
}
