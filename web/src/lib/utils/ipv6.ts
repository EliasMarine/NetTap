/**
 * IPv6 address maths for the IPv6 toolkit (NET-218): parse, classify and explain an
 * address, in the browser, with BigInt. The ranges and their wording are in ipv6-ranges.ts.
 */
import { KNOWN_MULTICAST, MULTICAST_SCOPES, RANGES, RESERVED, SIZE_NOTES, type RangeDef } from './ipv6-ranges';

export type ParseResult =
	| { ok: true; value: bigint; prefix: number | null; zone: string | null }
	| { ok: false; error: string; hint: 'ipv4' | null };

export interface AddressType extends RangeDef {
	value: bigint;
}

export interface InterfaceInfo {
	kind: 'eui64' | 'random' | 'low' | 'anycast';
	id: string;
	/** eui64 only: the MAC the address was probably built from, and whether that MAC is locally administered */
	mac?: string;
	localMac?: boolean;
}

export interface BlockInfo {
	len: number;
	block: string;
	first: string;
	last: string;
	/** How many /64 networks the block holds (en-GB digits), null below /64 */
	subnets64: string | null;
	/** Exact address count up to 2^64, else null (shown as 2^hostBits) */
	addresses: string | null;
	hostBits: number;
	note: string | null;
	/** No prefix was typed: `len` is the usual size for this kind of address */
	assumed: boolean;
}

export interface Inspection {
	ok: true;
	value: bigint;
	zone: string | null;
	typedPrefix: number | null;
	compressed: string;
	expanded: string;
	type: AddressType;
	reach: string;
	/** Multicast only: the group's name in plain words */
	group: string | null;
	ulaNote: string | null;
	embedded: { label: string; value: string }[];
	reverse: string;
	solicited: string | null;
	iface: InterfaceInfo | null;
	block: BlockInfo | null;
	/** A network written in CIDR (prefix ≤ 64, every bit after it zero), not one device's address */
	isNetwork: boolean;
	/** Link-local with no %zone: it can't be used without one */
	zoneMissing: boolean;
}

export type SlaacResult = { ok: true; address: string; id: string; mac: string } | { ok: false; error: string };

const ALL = (1n << 128n) - 1n;
const IID_MASK = (1n << 64n) - 1n;

const fail = (error: string, hint: 'ipv4' | null = null): { ok: false; error: string; hint: 'ipv4' | null } => ({ ok: false, error, hint });

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

function parseIPv4(s: string): bigint | null {
	const parts = s.split('.');
	if (parts.length !== 4) return null;
	// No leading zeros: "010" reads as octal in some tools, so it is ambiguous
	if (!parts.every((p) => /^(0|[1-9]\d{0,2})$/.test(p) && Number(p) <= 255)) return null;
	return parts.reduce((v, p) => (v << 8n) | BigInt(p), 0n);
}

const formatIPv4 = (v: bigint): string => [24n, 16n, 8n, 0n].map((s) => Number((v >> s) & 255n)).join('.');

function groupError(g: string): string | null {
	if (g === '') return 'There is an empty group: a lone colon at the start or end, or three colons in a row.';
	if (g.includes('.')) return 'An IPv4 part is only allowed at the very end, as in ::ffff:192.0.2.10.';
	if (!/^[0-9a-fA-F]+$/.test(g)) return `"${g}" isn't hex: groups use only the digits 0–9 and the letters a–f.`;
	if (g.length > 4) return `"${g}" is too long: each group holds at most four hex digits.`;
	return null;
}

/** "[2001:db8::1]" or "[2001:db8::1]:443", as pasted from a URL, becomes the bare address. */
function unwrap(s: string): string {
	const m = /^\[([^\]]+)\](?::\d{1,5})?$/.exec(s);
	return m ? m[1] : s;
}

/** Turns an IPv4 ending into two hex groups, or says why it isn't one. */
function withIPv4Ending(groups: string[]): { groups: string[] } | { error: string } {
	const last = groups[groups.length - 1];
	if (last === undefined || !last.includes('.')) return { groups };
	const v4 = parseIPv4(last);
	if (v4 === null) return { error: `"${last}" isn't a valid IPv4 ending: use four numbers from 0 to 255, such as 192.0.2.10.` };
	return { groups: [...groups.slice(0, -1), (v4 >> 16n).toString(16), (v4 & 0xffffn).toString(16)] };
}

