/**
 * Figures for a search's packets (NET-188): every one counted over the rows shown, never more.
 * Times are exact (BigInt nanoseconds on the daemon's decimal strings).
 */
import type { PacketRow } from '$lib/api/packets';
import { epochNs, nsEpoch } from './packet-query';
import { one } from './packet-describe';

export interface Noticed {
	/** 'error', 'warning', 'note', 'chat', 'comment', or TShark's number when it is none of these */
	severity: string;
	/** Wireshark's group name ('Sequence', 'Malformed'…), or TShark's number */
	group: string;
	message: string;
	/** Packets carrying this message */
	count: number;
	frames: number[];
}
export interface Sender {
	/** '' when the packet had no IP or Ethernet source */
	address: string;
	packets: number;
	bytes: number;
}
export interface PacketStats {
	packets: number;
	/** Last packet's time − first's, exact; null for < 2 packets */
	lastedSeconds: string | null;
	/** Sum of frame.len: whole packets, headers included */
	bytes: number;
	/** From the _ws.expert.* fields, grouped by message, most severe first */
	noticed: Noticed[];
	/** Only when a device anchor is given; `outBytes` is the frame.len of the packets it sent */
	direction: { out: number; in: number; other: number; outBytes: number } | null;
	/** By source address (ip.src / ipv6.src / eth.src fallback), most bytes first */
	senders: Sender[];
	/** TIMELINE_BUCKETS equal buckets across [first, last], for the chart; one when they share a time */
	timeline: { t: string; packets: number; bytes: number }[];
}

const TIMELINE_BUCKETS = 60;

/** TShark's expert severities (PI_*) */
const SEVERITY: Record<string, string> = {
	'8388608': 'error',
	'6291456': 'warning',
	'4194304': 'note',
	'2097152': 'chat',
	'1048576': 'comment',
};
/** TShark's expert groups (PI_*), as Wireshark names them */
const GROUP: Record<string, string> = Object.fromEntries(
	['Checksum', 'Sequence', 'Response code', 'Request code', 'Undecoded', 'Reassemble', 'Malformed', 'Debug', 'Protocol', 'Security', 'Comment', 'Decryption', 'Assumption', 'Deprecated', 'Receive', 'Interface', 'Dissector bug'].map(
		(name, i) => [String((i + 1) * 0x01000000), name],
	),
);

const values = (row: PacketRow, name: string) => row.fields[name] ?? [];
/**
 * The address that sent a packet: the first IP source TShark gave (the outer layer of a tunnel),
 * else the hardware address; '' with neither. The page's table and "Who sent what" both use it.
 */
export const sourceOf = (row: PacketRow): string => values(row, 'ip.src')[0] ?? values(row, 'ipv6.src')[0] ?? values(row, 'eth.src')[0] ?? '';
const destination = (row: PacketRow) => values(row, 'ip.dst')[0] ?? values(row, 'ipv6.dst')[0] ?? null;

function timeNs(row: PacketRow): bigint {
	const ns = epochNs(row.t);
	if (ns === null) throw new Error(`Packet ${row.n} has an unreadable time.`);
	return ns;
}

function noticed(rows: readonly PacketRow[]): Noticed[] {
	const groups = new Map<string, Noticed & { rank: number }>();
	for (const row of rows) {
		const messages = values(row, '_ws.expert.message');
		const severities = values(row, '_ws.expert.severity');
		const kinds = values(row, '_ws.expert.group');
		// The three lists pair up item by item; when they don't, the severity and group are unknown
		const paired = severities.length === messages.length && kinds.length === messages.length;
		messages.forEach((message, i) => {
			const sev = paired ? severities[i] : '';
			const grp = paired ? kinds[i] : '';
			const key = `${sev}\u0000${grp}\u0000${message}`;
			const item = groups.get(key) ?? { severity: SEVERITY[sev] ?? (sev || 'unknown'), group: GROUP[grp] ?? (grp || 'unknown'), message, count: 0, frames: [], rank: Number(sev) || 0 };
			if (item.frames.at(-1) !== row.n) item.frames.push(row.n);
			item.count = item.frames.length;
			groups.set(key, item);
		});
	}
	return [...groups.values()]
		.sort((a, b) => b.rank - a.rank || b.count - a.count || a.message.localeCompare(b.message))
		.map(({ rank: _rank, ...item }) => item);
}

