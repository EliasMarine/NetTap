/**
 * Packet analysis fixtures (NET-188): the capture index, one search's answer (a TV opening a
 * secure connection to a CDN, with one resent packet) and one packet's detail. Times are exact
 * epoch decimal strings relative to load time, as the daemon sends them.
 */
import type {
	CaptureFile,
	CapturesResponse,
	FieldsResponse,
	PacketDetail,
	PacketRow,
	PacketSearchResult,
} from '../../../src/lib/api/packets.ts';
import { MIN, NOW, type FixtureRoute } from './types.ts';

const MIB = 1024 ** 2;
const SECOND = 1000;

/** Whole epoch ms (relative to load) as an exact epoch decimal string. */
function epochAt(ms: number): string {
	const whole = Math.floor(ms);
	return `${Math.floor(whole / 1000)}.${String(whole % 1000).padStart(3, '0')}`;
}
const ago = (ms: number): string => epochAt(NOW - ms);

const LIMITS: CapturesResponse['limits'] = { max_window_seconds: 1800, max_files: 64, max_bytes: 3_000_000_000, rows: [100, 250, 1000] };

/** Four finished, indexed 10-minute files and the one being written, newest first. */
export const CAPTURE_FILES: CaptureFile[] = [
	{
		id: 'mnetsniff-enp4s0_live.pcap',
		name: 'mnetsniff-enp4s0_live.pcap',
		size_bytes: 81 * MIB,
		modified: new Date(NOW - 3 * SECOND).toISOString(),
		recent: true,
		state: 'pending',
		first: null,
		last: null,
		packets: null,
		encapsulation: null,
		cut_short: false,
		error: null,
	},
	...[1, 2, 3, 4].map((i): CaptureFile => {
		const startAgo = (i + 1) * 10 * MIN;
		return {
			id: `mnetsniff-enp4s0_${i}.pcap`,
			name: `mnetsniff-enp4s0_${i}.pcap`,
			size_bytes: 256 * MIB,
			modified: new Date(NOW - startAgo + 10 * MIN).toISOString(),
			recent: false,
			state: 'indexed',
			first: ago(startAgo),
			last: ago(startAgo - 10 * MIN + 2 * SECOND),
			packets: 240_000,
			encapsulation: 'ether',
			cut_short: false,
			error: null,
		};
	}),
];

export const CAPTURES: CapturesResponse = {
	files: CAPTURE_FILES,
	count: CAPTURE_FILES.length,
	bytes_total: CAPTURE_FILES.reduce((n, f) => n + f.size_bytes, 0),
	oldest_packet: CAPTURE_FILES.at(-1)!.first,
	unindexed: CAPTURE_FILES.filter((f) => f.state === 'pending').length,
	failed: 0,
	limits: LIMITS,
};

export const CAPTURES_EMPTY: CapturesResponse = {
	files: [],
	count: 0,
	bytes_total: 0,
	oldest_packet: null,
	unindexed: 0,
	failed: 0,
	limits: LIMITS,
};

/** The device and the server in the search: the TV is a LAN device in net-world.ts. */
export const TV = '192.168.1.22';
export const CDN = '203.0.113.45';
export const CDN_NAME = 'cdn.example-media.net';

/** The search window: 40 seconds inside file 2 (which ran from 30 to 20 minutes ago). */
const WINDOW_START = NOW - 25 * MIN;
export const SEARCH_FROM = epochAt(WINDOW_START);
export const SEARCH_TO = epochAt(WINDOW_START + 40 * SECOND);

const CHAT = '2097152';
const WARN = '6291456';
const SEQUENCE = '33554432';

function packet(n: number, msIn: number, len: number, protocol: string, info: string, out: boolean, extra: Record<string, string[]> = {}): PacketRow {
	const [src, dst, sp, dp] = out ? [TV, CDN, '51834', '443'] : [CDN, TV, '443', '51834'];
	return {
		n,
		t: epochAt(WINDOW_START + 2 * SECOND + msIn),
		len,
		cap_len: len,
		md5: n.toString(16).padStart(32, '0'),
		protocol,
		info,
		fields: {
			'eth.src': [out ? '02:00:5e:10:00:22' : '02:00:5e:00:00:01'],
			'ip.src': [src],
			'ip.dst': [dst],
			'tcp.srcport': [sp],
			'tcp.dstport': [dp],
			'tcp.stream': ['7'],
			...extra,
		},
	};
}

