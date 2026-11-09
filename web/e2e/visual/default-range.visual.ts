/** NET-195: Settings › Display's default range, read where each page's range starts. A hard load
 * server-renders the page's own default, hydrates onto the saved range and loads it once. No mocks:
 * the real build, a real session from auth.setup.ts and the fixture daemon. */
import { test, expect } from '@playwright/test';
import { expectNoConsoleErrors, setMode, stubUpstreams, watchApi, watchConsole } from './harness.ts';

const SAVED_HOURS = 168;

/**
 * One endpoint per page that the page calls once per load (checked on origin/main before relying on it).
 * `also`: the spans of the page's other requests to it, which are not a load of the range.
 */
const PAGES = [
	// the range starts in a $state initializer
	// OLD CODE: { path: '/', pills: 'Time range', endpoint: '/api/traffic/bandwidth' }, (NET-228: + the KPI trend's request)
	// NET-228: the KPI trend asks once for two settled windows of the range (lib/utils/window-trend.ts)
	{ path: '/', pills: 'Time range', endpoint: '/api/traffic/bandwidth', also: [2 * SAVED_HOURS] },
	// the range starts in the URL hand-off effect's fallback
	{ path: '/alerts', pills: 'Time range', endpoint: '/api/alerts/timeline', also: [] },
	// the range is derived from the URL, with the saved one as its fallback, and drawn by the server
	{ path: '/devices', pills: 'Seen in the last', endpoint: '/api/devices', also: [] },
] as const;

test.describe('the saved default range on a hard load (NET-195)', () => {
	test.beforeEach(async ({ page }) => {
		await page.addInitScript(() => localStorage.setItem('nettap-display-settings', JSON.stringify({ defaultRange: '7d' })));
	});

	for (const { path, pills, endpoint, also } of PAGES) {
		test(`${path} opens on the saved 7 days, hydrates cleanly and loads it once`, async ({ page }) => {
			await setMode('populated');
			await stubUpstreams(page, 'populated');
			// Svelte reports hydration problems with console.warn, which watchConsole leaves out
			const messages: string[] = [];
			page.on('console', (msg) => {
				if (msg.type() === 'error' || msg.type() === 'warning') messages.push(`${msg.type()}: ${msg.text()}`);
			});
			const errors = watchConsole(page);
			// every request to the exact path, whatever its window (/api/devices/count is another path)
			const asked: URL[] = [];
			page.on('request', (r) => {
				const url = new URL(r.url());
				if (url.pathname === endpoint) asked.push(url);
			});
			const apiIdle = watchApi(page);

			await page.goto(path);
			await apiIdle();

			const spans = asked.map((u) => (Date.parse(u.searchParams.get('to')!) - Date.parse(u.searchParams.get('from')!)) / 3_600_000);
			// OLD CODE: expect(spans, `${endpoint} requests in one load, as hours`).toEqual([SAVED_HOURS]); (NET-228)
			// a load of the default 24 h, or a second load of the saved range or of the trend, still shows here
			const byHours = (a: number, b: number) => a - b;
			expect(spans.sort(byHours), `${endpoint} requests in one load, as hours`).toEqual([SAVED_HOURS, ...also].sort(byHours));
			await expect(page.getByRole('group', { name: pills }).getByRole('button', { name: '7d' })).toHaveAttribute('aria-pressed', 'true');
			expect(messages.filter((m) => /hydrat/i.test(m)), 'hydration warnings').toEqual([]);
			expectNoConsoleErrors(errors, { route: path, mode: 'populated' });
		});
	}
});
