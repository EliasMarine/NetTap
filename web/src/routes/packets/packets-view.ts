/**
 * Packet analysis page (NET-188): the page's own wording and exact time maths.
 *
 * Times stay epoch decimal strings ("1794061927.412345"). Anything that compares or subtracts
 * them goes through nanoseconds as a BigInt, so nothing is rounded; a JS number is used only
 * to print a clock time.
 */
import type { CaptureFile, PacketRow, PacketSearchResult } from '$lib/api/packets';
import { PacketApiError } from '$lib/api/packets';
import type { LanPolicy } from '$lib/api/network';
import { isIpAddress } from '$lib/stores/lan';
import { epochNs, filterFor, MAX_WINDOW_NS, nsEpoch, type PacketQuestion } from '$lib/utils/packet-query';
import { LIBRARY } from '$lib/utils/packet-library';

export { plural } from '$lib/utils/packet-describe';

const MS = 1_000_000n;

/** "How many" in the builder and on a search's filter line */
export const LIMIT_OPTIONS = [
	{ value: '100', label: '100' },
	{ value: '250', label: '250' },
	{ value: '1000', label: '1,000' },
];

const pad = (n: number, w = 2) => String(n).padStart(w, '0');

/** "14:32:07.412": the local clock time to the millisecond, truncated, never rounded up. */
export function clockTime(t: string, withMs = true): string {
	const ns = epochNs(t);
	if (ns === null) return t;
	const ms = ns / MS;
	const d = new Date(Number(ms));
	const hms = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
	return withMs ? `${hms}.${pad(Number(ms % 1000n), 3)}` : hms;
}

