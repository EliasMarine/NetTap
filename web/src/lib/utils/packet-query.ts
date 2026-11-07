/**
 * The packet page's question, filter, window and URL (NET-188), and the links from a
 * connection on Connections.
 *
 * Times are epoch-second decimal strings, as the daemon takes them; all maths on them is in
 * BigInt nanoseconds, never JS floats, so "1794026197.218929" keeps every digit.
 */
import type { PacketRowLimit } from '$lib/api/packets';
import type { LanPolicy } from '$lib/api/network';
import { inCidr, isIpAddress, lanStatus } from '$lib/stores/lan';
import { PRIVATE_RANGES, toNumber } from '$lib/utils/dhcpSubnet';
import { canonicalName, isHostName } from '$lib/utils/drilldown';
import { KINDS, LIBRARY } from './packet-library';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The other side of the conversation. */
export type OtherSide =
	| { kind: 'anyone' }
	/** An IPv4/IPv6 address, or a site name, typed by the user */
	| { kind: 'address'; value: string }
	/** An address outside the LAN (see filterFor) */
	| { kind: 'internet' };
/** Last 5, 15 or 30 minutes */
export type WhenPreset = 300 | 900 | 1800;
export type When = { kind: 'last'; seconds: WhenPreset } | { kind: 'range'; from: string; to: string };
export interface PacketQuestion {
	/** A LAN device's IP, or null for any device */
	device: string | null;
	other: OtherSide;
	/** tcp.port or udp.port; 1–65535 */
	port: number | null;
	/** Kind ids or library filter ids */
	kinds: string[];
	when: When;
	limit: PacketRowLimit;
}

/** `conn` is only set for a connection opened from Connections. */
export interface ConnectionContext {
	start: string;
	duration: number | null;
	segment: number;
	/** connectionFilter's `exact`, kept in the URL: the filter text can be edited, so it can't tell */
	exact: boolean;
}
export interface PacketUrlState {
	filter: string;
	from: string;
	to: string;
	limit: PacketRowLimit;
	/** The direction anchor (an IP), separate from the filter */
	device: string | null;
	conn: ConnectionContext | null;
}

/** A row from Connections. Ports null when the record has none. */
export interface ConnectionRef {
	proto: string;
	srcIp: string;
	srcPort: number | null;
	dstIp: string;
	dstPort: number | null;
	/** Epoch decimal string */
	start: string;
	/** Seconds */
	duration: number | null;
}
export interface Segment {
	index: number;
	count: number;
	from: string;
	to: string;
	label: string;
}

// ---------------------------------------------------------------------------
// Exact epoch maths
// ---------------------------------------------------------------------------

const NS = 1_000_000_000n;
/** The daemon's EPOCH rule (services/packet_parse.py): up to 11 digits, up to 9 decimals. */
const EPOCH = /^[0-9]{1,11}(\.[0-9]{1,9})?$/;
/** The daemon's cap on one search window (MAX_WINDOW_NS there): 30 minutes. */
export const MAX_WINDOW_SECONDS = 1800;
export const MAX_WINDOW_NS = BigInt(MAX_WINDOW_SECONDS) * NS;
/** Longer than any capture is kept; also bounds the number of segments */
const MAX_CONNECTION_S = 366 * 86_400;

/** An epoch (or seconds) decimal string to exact nanoseconds; null when it breaks the daemon's rule. */
export function epochNs(text: string): bigint | null {
	if (!EPOCH.test(text)) return null;
	const [whole, frac = ''] = text.split('.');
	return BigInt(whole) * NS + BigInt(frac.padEnd(9, '0'));
}

/** Nanoseconds to the shortest exact decimal string ("1794026196.218929"). */
export function nsEpoch(ns: bigint): string {
	const frac = (ns % NS).toString().padStart(9, '0').replace(/0+$/, '');
	return frac ? `${ns / NS}.${frac}` : `${ns / NS}`;
}

/** Epoch decimal strings; `last` ends at nowMs. */
export function windowFor(when: When, nowMs: number): { from: string; to: string } {
	if (when.kind === 'range') return { from: when.from, to: when.to };
	const to = BigInt(Math.floor(nowMs)) * 1_000_000n;
	return { from: nsEpoch(to - BigInt(when.seconds) * NS), to: nsEpoch(to) };
}

// ---------------------------------------------------------------------------
// The filter
// ---------------------------------------------------------------------------

