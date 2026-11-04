import { describe, it, expect } from 'vitest';
import { topSeries, REST_KEY } from './series';

const item = (key: string, value: number) => ({ key, label: key, value, source: { id: key } });

describe('topSeries', () => {
	it('keeps up to six items as they are, coloured 1–6 by size', () => {
		const s = topSeries([item('a', 1), item('b', 9), item('c', 5)]);
		expect(s.map((x) => [x.key, x.colour])).toEqual([['b', 1], ['c', 2], ['a', 3]]);
	});

	it('folds everything past the top five into a reserved remainder', () => {
		const items = 'abcdefgh'.split('').map((k, i) => item(k, 100 - i));
		const s = topSeries(items);
		expect(s).toHaveLength(6);
		expect(s.map((x) => x.colour)).toEqual([1, 2, 3, 4, 5, 6]);
		const rest = s[5];
		expect(rest.key).toBe(REST_KEY);
		expect(rest.label).toBe('Everything else');
		expect(rest.members!.map((m) => m.key)).toEqual(['f', 'g', 'h']);
		expect(rest.value).toBe(95 + 94 + 93);
	});

	it('preserves the total', () => {
		const items = 'abcdefghij'.split('').map((k, i) => item(k, i + 1));
		const total = items.reduce((a, b) => a + b.value, 0);
		expect(topSeries(items).reduce((a, b) => a + b.value, 0)).toBe(total);
	});

	it('keeps a real "other" category apart from the synthetic remainder', () => {
		const items = [item('other', 50), ...'abcdef'.split('').map((k) => item(k, 1))];
		const s = topSeries(items);
		expect(s[0].key).toBe('other');
		expect(s.filter((x) => x.key === REST_KEY)).toHaveLength(1);
	});

	it('breaks ties by label and treats bad values as zero', () => {
		const s = topSeries([item('b', 2), item('a', 2), item('z', Number.NaN)]);
		expect(s.map((x) => x.key)).toEqual(['a', 'b', 'z']);
		expect(s[2].value).toBe(0);
	});

	it('passes the original items through for callbacks, including inside the remainder', () => {
		const items = 'abcdefg'.split('').map((k, i) => item(k, 10 - i));
		const s = topSeries(items);
		expect(s[0].source).toEqual({ id: 'a' });
		expect(s[5].members![1].source).toEqual({ id: 'g' });
	});
});
