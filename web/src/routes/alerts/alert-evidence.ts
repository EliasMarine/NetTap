/**
 * The evidence behind one alert (NET-355), for the drawer's Evidence block: what Suricata saw,
 * the fields it recorded, the Zeek records that share the alert's community ID, and the packets
 * with the alert's addresses and ports near its time. Every claim is what the data shows: no
 * opener, no "this connection", no coverage the capture index can't vouch for.
 */
import type { Alert } from '$api/alerts';
import type { PacketSearchResult } from '$api/packets';
import { getField, asString } from '$lib/utils/tshark-filter';
import { epochMs } from '$lib/utils/connection-duration';
import { port } from '$lib/utils/connection-ref';
import { compress, parse as parseIPv6 } from '$lib/utils/ipv6';
import { connectionFilter, nsEpoch, type ConnectionTuple } from '$lib/utils/packet-query';
import { logsHrefForQuery, type DrillWindow } from '$lib/utils/drilldown';
import { dnsNamesOf } from './alert-view';

const MINUTE = 60_000;
/** The preview's window either side of the alert */
export const PREVIEW_MS = MINUTE;
/** Suricata stamps a flow-timeout alert up to ~608 s after the last packet (alert_findings.FLOW_TIMEOUT_MS) */
export const BEFORE_MS = 11 * MINUTE;
const ZEEK_BACK_MS = 24 * 60 * MINUTE;
const ZEEK_AHEAD_MS = 15 * MINUTE;
const PAYLOAD_MAX = 2000;
/** Community ID v1: "1:" + base64 of a SHA-1 (28 characters, one "=" of padding) */
const COMMUNITY_ID = /^1:[A-Za-z0-9+/]{27}=$/;

export type Problem = { problem: string };

/** The alert's time in epoch ms (ISO, numeric or digit-string ms), or null. */
export function alertTimeMs(alert: Alert): number | null {
	for (const raw of [alert.timestamp, getField(alert, '@timestamp')]) {
		const ms = epochMs(Array.isArray(raw) ? raw[0] : raw);
		if (Number.isFinite(ms) && ms > 0) return ms;
	}
	return null;
}

/** One address in canonical form (IPv4 dotted quad, IPv6 compressed), or null. */
export function canonicalIp(text: string): string | null {
	const t = text.trim();
	const quad = t.split('.');
	if (quad.length === 4 && quad.every((q) => /^\d{1,3}$/.test(q) && Number(q) <= 255)) return quad.map(Number).join('.');
	if (!t.includes(':')) return null;
	const v6 = parseIPv6(t);
	return v6.ok && v6.prefix === null && v6.zone === null ? compress(v6.value) : null;
}

/** The flat field the daemon adds, else the ECS one. */
const pick = (alert: Alert, flat: unknown, path: string): unknown => flat ?? getField(alert, path);

/** The alert's five-tuple with canonical addresses, or why there isn't one. */
export function alertEndpoints(alert: Alert): ConnectionTuple | Problem {
	const src = canonicalIp(asString(pick(alert, alert.src_ip, 'source.ip')));
	const dst = canonicalIp(asString(pick(alert, alert.dest_ip, 'destination.ip')));
	if (!src || !dst) return { problem: "This alert doesn't carry two IP addresses to look for." };
	if (src.includes(':') !== dst.includes(':')) return { problem: 'Its addresses are in different families, IPv4 and IPv6.' };
	return {
		proto: asString(pick(alert, alert.proto, 'network.transport')).toLowerCase(),
		srcIp: src,
		srcPort: port(pick(alert, alert.src_port, 'source.port')),
		dstIp: dst,
		dstPort: port(pick(alert, alert.dest_port, 'destination.port')),
	};
}

export interface Preview {
	filter: string;
	exact: boolean;
	/** Epoch decimal strings */
	from: string;
	to: string;
	label: string;
}

const epoch = (ms: number): string => nsEpoch(BigInt(Math.round(ms)) * 1_000_000n);

/** The packet search for the alert: its tuple, a minute either side. */
export function packetPreview(alert: Alert): Preview | Problem {
	const at = alertTimeMs(alert);
	if (at === null) return { problem: "This alert has no time to search around." };
	const ends = alertEndpoints(alert);
	if ('problem' in ends) return ends;
	let built: { filter: string; exact: boolean };
	try {
		built = connectionFilter(ends);
	} catch (err) {
		return { problem: err instanceof Error ? err.message : "This alert's addresses can't be searched." };
	}
	// an address-pair filter on one address would match every conversation of that host
	if (!built.exact && ends.srcIp === ends.dstIp) return { problem: 'Both ends are the same address with no ports, so a search would match all of its traffic.' };
	return {
		...built,
		from: epoch(at - PREVIEW_MS),
		to: epoch(at + PREVIEW_MS),
		label: built.exact
			? "Packets with this alert's addresses and ports, from a minute before to a minute after the alert"
			: 'Packets between the two addresses, from a minute before to a minute after the alert',
	};
}

