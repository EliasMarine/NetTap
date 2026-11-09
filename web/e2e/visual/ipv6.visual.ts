/** NET-218: the IPv6 toolkit on the real build, with a real session from auth.setup.ts. A shared
 * ?address= link server-renders its result, the page hydrates (an example click updates it), and
 * the collapsed ranges table opens. */
import { test, expect } from '@playwright/test';
import { expectNoConsoleErrors, setMode, stubUpstreams, watchConsole } from './harness.ts';

test('the IPv6 toolkit explains a shared address and stays interactive', async ({ page }) => {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	// Svelte reports hydration problems with console.warn, which watchConsole leaves out
	const warnings: string[] = [];
	page.on('console', (msg) => {
		if (msg.type() === 'warning') warnings.push(msg.text());
	});
	const errors = watchConsole(page);

	await page.goto('/tools/ipv6?address=2001:db8::1234');
	await expect(page.getByRole('heading', { level: 1, name: 'IPv6 toolkit' })).toBeVisible();
	await expect(page.locator('.chip', { hasText: 'Documentation' })).toBeVisible();
	await expect(page.getByText('2001:0db8:0000:0000:0000:0000:0000:1234')).toBeVisible();

	await page.getByRole('button', { name: 'Link-local from a MAC' }).click();
	await expect(page.getByText('Matches the EUI-64 pattern')).toBeVisible();
	await expect(page).toHaveURL(/address=fe80/);
	// The maker comes from the daemon after the debounce: wait for it, so the console check below sees that request too
	await expect(page.getByText('PCS Systemtechnik GmbH')).toBeVisible();

	const ranges = page.locator('details.ranges');
	await expect(ranges).not.toHaveAttribute('open');
	await ranges.locator('summary').click();
	await expect(page.getByRole('table', { name: 'IPv6 address ranges' })).toBeVisible();

	expect(warnings).toEqual([]);
	expectNoConsoleErrors(errors, { route: '/tools/ipv6', mode: 'populated' });
});
