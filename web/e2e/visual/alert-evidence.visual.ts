/** NET-355: the alert drawer's Evidence block with a full page of packets, on a desktop and a phone.
 * Every part shows, and the packet scroller never pushes the drawer's actions out of reach. */
import { test, expect } from '@playwright/test';
import type { PacketSearchResult } from '../../src/lib/api/packets.ts';
import { expectNoConsoleErrors, expectReached, setMode, stubUpstreams, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';
import { ROWS } from './fixtures/packets.ts';

/** The fixture alert that carries a community ID (fixtures/alerts.ts) */
const SIGNATURE = 'ET MALWARE Example Agent.Gen CnC Checkin';
const COMMUNITY_ID = '1:BHcgw+xc46L4m7IOXm9O5K6Vg8o=';
const PACKETS = 100;
const HEADINGS = ['What Suricata saw', 'Fields Suricata recorded', 'Zeek records sharing this community ID', 'Packets near the alert time'];

// The fixture daemon answers by path alone, so the drawer's two searches get their own answers here
const ZEEK = {
	hits: ['CQ3vXb1kTz9mFq2Lw', 'CQ3vXb1kTz9mFq2Lx'].map((uid, i) => ({
		_id: `zeek-${i + 1}`,
		_index: 'arkime_sessions3-fixture',
		_source: { '@timestamp': new Date(Date.now() - (7 - i) * 60_000).toISOString(), event: { dataset: 'conn', provider: 'zeek' }, zeek: { uid, conn: { conn_state: 'SF' } } },
	})),
	total: 2,
	search_after: null,
	size: 10,
	log_type: 'all',
};

for (const viewport of [VIEWPORTS[1], VIEWPORTS[2]]) {
	test(`an alert's evidence and its actions fit @ ${viewport.width}`, async ({ page }, testInfo) => {
		const ctx = { route: '/alerts', mode: 'populated' } as const;
		const errors = watchConsole(page);
		await setMode('populated');
		await stubUpstreams(page, 'populated');
		await page.route(
			(url) => url.pathname === '/api/logs/search' && (url.searchParams.get('query') ?? '').includes(`network.community_id:"${COMMUNITY_ID}"`),
			(route) => route.fulfill({ json: ZEEK }),
		);
		let searched: unknown;
		await page.route(
			(url) => url.pathname === '/api/packets/search',
			async (route) => {
				searched = route.request().postDataJSON();
				const real = await route.fetch();
				const base = (await real.json()) as PacketSearchResult;
				const rows = Array.from({ length: PACKETS }, (_, i) => ({ ...ROWS[i % ROWS.length], n: i + 1, md5: (i + 1).toString(16).padStart(32, '0') }));
				const json: PacketSearchResult = {
					...base,
					rows,
					limit: 100,
					termination: 'limit',
					complete: false,
					manifest: { ...base.manifest, frames: rows.map(({ n, t, cap_len, md5 }) => ({ n, t, cap_len, md5 })) },
				};
				await route.fulfill({ response: real, json });
			},
		);
		await page.setViewportSize(viewport);
		const apiIdle = watchApi(page);
		await page.goto('/alerts');
		await expectReached(page, '/alerts', 'Alerts');
		await apiIdle();

		await page.locator('main button.alert-row', { hasText: SIGNATURE }).click();
		const drawer = page.getByRole('complementary', { name: 'Alert details' });
		const evidence = drawer.getByRole('region', { name: 'Evidence' });
		for (const name of HEADINGS) await expect(evidence.getByRole('heading', { name })).toBeVisible();
		await expect(evidence.getByRole('table', { name: "Zeek records sharing this alert's community ID" }).getByRole('row')).toHaveCount(ZEEK.hits.length + 1);

		await evidence.getByRole('button', { name: 'Show packets' }).click();
		await expect(evidence.getByRole('table', { name: 'Packets near the alert time' }).getByRole('row')).toHaveCount(PACKETS + 1);
		expect(searched).toMatchObject({ filter: expect.any(String), from: expect.any(String), to: expect.any(String), limit: 100 });
		await expect(evidence.getByRole('link', { name: 'Open in Packets' })).toBeVisible();
		await expect(evidence.getByRole('button', { name: `Download these ${PACKETS} packets` })).toBeVisible();

		const acknowledge = drawer.getByRole('button', { name: 'Acknowledge', exact: true });
		await acknowledge.scrollIntoViewIfNeeded();
		await expect(acknowledge).toBeInViewport();
		await acknowledge.click({ trial: true }); // reachable: nothing, the packet scroller included, covers it

		await sweep(page, testInfo, ctx, { variants: ['ember'], viewports: [viewport] });
		expectNoConsoleErrors(errors, ctx);
	});
}
