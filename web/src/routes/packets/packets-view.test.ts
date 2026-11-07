import { describe, it, expect } from 'vitest';
import { PacketApiError, type CaptureFile, type PacketRow, type PacketSearchResult } from '$lib/api/packets';
import {
	addressName,
	clockTime,
	conversationFilter,
	coverage,
	coverageNote,
	dayWords,
	durationParts,
	expertWord,
	fileSpanWindow,
	isIp,
	planFiles,
	readerVersion,
	searchProblem,
	sinceFirst,
	spanWords,
	writtenFilter,
	ROUTER_FILTER,
} from './packets-view';
import type { PacketQuestion } from '$lib/utils/packet-query';

const file = (over: Partial<CaptureFile> = {}): CaptureFile => ({
	id: 'a.pcap',
	name: 'a.pcap',
	size_bytes: 100,
	modified: '2026-11-06T14:40:00Z',
	recent: false,
	state: 'indexed',
	first: '1000',
	last: '1600',
	packets: 10,
	encapsulation: 'ether',
	cut_short: false,
	error: null,
	...over,
});

const row = (fields: Record<string, string[]>): PacketRow => ({
	n: 1,
	t: '1000',
	len: 60,
	cap_len: 60,
	md5: '0'.repeat(32),
	protocol: 'TCP',
	info: '',
	fields,
});

const result = (over: Partial<PacketSearchResult>): PacketSearchResult =>
	({
		rows: [],
		termination: 'eof',
		complete: true,
		provisional: false,
		message: null,
		manifest: { from: '0', to: '1', filter: '', files: [], frames: [] },
		files: [],
		skipped_files: [],
		window: { requested: { from: '0', to: '1' }, effective: { from: '0', to: '1' }, from_iso: '', to_iso: '' },
		filter: '',
		limit: 250,
		tshark_version: null,
		seconds: 1,
		...over,
	}) as PacketSearchResult;

describe('exact epoch maths', () => {
	it('prints the clock time truncated to the millisecond, never rounded up', () => {
		const t = '1794061927.4129999';
		expect(clockTime(t)).toMatch(/:\d\d\.412$/);
		expect(clockTime(t, false)).toMatch(/^\d\d:\d\d:\d\d$/);
	});

	it('says how long after the first packet, exactly', () => {
		expect(sinceFirst('100.5', '100.5')).toBe('start');
		expect(sinceFirst('100.519', '100.5')).toBe('+19 ms');
		expect(sinceFirst('101.704', '100.5')).toBe('+1.204 s');
	});

	it('words a duration from an exact decimal', () => {
		expect(durationParts('0.021')).toEqual({ value: '21', unit: 'ms' });
		expect(durationParts('34.25')).toEqual({ value: '34.2', unit: 's' });
		expect(durationParts('134')).toEqual({ value: '2', unit: 'min 14 s' });
		expect(durationParts('8040')).toEqual({ value: '2', unit: 'h 14 min' });
		expect(spanWords(27_600)).toBe('7 h 40 min');
		expect(spanWords(90)).toBe('1 min');
	});

	it('names the day', () => {
		const now = new Date(2026, 10, 6, 15, 0);
		expect(dayWords(String(new Date(2026, 10, 6, 9).getTime() / 1000), now)).toBe('today');
		expect(dayWords(String(new Date(2026, 10, 5, 9).getTime() / 1000), now)).toBe('yesterday');
		expect(dayWords(String(new Date(2026, 10, 1, 9).getTime() / 1000), now)).toBe('1 Nov');
	});
});

describe('planFiles', () => {
	// The daemon indexes a file without an entry first, then reads only the files that overlap
	it('reads overlapping indexed files only, counts unindexed ones apart, and never reads a failed one', () => {
		const files = [
			file({ id: 'live', recent: true, state: 'pending', first: null, last: null, size_bytes: 5 }),
			file({ id: 'waiting', state: 'pending', first: null, last: null, size_bytes: 7 }),
			file({ id: 'in', first: '1000', last: '1600', size_bytes: 100 }),
			file({ id: 'before', first: '100', last: '999.999', size_bytes: 1000 }),
			file({ id: 'broken', state: 'failed', first: null, last: null, error: 'cut short' }),
		];
		const plan = planFiles(files, '1000', '1300')!;
		expect(plan.read.map((f) => f.id)).toEqual(['in']);
		expect(plan.bytes).toBe(100);
		expect(plan.unindexed).toBe(2);
		expect(plan.failed.map((f) => f.id)).toEqual(['broken']);
	});

	it("previews a past window's one matching file, without the live file's size", () => {
		const files = [
			file({ id: 'live', recent: true, state: 'pending', first: null, last: null, size_bytes: 81_000_000 }),
			file({ id: 'now', first: '5000', last: '5600', size_bytes: 256 }),
			file({ id: 'then', first: '1000', last: '1600', size_bytes: 128 }),
		];
		const plan = planFiles(files, '1100', '1200')!;
		expect(plan.read.map((f) => f.id)).toEqual(['then']);
		expect(plan.bytes).toBe(128);
		expect(plan.unindexed).toBe(1);
	});

	it('includes a file whose last packet is exactly the window start, and excludes one starting at its end', () => {
		const files = [file({ id: 'edge', first: '900', last: '1000' }), file({ id: 'after', first: '1300', last: '1400' })];
		expect(planFiles(files, '1000', '1300')!.read.map((f) => f.id)).toEqual(['edge']);
	});

	it('has no plan for a window that is empty or backwards', () => {
		expect(planFiles([file()], '1300', '1300')).toBeNull();
		expect(planFiles([file()], 'x', '1300')).toBeNull();
	});
});

