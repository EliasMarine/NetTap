/**
 * App issues the harness knows about, logged as follow-ups and not fixed in PR 1.
 * A matching failure becomes a test annotation; anything else still fails.
 */
import type { FixtureMode } from './harness.ts';
import { FIRSTRUN_URL } from '../../playwright.visual.config.ts';

export interface KnownIssue {
	route: string;
	modes: readonly FixtureMode[];
	/** Substring or pattern of the console error, or of the check: `horizontal scroll @ <width>`. */
	match: string | RegExp;
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
	// OLD CODE START — NET-197: API calls without a session answer 401 now, not a redirect to /setup
	// {
	// 	route: '/go-live',
	// 	modes: ['empty', 'error'],
	// 	match: 'EventSource\'s response has a MIME type ("text/html") that is not "text/event-stream"',
	// 	note: 'first run: the layout EventSource to /api/notifications/stream is redirected to /setup',
	// },
	// OLD CODE END
	// OLD CODE START — NET-197 review: any 401 on the page matched, so a first-run path that started
	// refusing, or a 401 on Go Live in a signed-in project, would have hidden here too
	// {
	// 	// shortcut: matches any 401 on this page, so a first-run path (/api/bridge/*) that started
	// 	// refusing would hide here too; hooks.server.store.test.ts is what guards those paths
	// 	route: '/go-live',
	// 	modes: ['empty', 'error'],
	// 	match: 'the server responded with a status of 401 (Unauthorized)',
	// 	note: "first run with no session: the shell's calls and Go Live's capture mode get 401 (NET-197); in the real flow the Account step signs in first",
	// },
	// OLD CODE END
	{
		// Only the firstrun instance's URLs, and only the calls that run log; the console text ends with the resource URL
		route: '/go-live',
		modes: ['empty', 'error'],
		match: new RegExp(
			`status of 401 \\(Unauthorized\\) \\(${FIRSTRUN_URL.replaceAll('.', '\\.')}/api/` +
				'(capture/mode|capture/health|system/ping|storage/status|alerts/count|notifications(/stream|/from-alerts)?)[?)]',
		),
		note: "first run with no session: the shell's calls and Go Live's capture mode get 401 (NET-197); in the real flow the Account step signs in first",
	},
];

export function knownIssue(route: string, mode: FixtureMode, text: string): KnownIssue | undefined {
	return KNOWN_ISSUES.find(
		(i) => i.route === route && i.modes.includes(mode) && (typeof i.match === 'string' ? text.includes(i.match) : i.match.test(text)),
	);
}