/** The 11 minutes before the alert, for an alert raised when its connection timed out. */
export function beforeWindow(alert: Alert): DrillWindow | null {
	const at = alertTimeMs(alert);
	return at === null ? null : { from: epoch(at - BEFORE_MS), to: epoch(at) };
}

export interface Recorded {
	label: string;
	value: string;
}

const text = (v: unknown): string => {
	const s = Array.isArray(v) ? v[0] : v;
	return typeof s === 'string' || typeof s === 'number' ? String(s).trim() : '';
};

/** The protocol fields Suricata recorded, from a fixed list; empty ones dropped. */
export function recordedFields(alert: Alert): Recorded[] {
	const f = (path: string) => text(getField(alert, path));
	const request = [f('suricata.http.http_method'), f('suricata.http.url')].filter(Boolean).join(' ');
	const payload = f('suricata.payload_printable') || f('payload_printable');
	const rows: Recorded[] = [
		{ label: 'DNS names', value: dnsNamesOf(alert).join(', ') },
		{ label: 'Server name', value: f('suricata.tls.sni') },
		{ label: 'TLS fingerprint (JA4)', value: f('suricata.tls.ja4') },
		{ label: 'Web host', value: f('suricata.http.hostname') },
		{ label: 'Request', value: request },
		{ label: 'Response status', value: f('suricata.http.status') },
		{ label: 'User agent', value: f('suricata.http.http_user_agent') },
		{ label: 'File name', value: f('suricata.fileinfo.filename') },
		{ label: 'Payload', value: payload.length > PAYLOAD_MAX ? `${payload.slice(0, PAYLOAD_MAX)}…` : payload },
	];
	return rows.filter((r) => r.value !== '');
}

export interface TrafficEnd {
	ip: string;
	port: number | null;
	/** "AS62041 Telegram Messenger LLP, United Kingdom" when the alert carries it for this address */
	owner: string;
}

export interface Traffic {
	/** "TLS", "TCP", or '' */
	app: string;
	from: TrafficEnd;
	to: TrafficEnd;
}

/**
 * What Suricata saw, as the alert records it: the application and both ends with who owns them.
 * No claim about who opened the connection or which end is the server (a reply-side rule puts the
 * server in source). Rendered as "Suricata saw TLS traffic from A port 1 to B port 2."
 */
export function trafficOf(alert: Alert): Traffic | null {
	const ends = alertEndpoints(alert);
	if ('problem' in ends) return null;
	const owner = (side: 'source' | 'destination') =>
		[text(getField(alert, `${side}.as.full`)), text(getField(alert, `${side}.geo.country_name`))].filter(Boolean).join(', ');
	return {
		app: (text(getField(alert, 'network.application')) || ends.proto).toUpperCase(),
		from: { ip: ends.srcIp, port: ends.srcPort, owner: owner('source') },
		to: { ip: ends.dstIp, port: ends.dstPort, owner: owner('destination') },
	};
}

export interface ZeekLookup {
	query: string;
	from: string;
	to: string;
	/** Log Explorer over the same query and window */
	href: string;
}

/** The Zeek records that share the alert's community ID, a day before to 15 minutes after it. */
export function zeekQuery(alert: Alert): ZeekLookup | null {
	const id = text(getField(alert, 'network.community_id'));
	const at = alertTimeMs(alert);
	if (!COMMUNITY_ID.test(id) || at === null) return null;
	const clauses = [`network.community_id:"${id}"`, 'event.provider:zeek'];
	const win = { from: new Date(at - ZEEK_BACK_MS).toISOString(), to: new Date(at + ZEEK_AHEAD_MS).toISOString() };
	return { query: clauses.join(' AND '), ...win, href: logsHrefForQuery(clauses, win, '24h') };
}

/** The one line that says what a packet search's empty result means (never "none" unless it read a file to the end). */
export function emptyResultText(result: PacketSearchResult): string {
	if (result.skipped_files.length) return "Some capture files couldn't be read, so packets may still be there.";
	if (result.termination === 'deadline') return 'The search stopped before it finished, so packets may still be there.';
	if (result.complete && result.files.length === 0) return 'No capture was available for this window.';
	if (result.complete) return `No matching packets in the captures searched${result.provisional ? ' so far' : ''}.`;
	return "The search didn't finish, so packets may still be there.";
}

/** "alert-2033967-20261123-014044.pcap" */
export function pcapName(alert: Alert): string {
	const at = alertTimeMs(alert);
	const stamp = at === null ? 'unknown' : new Date(at).toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');
	return `alert-${alert.alert?.signature_id ?? 'rule'}-${stamp}.pcap`;
}
