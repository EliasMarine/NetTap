/**
 * Charts fill their cards (NET-192). On every page with populated fixtures, at 1440 and 1024 px:
 * - a card holding an AreaChart or a Donut leaves at most 24 px under its last content and nothing
 *   hangs out of it (the DNS chart left 223 px, Live's donut 303 px);
 * - a col card's donut svg covers its box, so the ring is drawn at min(box width, box height);
 * - a Ring is never squashed below its 128 px (it shrank to 58 px beside long text on IoT).
 * The measures are the chart region and its card, not the svg alone.
 */
import { expect, test } from '@playwright/test';
import { APP_ROUTES } from './routes.ts';
import { expectReached, setMode, stubUpstreams, watchApi } from './harness.ts';

const WIDTHS = [
	{ width: 1440, height: 900 },
	{ width: 1024, height: 768 },
] as const;
const MAX_GAP = 24;
/** Pages whose populated fixtures draw a chart card: the spec must find one, or it measures nothing. */
const CHART_PAGES = new Set(['/', '/dns', '/alerts', '/live', '/pcap', '/bandwidth', '/iot', '/compliance']);
const RING = 128;

interface Measured {
	card: string;
	gap: number;
	overflow: number;
	donut?: { box: [number, number]; svg: [number, number] };
}

/** Runs in the page: every chart card's bottom gap and overflow, every Ring's width. */
function measure(): { cards: Measured[]; rings: number[] } {
	const px = (v: string) => parseFloat(v) || 0;
	const shown = (el: Element) => {
		const r = el.getBoundingClientRect();
		const cs = getComputedStyle(el);
		return (r.width > 0 || r.height > 0) && cs.display !== 'none' && cs.visibility !== 'hidden';
	};
	const cards: Measured[] = [];
	for (const card of document.querySelectorAll('main .card')) {
		if (!shown(card)) continue;
		const own = [...card.querySelectorAll('*')].filter((e) => e.closest('.card') === card && shown(e));
		const area = own.some((e) => e.matches('.chart') && e.querySelector('path.line'));
		const donutBox = own.find((e) => e.matches('.donut-box'));
		if (!area && !donutBox) continue;
		const cs = getComputedStyle(card);
		const cr = card.getBoundingClientRect();
		const inner = cr.bottom - px(cs.borderBottomWidth) - px(cs.paddingBottom);
		let lowest = 0;
		for (const e of own) {
			if (e.closest('svg') && e.tagName.toLowerCase() !== 'svg') continue;
			lowest = Math.max(lowest, e.getBoundingClientRect().bottom);
		}
		const m: Measured = {
			card: card.querySelector('.card-title')?.textContent?.trim() ?? '(untitled)',
			gap: Math.round(inner - lowest),
			overflow: Math.round(Math.max(0, lowest - inner)),
		};
		if (donutBox && card.matches('.col')) {
			const b = donutBox.getBoundingClientRect();
			const s = donutBox.querySelector('svg')!.getBoundingClientRect();
			m.donut = { box: [Math.round(b.width), Math.round(b.height)], svg: [Math.round(s.width), Math.round(s.height)] };
		}
		cards.push(m);
	}
	const rings = [...document.querySelectorAll('main svg')]
		.filter((s) => s.querySelector(':scope > circle.track') && shown(s))
		.map((s) => Math.round(s.getBoundingClientRect().width));
	return { cards, rings };
}

for (const route of APP_ROUTES) {
	test(`${route.path} charts fill their cards`, async ({ page }, testInfo) => {
		test.skip(testInfo.project.name === 'reduced-motion', 'layout is the same with reduced motion');
		await setMode('populated');
		await stubUpstreams(page, 'populated');
		for (const size of WIDTHS) {
			const apiIdle = watchApi(page);
			await page.setViewportSize(size);
			await page.goto(route.path);
			await expectReached(page, route.path, route.marker);
			await apiIdle();
			const { cards, rings } = await page.evaluate(measure);
			if (CHART_PAGES.has(route.path)) {
				expect(cards.length + rings.length, `${route.path} at ${size.width} px: no chart card measured`).toBeGreaterThan(0);
			}
			for (const c of cards) {
				const where = `${route.path} at ${size.width} px, "${c.card}"`;
				expect.soft(c.gap, `${where}: empty space under the chart`).toBeLessThanOrEqual(MAX_GAP);
				expect.soft(c.overflow, `${where}: content hangs out of the card`).toBe(0);
				if (c.donut) {
					const off = Math.max(...c.donut.svg.map((v, i) => Math.abs(v - c.donut!.box[i])));
					expect.soft(off, `${where}: the donut svg covers its box (${c.donut.svg} in ${c.donut.box})`).toBeLessThanOrEqual(2);
					expect.soft(Math.min(...c.donut.box), `${where}: the donut box is at least 160 px`).toBeGreaterThanOrEqual(160);
				}
			}
			for (const w of rings) expect.soft(w, `${route.path} at ${size.width} px: a Ring is squashed`).toBeGreaterThanOrEqual(RING);
		}
	});
}
