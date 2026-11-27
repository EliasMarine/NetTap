/**
 * NET-376 (wide-desktop layout, phase 1): a short card beside a long one keeps its own height.
 * The system's .grid stretches every card in a row to the tallest, so on the G11 Live's Top talkers
 * was 5,418 px tall beside the feed and DNS's Query types 2,311 px beside Domains. Correction 11
 * (a11y.css) gives a .fit card its own height on desktop; Live's two side cards share a .stack column.
 *
 * Growing one card with min-height stands in for a long table, so no fixture has to be made long.
 * Each check grows one side well past both, asserts the other kept its height, restores, then
 * reverses: today's stretch fails it, and so does a missing .fit on either card. A real browser,
 * since jsdom has no layout.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { expectReached, setMode, settle, stubUpstreams, watchApi } from './harness.ts';

type Size = { width: number; height: number };

const WIDE: Size[] = [
	{ width: 1440, height: 900 },
	{ width: 1920, height: 1080 },
	{ width: 2560, height: 1440 },
];

/** Each pair is one grid row on desktop; spans are the cards' c-N classes. */
const PAIRS = [
	{ path: '/dns', marker: 'DNS analytics', a: 'Domains', b: 'Query types', spans: [8, 4] },
	{ path: '/dns', marker: 'DNS analytics', a: 'NXDOMAIN errors', b: 'Suspicious DNS patterns', spans: [6, 6] },
	{ path: '/pcap', marker: 'PCAP search', a: 'Available files', b: 'Protocols in preview', spans: [8, 4] },
	{ path: '/infrastructure', marker: 'Infrastructure', a: 'Logstash pipeline', b: 'OpenSearch cluster', spans: [5, 7] },
	{ path: '/alerts', marker: 'Alerts', a: 'Alert categories', b: 'Top signatures', spans: [4, 8] },
	{ path: '/iot', marker: 'IoT trust score', a: 'Smart home health', b: 'Findings', spans: [4, 8] },
	{ path: '/threats', marker: 'Threats', a: 'Beaconing', b: 'DNS anomalies', spans: [6, 6] },
	{ path: '/system', marker: 'System', a: 'Drive health', b: 'Services', spans: [6, 6] },
] as const;

/** The card whose own title is `title`: the nearest card around the exact heading. The last match,
 * since IoT swaps its first "Smart home health" card for a same-titled one once Findings arrives. */
function card(page: Page, title: string): Locator {
	return page
		.locator('main')
		.getByRole('heading', { name: title, exact: true })
		.last()
		.locator('xpath=ancestor::article[contains(concat(" ", normalize-space(@class), " "), " card ")][1]');
}

type Box = { top: number; bottom: number; left: number; right: number; width: number; height: number };

function box(el: Locator): Promise<Box> {
	return el.evaluate((node) => {
		const r = node.getBoundingClientRect();
		return { top: r.top + scrollY, bottom: r.bottom + scrollY, left: r.left, right: r.right, width: r.width, height: r.height };
	});
}

/** The width of a span-n card in the page grid that holds `el`: n tracks plus the gaps between them. */
async function spanWidth(el: Locator, n: number): Promise<number> {
	const { width, gap } = await el.evaluate((node) => {
		const grid = node.closest('.grid')!;
		return { width: grid.clientWidth, gap: parseFloat(getComputedStyle(grid).columnGap) };
	});
	return (n * (width + gap)) / 12 - gap;
}

async function open(page: Page, path: string, marker: string | RegExp, size: Size): Promise<void> {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.setViewportSize(size);
	const apiIdle = watchApi(page);
	await page.goto(path);
	await expectReached(page, path, marker);
	await apiIdle();
}

async function resize(page: Page, size: Size): Promise<void> {
	await page.setViewportSize(size);
	await settle(page);
}

/** Loaded, not the loading skeletons (which share a height whatever the CSS). */
async function loaded(...cards: Locator[]): Promise<void> {
	for (const c of cards) {
		await expect(c).toBeVisible();
		await expect(c.locator('[aria-busy="true"]')).toHaveCount(0);
	}
}

const heightOf = async (el: Locator) => (await box(el)).height;
const grow = (el: Locator, px: number) => el.evaluate((node, h) => ((node as HTMLElement).style.minHeight = `${h}px`), px);
const unGrow = (el: Locator) => el.evaluate((node) => ((node as HTMLElement).style.minHeight = ''));

/** Grow `tall` well past both, assert it grew and every one of `keep` kept its height, then restore. */
async function growKeeps(what: string, tall: Locator, keep: Locator[]): Promise<void> {
	const t0 = await heightOf(tall);
	const k0 = await Promise.all(keep.map(heightOf));
	await grow(tall, Math.ceil(Math.max(t0, ...k0)) + 600);
	expect(await heightOf(tall), `${what}: the grown card grew`).toBeGreaterThan(t0 + 500);
	const k1 = await Promise.all(keep.map(heightOf));
	k1.forEach((h, i) => expect(Math.abs(h - k0[i]), `${what}: the other card kept its height (${k0[i]} → ${h})`).toBeLessThanOrEqual(1));
	await unGrow(tall);
	expect(Math.abs((await heightOf(tall)) - t0), `${what}: restored`).toBeLessThanOrEqual(1);
}

