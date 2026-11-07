import { describe, it, expect } from 'vitest';
import type { SuricataCategoryFigures } from '../../../src/lib/api/drilldown.ts';
import { SURICATA_CATEGORY, SURICATA_CATEGORY_EMPTY } from './suricata-category.ts';

// NET-160 slice 2b-2: the fixtures add up as the daemon's figures do, or the page tests and the
// visual sweep would show numbers the real page never could
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe('Suricata category fixtures', () => {
	it.each([
		['populated', SURICATA_CATEGORY],
		['empty', SURICATA_CATEGORY_EMPTY],
	] as [string, SuricataCategoryFigures][])('%s: totals agree with their parts', (_name, f) => {
		expect(sum(Object.values(f.severity))).toBe(f.total);
		expect(sum(f.timeline.map((p) => p.n))).toBe(f.total);
		if (f.rules.complete) expect(sum(f.rules.rows.map((r) => r.count))).toBe(f.total);
		for (const side of [f.sources, f.targets]) {
			if (side.complete) expect(sum(side.rows.map((r) => r.count)) + side.missing).toBe(f.total);
			else expect(side.distinct).toBeNull();
		}
		for (const c of f.also_tagged.rows) expect(c.count).toBeLessThanOrEqual(f.total);
	});
});