/** "today", "yesterday" or "6 Nov", for the day a time falls on. */
export function dayWords(t: string, now: Date = new Date()): string {
	const ns = epochNs(t);
	if (ns === null) return '';
	const d = new Date(Number(ns / MS));
	const day = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
	if (day(d) === day(now)) return 'today';
	const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
	if (day(d) === day(yesterday)) return 'yesterday';
	return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

/** "Today, 14:32:07" for a table cell. */
export function whenText(t: string, now: Date = new Date()): string {
	const day = dayWords(t, now);
	return `${day.charAt(0).toUpperCase()}${day.slice(1)}, ${clockTime(t, false)}`;
}

/** "start", "+19 ms", "+1.204 s": how long after the first packet, exact to the millisecond. */
export function sinceFirst(t: string, first: string): string {
	const a = epochNs(t);
	const b = epochNs(first);
	if (a === null || b === null) return '';
	const ms = (a - b) / MS;
	if (a === b) return 'start';
	if (ms < 1000n) return `+${ms} ms`;
	return `+${ms / 1000n}.${pad(Number(ms % 1000n), 3)} s`;
}

/** A length of time from an exact decimal number of seconds: { value: '2', unit: 'min 14 s' }. */
export function durationParts(seconds: string): { value: string; unit: string } {
	const ns = epochNs(seconds);
	if (ns === null) return { value: seconds, unit: 's' };
	const ms = ns / MS;
	if (ms < 1000n) return { value: String(ms), unit: 'ms' };
	const s = ms / 1000n;
	if (s < 60n) return { value: `${s}.${pad(Number(ms % 1000n), 3).slice(0, 1)}`, unit: 's' };
	if (s < 3600n) return { value: String(s / 60n), unit: s % 60n ? `min ${s % 60n} s` : 'min' };
	return { value: String(s / 3600n), unit: `h ${(s % 3600n) / 60n} min` };
}

/** "7 h 40 min" from whole seconds, for "Packets kept". */
export function spanWords(seconds: number): string {
	const s = Math.max(0, Math.floor(seconds));
	if (s < 60) return `${s} s`;
	if (s < 3600) return `${Math.floor(s / 60)} min`;
	if (s < 86_400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
	return `${Math.floor(s / 86_400)} days ${Math.floor((s % 86_400) / 3600)} h`;
}

/** True when [first, last] of an indexed file overlaps [from, to). */
function overlaps(file: CaptureFile, from: bigint, to: bigint): boolean {
	const first = epochNs(file.first ?? '');
	const last = epochNs(file.last ?? '');
	return first !== null && last !== null && first < to && last >= from;
}

export interface FilePlan {
	/** Indexed files that overlap the window: the files the daemon reads, newest first. */
	read: CaptureFile[];
	bytes: number;
	/** Files that may hold packets in the window but can't be read: the search will be incomplete. */
	failed: CaptureFile[];
	/** Files not indexed yet (the one being written among them): read only if they turn out to overlap. */
	unindexed: number;
}

/**
 * The daemon's file choice for [from, to) (capture_index.select): it indexes any file without an
 * entry first, then reads only the files that overlap. So the plan counts indexed files that
 * overlap, and the unindexed ones apart, as "up to". Failed files are never read and make any
 * search incomplete.
 */
export function planFiles(files: readonly CaptureFile[], from: string, to: string): FilePlan | null {
	const a = epochNs(from);
	const b = epochNs(to);
	if (a === null || b === null || a >= b) return null;
	const read = files.filter((f) => f.state === 'indexed' && overlaps(f, a, b));
	return {
		read,
		bytes: read.reduce((n, f) => n + f.size_bytes, 0),
		failed: files.filter((f) => f.state === 'failed'),
		unindexed: files.filter((f) => f.state === 'pending').length,
	};
}

/**
 * "Search this file's time span" (PLAN B6): [first, last + 1 µs) so the last packet is inside
 * the exclusive end, and only the first 30 minutes of a longer file. Null until indexed.
 */
export function fileSpanWindow(file: CaptureFile): { from: string; to: string; cut: boolean } | null {
	const first = epochNs(file.first ?? '');
	const last = epochNs(file.last ?? '');
	if (first === null || last === null || last < first) return null;
	const end = last + 1000n;
	const cap = first + MAX_WINDOW_NS;
	return { from: nsEpoch(first), to: nsEpoch(end < cap ? end : cap), cut: end > cap };
}

/** The first value TShark gave for a field, or undefined. */
export const field = (row: PacketRow, name: string): string | undefined => row.fields[name]?.[0];

export function destinationOf(row: PacketRow): string | undefined {
	return field(row, 'ip.dst') ?? field(row, 'ipv6.dst') ?? field(row, 'eth.dst');
}

export function srcPortOf(row: PacketRow): string | undefined {
	return field(row, 'tcp.srcport') ?? field(row, 'udp.srcport');
}

export function dstPortOf(row: PacketRow): string | undefined {
	return field(row, 'tcp.dstport') ?? field(row, 'udp.dstport');
}

/** An IP address worth a device or address page; a hardware address (aa:bb:…) passes isIpAddress's IPv6 shape test, so it is ruled out here. */
export function isIp(address: string | undefined): address is string {
	return !!address && isIpAddress(address) && !/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(address);
}

/**
 * A name for an address: the device name for a LAN device, else the site name a Client Hello
 * on the same connection asked for, else the address itself.
 */
export function addressName(
	address: string | undefined,
	devices: ReadonlyMap<string, string>,
	sites: ReadonlyMap<string, string>,
): string {
	if (!address) return 'Unknown';
	return devices.get(address) ?? sites.get(address) ?? address;
}

/** The "Packets" KPI's chip: what the rows cover. Never "All of them" unless the read was complete. */
export function coverage(result: PacketSearchResult): { text: string; complete: boolean } {
	const n = result.rows.length;
	if (result.complete) return { text: result.provisional ? 'All saved so far' : 'All of them', complete: true };
	if (result.termination === 'limit') return { text: `First ${n.toLocaleString('en-GB')}`, complete: false };
	if (result.termination === 'deadline') return { text: 'Search stopped early', complete: false };
	return { text: 'Some files not read', complete: false };
}

/** The line under the chip, saying why the rows are or aren't everything. */
export function coverageNote(result: PacketSearchResult): string {
	if (result.complete) {
		return result.provisional ? 'a file in this window is still being written' : 'the window holds no more';
	}
	if (result.termination === 'limit') return `more match: the search stops at ${result.limit.toLocaleString('en-GB')}`;
	if (result.termination === 'deadline') return 'more may match in this window';
	return `${result.skipped_files.length.toLocaleString('en-GB')} capture ${result.skipped_files.length === 1 ? 'file' : 'files'} couldn't be read`;
}

export type SearchProblem =
	| { kind: 'changed'; message: string }
	| { kind: 'busy'; message: string }
	| { kind: 'memory'; message: string }
	| { kind: 'refused'; message: string }
	| { kind: 'failed'; message: string };

/** How the page tells a failed request apart: by the daemon's status, with its own message. */
export function searchProblem(err: unknown): SearchProblem {
	const message = err instanceof Error && err.message ? err.message : 'The request failed.';
	if (!(err instanceof PacketApiError)) return { kind: 'failed', message };
	if (err.status === 409) return { kind: 'changed', message };
	if (err.status === 503) return { kind: 'busy', message };
	if (err.status === 507) return { kind: 'memory', message };
	if (err.status === 400 || err.status === 422) return { kind: 'refused', message };
	return { kind: 'failed', message };
}

/** TShark's expert severity as its own word ("Warning"), from the name or the number it printed. */
export function expertWord(severity: string): string {
	if (!/^\d+$/.test(severity)) return `${severity.charAt(0).toUpperCase()}${severity.slice(1)}`;
	const n = Number(severity);
	// epan/proto.h: PI_COMMENT 0x00100000 … PI_ERROR 0x00800000
	if (n >= 0x00800000) return 'Error';
	if (n >= 0x00600000) return 'Warning';
	if (n >= 0x00400000) return 'Note';
	if (n >= 0x00200000) return 'Chat';
	return 'Comment';
}

/** "TShark 4.0.17" from the status's long version text. */
export function readerVersion(version: string | null | undefined): string | null {
	const m = /(\d+\.\d+\.\d+)/.exec(version ?? '');
	return m ? `TShark ${m[1]}` : null;
}

/** Library filters whose text holds an example value, so neither runs as the library writes it. */
export const ROUTER_FILTER = 'dns-skips-router';
export const CONVERSATION_FILTER = 'one-conversation';
const ROUTER_TEXT = LIBRARY.flatMap((g) => g.filters).find((f) => f.id === ROUTER_FILTER)?.filter ?? '';
/** The example router address in the library's text: never searched unless the user types it. */
export const ROUTER_EXAMPLE_ADDRESS = '192.168.1.1';
const ROUTER_EXAMPLE = `ip.addr == ${ROUTER_EXAMPLE_ADDRESS}`;

/**
 * The filter the builder's choices write, or the plain-English reason they can't make one.
 * "Lookups that skip your router" takes the router's address the user gives (`router`): NetTap
 * can't tell which device is the router, and the library's 192.168.1.1 is only an example.
 */
export function writtenFilter(question: PacketQuestion, lan: LanPolicy | null, router = ''): { filter: string; problem: string } {
	let filter: string;
	try {
		filter = filterFor(question, lan);
	} catch (err) {
		return { filter: '', problem: err instanceof Error ? err.message : "These choices can't make a filter." };
	}
	if (!question.kinds.includes(ROUTER_FILTER)) return { filter, problem: '' };
	const address = router.trim();
	if (!isIpAddress(address)) {
		return { filter: '', problem: "Enter your router's address for “Lookups that skip your router”. NetTap can't tell which device is your router." };
	}
	// Only the library filter's own text changes: a device or other side of 192.168.1.1 stays as chosen.
	// shortcut: an IPv6 router can push a filter near 500 characters past the cap; the daemon then refuses it
	const filled = ROUTER_TEXT.replace(ROUTER_EXAMPLE, `${address.includes(':') ? 'ipv6' : 'ip'}.addr == ${address}`);
	return { filter: filter.replace(ROUTER_TEXT, filled), problem: '' };
}

/** This packet's TCP or UDP conversation, for a search of the same window, or null outside one. */
export function conversationFilter(row: PacketRow): string | null {
	for (const name of ['tcp.stream', 'udp.stream']) {
		const stream = field(row, name);
		if (stream !== undefined && /^\d+$/.test(stream)) return `${name} == ${stream}`;
	}
	return null;
}
