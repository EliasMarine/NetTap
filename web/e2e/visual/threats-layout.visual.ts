/** The Threats page's auto-investigation, opened: its three sections share the body's width instead
 * of sitting in narrow columns beside empty ones (the todo used to span every auto-fit track, so
 * none collapsed), and a full-length IPv6 address breaks only after a colon. No horizontal page
 * scroll from 390 px up. */
import { test, expect, type Page } from '@playwright/test';
import { expectReached, setMode, settle, stubUpstreams, watchApi } from './harness.ts';
import { INVESTIGATION_IPV6, REPORT_WITH_IPV6_INVESTIGATION } from './fixtures/threats.ts';

async function open(page: Page): Promise<void> {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.route((url) => url.pathname === '/api/threats/report', (r) => r.fulfill({ json: REPORT_WITH_IPV6_INVESTIGATION }));
	await page.setViewportSize({ width: 1440, height: 900 });
	const apiIdle = watchApi(page);
	await page.goto('/threats');
	await expectReached(page, '/threats', 'Threats');
	await apiIdle();
	// the first investigation opens on its own
	await expect(page.locator('main .inv-body')).toBeVisible();
}

/** Each section's width over the body's, and whether any address line breaks inside a group. Runs in the page. */
function measure() {
	const body = document.querySelector('main .inv-body')!.getBoundingClientRect().width;
	const sections = [...document.querySelectorAll('main .inv-sections > section')].map((s) => s.getBoundingClientRect().width / body);
	const todoInGrid = !!document.querySelector('main .inv-sections .inv-todo');
	return { sections, todoInGrid };
}

test.describe('Threats auto-investigation layout', () => {
	test('the sections share the body, the todo sits below them, and nothing scrolls sideways', async ({ page }, testInfo) => {
		await open(page);
		const wide = await page.evaluate(measure);
		expect(wide.todoInGrid, 'the todo is outside the sections grid').toBe(false);
		expect(wide.sections).toHaveLength(3);
		for (const share of wide.sections) expect(share, 'each section at 1440 px').toBeGreaterThan(0.25);
		for (const width of [1440, 1024, 768, 390]) {
			await page.setViewportSize({ width, height: 900 });
			await settle(page);
			const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
			expect.soft(scrollWidth, `horizontal scroll @ ${width}`).toBeLessThanOrEqual(width);
			await page.screenshot({ path: testInfo.outputPath(`investigation-${width}.png`), fullPage: true });
		}
	});

	test('a full-length IPv6 address breaks only after a colon', async ({ page }) => {
		await open(page);
		await page.setViewportSize({ width: 390, height: 900 });
		await settle(page);
		const ip = page.locator('main .inv-body dd.ip').first();
		await expect(ip).toHaveText(INVESTIGATION_IPV6.source);
		// every rendered line of the address ends at a colon or at its end
		const lines = await ip.evaluate((el) => {
			const range = document.createRange();
			range.selectNodeContents(el);
			const tops = new Map<number, string>();
			const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
			for (let node = walker.nextNode(); node; node = walker.nextNode()) {
				const text = node.textContent ?? '';
				for (let i = 0; i < text.length; i++) {
					range.setStart(node, i);
					range.setEnd(node, i + 1);
					const top = Math.round(range.getBoundingClientRect().top);
					tops.set(top, (tops.get(top) ?? '') + text[i]);
				}
			}
			return [...tops.values()];
		});
		for (const line of lines.slice(0, -1)) expect(line.endsWith(':'), `a line of the address: ${line}`).toBe(true);
	});
});
