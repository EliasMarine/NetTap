/** One daemon path the fixture daemon answers. Bodies are typed where they are declared (`satisfies`). */
export interface FixtureRoute {
	/** Daemon pathname without the query: an exact string, or a pattern for paths that carry an id. */
	path: string | RegExp;
	/** A valid empty shape. Required: `empty` mode must answer every path. */
	empty: unknown;
	/** Falls back to `empty`. */
	populated?: unknown;
	/** Falls back to `populated`, then `empty`. Only for pages that have a stale-data state. */
	stale?: unknown;
	/** HTTP method; any method when omitted. */
	method?: string;
}

/** Synthetic timestamps relative to load time, so "last 24h" views always have data in range. */
export const NOW = Date.now();
export const iso = (msAgo: number): string => new Date(NOW - msAgo).toISOString();
export const MIN = 60_000;
export const HOUR = 60 * MIN;
export const DAY = 24 * HOUR;
