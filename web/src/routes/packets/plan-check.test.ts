import { describe, it, expect } from 'vitest';
import type { CaptureFile, CapturesResponse } from '$lib/api/packets';
import { planCheck } from './plan-check';

// NET-349: the daemon refuses a search over 64 files or 3 GB, so the page must not offer one

const file = (id: string, first: string, last: string, size_bytes: number, state: CaptureFile['state'] = 'indexed'): CaptureFile => ({
	id,
	name: id,
	size_bytes,
	modified: '2026-11-06T14:40:00Z',
	recent: false,
	state,
	first,
	last,
	packets: 1,
	encapsulation: 'ether',
	cut_short: false,
	error: null,
});

const captures = (files: CaptureFile[], max_files = 64, max_bytes = 3_000_000_000): CapturesResponse => ({
	files,
	count: files.length,
	bytes_total: files.reduce((n, f) => n + f.size_bytes, 0),
	oldest_packet: null,
	unindexed: 0,
	failed: 0,
	limits: { max_window_seconds: 1800, max_files, max_bytes, rows: [100, 250, 1000] },
});

const FILES = [file('a.pcap', '1000', '1599', 1_000), file('b.pcap', '1600', '2199', 2_000), file('c.pcap', '2200', '2799', 3_000)];

describe('planCheck', () => {
	it('fits when the files the window reads are within both limits', () => {
		const { plan, overLimit } = planCheck(captures(FILES), '1500', '2300');
		expect(plan?.read.map((f) => f.id)).toEqual(['a.pcap', 'b.pcap', 'c.pcap']);
		expect(plan?.bytes).toBe(6_000);
		expect(overLimit).toBe(false);
	});

	it('is over the limit with more files than one search reads', () => {
		expect(planCheck(captures(FILES, 2), '1500', '2300').overLimit).toBe(true);
		// Exactly at the limit still fits, as in the daemon (len > MAX_FILES)
		expect(planCheck(captures(FILES, 3), '1500', '2300').overLimit).toBe(false);
	});

	it('is over the limit with more bytes than one search reads', () => {
		expect(planCheck(captures(FILES, 64, 5_999), '1500', '2300').overLimit).toBe(true);
		expect(planCheck(captures(FILES, 64, 6_000), '1500', '2300').overLimit).toBe(false);
	});

	it('counts only the indexed files the window overlaps', () => {
		const files = [...FILES, file('big.pcap', '1500', '2300', 10_000, 'pending')];
		const { plan, overLimit } = planCheck(captures(files, 1, 1_500), '1000', '1500');
		expect(plan?.read.map((f) => f.id)).toEqual(['a.pcap']);
		expect(plan?.unindexed).toBe(1);
		expect(overLimit).toBe(false);
	});

	it('has no plan and nothing over the limit for an empty window', () => {
		expect(planCheck(captures(FILES, 0, 0), '2000', '2000')).toEqual({ plan: null, overLimit: false });
	});
});