/** `ip.addr == X` or `ipv6.addr == X`; throws on anything that isn't an address. */
function addressFilter(text: string, field: 'addr' | 'src' | 'dst' = 'addr'): string {
	const ip = text.trim();
	if (toNumber(ip) !== null) return `ip.${field} == ${ip}`;
	// isIpAddress passes only hex digits, ':' and '.' for IPv6, so nothing else reaches the filter
	if (isIpAddress(ip)) return `ipv6.${field} == ${ip.toLowerCase()}`;
	throw new Error(`“${ip}” isn't an IP address.`);
}

/** A site name in a Client Hello's SNI, a DNS question or answer, or a plain-HTTP Host header: that exact name. */
function siteFilter(text: string): string {
	if (!isHostName(text)) {
		throw new Error('A site name can only use letters, digits, dots, hyphens and underscores, like www.example.com.');
	}
	const name = canonicalName(text);
	return `tls.handshake.extensions_server_name == "${name}" || dns.qry.name == "${name}" || http.host == "${name}"`;
}

/** IPv4 blocks that never reach the internet: this network, loopback, link-local, and 224.0.0.0/3 (multicast, reserved and broadcast). */
const LOCAL_ONLY = ['0.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16', '224.0.0.0/3'];

/**
 * The LAN's IPv4 blocks as lanStatus reads the policy: its subnets, or every RFC 1918 range when
 * it lists none. inCidr is the LAN rule's own parser: a block it can't read never counts as LAN,
 * so it stays out of the filter too, and only the parsed numbers reach the filter text.
 */
function lanBlocks(lan: LanPolicy): string[] {
	const listed = lan.subnets.length ? lan.subnets : PRIVATE_RANGES.map(([net, bits]) => `${net}/${bits}`);
	return listed.flatMap((cidr) => {
		const [base = '', bits = ''] = cidr.split('/');
		const n = toNumber(base);
		return n !== null && inCidr(n, cidr) ? [`${base}/${Number(bits)}`] : [];
	});
}

/**
 * "The internet" (the NET-160 LAN rule, stores/lan.ts): an IPv4 packet with a source or
 * destination outside both the LAN's blocks and the local-only blocks (LOCAL_ONLY: broadcasts,
 * multicast and link-local never leave the network), or an IPv6 packet with a global unicast
 * address (2000::/3). The LAN rule never counts IPv6 as LAN; link-local, unique-local (fd00::/8)
 * and multicast IPv6 stay out here for the same reason as their IPv4 forms. So CGNAT (100.64/10)
 * counts as the internet; a DHCP broadcast or an mDNS announcement does not. Checked on TShark
 * 4.0.17 against packets of each kind.
 */
function internetFilter(lan: LanPolicy | null): string {
	if (!lan) {
		throw new Error("NetTap hasn't loaded your network's address ranges yet, so it can't tell the internet apart. Try again in a moment.");
	}
	// A set keeps this under the daemon's 500 characters; TShark 4.0 wants commas between its elements
	const blocks = `{${[...lanBlocks(lan), ...LOCAL_ONLY].join(', ')}}`;
	return `(ip && (!(ip.src in ${blocks}) || !(ip.dst in ${blocks}))) || ipv6.addr == 2000::/3`;
}

function otherFilter(other: OtherSide, lan: LanPolicy | null): string {
	if (other.kind === 'anyone') return '';
	if (other.kind === 'internet') return internetFilter(lan);
	const value = other.value.trim();
	if (!value) throw new Error('Type an address or a site name.');
	return isIpAddress(value) ? addressFilter(value) : siteFilter(value);
}

function portFilter(port: number | null): string {
	if (port === null) return '';
	if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('A port is a whole number from 1 to 65535.');
	return `tcp.port == ${port} || udp.port == ${port}`;
}

/** The daemon's cap on a filter's length (MAX_FILTER in services/packet_manifest.py). */
export const MAX_FILTER = 500;

const BY_ID = new Map(
	[...KINDS, ...LIBRARY.flatMap((g) => g.filters)].map((f) => [f.id, f.filter] as const),
);

/** Parts joined by `op`; a part holding the other operator gets brackets, so precedence never matters. */
function join(parts: string[], op: '&&' | '||'): string {
	const kept = parts.filter(Boolean);
	const other = op === '&&' ? '||' : '&&';
	return kept.map((p) => (kept.length > 1 && p.includes(other) ? `(${p})` : p)).join(` ${op} `);
}

/** The library's "Narrow it down" filters: each one cuts the search down, so it is ANDed, never ORed. */
const NARROW = new Set(LIBRARY.find((g) => g.id === 'narrow')?.filters.map((f) => f.id) ?? []);