describe('fileSpanWindow', () => {
	it('ends 1 µs after the last packet, so a one-packet file is covered', () => {
		expect(fileSpanWindow(file({ first: '1000.5', last: '1000.5' }))).toEqual({ from: '1000.5', to: '1000.500001', cut: false });
	});

	it('keeps only the first 30 minutes of a longer file', () => {
		expect(fileSpanWindow(file({ first: '1000', last: '5000' }))).toEqual({ from: '1000', to: '2800', cut: true });
	});

	it('has no span until the file is indexed', () => {
		expect(fileSpanWindow(file({ first: null, last: null, state: 'pending' }))).toBeNull();
	});
});

describe('addresses', () => {
	it('links IP addresses only, never a hardware address', () => {
		expect(isIp('192.168.1.5')).toBe(true);
		expect(isIp('2001:db8::1')).toBe(true);
		expect(isIp('aa:bb:cc:dd:ee:ff')).toBe(false);
		expect(isIp(undefined)).toBe(false);
	});

	it('names a device first, then a site, then shows the address', () => {
		const devices = new Map([['192.168.1.5', 'Kitchen iPad']]);
		const sites = new Map([['203.0.113.9', 'cdn.example.net']]);
		expect(addressName('192.168.1.5', devices, sites)).toBe('Kitchen iPad');
		expect(addressName('203.0.113.9', devices, sites)).toBe('cdn.example.net');
		expect(addressName('198.51.100.1', devices, sites)).toBe('198.51.100.1');
		expect(addressName(undefined, devices, sites)).toBe('Unknown');
	});
});

describe('coverage', () => {
	it('says "All of them" only when the read was complete and nothing is still being written', () => {
		expect(coverage(result({ complete: true })).text).toBe('All of them');
		expect(coverage(result({ complete: true, provisional: true })).text).toBe('All saved so far');
		expect(coverageNote(result({ complete: true, provisional: true }))).toMatch(/still being written/);
	});

	it('never calls a limited, stopped or skipping read complete', () => {
		const rows = new Array(250).fill(row({}));
		expect(coverage(result({ complete: false, termination: 'limit', rows }))).toEqual({ text: 'First 250', complete: false });
		expect(coverage(result({ complete: false, termination: 'deadline' })).text).toBe('Search stopped early');
		const skipped = result({ complete: false, termination: 'eof', skipped_files: [{ id: 'x', error: 'bad', modified: '' }] });
		expect(coverage(skipped).text).toBe('Some files not read');
		expect(coverageNote(skipped)).toBe("1 capture file couldn't be read");
	});
});

describe('searchProblem', () => {
	it.each([
		[409, 'changed'],
		[503, 'busy'],
		[507, 'memory'],
		[400, 'refused'],
		[502, 'failed'],
	])('tells %s apart as %s, keeping the daemon’s message', (status, kind) => {
		expect(searchProblem(new PacketApiError('Because.', status))).toEqual({ kind, message: 'Because.' });
	});

	it('treats a network error as a failure', () => {
		expect(searchProblem(new TypeError('Failed to fetch'))).toEqual({ kind: 'failed', message: 'Failed to fetch' });
	});
});

describe('wording', () => {
	it('words TShark’s expert severity from its number or its name', () => {
		expect(expertWord('2097152')).toBe('Chat');
		expect(expertWord(String(0x00600000))).toBe('Warning');
		expect(expertWord(String(0x00800000))).toBe('Error');
		expect(expertWord('warning')).toBe('Warning');
	});

	it('shortens the reader version', () => {
		expect(readerVersion('TShark (Wireshark) 4.0.17 (Git v4.0.17 packaged as 4.0.17-0+deb12u1)')).toBe('TShark 4.0.17');
		expect(readerVersion('')).toBeNull();
	});
});

describe('library filters that hold an example value', () => {
	const question = (over: Partial<PacketQuestion> = {}): PacketQuestion => ({
		device: null,
		other: { kind: 'anyone' },
		port: null,
		kinds: [ROUTER_FILTER],
		when: { kind: 'last', seconds: 900 },
		limit: 100,
		...over,
	});

	it('never runs “Lookups that skip your router” with the example address', () => {
		expect(writtenFilter(question(), null)).toEqual({ filter: '', problem: expect.stringContaining("Enter your router's address") });
		expect(writtenFilter(question(), null, 'router').filter).toBe('');
	});

	it('fills in the router the user gives, IPv4 or IPv6, and nothing else', () => {
		expect(writtenFilter(question(), null, ' 10.0.0.1 ').filter).toBe('dns && !(ip.addr == 10.0.0.1)');
		expect(writtenFilter(question(), null, 'fd00::1').filter).toBe('dns && !(ipv6.addr == fd00::1)');
		// A device that happens to be 192.168.1.1 keeps its own address
		expect(writtenFilter(question({ device: '192.168.1.1' }), null, '10.0.0.1').filter).toBe('ip.addr == 192.168.1.1 && dns && !(ip.addr == 10.0.0.1)');
	});

	it('offers one conversation only for a packet with a TCP or UDP stream number', () => {
		const row = (fields: Record<string, string[]> = {}): PacketRow => ({ n: 1, t: '1.0', len: 1, cap_len: 1, md5: '', protocol: 'TCP', info: '', fields });
		expect(conversationFilter(row({ 'tcp.stream': ['7'] }))).toBe('tcp.stream == 7');
		expect(conversationFilter(row({ 'udp.stream': ['3'] }))).toBe('udp.stream == 3');
		expect(conversationFilter(row())).toBeNull();
		expect(conversationFilter(row({ 'tcp.stream': ['7 || 1'] }))).toBeNull();
	});
});
