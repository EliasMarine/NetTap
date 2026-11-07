/**
 * Wording for the Suricata category page (NET-160 slice 2b-2): its windows, the timeline's slot,
 * and what a top list says when the snapshot couldn't read every key.
 */
import type { SuricataTopList } from '$lib/api/drilldown';
import { DRILL_RANGES, fmt, partialListNote } from '$lib/utils/drilldown';

export interface CategoryRange {
	value: string;
	label: string;
	hours: number;
	words: string;
}

// OLD CODE START — NET-196: the app's one list (DRILL_RANGES)
// export const CATEGORY_RANGES: readonly CategoryRange[] = [
// 	// OLD CODE: { value: '15m', label: '15m', hours: 0.25, words: 'last 15 minutes' }, (NET-192 PR 4)
// 	{ value: '1h', label: '1h', hours: 1, words: 'last hour' },
// 	// OLD CODE: { value: '4h', label: '4h', hours: 4, words: 'last 4 hours' }, (NET-192 PR 4)
// 	{ value: '6h', label: '6h', hours: 6, words: 'last 6 hours' },
// 	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours' },
// 	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days' },
// 	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days' },
// ];
// OLD CODE END
/** The Alerts page's ranges, so every link from here opens on a range it offers (NET-192 PR 4: Home's five). */
export const CATEGORY_RANGES: readonly CategoryRange[] = DRILL_RANGES;

/** The timeline's slot as the daemon picks it for a window this long (api/alerts.py _sparkline_interval). */
export function slotWords(hours: number): string {
	if (hours <= 6) return '10 minutes';
	if (hours <= 24) return 'hour';
	if (hours <= 168) return '6 hours';
	return 'day';
}

/**
 * How much of a top list is on screen: "Top 20 of 312 addresses", "3 rules", or, when the
 * snapshot stopped reading keys, the highest counts among those it read (not a true top list).
 */
export function listScope(list: SuricataTopList<unknown>, noun: string): string {
	// one wording with the Alerts page's top lists (partialListNote)
	if (!list.complete || list.distinct === null) return partialListNote(noun, list.examined);
	return list.rows.length < list.distinct ? `Top ${fmt(list.rows.length)} of ${fmt(list.distinct)} ${noun}` : `${fmt(list.distinct)} ${noun}`;
}
