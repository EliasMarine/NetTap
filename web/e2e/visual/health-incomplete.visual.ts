/** NET-168: a health check that only partly ran is amber on Home's and System's health strips,
 * and the System overview chip says "Incomplete" in amber. Unit tests check the classes; this
 * checks the colour the browser actually paints, in every theme, so a missing CSS rule fails. */
import { test, expect, type Page } from '@playwright/test';
import { VARIANTS, expectReached, setMode, setVariant, settle, stubUpstreams, watchApi } from './harness.ts';

/** The page's computed colour for a token, as `rgb(…)`. */
function tokenColour(page: Page, token: string): Promise<string> {
	return page.evaluate((t) => {
		const probe = document.createElement('span');
		probe.style.color = `var(${t})`;
		document.body.append(probe);
		const colour = getComputedStyle(probe).color;
		probe.remove();
		return colour;
	}, token);
}

/** Every /api/system/health reply is the fixture's own, with the status set to incomplete. */
async function reportIncomplete(page: Page): Promise<void> {
	await page.route('**/api/system/health', async (route) => {
		const real = await route.fetch();
		const body = (await real.json()) as Record<string, unknown>;
		await route.fulfill({ response: real, json: { ...body, status: 'incomplete', healthy: null } });
	});
}

// Home names the stage "System"; the System page names it "NetTap".
const PAGES = [
	{ path: '/', heading: 'Network overview', stage: 'System' },
	{ path: '/system', heading: 'System', stage: 'NetTap' },
] as const;

test.describe('an incomplete health check is amber (NET-168)', () => {
	for (const variant of VARIANTS) {
		for (const { path, heading, stage } of PAGES) {
			test(`${path} in ${variant}`, async ({ page }) => {
				await setMode('populated');
				await stubUpstreams(page, 'populated');
				await reportIncomplete(page);
				await page.setViewportSize({ width: 1440, height: 900 });
				const apiIdle = watchApi(page);
				await page.goto(path);
				await expectReached(page, path, heading);
				await apiIdle();
				await setVariant(page, variant);
				await settle(page);

				const amber = await tokenColour(page, '--sev-medium');
				const orange = await tokenColour(page, '--sev-high');
				expect(amber, 'amber and orange are different colours').not.toBe(orange);

				const key = page.locator('main .pipe-k').filter({ hasText: new RegExp(`^${stage}$`) });
				const icon = key.getByRole('img', { name: 'Warning' });
				await expect(icon).toBeVisible();
				await expect(icon).toHaveCSS('color', amber);
				await expect(key.locator('xpath=..').locator('.pipe-v')).toHaveText("Incomplete · some checks couldn't run");

				if (path === '/system') {
					const chip = page.locator('main .chip').filter({ hasText: /^Incomplete$/ });
					await expect(chip).toHaveCSS('color', amber);
				}
			});
		}
	}
});