function direction(rows: readonly PacketRow[], device: string): PacketStats['direction'] {
	const me = device.trim().toLowerCase();
	const counts = { out: 0, in: 0, other: 0, outBytes: 0 };
	for (const row of rows) {
		// The outer IP layer; a packet without one (ARP…) is "other", as a hardware address never matches
		if (sourceOf(row).toLowerCase() === me) {
			counts.out += 1;
			counts.outBytes += row.len;
		} else if (destination(row)?.toLowerCase() === me) counts.in += 1;
		else counts.other += 1;
	}
	return counts;
}

function senders(rows: readonly PacketRow[]): Sender[] {
	const by = new Map<string, Sender>();
	for (const row of rows) {
		const address = sourceOf(row);
		const s = by.get(address) ?? { address, packets: 0, bytes: 0 };
		by.set(address, { address, packets: s.packets + 1, bytes: s.bytes + row.len });
	}
	return [...by.values()].sort((a, b) => b.bytes - a.bytes || b.packets - a.packets || a.address.localeCompare(b.address));
}

function timeline(rows: readonly PacketRow[], times: bigint[], first: bigint, last: bigint): PacketStats['timeline'] {
	const span = last - first;
	const n = span === 0n ? 1 : TIMELINE_BUCKETS;
	// Rounded up, so n buckets always reach the last packet
	const width = span === 0n ? 1n : (span + BigInt(n) - 1n) / BigInt(n);
	const buckets = Array.from({ length: n }, (_, i) => ({ t: nsEpoch(first + BigInt(i) * width), packets: 0, bytes: 0 }));
	rows.forEach((row, i) => {
		const b = buckets[Math.min(n - 1, Number((times[i] - first) / width))];
		b.packets += 1;
		b.bytes += row.len;
	});
	return buckets;
}

export function packetStats(rows: readonly PacketRow[], device: string | null): PacketStats {
	const times = rows.map(timeNs);
	const first = times.reduce((a, b) => (b < a ? b : a), times[0] ?? 0n);
	const last = times.reduce((a, b) => (b > a ? b : a), times[0] ?? 0n);
	return {
		packets: rows.length,
		lastedSeconds: rows.length < 2 ? null : nsEpoch(last - first),
		bytes: rows.reduce((sum, row) => sum + row.len, 0),
		noticed: noticed(rows),
		direction: device ? direction(rows, device) : null,
		senders: senders(rows),
		timeline: rows.length ? timeline(rows, times, first, last) : [],
	};
}

/**
 * Server name per server IP, from a TLS Client Hello's SNI on the same tcp.stream within these
 * rows only. An IP is named only when every row it appears in is on a TCP stream whose Client
 * Hello gave that same name: a CDN address serving two sites, or a stream whose Client Hello
 * isn't in these rows, leaves it unnamed rather than guessed.
 */
export function serverNames(rows: readonly PacketRow[]): Map<string, string> {
	const byStream = new Map<string, string | null>();
	const byServer = new Map<string, string | null>();
	const merge = (map: Map<string, string | null>, key: string, name: string) =>
		map.set(key, map.has(key) && map.get(key) !== name ? null : name);
	for (const row of rows) {
		const stream = one(row.fields, 'tcp.stream');
		const sni = one(row.fields, 'tls.handshake.extensions_server_name');
		const server = values(row, 'ip.dst').length + values(row, 'ipv6.dst').length === 1 ? destination(row) : null;
		if (!values(row, 'tls.handshake.type').includes('1') || stream === null || sni === null || server === null) continue;
		merge(byStream, stream, sni);
		merge(byServer, server, sni);
	}
	for (const row of rows) {
		const stream = one(row.fields, 'tcp.stream');
		const name = stream === null ? undefined : byStream.get(stream);
		for (const ip of ['ip.src', 'ip.dst', 'ipv6.src', 'ipv6.dst'].flatMap((f) => values(row, f))) {
			if (byServer.has(ip) && byServer.get(ip) !== name) byServer.set(ip, null);
		}
	}
	return new Map([...byServer].filter((e): e is [string, string] => e[1] !== null));
}
