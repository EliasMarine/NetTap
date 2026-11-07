import { describe, it, expect } from 'vitest';
import type { PacketNode } from '../../../src/lib/api/packets.ts';
import { CAPTURES, PACKET_DETAIL, ROWS, SEARCH_FROM, SEARCH_RESULT, SEARCH_TO } from './packets.ts';

const ns = (t: string) => {
	const [whole, frac = ''] = t.split('.');
	return BigInt(whole) * 1_000_000_000n + BigInt(frac.padEnd(9, '0'));
};

// NET-188: the page shows these figures side by side, so they must add up as the daemon's do
describe('packet fixtures', () => {
	it('totals the capture index the way the daemon does', () => {
		expect(CAPTURES.count).toBe(CAPTURES.files.length);
		expect(CAPTURES.bytes_total).toBe(CAPTURES.files.reduce((n, f) => n + f.size_bytes, 0));
		expect(CAPTURES.unindexed).toBe(CAPTURES.files.filter((f) => f.state === 'pending').length);
		const firsts = CAPTURES.files.flatMap((f) => (f.first ? [ns(f.first)] : []));
		expect(ns(CAPTURES.oldest_packet!)).toBe(firsts.reduce((a, b) => (b < a ? b : a)));
	});

	it('returns rows in frame order, inside the window, each in the manifest', () => {
		const from = ns(SEARCH_FROM);
		const to = ns(SEARCH_TO);
		for (const [i, row] of ROWS.entries()) {
			expect(ns(row.t) >= from && ns(row.t) < to, `row ${row.n} inside the window`).toBe(true);
			if (i > 0) expect(row.n).toBeGreaterThan(ROWS[i - 1].n);
		}
		expect(SEARCH_RESULT.manifest.frames).toEqual(ROWS.map((r) => ({ n: r.n, t: r.t, cap_len: r.cap_len, md5: r.md5 })));
	});

	it('reads from a file whose packets cover the window', () => {
		const file = CAPTURES.files.find((f) => f.id === SEARCH_RESULT.files[0].id)!;
		expect(ns(file.first!) <= ns(SEARCH_FROM) && ns(file.last!) >= ns(SEARCH_TO)).toBe(true);
	});

	it('marks only bytes that hold the field’s value', () => {
		const marked = (nodes: PacketNode[]): PacketNode[] => nodes.flatMap((n) => [...(n.mark ? [n] : []), ...marked(n.children)]);
		const fields = marked(PACKET_DETAIL.layers);
		expect(fields.length).toBeGreaterThan(0);
		for (const f of fields) {
			const [pos, size] = f.mark!;
			expect(PACKET_DETAIL.bytes_hex.slice(pos * 2, (pos + size) * 2), f.name).toBe(f.value);
		}
		expect(PACKET_DETAIL.bytes_hex.length / 2).toBe(PACKET_DETAIL.cap_len);
	});
});