export const ROWS: PacketRow[] = [
	packet(101, 0, 74, 'TCP', '51834 → 443 [SYN] Seq=0 Win=64240 Len=0 MSS=1460', true, {
		'tcp.flags': ['0x0002'],
		'_ws.expert.message': ['Connection establish request (SYN): server port 443'],
		'_ws.expert.severity': [CHAT],
		'_ws.expert.group': [SEQUENCE],
	}),
	packet(102, 19, 74, 'TCP', '443 → 51834 [SYN, ACK] Seq=0 Ack=1 Win=65160 Len=0 MSS=1460', false, { 'tcp.flags': ['0x0012'] }),
	packet(103, 19, 66, 'TCP', '51834 → 443 [ACK] Seq=1 Ack=1 Win=502 Len=0', true, { 'tcp.flags': ['0x0010'] }),
	packet(104, 21, 583, 'TLSv1.3', `Client Hello (SNI=${CDN_NAME})`, true, {
		'tcp.flags': ['0x0018'],
		'tls.handshake.type': ['1'],
		'tls.handshake.extensions_server_name': [CDN_NAME],
	}),
	packet(105, 40, 1514, 'TLSv1.3', 'Server Hello, Change Cipher Spec, Application Data', false, { 'tcp.flags': ['0x0010'], 'tls.handshake.type': ['2'] }),
	packet(106, 62, 1514, 'TLSv1.3', 'Application Data', false, { 'tcp.flags': ['0x0010'] }),
	packet(107, 276, 1514, 'TCP', '[TCP Retransmission] 443 → 51834 [ACK] Seq=4345 Ack=740 Win=501 Len=1448', false, {
		'tcp.flags': ['0x0010'],
		'_ws.expert.message': ['This frame is a (suspected) retransmission'],
		'_ws.expert.severity': [WARN],
		'_ws.expert.group': [SEQUENCE],
	}),
	packet(108, 278, 66, 'TCP', '51834 → 443 [ACK] Seq=740 Ack=10137 Win=501 Len=0', true, { 'tcp.flags': ['0x0010'] }),
	packet(109, 34_000, 66, 'TCP', '51834 → 443 [FIN, ACK] Seq=740 Ack=10137 Win=501 Len=0', true, { 'tcp.flags': ['0x0011'] }),
];

const SEARCH_FILE = CAPTURE_FILES[2];

export const SEARCH_RESULT: PacketSearchResult = {
	rows: ROWS,
	termination: 'eof',
	complete: true,
	provisional: false,
	message: null,
	manifest: {
		from: SEARCH_FROM,
		to: SEARCH_TO,
		filter: `ip.addr == ${TV} && ip.addr == ${CDN}`,
		files: [{ id: SEARCH_FILE.id, size: SEARCH_FILE.size_bytes, mtime_ns: '1794061800000000000', recent: false }],
		frames: ROWS.map((r) => ({ n: r.n, t: r.t, cap_len: r.cap_len, md5: r.md5 })),
	},
	files: [{ id: SEARCH_FILE.id, size_bytes: SEARCH_FILE.size_bytes, first: SEARCH_FILE.first, last: SEARCH_FILE.last, cut_short: false }],
	skipped_files: [],
	window: {
		requested: { from: SEARCH_FROM, to: SEARCH_TO },
		effective: { from: SEARCH_FROM, to: SEARCH_TO },
		from_iso: new Date(WINDOW_START).toISOString(),
		to_iso: new Date(WINDOW_START + 40 * SECOND).toISOString(),
	},
	filter: `ip.addr == ${TV} && ip.addr == ${CDN}`,
	limit: 250,
	tshark_version: '4.0.17',
	seconds: 1.8,
};

export const SEARCH_EMPTY: PacketSearchResult = {
	...SEARCH_RESULT,
	rows: [],
	manifest: { ...SEARCH_RESULT.manifest, frames: [] },
};