const toBig = (gs: string[]): bigint => gs.reduce((v, g) => (v << 16n) | BigInt('0x' + g), 0n);

function parseAddress(addr: string): { ok: true; value: bigint } | { ok: false; error: string; hint: null } {
	const halves = addr.split('::');
	if (halves.length > 2) return { ok: false, error: 'Only one :: is allowed: it stands for a single run of zero groups.', hint: null };
	const split = (part: string) => (part === '' ? [] : part.split(':'));
	const compressed = halves.length === 2;
	const head = split(halves[0]);
	const tail = compressed ? split(halves[1]) : [];
	// An IPv4 ending belongs to the last side written; one before :: is caught by groupError
	const ending = withIPv4Ending(compressed ? tail : head);
	if ('error' in ending) return { ok: false, error: ending.error, hint: null };
	const headGroups = compressed ? head : ending.groups;
	const tailGroups = compressed ? ending.groups : [];
	const all = [...headGroups, ...tailGroups];
	for (const g of all) {
		const e = groupError(g);
		if (e) return { ok: false, error: e, hint: null };
	}
	if (compressed && all.length > 7) return { ok: false, error: 'Too many groups: with :: an address has at most seven written groups.', hint: null };
	if (!compressed && all.length !== 8) {
		const error = all.length < 8
			? `Only ${all.length} groups: a full address has eight. Use :: to stand for a run of zeros.`
			: `${all.length} groups is too many: an address has eight.`;
		return { ok: false, error, hint: null };
	}
	return { ok: true, value: (toBig(headGroups) << BigInt(16 * (8 - headGroups.length))) | toBig(tailGroups) };
}

