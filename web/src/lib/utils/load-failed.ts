/**
 * #96: what a section says when its request failed, so a failure never reads as "none" or 0.
 * `stale` means the section still shows figures from an earlier successful load.
 */
export function loadFailed(what: string, stale = false): string {
	return stale
		? `Couldn't refresh ${what}; showing the last figures loaded.`
		: `Couldn't load ${what}: the request failed.`;
}
