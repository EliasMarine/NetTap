/**
 * App issues the harness knows about, logged as follow-ups and not fixed in PR 1.
 * A matching failure becomes a test annotation; anything else still fails.
 */
import type { FixtureMode } from './harness.ts';

export interface KnownIssue {
	route: string;
	modes: readonly FixtureMode[];
	/** Substring of the console error, or of the check: `horizontal scroll @ <width>`. */
	match: string;
	note: string;
}

export const KNOWN_ISSUES: readonly KnownIssue[] = [
	{
		route: '/',
		modes: ['populated'],
		match: 'horizontal scroll @ 1440',
		note: 'Home stays 1522 px wide after the in-page 1920→1440 resize (a fresh load at 1440 is fine)',
	},
	{
		route: '/traffic/streaming',
		modes: ['error'],
		match: '[traffic/category] detail failed',
		note: "the page's own console.error on the expected 503 (traffic/[category]/+page.svelte)",
	},
	{
		route: '/go-live',
		modes: ['empty', 'error'],
		match: 'EventSource\'s response has a MIME type ("text/html") that is not "text/event-stream"',
		note: 'first run: the layout EventSource to /api/notifications/stream is redirected to /setup',
	},
];

export function knownIssue(route: string, mode: FixtureMode, text: string): KnownIssue | undefined {
	return KNOWN_ISSUES.find((i) => i.route === route && i.modes.includes(mode) && text.includes(i.match));
}