/** Parses "addr", "addr/len", "addr%zone", "addr%zone/len" or "[addr]:port". */
export function parse(input: string): ParseResult {
	const raw = unwrap(input.trim());
	if (raw === '') return fail('');
	const [addrZone, prefixText, ...extra] = raw.split('/');
	if (extra.length) return fail('Only one / is allowed, before the prefix length.');
	if (prefixText !== undefined && (!/^\d{1,3}$/.test(prefixText) || Number(prefixText) > 128)) {
		return fail('The prefix after / must be a whole number from 0 to 128.');
	}
	const pct = addrZone.indexOf('%');
	const addr = pct === -1 ? addrZone : addrZone.slice(0, pct);
	const zone = pct === -1 ? null : addrZone.slice(pct + 1);
	if (zone !== null && !/^[A-Za-z0-9_.-]{1,32}$/.test(zone)) {
		return fail('The zone after % must be an interface name, such as eth0 or br0.');
	}
	if (!addr.includes(':')) {
		return parseIPv4(addr) !== null
			? fail('That is an IPv4 address. The Subnet calculator handles IPv4.', 'ipv4')
			: fail('An IPv6 address is groups of hex digits separated by colons, such as 2001:db8::1.');
	}
	const parsed = parseAddress(addr);
	return parsed.ok ? { ok: true, value: parsed.value, prefix: prefixText === undefined ? null : Number(prefixText), zone } : parsed;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

const groupsOf = (v: bigint): number[] => Array.from({ length: 8 }, (_, i) => Number((v >> BigInt(16 * (7 - i))) & 0xffffn));
const maskOf = (len: number): bigint => (len === 0 ? 0n : (ALL << BigInt(128 - len)) & ALL);
const inPrefix = (v: bigint, net: bigint, len: number): boolean => (v & maskOf(len)) === (net & maskOf(len));
/** Constant addresses below are written by us, so a parse failure is a bug */
const constant = (s: string): bigint => {
	const p = parseAddress(s);
	if (!p.ok) throw new Error(`ipv6: bad constant ${s}`);
	return p.value;
};

const MAPPED = constant('::ffff:0:0');
const SOLICITED = constant('ff02::1:ff00:0');
const LINK_LOCAL = constant('fe80::');

const expand = (v: bigint): string => groupsOf(v).map((g) => g.toString(16).padStart(4, '0')).join(':');

/** RFC 5952 form: lower case, no leading zeros, the longest run of two or more zero groups as ::. */
export function compress(v: bigint): string {
	if (inPrefix(v, MAPPED, 96)) return '::ffff:' + formatIPv4(v & 0xffffffffn);
	const gs = groupsOf(v);
	let best = { start: -1, len: 0 };
	let start = -1;
	gs.forEach((g, i) => {
		if (g !== 0) {
			start = -1;
			return;
		}
		if (start === -1) start = i;
		if (i - start + 1 > best.len) best = { start, len: i - start + 1 };
	});
	const hex = gs.map((g) => g.toString(16));
	if (best.len < 2) return hex.join(':');
	return hex.slice(0, best.start).join(':') + '::' + hex.slice(best.start + best.len).join(':');
}

const reverseName = (v: bigint): string => v.toString(16).padStart(32, '0').split('').reverse().join('.') + '.ip6.arpa';

const iidText = (v: bigint): string => groupsOf(v).slice(4).map((g) => g.toString(16)).join(':');
const formatMac = (m: bigint): string => (m.toString(16).padStart(12, '0').match(/../g) ?? []).join(':');

// ---------------------------------------------------------------------------
// Classifying
// ---------------------------------------------------------------------------

export const TYPES: AddressType[] = RANGES.map((r) => ({ ...r, value: constant(r.net) }));
const RESERVED_TYPE: AddressType = { ...RESERVED, value: 0n };
const MULTICAST_NAMES = KNOWN_MULTICAST.map(([a, name]) => ({ value: constant(a), name }));

/** The most specific range holding the address (longest prefix wins), else Reserved. */
export function classify(v: bigint): AddressType {
	return TYPES.filter((t) => inPrefix(v, t.value, t.len)).reduce<AddressType | null>((best, t) => (best && best.len >= t.len ? best : t), null) ?? RESERVED_TYPE;
}

function multicastInfo(v: bigint): { reach: string; group: string } {
	const scope = Number((v >> 112n) & 0xfn);
	const known = MULTICAST_NAMES.find((k) => k.value === v);
	const low24 = v & 0xffffffn;
	const ending = `${(low24 >> 16n).toString(16).padStart(2, '0')}:${(low24 & 0xffffn).toString(16).padStart(4, '0')}`;
	const group = known
		? known.name
		: inPrefix(v, SOLICITED, 104)
			? `Neighbour discovery: every device with an address ending in …${ending} listens here`
			: 'A group this list doesn\'t name';
	return { reach: MULTICAST_SCOPES[scope] ?? `Scope ${scope.toString(16)} (unassigned)`, group };
}

function embeddedIPv4(v: bigint, key: string): { label: string; value: string }[] {
	if (key === 'mapped' || key === 'nat64') return [{ label: 'Embedded IPv4', value: formatIPv4(v & 0xffffffffn) }];
	if (key === '6to4') return [{ label: 'IPv4 of the tunnel end', value: formatIPv4((v >> 80n) & 0xffffffffn) }];
	if (key === 'teredo') {
		// The client's address and port are stored inverted (RFC 4380)
		return [
			{ label: 'Teredo server', value: formatIPv4((v >> 64n) & 0xffffffffn) },
			{ label: 'Client public IPv4', value: formatIPv4(~v & 0xffffffffn) },
			{ label: 'Client public port', value: String(Number((~v >> 32n) & 0xffffn)) },
		];
	}
	return [];
}

/** What the last 64 bits suggest about the device; only a pattern, never proof (RFC 7136). */
function interfaceInfo(v: bigint): InterfaceInfo {
	const iid = v & IID_MASK;
	const id = iidText(v);
	if (((iid >> 24n) & 0xffffn) === 0xfffen) {
		// Modified EUI-64: MAC bytes 1-3, ff:fe, bytes 4-6, with the universal/local bit flipped back
		const mac = (((iid >> 40n) << 24n) | (iid & 0xffffffn)) ^ (0x02n << 40n);
		return { kind: 'eui64', id, mac: formatMac(mac), localMac: ((mac >> 40n) & 0x02n) !== 0n };
	}
	if (iid === 0n) return { kind: 'anycast', id };
	if (iid < 0x10000n) return { kind: 'low', id };
	return { kind: 'random', id };
}

function blockInfo(v: bigint, len: number, assumed: boolean): BlockInfo {
	const mask = maskOf(len);
	const network = v & mask;
	const hostBits = 128 - len;
	return {
		len,
		block: `${compress(network)}/${len}`,
		first: compress(network),
		last: compress(network | (~mask & ALL)),
		subnets64: len <= 64 ? (1n << BigInt(64 - len)).toLocaleString('en-GB') : null,
		addresses: hostBits <= 64 ? (1n << BigInt(hostBits)).toLocaleString('en-GB') : null,
		hostBits,
		note: SIZE_NOTES[len] ?? null,
		assumed,
	};
}

/** Everything the page shows about one typed address. */
export function inspect(input: string): Inspection | { ok: false; error: string; hint: 'ipv4' | null } {
	const p = parse(input);
	if (!p.ok) return p;
	const v = p.value;
	const type = classify(v);
	const multicast = type.key === 'multicast' ? multicastInfo(v) : null;
	const isNetwork = p.prefix !== null && p.prefix <= 64 && (v & ~maskOf(p.prefix) & ALL) === 0n;
	const device = type.iid && !isNetwork;
	const len = p.prefix ?? type.block;
	return {
		ok: true,
		value: v,
		zone: p.zone,
		typedPrefix: p.prefix,
		compressed: compress(v),
		expanded: expand(v),
		type,
		reach: multicast ? multicast.reach : type.reach,
		group: multicast ? multicast.group : null,
		ulaNote: type.key === 'ula' ? (v >> 120n === 0xfdn ? 'It starts with fd, so your router picked this prefix at random.' : 'It starts with fc, which is reserved and not yet defined for use.') : null,
		embedded: embeddedIPv4(v, type.key),
		reverse: reverseName(v),
		solicited: device ? compress(SOLICITED | (v & 0xffffffn)) : null,
		iface: device ? interfaceInfo(v) : null,
		block: len === null ? null : blockInfo(v, len, p.prefix === null),
		isNetwork,
		zoneMissing: type.key === 'linklocal' && p.zone === null,
	};
}

// ---------------------------------------------------------------------------
// MAC to address (SLAAC)
// ---------------------------------------------------------------------------

function parseMac(s: string): bigint | null {
	const hex = s.trim().replace(/[\s:.-]/g, '');
	return /^[0-9a-fA-F]{12}$/.test(hex) ? BigInt('0x' + hex) : null;
}

/** The 64-bit interface ID SLAAC builds from a MAC (modified EUI-64). */
const eui64 = (mac: bigint): bigint => (((mac >> 24n) << 40n) | (0xfffen << 24n) | (mac & 0xffffffn)) ^ (0x02n << 56n);

/** The address a device with this MAC builds on a /64: fe80::/64 when no prefix is given. */
export function slaac(macText: string, prefixText = ''): SlaacResult {
	const mac = parseMac(macText);
	if (mac === null) return { ok: false, error: 'Enter a MAC address as 12 hex digits, with or without : - or . between them.' };
	if ((mac >> 40n) & 1n) return { ok: false, error: 'That is a multicast (group) MAC address. Devices only build addresses from their own unicast MAC.' };
	let network = LINK_LOCAL;
	if (prefixText.trim() !== '') {
		const p = parse(prefixText);
		if (!p.ok) return { ok: false, error: `Network prefix: ${p.error}` };
		if (p.prefix !== null && p.prefix !== 64) return { ok: false, error: 'SLAAC only works on a /64. Give the prefix as /64, or leave the length off.' };
		if (p.value & IID_MASK) return { ok: false, error: 'Give the network prefix, such as 2001:db8:1:2::/64: the last 64 bits must be zero.' };
		const type = classify(p.value);
		if (!type.iid) return { ok: false, error: `${type.label} addresses aren't built with SLAAC. Use a unicast /64, such as 2001:db8:1:2::/64.` };
		network = p.value;
	}
	const value = network | eui64(mac);
	return { ok: true, address: compress(value), id: iidText(value), mac: formatMac(mac) };
}
