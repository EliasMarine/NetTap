/** NET-357: a page's range lives in its URL. Back and Forward keep it, a range pill replaces the entry
 * instead of pushing one, and Home's category bars carry the window their figures were counted over.
 * The real build, a real session from auth.setup.ts and the fixture daemon. */
import { test, expect, type Page } from '@playwright/test';
import { expectNoConsoleErrors, setMode, stubUpstreams, watchApi, watchConsole } from './harness.ts';

const HOUR_MS = 3_600_000;
// Midday UTC, so the hour falls on one calendar day in every time zone the browser may run in
const FROM = '2026-11-20T12:00:00.000Z';
const TO = '2026-11-20T13:00:00.000Z';

const pills = (page: Page) => page.getByRole('group', { name: 'Time range' });
const spanMs = (url: string) => {
	const q = new URL(url).searchParams;
	return Date.parse(q.get('to')!) - Date.parse(q.get('from')!);
};
const onPath = (pathname: string) => (r: { url(): string }) => new URL(r.url()).pathname === pathname;

/** The label customRange gives a same-day window (drilldown.ts windowWords), in the browser's own zone. */
const windowLabel = (page: Page) =>
	page.evaluate(([from, to]) => {
		const time = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
		return `${time(from)} to ${time(to)}, ${new Date(from).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`;
	}, [FROM, TO]);

test.describe('the range in the URL (NET-357)', () => {
	let errors: string[];

	test.beforeEach(async ({ page }) => {
		await setMode('populated');
		await stubUpstreams(page, 'populated');
		errors = watchConsole(page);
	});

	test.afterEach(() => expectNoConsoleErrors(errors, { route: '/', mode: 'populated' }));

	test('Back from a Home card returns to the range picked there, and Forward to the card', async ({ page }) => {
		const apiIdle = watchApi(page);
		await page.goto('/');
		await apiIdle();

		await pills(page).getByRole('button', { name: '1h' }).click();
		await expect(page).toHaveURL((u) => u.pathname === '/' && u.search === '?range=1h');
		await apiIdle();

		// by the card's own label: hasText alone is a substring, and other cards' notes mention devices
		await page.locator('main a.kpi').filter({ has: page.locator('.kpi-top', { hasText: /^Devices$/ }) }).click();
		await expect(page).toHaveURL((u) => u.pathname === '/devices');
		await apiIdle();

		const summary = page.waitForRequest(onPath('/api/traffic/summary'));
		await page.goBack();
		await expect(page).toHaveURL((u) => u.pathname === '/' && u.search === '?range=1h');
		await expect(pills(page).getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');
		expect(spanMs((await summary).url()), 'the summary Home loads after Back, in ms').toBe(HOUR_MS);
		await apiIdle();

		await page.goForward();
		await expect(page).toHaveURL((u) => u.pathname === '/devices');
	});

	test('a category bar opens its page over the exact window its figure was counted over', async ({ page }) => {
		const apiIdle = watchApi(page);
		await page.goto('/');
		await apiIdle();

		// Only the 1h load's categories: a reply whose window is known to the millisecond
		await page.route(
			(u) => u.pathname === '/api/traffic/categories',
			(route) =>
				route.fulfill({
					json: {
						from: FROM,
						to: TO,
						categories: [{ name: 'streaming', label: 'Streaming', total_bytes: 4_200_000_000, connection_count: 120, top_services: [] }],
					},
				}),
		);
		const categories = page.waitForResponse(onPath('/api/traffic/categories'));
		await pills(page).getByRole('button', { name: '1h' }).click();
		expect(spanMs((await categories).request().url()), 'the categories request, in ms').toBe(HOUR_MS);
		await apiIdle();

		const bar = page.locator('main .card').filter({ hasText: 'Traffic categories' }).getByRole('link', { name: 'Streaming' });
		await expect(bar).toHaveAttribute('href', `/traffic/streaming?${new URLSearchParams({ from: FROM, to: TO, range: '1h' })}`);

		const detail = page.waitForRequest(onPath('/api/traffic/categories/streaming'));
		await bar.click();
		const asked = new URL((await detail).url()).searchParams;
		expect([asked.get('from'), asked.get('to')], 'the category request’s window').toEqual([FROM, TO]);
		await expect(page).toHaveURL((u) => u.pathname === '/traffic/streaming' && u.searchParams.get('from') === FROM && u.searchParams.get('to') === TO);
		await expect(pills(page).getByRole('button', { pressed: true })).toHaveText(await windowLabel(page));
		await apiIdle();
	});

	test('a range pill on a category page replaces its history entry instead of pushing one', async ({ page }) => {
		const apiIdle = watchApi(page);
		await page.goto('/');
		await apiIdle();
		await page.goto('/traffic/streaming?range=1h');
		await apiIdle();
		await expect(pills(page).getByRole('button', { name: '1h' })).toHaveAttribute('aria-pressed', 'true');

		const detail = page.waitForRequest(onPath('/api/traffic/categories/streaming'));
		await pills(page).getByRole('button', { name: '6h' }).click();
		await expect(page).toHaveURL((u) => u.pathname === '/traffic/streaming' && u.search === '?range=6h');
		await expect(pills(page).getByRole('button', { name: '6h' })).toHaveAttribute('aria-pressed', 'true');
		expect(spanMs((await detail).url()), 'the category request after 6h, in ms').toBe(6 * HOUR_MS);
		await apiIdle();

		// A pushed entry would land on ?range=1h; a replaced one leaves Home as the entry before
		await page.goBack();
		await expect(page).toHaveURL((u) => u.pathname === '/' && u.search === '');
	});
});
