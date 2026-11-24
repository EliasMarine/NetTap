/**
 * NET-372 (QA 2026-11-23 #12): a long device name in IoT › Findings widened the whole page at
 * 320 px (document 347 px): the name button kept `.link`'s nowrap. It must wrap inside its card,
 * a name with no spaces too, and in a privacy finding's sentence as well. A real browser, since
 * jsdom has no layout.
 */
import { test, expect, type Locator } from '@playwright/test';
import type { PrivacyReport, ProtocolAudit } from '../../src/lib/api/iot.ts';
import { expectReached, setMode, settle, stubUpstreams, watchApi } from './harness.ts';

// A maker name as a device without a hostname shows (only in the button), and one unbroken run
// only overflow-wrap can break (in the button and at the start of its privacy finding's sentence)
const SPACED = 'Hon Hai Precision Industry Co., Ltd. (Foxconn) smart plug';
const UNBROKEN = 'espressif_esp32c3_devkitm1_living_room_humidity_sensor_0042';

const audit: ProtocolAudit = {
	devices: [{
		mac: '02:00:5e:10:00:90',
		name: SPACED,
		category: 'plug',
		findings: [{ type: 'unexpected_port', severity: 'medium', port: 8883, connection_count: 3, description: 'Uses port 8883 which is not expected for a plug' }],
		violation_count: 1,
		compliant: false,
	}],
};

// one tracker and nothing else to report: exactly one finding, "<name> contacted 1 tracker domain"
const privacy: PrivacyReport = {
	devices: [{
		mac: '02:00:5e:10:00:91',
		name: UNBROKEN,
		privacy_grade: 'B',
		privacy_score: 80,
		tracker_domains: [{ domain: 'telemetry.example.org', query_count: 12 }],
		tracker_count: 1,
		tracker_lookup_share: 0.1,
		third_party_orgs: 1,
		encryption_ratio: null,
		phone_home_per_hour: 0,
	}],
};

/** How many lines the first `length` characters of `el`'s text take, and whether `el` stays inside its finding. */
function layout(el: Locator, length: number) {
	return el.evaluate((node, n) => {
		const text = node.firstChild!;
		const range = document.createRange();
		range.setStart(text, 0);
		range.setEnd(text, n);
		const lines = new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
		const own = node.getBoundingClientRect();
		const finding = node.closest('.finding-body')!.getBoundingClientRect();
		return { lines, inside: own.right <= finding.right + 0.5 };
	}, length);
}

test('a long device name in Findings wraps inside its card at 320 px (NET-372)', async ({ page }, testInfo) => {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.route((url) => url.pathname === '/api/iot/protocol-audit', (r) => r.fulfill({ json: audit }));
	await page.route((url) => url.pathname === '/api/iot/privacy-report', (r) => r.fulfill({ json: privacy }));
	await page.setViewportSize({ width: 320, height: 800 });
	const apiIdle = watchApi(page);
	await page.goto('/iot');
	await expectReached(page, '/iot', 'IoT trust score');
	await apiIdle();
	await settle(page);

	const sentence = page.locator('main .finding-body p', { hasText: `${UNBROKEN} contacted 1 tracker domain` });
	const cases: [string, Locator, number][] = [
		['spaced name button', page.locator('main .finding-device', { hasText: SPACED }), SPACED.length],
		['unbroken name button', page.locator('main .finding-device', { hasText: UNBROKEN }), UNBROKEN.length],
		['unbroken name in its sentence', sentence, UNBROKEN.length],
	];
	for (const [what, el, length] of cases) {
		await expect(el, what).toBeVisible();
		const { lines, inside } = await layout(el, length);
		expect.soft(inside, `${what}: inside its finding`).toBe(true);
		// a clipped or ellipsised single line would fit too: the name itself must wrap
		expect.soft(lines, `${what}: the name wraps`).toBeGreaterThan(1);
	}
	await page.screenshot({ path: testInfo.outputPath('iot-findings-320.png'), fullPage: true });
	expect(await page.evaluate(() => document.documentElement.scrollWidth), 'no horizontal page scroll').toBeLessThanOrEqual(320);
});
