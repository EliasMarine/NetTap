import { describe, it, expect } from 'vitest';
import type { SuricataRuleFigures } from '../../../src/lib/api/drilldown.ts';
import { SURICATA_RULE, SURICATA_RULE_EMPTY } from './suricata-rule.ts';

// The fixtures add up as the daemon's figures do, or the page tests and the visual sweep would
// show numbers the real page never could
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe('Suricata rule fixtures', () => {
	it.each([
		['populated', SURICATA_RULE],
		['empty', SURICATA_RULE_EMPTY],
	] as [string, SuricataRuleFigures][])('%s: totals agree with their parts', (_name, f) => {
		expect(sum(Object.values(f.severity))).toBe(f.total);
		expect(sum(f.timeline.map((p) => p.n))).toBe(f.total);
		expect(f.activity ? f.activity_total : f.counted_total).toBe(f.total);
		if (f.rules_complete) expect(sum(f.rules.map((r) => r.alerts)) + f.no_sid).toBe(f.total);
		for (const group of [f.devices, f.remotes, f.unplaced]) {
			if (!group.complete) expect(group.distinct).toBeNull();
			for (const row of group.rows) {
				expect(row.alerts).toBeLessThanOrEqual(f.total);
				expect(row.alerts).toBeGreaterThanOrEqual(Math.max(row.as_source, row.as_target));
				expect(row.alerts).toBeLessThanOrEqual(row.as_source + row.as_target);
			}
		}
		for (const link of [...f.learn_more, ...f.rules.flatMap((r) => r.learn_more)]) expect(link.url.startsWith('https://')).toBe(true);
	});
});
