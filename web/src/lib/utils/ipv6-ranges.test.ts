import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { RANGES } from './ipv6-ranges';
import { parse, TYPES } from './ipv6';

describe('the range table', () => {
	it('gives every range its own key', () => {
		const keys = RANGES.map((r) => r.key);
		expect(new Set(keys).size).toBe(keys.length);
	});

	it.each(RANGES)('$key: $net/$len is a valid prefix with a sensible assumed block', (r) => {
		const p = parse(`${r.net}/${r.len}`);
		expect(p.ok, `${r.net}/${r.len} should parse`).toBe(true);
		// The block shown when no prefix is typed can't be wider than the range itself
		if (r.block !== null) expect(r.block).toBeGreaterThanOrEqual(r.len);
		// A device part needs a network of /64 or wider around it
		if (r.iid) expect(r.block).not.toBeNull();
		if (r.iid && r.block !== null) expect(r.block).toBeLessThanOrEqual(64);
	});
});

describe('the IANA special-purpose registry snapshot', () => {
	// The registry's own CSV, downloaded 2026-11-08: every row must have a range, with the same reachability
	const csv = readFileSync(resolve(process.cwd(), 'src/lib/utils/iana-ipv6-special-registry.csv'), 'utf8').trim().split('\n').slice(1);
	const rows = csv.map((line) => {
		const cols = line.split(',');
		return { block: cols[0].replace(/\s*\[\d+\]/, ''), reachable: cols[8].replace(/\s*\[\d+\]/, '').trim() };
	});

	it('has 25 rows', () => {
		expect(rows).toHaveLength(25);
	});

	it.each(rows)('$block has a range with matching reachability', ({ block, reachable }) => {
		const [net, len] = block.split('/');
		const p = parse(net);
		if (!p.ok) throw new Error(`${block}: ${p.error}`);
		const range = TYPES.find((t) => t.value === p.value && t.len === Number(len));
		expect(range, `no range for ${block}`).toBeDefined();
		const expected = reachable === 'True' ? true : reachable === 'False' ? false : null;
		expect(range?.globallyReachable).toBe(expected);
	});
});
