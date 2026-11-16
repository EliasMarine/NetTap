import { describe, it, expect } from 'vitest';
import { addressScope, dominantLevel, groupCount, ratingWords, roleOf } from './rule-view';
import type { RuleAddresses } from '$lib/api/drilldown';

const row = (as_source: number, as_target: number) => ({ ip: '192.0.2.1', as_source, as_target, alerts: Math.max(as_source, as_target), first_seen: null, last_seen: null });
const group = (rows: number, distinct: number | null, complete = true, examined = rows): RuleAddresses => ({
	rows: Array.from({ length: rows }, () => row(1, 0)),
	distinct,
	examined,
	complete,
	picked_by: 'source_plus_destination',
});

describe('rule page wording', () => {
	it('picks the most common severity, the higher on a tie, and none for no alerts', () => {
		expect(dominantLevel({ high: 1, medium: 5, low: 5, info: 0 })).toBe('medium');
		expect(dominantLevel({ high: 0, medium: 0, low: 0, info: 3 })).toBe('info');
		expect(dominantLevel({ high: 0, medium: 0, low: 0, info: 0 })).toBeNull();
	});

	it('says how much of a group is shown, never as a top list', () => {
		expect(addressScope(group(3, 3))).toEqual({ text: '3 addresses', partial: false });
		expect(addressScope(group(1, 1)).text).toBe('1 address');
		expect(addressScope(group(20, 312))).toEqual({ text: '20 of 312 addresses, picked by how often each is a source or destination', partial: false });
		const capped = addressScope(group(20, null, false, 5000));
		expect(capped.partial).toBe(true);
		expect(capped.text).toContain('discovery stopped at its limit');
		for (const g of [group(3, 3), group(20, 312), group(20, null, false)]) expect(addressScope(g).text).not.toMatch(/\btop\b|highest/i);
	});

	it('counts a group exactly, or as "at least" when discovery stopped short', () => {
		expect(groupCount(group(3, 3))).toBe('3');
		expect(groupCount(group(20, null, false, 5000))).toBe('5,000+');
	});

	it('names each address role and ET rating', () => {
		expect([roleOf(row(2, 0)), roleOf(row(0, 2)), roleOf(row(1, 1))]).toEqual(['Sent it', 'Received it', 'Both']);
		expect(ratingWords(['Major', 'Minor'])).toBe('Major, Minor');
		expect(ratingWords([])).toBe('Not recorded');
	});
});