/** The URL query for SEARCH_RESULT, as the page writes it. */
export const SEARCH_QUERY = new URLSearchParams({
	filter: SEARCH_RESULT.filter,
	from: SEARCH_FROM,
	to: SEARCH_TO,
	limit: '250',
	device: TV,
}).toString();

/** A 74-byte SYN: Ethernet, IPv4 and TCP, each marked where the daemon proved its bytes. */
const SYN_HEX =
	'02005e00000102005e1000220800' + // eth: dst, src, type
	'4500003c1c4640004006' + '0000' + 'c0a80116' + 'cb00712d' + // ip
	'ca7a01bb' + '00000000' + '00000000' + 'a0027210' + '00000000' + // tcp
	'020405b4' + '0402' + '080a0000000000000000' + '01' + '030307'; // tcp options: 20 bytes

export const PACKET_DETAIL: PacketDetail = {
	n: 101,
	t: ROWS[0].t,
	len: 74,
	cap_len: 74,
	md5: ROWS[0].md5,
	marking: 'headers',
	bytes_hex: SYN_HEX,
	layers: [
		{
			kind: 'proto', name: 'eth', showname: 'Ethernet II, Src: 02:00:5e:10:00:22, Dst: 02:00:5e:00:00:01', show: '', value: '', pos: 0, size: 14, hide: false, markable: true,
			children: [
				{ kind: 'field', name: 'eth.dst', showname: 'Destination: 02:00:5e:00:00:01', show: '02:00:5e:00:00:01', value: '02005e000001', pos: 0, size: 6, hide: false, children: [], mark: [0, 6] },
				{ kind: 'field', name: 'eth.src', showname: 'Source: 02:00:5e:10:00:22', show: '02:00:5e:10:00:22', value: '02005e100022', pos: 6, size: 6, hide: false, children: [], mark: [6, 6] },
			],
		},
		{
			kind: 'proto', name: 'ip', showname: `Internet Protocol Version 4, Src: ${TV}, Dst: ${CDN}`, show: '', value: '', pos: 14, size: 20, hide: false, markable: true,
			children: [
				{ kind: 'field', name: 'ip.ttl', showname: 'Time to Live: 64', show: '64', value: '40', pos: 22, size: 1, hide: false, children: [], mark: [22, 1] },
				{ kind: 'field', name: 'ip.dst', showname: `Destination Address: ${CDN}`, show: CDN, value: 'cb00712d', pos: 30, size: 4, hide: false, children: [], mark: [30, 4] },
			],
		},
		{
			kind: 'proto', name: 'tcp', showname: 'Transmission Control Protocol, Src Port: 51834, Dst Port: 443, Seq: 0, Len: 0', show: '', value: '', pos: 34, size: 40, hide: false, markable: false,
			children: [
				{ kind: 'field', name: 'tcp.srcport', showname: 'Source Port: 51834', show: '51834', value: 'ca7a', pos: 34, size: 2, hide: false, children: [], mark: null },
			],
		},
	],
};

export const FIELDS: FieldsResponse = {
	prefix: 'tls.handshake.extensions_s',
	fields: [
		{ field: 'tls.handshake.extensions_server_name', name: 'Server Name', type: 'FT_STRING', description: '' },
		{ field: 'tls.handshake.extensions_server_name_len', name: 'Server Name length', type: 'FT_UINT16', description: '' },
	],
	more: false,
};

export const PACKETS_ROUTES: FixtureRoute[] = [
	{ path: '/api/packets/captures', empty: CAPTURES_EMPTY, populated: CAPTURES },
	{ path: '/api/packets/search', method: 'POST', empty: SEARCH_EMPTY, populated: SEARCH_RESULT },
	{ path: '/api/packets/packet', method: 'POST', empty: PACKET_DETAIL },
	{ path: '/api/packets/fields', empty: { prefix: '', fields: [], more: false } satisfies FieldsResponse, populated: FIELDS },
	{ path: '/api/packets/check-filter', method: 'POST', empty: { ok: true, filter: '' } },
];
