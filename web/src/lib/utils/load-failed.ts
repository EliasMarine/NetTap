import { chartTime, formatWhen } from './drilldown';

/**
 * #96: what a section says when its request failed, so a failure never reads as "none" or 0.
 * `stale` means the section still shows figures from an earlier successful load; `at` is when
 * that load landed (ms), so the note can say how old they are (NET-348).
 */
// OLD CODE START — NET-348: the note never said how old the figures it kept were
// export function loadFailed(what: string, stale = false): string {
// 	return stale
// 		? `Couldn't refresh ${what}; showing the last figures loaded.`
// 		: `Couldn't load ${what}: the request failed.`;
// }
// OLD CODE END
export function loadFailed(what: string, stale = false, at?: number | null): string {
	if (!stale) return `Couldn't load ${what}: the request failed.`;
	if (at == null) return `Couldn't refresh ${what}; showing the last figures loaded.`;
	return `Couldn't refresh ${what}; showing figures from ${loadedWhen(at)}.`;
}

/** "20:41" today, "19 Nov, 23:58" on another day. */
function loadedWhen(at: number): string {
	const today = new Date(at).toDateString() === new Date().toDateString();
	return today ? chartTime(at, 1) : formatWhen(new Date(at).toISOString());
}