function kindsFilter(kinds: readonly string[]): string {
	const ids = [...new Set(kinds)];
	const filterOf = (id: string) => {
		const filter = BY_ID.get(id);
		if (filter === undefined) throw new Error(`NetTap doesn't know the kind of traffic “${id}”.`);
		return filter;
	};
	const wide = ids.filter((id) => !NARROW.has(id)).map(filterOf);
	// "All traffic" (the empty filter) next to anything else is still every packet
	const any = wide.includes('') ? '' : join(wide, '||');
	return join([any, ...ids.filter((id) => NARROW.has(id)).map(filterOf)], '&&');
}

/**
 * The display filter: device AND other side AND port AND (any of the kinds); '' means every
 * packet. `kinds` takes Kind ids and library filter ids alike. Throws Error with a plain-English
 * message on input it can't express (a site name with a quote, a port outside 1–65535, a
 * filter longer than the daemon's 500 characters…).
 */
export function filterFor(q: Pick<PacketQuestion, 'device' | 'other' | 'port' | 'kinds'>, lan: LanPolicy | null): string {
	const device = q.device === null ? '' : addressFilter(q.device);
	const filter = join([device, otherFilter(q.other, lan), portFilter(q.port), kindsFilter(q.kinds)], '&&');
	if (filter.length > MAX_FILTER) {
		throw new Error(`This question needs a filter of ${filter.length} characters, and the packet reader takes ${MAX_FILTER}. Pick fewer kinds of traffic.`);
	}
	return filter;
}

// ---------------------------------------------------------------------------
// URL state
// ---------------------------------------------------------------------------

const LIMITS: readonly PacketRowLimit[] = [100, 250, 1000];

/** The connection the URL names: null for none, undefined when it is invalid. */
function readConn(params: URLSearchParams): ConnectionContext | null | undefined {
	const start = params.get('conn');
	if (start === null) return null;
	const durText = params.get('dur');
	const segText = params.get('seg') ?? '';
	const exactText = params.get('exact');
	if (durText?.trim() === '' || !/^\d{1,6}$/.test(segText) || (exactText !== '1' && exactText !== '0')) return undefined;
	const duration = durText === null ? null : Number(durText);
	const segment = Number(segText);
	const exact = exactText === '1';
	try {
		return segment < connectionSegments(start, duration).length ? { start, duration, segment, exact } : undefined;
	} catch {
		// A bad start or duration: the URL is refused, like any other invalid value
		return undefined;
	}
}

/**
 * Everything the URL holds. null when the URL has no search (first visit), and for any invalid
 * value (a bad epoch, a limit other than 100/250/1000, from >= to, a window over 1800 s, a device
 * that isn't an IP, a connection segment that doesn't exist, a connection without exact=1 or
 * exact=0): never a guess.
 */
export function readUrlState(params: URLSearchParams): PacketUrlState | null {
	const from = params.get('from') ?? '';
	const to = params.get('to') ?? '';
	const limit = LIMITS.find((l) => String(l) === params.get('limit'));
	const a = epochNs(from);
	const b = epochNs(to);
	if (a === null || b === null || limit === undefined || a >= b || b - a > MAX_WINDOW_NS) return null;
	const device = params.get('device');
	if (device !== null && !isIpAddress(device)) return null;
	const conn = readConn(params);
	if (conn === undefined) return null;
	return { filter: params.get('filter') ?? '', from, to, limit, device, conn };
}

/** '/packets?…', which round-trips with readUrlState. */
export function packetsUrl(state: PacketUrlState): string {
	const params = new URLSearchParams({ filter: state.filter, from: state.from, to: state.to, limit: String(state.limit) });
	if (state.device) params.set('device', state.device);
	if (state.conn) {
		params.set('conn', state.conn.start);
		if (state.conn.duration !== null) params.set('dur', String(state.conn.duration));
		params.set('seg', String(state.conn.segment));
		params.set('exact', state.conn.exact ? '1' : '0');
	}
	return `/packets?${params}`;
}

// ---------------------------------------------------------------------------
// A connection from Connections
// ---------------------------------------------------------------------------

const NO_EXACT = 'all traffic between these two addresses (no exact connection)';

function isPort(p: number | null): p is number {
	return p !== null && Number.isInteger(p) && p >= 0 && p <= 65535;
}

/**
 * The exact bidirectional five-tuple for tcp/udp with both ports (ip.* or ipv6.* by address
 * family); otherwise all traffic between the two addresses, exact=false. Throws on an address
 * that isn't an IP, or on two address families.
 */