for (const pair of PAIRS) {
	test(`${pair.path}: ${pair.a} and ${pair.b} keep their own heights on desktop (NET-376)`, async ({ page }, testInfo) => {
		test.skip(testInfo.project.name === 'reduced-motion', 'layout only: the app pass covers it');
		await open(page, pair.path, pair.marker, WIDE[0]);
		await loaded(card(page, pair.a), card(page, pair.b));
		for (const size of WIDE) {
			await resize(page, size);
			const at = `${pair.path} at ${size.width}`;
			const A = card(page, pair.a);
			const B = card(page, pair.b);
			// one row: a shared top edge and each card at its span's width
			const [ra, rb] = [await box(A), await box(B)];
			expect(Math.abs(ra.top - rb.top), `${at}: ${pair.a} and ${pair.b} share a row`).toBeLessThanOrEqual(1);
			expect(Math.abs(ra.width - (await spanWidth(A, pair.spans[0]))), `${at}: ${pair.a} is c-${pair.spans[0]} wide`).toBeLessThanOrEqual(2);
			expect(Math.abs(rb.width - (await spanWidth(B, pair.spans[1]))), `${at}: ${pair.b} is c-${pair.spans[1]} wide`).toBeLessThanOrEqual(2);
			await growKeeps(`${at}, ${pair.a} grown`, A, [B]);
			await growKeeps(`${at}, ${pair.b} grown`, B, [A]);
		}
	});
}

test('/live: Top talkers and Protocols share one column beside the feed (NET-376)', async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === 'reduced-motion', 'layout only: the app pass covers it');
	await open(page, '/live', /Live/, WIDE[0]);
	await loaded(card(page, 'Top talkers'), card(page, 'Protocols'), card(page, 'Live connections'));
	const talkers = card(page, 'Top talkers');
	const protocols = card(page, 'Protocols');
	const feed = card(page, 'Live connections');
	const stack = talkers.locator('xpath=..');

	for (const size of WIDE) {
		await resize(page, size);
		const at = `/live at ${size.width}`;
		const [t, p, f, s] = [await box(talkers), await box(protocols), await box(feed), await box(stack)];
		const gap = await stack.evaluate((node) => parseFloat(getComputedStyle(node).rowGap));
		expect(Math.abs(t.top - f.top), `${at}: Top talkers and the feed start level`).toBeLessThanOrEqual(1);
		expect(Math.abs(p.top - t.bottom - gap), `${at}: Protocols sits one gap below Top talkers`).toBeLessThanOrEqual(1);
		expect(Math.abs(s.width - (await spanWidth(stack, 4))), `${at}: the column is c-4 wide`).toBeLessThanOrEqual(2);
		expect(Math.abs(f.width - (await spanWidth(feed, 8))), `${at}: the feed is c-8 wide`).toBeLessThanOrEqual(2);
		expect(f.left, `${at}: the feed is right of the column`).toBeGreaterThanOrEqual(s.right);
		await growKeeps(`${at}, feed grown`, feed, [talkers, protocols]);
		await growKeeps(`${at}, Protocols grown`, protocols, [feed]);
	}

	// Tablet (app width 761–1100 px): the two cards pair half-width, as before NET-376
	await resize(page, { width: 1024, height: 768 });
	const app = await page.locator('.app').evaluate((node) => node.clientWidth);
	expect(app, 'tablet app width').toBeLessThanOrEqual(1100);
	expect(app, 'tablet app width').toBeGreaterThan(760);
	const [tt, pt] = [await box(talkers), await box(protocols)];
	expect(Math.abs(tt.top - pt.top), 'tablet: Top talkers and Protocols side by side').toBeLessThanOrEqual(1);
	expect(Math.abs(tt.width - (await spanWidth(talkers, 6))), 'tablet: Top talkers is half width').toBeLessThanOrEqual(2);
	expect(Math.abs(pt.width - (await spanWidth(protocols, 6))), 'tablet: Protocols is half width').toBeLessThanOrEqual(2);

	// Phone: full width, Protocols under Top talkers
	for (const size of [{ width: 760, height: 900 }, { width: 390, height: 844 }]) {
		await resize(page, size);
		const full = await spanWidth(talkers, 12);
		const [tp, pp] = [await box(talkers), await box(protocols)];
		expect(Math.abs(tp.width - full), `phone ${size.width}: Top talkers is full width`).toBeLessThanOrEqual(2);
		expect(Math.abs(pp.width - full), `phone ${size.width}: Protocols is full width`).toBeLessThanOrEqual(2);
		expect(pp.top, `phone ${size.width}: Protocols is under Top talkers`).toBeGreaterThanOrEqual(tp.bottom);
	}
});

test('/alerts on a tablet: .fit is desktop only, so Alert categories still matches Threat summary (NET-376)', async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === 'reduced-motion', 'layout only: the app pass covers it');
	// 16 px body insets each side: a 1132 px window gives an app width of about 1100
	await open(page, '/alerts', 'Alerts', { width: 1132, height: 900 });
	const summary = card(page, 'Threat summary');
	const categories = card(page, 'Alert categories');
	await loaded(summary, categories);
	const app = await page.locator('.app').evaluate((node) => node.clientWidth);
	expect(app, 'tablet app width').toBeLessThanOrEqual(1100);
	expect(app, 'tablet app width').toBeGreaterThan(760);
	const [s, c] = [await box(summary), await box(categories)];
	expect(Math.abs(s.top - c.top), 'Threat summary and Alert categories pair on a tablet').toBeLessThanOrEqual(1);
	await grow(summary, Math.ceil(Math.max(s.height, c.height)) + 600);
	expect(Math.abs((await heightOf(categories)) - (await heightOf(summary))), 'Alert categories stretches to its tablet pair').toBeLessThanOrEqual(1);
	await unGrow(summary);
});
