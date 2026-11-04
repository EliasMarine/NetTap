/**
 * Slow mode's contract (PLAN.md §7): the fixture daemon holds every response until the test
 * releases it, so a page's loading state can be checked for as long as it lasts. Per-route
 * loading assertions arrive with the page fixtures in step C; this proves the mechanism.
 */
import { expect, test } from '@playwright/test';
import { expectReached, heldCount, releaseHeld, setMode, VIEWPORTS, watchApi } from './harness.ts';

test('slow mode holds responses until the test releases them', async ({ page }) => {
	await setMode('slow');
	const apiIdle = watchApi(page);
	await page.setViewportSize(VIEWPORTS[0]);
	// DNS Analytics loads everything in the browser, so the HTML arrives while its data is held.
	await page.goto('/dns');
	await expectReached(page, '/dns', 'DNS Analytics');

	await expect.poll(heldCount, { message: 'responses held by the fixture daemon' }).toBeGreaterThan(0);
	await page.waitForTimeout(500);
	expect(await heldCount(), 'still held: nothing is sent until release').toBeGreaterThan(0);

	expect(await releaseHeld()).toBeGreaterThan(0);
	// Leaving slow mode sends anything the page asked for after the release.
	await setMode('populated');
	await apiIdle();
	expect(await heldCount()).toBe(0);
});