export function connectionFilter(c: ConnectionRef): { filter: string; exact: boolean; label: string } {
	const a = addressFilter(c.srcIp);
	const b = addressFilter(c.dstIp);
	if (a.startsWith('ipv6.') !== b.startsWith('ipv6.')) throw new Error('A connection has both its addresses in one family, IPv4 or IPv6.');
	const proto = c.proto.toLowerCase();
	if ((proto === 'tcp' || proto === 'udp') && isPort(c.srcPort) && isPort(c.dstPort)) {
		const way = (s: string, sp: number, d: string, dp: number) =>
			`(${addressFilter(s, 'src')} && ${proto}.srcport == ${sp} && ${addressFilter(d, 'dst')} && ${proto}.dstport == ${dp})`;
		return {
			filter: `${way(c.srcIp, c.srcPort, c.dstIp, c.dstPort)} || ${way(c.dstIp, c.dstPort, c.srcIp, c.srcPort)}`,
			exact: true,
			label: `the ${proto.toUpperCase()} connection from ${c.srcIp.trim()} port ${c.srcPort} to ${c.dstIp.trim()} port ${c.dstPort}`,
		};
	}
	return { filter: `${a} && ${b}`, exact: false, label: NO_EXACT };
}

/** "2 h 14 min", "29 min 58 s", "34 s", "under 1 s": rounded down, never overstated. */
function lengthText(seconds: number): string {
	const s = Math.floor(seconds);
	if (s < 1) return 'under 1 s';
	if (s < 60) return `${s} s`;
	if (s < 3600) return s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`;
	const m = Math.floor((s % 3600) / 60);
	return m ? `${Math.floor(s / 3600)} h ${m} min` : `${Math.floor(s / 3600)} h`;
}

/**
 * The window start − 1 s … start + duration + 1 s, in exact BigInt nanoseconds. Up to 1800 s in
 * all (a duration up to 1798 s) is one segment; longer is cut into 1800 s segments, the last
 * shorter, each [from, to) so they neither overlap nor miss a packet. duration null gives one
 * 60 s window from start − 1 s, labelled as unknown length. Throws on a bad start or duration.
 */
export function connectionSegments(start: string, duration: number | null): Segment[] {
	const startNs = epochNs(start);
	if (startNs === null) throw new Error(`“${start}” isn't an epoch time.`);
	if (duration !== null && !(Number.isFinite(duration) && duration >= 0 && duration <= MAX_CONNECTION_S)) {
		throw new Error('A connection lasts from zero seconds to a year.');
	}
	const from = startNs - NS;
	if (duration === null) {
		return [{ index: 0, count: 1, from: nsEpoch(from), to: nsEpoch(from + 60n * NS), label: "the first minute (the connection's length isn't recorded)" }];
	}
	// Below 2^53 ns (104 days) a float duration rounds back to its own decimal nanoseconds; beyond, within a few ns
	const end = startNs + BigInt(Math.round(duration * 1e9)) + NS;
	const count = Number((end - from + MAX_WINDOW_NS - 1n) / MAX_WINDOW_NS);
	const length = lengthText(duration);
	return Array.from({ length: count }, (_, index) => {
		const a = from + BigInt(index) * MAX_WINDOW_NS;
		const b = a + MAX_WINDOW_NS < end ? a + MAX_WINDOW_NS : end;
		const label =
			count === 1
				? `the whole connection (${length})`
				: index === count - 1
					? `minute ${index * 30} to the end of a ${length} connection`
					: `minutes ${index * 30} to ${index * 30 + 30} of a ${length} connection`;
		return { index, count, from: nsEpoch(a), to: nsEpoch(b), label };
	});
}

/**
 * The /packets URL for one segment of a connection: its filter, the segment's window, 1,000
 * packets, the LAN side as the device when exactly one side is on the LAN, and the connection.
 */
export function connectionUrl(c: ConnectionRef, lan: LanPolicy | null, segment = 0): string {
	const { filter, exact } = connectionFilter(c);
	const seg = connectionSegments(c.start, c.duration)[segment];
	if (!seg) throw new Error(`This connection has no segment ${segment + 1}.`);
	const srcLan = lanStatus(lan, c.srcIp.trim()) === true;
	const dstLan = lanStatus(lan, c.dstIp.trim()) === true;
	const device = srcLan !== dstLan ? (srcLan ? c.srcIp : c.dstIp).trim() : null;
	return packetsUrl({ filter, from: seg.from, to: seg.to, limit: 1000, device, conn: { start: c.start, duration: c.duration, segment, exact } });
}
