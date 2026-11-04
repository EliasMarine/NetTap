/**
 * Series aggregation for colour-identified charts: donuts and stack bars (PLAN.md §4.1).
 * Bar lists are never aggregated.
 */
export const REST_KEY = '__rest__';

export interface SeriesItem<T = unknown> {
	key: string;
	label: string;
	value: number;
	/** The caller's original item, passed back to click and filter callbacks. */
	source?: T;
}

export interface Series<T = unknown> extends SeriesItem<T> {
	/** 1–6: the `--data-N` token. */
	colour: number;
	/** Only on the remainder: the items folded into it, with their identities intact. */
	members?: SeriesItem<T>[];
}

export function topSeries<T>(items: readonly SeriesItem<T>[], max = 6): Series<T>[] {
	const clean = items.map((it) => ({ ...it, value: Number.isFinite(it.value) && it.value > 0 ? it.value : 0 }));
	const sorted = [...clean].sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
	if (sorted.length <= max) return sorted.map((it, i) => ({ ...it, colour: i + 1 }));
	const kept = sorted.slice(0, max - 1).map((it, i) => ({ ...it, colour: i + 1 }));
	const members = sorted.slice(max - 1);
	return [
		...kept,
		{
			key: REST_KEY,
			label: 'Everything else',
			value: members.reduce((a, b) => a + b.value, 0),
			colour: max,
			members,
		},
	];
}
