/**
 * README and docs media: stills of the main pages and a short captioned tour video, drawn from the populated
 * fixtures, so no real network ever appears (RFC 1918 / 5737 addresses, example.com names, home = London).
 * Run with `npm run capture:media` (needs ffmpeg on PATH; opens a Chrome window, so the globe draws on
 * the real GPU). It rewrites the files it names in .github/assets/media/ (the README's). The MP4 is
 * gitignored there: only the untracked docs site uses it, so copy it into docs/assets/media/ by hand.
 * Not part of `npm run test:visual`: the `media` project exists only under NETTAP_CAPTURE_MEDIA.
 */
import { expect, test, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { APP_URL, STORAGE_STATE } from '../../playwright.visual.config.ts';
import { ROWS, SEARCH_QUERY } from './fixtures/packets.ts';
import { expectReached, setMode, settle, stubUpstreams, watchApi } from './harness.ts';

// OLD CODE START — NET-214: docs/ is untracked now; the README's media live in .github/assets/media
// const OUT = path.resolve(import.meta.dirname, '../../../docs/assets/media');
// OLD CODE END
const OUT = path.resolve(import.meta.dirname, '../../../.github/assets/media');
const VIEWPORT = { width: 1440, height: 900 };
const GIF_FPS = 12;

interface Still {
	file: string;
	path: string;
	/** Query string the page opens with, e.g. a packet search. */
	search?: string;
	marker: string | RegExp;
	/** Runs after the page has its data, before the screenshot. */
	prepare?: (page: Page) => Promise<void>;
}

// The README shows live-globe-expanded full width, then the rest in this order, two per row.
const STILLS: readonly Still[] = [
	{ file: 'live-globe-expanded', path: '/live', marker: /Live/, prepare: expandGlobe },
	{ file: 'home', path: '/', marker: 'Network overview' },
	{ file: 'live-globe', path: '/live', marker: /Live/, prepare: (page) => globeRunning(page).then(() => scrollToGlobe(page, 1_000)) },
	{ file: 'alerts', path: '/alerts', marker: 'Alerts' },
	{ file: 'alert-category', path: '/alerts/malware', marker: /malware/i },
	{ file: 'packets', path: '/packets', search: SEARCH_QUERY, marker: 'Packet analysis', prepare: packetsFound },
	{ file: 'packet-detail', path: '/packets', search: SEARCH_QUERY, marker: 'Packet analysis', prepare: packetOpen },
	{ file: 'devices', path: '/devices', marker: 'Devices' },
	{ file: 'device-detail', path: '/devices/mac/02:00:5e:10:00:20', marker: 'laptop-01.example.com' },
	{ file: 'threats', path: '/threats', marker: 'Threats' },
	{ file: 'certificates', path: '/certificates', marker: 'Certificates' },
];

const globeCard = (page: Page) => page.locator('main .globe-card');

/** The globe must really draw (not the flat fallback), then run long enough for arcs and packets to show. */
async function globeRunning(page: Page): Promise<void> {
	await expect(globeCard(page)).toHaveAttribute('data-backend', /^(WebGPU|WebGL 2)$/, { timeout: 20_000 });
	await page.waitForTimeout(2_500);
}

async function smoothScroll(page: Page, top: number, holdMs: number): Promise<void> {
	await page.evaluate((y) => window.scrollTo({ top: y, behavior: 'smooth' }), top);
	await page.waitForTimeout(holdMs);
}

/** Scroll so the whole globe card is in view: at 900 px tall it starts below the fold. */
async function scrollToGlobe(page: Page, holdMs: number): Promise<void> {
	const top = await globeCard(page).evaluate((el) => el.getBoundingClientRect().top + window.scrollY - 24);
	await smoothScroll(page, top, holdMs);
}

/** Expand the globe to fill the window, as a modal, and let the camera settle at the new size. */
async function expandGlobe(page: Page): Promise<void> {
	await globeRunning(page);
	await globeCard(page).getByRole('button', { name: 'Expand' }).click();
	const dialog = page.getByRole('dialog', { name: 'Where your traffic goes' });
	await expect(dialog).toHaveAttribute('aria-modal', 'true');
	expect(await dialog.boundingBox(), 'the expanded globe fills the window').toEqual({ x: 0, y: 0, ...VIEWPORT });
	await page.mouse.move(0, 0); // off the destinations list, so no row shows its hover state
	await page.waitForTimeout(2_500);
}

/** A packet search's answer, as packets.visual.ts opens it: every fixture row and the conversation chart. */
async function packetsFound(page: Page): Promise<void> {
	// NET-276: a search opened by its URL waits for Run
	await page.getByRole('button', { name: 'Run the search' }).click();
	await expect(page.getByRole('table', { name: 'Packets' }).getByRole('row')).toHaveCount(ROWS.length + 1);
	await expect(page.getByRole('heading', { name: 'The conversation over time' })).toBeVisible();
}

/** Packet 1 in its drawer: the IPv4 layer open and its destination address picked, so the hex bytes light up. */
async function packetOpen(page: Page): Promise<void> {
	await packetsFound(page);
	await page.getByRole('button', { name: `Open packet ${ROWS[0].n}` }).click();
	const drawer = page.getByRole('complementary', { name: `Packet 1 of ${ROWS.length}` });
	await drawer.getByText(/^Internet Protocol Version 4/).click();
	await drawer.getByRole('button', { name: /Destination Address/ }).click();
	await expect(drawer.locator('.hex mark').first()).toBeVisible();
	await page.mouse.move(0, 0); // off the layer tree, so no row shows its hover state
}

/** The tour's caption: what the screen on view shows. It sits on a band that fades the page to black along
 * the bottom of the content column, so it never half-covers a heading. It lives only in this recording.
 * Without a title it fades the caption out, before a page change. */
async function caption(page: Page, title?: string, text?: string): Promise<void> {
	await page.evaluate(
		async ([title, text]) => {
			let band = document.getElementById('media-caption');
			if (!band) {
				const main = document.querySelector('main')!.getBoundingClientRect();
				band = document.createElement('div');
				band.id = 'media-caption';
				// app tokens, so it reads as part of the UI; the text stays readable in the 800 px GIF
				band.style.cssText = [
					'position:fixed', `left:${main.left}px`, 'right:0', 'bottom:0', 'height:160px', 'z-index:2147483647',
					'display:flex', 'align-items:flex-end', 'justify-content:center', 'padding-bottom:var(--sp-8)',
					'pointer-events:none', 'background:linear-gradient(to bottom, transparent, var(--bg) 72%)',
				].join(';');
				const pill = document.createElement('div');
				pill.style.cssText = [
					'display:flex', 'gap:var(--sp-4)', 'align-items:center', 'white-space:nowrap', 'opacity:0',
					'transition:opacity 250ms ease', 'padding:var(--sp-3) var(--sp-6)', 'border:1px solid var(--line-strong)',
					'border-radius:var(--r-pill)', 'background:var(--surface-2)', 'box-shadow:var(--shadow-pop)',
					'color:var(--text-1)', 'font:500 var(--text-xl)/1.3 var(--font-display)',
				].join(';');
				band.append(pill);
				document.body.append(band);
			}
			const pill = band.firstElementChild as HTMLElement;
			if (pill.style.opacity !== '0') {
				pill.style.opacity = '0';
				await new Promise((done) => setTimeout(done, 250));
			}
			if (!title) return;
			const label = document.createElement('b');
			label.textContent = title;
			label.style.cssText = 'color:var(--accent);font-weight:600;padding-right:var(--sp-4);border-right:1px solid var(--line-strong)';
			pill.replaceChildren(label, text ?? '');
			pill.style.opacity = '1';
		},
		[title, text] as const,
	);
}

/** Closing card: the app's own brand mark and the README's tagline, over the page, before the video fades out. */
async function endCard(page: Page, holdMs: number): Promise<void> {
	await caption(page);
	await page.evaluate(() => {
		const card = document.createElement('div');
		card.style.cssText = [
			'position:fixed', 'inset:0', 'z-index:2147483647', 'display:grid', 'place-content:center', 'justify-items:center',
			'gap:var(--sp-6)', 'background:var(--bg)', 'opacity:0', 'transition:opacity 400ms ease', 'pointer-events:none',
		].join(';');
		const brand = document.querySelector('nav.sidebar a[href="/"]')!.cloneNode(true) as HTMLElement;
		brand.style.zoom = '2.5';
		const tagline = document.createElement('p');
		tagline.textContent = 'See what every device on your network is doing.';
		tagline.style.cssText = 'margin:0;color:var(--text-2);font:500 var(--text-xl)/1.3 var(--font-display)';
		card.append(brand, tagline);
		document.body.append(card);
		requestAnimationFrame(() => (card.style.opacity = '1'));
	});
	await page.waitForTimeout(holdMs);
}

/** Records the page through Chrome's screencast, frame by frame as JPEGs at the viewport's size: sharp text
 * and a smooth globe, where recordVideo encodes at 1 Mbit/s. Returns a stop function that writes the ffconcat list. */
async function startScreencast(page: Page, dir: string): Promise<() => Promise<{ list: string; seconds: number }>> {
	mkdirSync(dir, { recursive: true });
	const cdp = await page.context().newCDPSession(page);
	const stamps: number[] = [];
	const now = () => Date.now() / 1000;
	let clockOffset = 0; // Chrome's frame clock minus ours, so the last frame can be held until stop
	cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
		writeFileSync(path.join(dir, `${stamps.length}.jpg`), Buffer.from(data, 'base64'));
		const stamp = metadata.timestamp ?? now();
		if (!stamps.length) clockOffset = stamp - now();
		stamps.push(stamp);
		// a frame that lands as the context closes has no session left to ack
		cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => undefined);
	});
	await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 95, maxWidth: VIEWPORT.width * 2, maxHeight: VIEWPORT.height * 2 });
	return async () => {
		const end = now() + clockOffset;
		await cdp.send('Page.stopScreencast');
		expect(stamps.length, 'screencast frames').toBeGreaterThan(0);
		// Chrome sends a frame when the screen changes: each one shows until the next arrives, the last until stop
		const shown = stamps.map((t, i) => Math.max((stamps[i + 1] ?? end) - t, 0.001));
		const list = path.join(dir, 'frames.txt');
		writeFileSync(list, ['ffconcat version 1.0', ...shown.flatMap((d, i) => [`file ${i}.jpg`, `duration ${d.toFixed(4)}`]), `file ${stamps.length - 1}.jpg`].join('\n'));
		return { list, seconds: shown.reduce((sum, d) => sum + d, 0) };
	};
}

/** A 256-colour palette PNG: about half the size, and no visible banding on these dark pages. */
function shrinkPng(source: string, target: string): void {
	execFileSync('ffmpeg', [
		'-y', '-loglevel', 'error', '-i', source,
		'-vf', 'split[a][b];[a]palettegen=max_colors=256:stats_mode=single[p];[b][p]paletteuse=dither=sierra2_4a',
		target,
	]);
}

test.beforeAll(async () => {
	await setMode('populated');
	mkdirSync(OUT, { recursive: true });
});

test.describe('stills', () => {
	test.use({ viewport: VIEWPORT, deviceScaleFactor: 2 });

	for (const still of STILLS) {
		test(still.file, async ({ page }, testInfo) => {
			await stubUpstreams(page, 'populated');
			const apiIdle = watchApi(page);
			await page.goto(`${still.path}${still.search ? `?${still.search}` : ''}`);
			await expectReached(page, still.path, still.marker);
			await apiIdle();
			await still.prepare?.(page);
			await settle(page);
			const raw = testInfo.outputPath(`${still.file}.png`);
			await page.screenshot({ path: raw });
			shrinkPng(raw, path.join(OUT, `${still.file}.png`));
		});
	}
});

/** Click a sidebar entry, caption the page it opens, and hold on it. */
async function visit(page: Page, href: string, marker: string | RegExp, [title, text]: [string, string], holdMs: number): Promise<void> {
	await caption(page);
	// by href: a badge (Alerts' count) is part of the link's accessible name
	await page.locator(`nav.sidebar a[href="${href}"]`).click({ timeout: 10_000 });
	await expect(page.locator('main').getByRole('heading', { name: marker }).first()).toBeVisible();
	await caption(page, title, text);
	await page.waitForTimeout(holdMs);
}

test('tour video', async ({ browser }, testInfo) => {
	test.setTimeout(180_000);
	const context = await browser.newContext({ baseURL: APP_URL, storageState: STORAGE_STATE, viewport: VIEWPORT, deviceScaleFactor: 2 });
	const page = await context.newPage();
	await stubUpstreams(page, 'populated');
	const apiIdle = watchApi(page);
	await page.goto('/');
	await expectReached(page, '/', 'Network overview');
	await apiIdle();
	await caption(page, 'Home', 'Your whole network at a glance');
	const stop = await startScreencast(page, testInfo.outputPath('frames'));

	await page.waitForTimeout(3_000);
	await caption(page, 'Home', 'Top devices, traffic types and alerts');
	await smoothScroll(page, 700, 2_500);
	await smoothScroll(page, 0, 1_000);
	await visit(page, '/live', /Live/, ['Live monitor', 'Where your traffic goes, right now'], 0);
	await globeRunning(page);
	await scrollToGlobe(page, 5_000);
	await visit(page, '/devices', 'Devices', ['Devices', 'Every device on your network, busiest first'], 3_000);
	await visit(page, '/alerts', 'Alerts', ['Alerts', 'Intrusion alerts in plain English'], 2_500);
	await caption(page, 'Alerts', 'Grouped by type, with the device involved');
	await smoothScroll(page, 600, 2_500);
	await visit(page, '/threats', 'Threats', ['Threats', 'Kill chains, beaconing and threat-intel matches'], 3_000);
	await visit(page, '/certificates', 'Certificates', ['Certificates', 'TLS certificates that need a look'], 3_000);
	await endCard(page, 3_000);

	const { list, seconds } = await stop();
	await context.close();
	encodeVideo(list, seconds);
});

/** MP4 for the docs site, GIF for the README: GitHub plays a GIF inline but not a repo-hosted MP4. */
function encodeVideo(list: string, seconds: number): void {
	const fade = `fade=t=in:d=0.5,fade=t=out:st=${(seconds - 0.8).toFixed(2)}:d=0.8`;
	const ffmpeg = (filters: string, args: string[]) =>
		execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-i', list, '-vf', filters, ...args]);
	ffmpeg(`fps=30,${fade}`, [
		'-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-preset', 'slow', '-movflags', '+faststart', '-an',
		path.join(OUT, 'nettap-tour.mp4'),
	]);
	// Under 8 MB: unchanged frames are held, not repeated; one palette for the clip; only changed rectangles redrawn
	const gif = path.join(OUT, 'nettap-tour.gif');
	ffmpeg(
		`fps=${GIF_FPS},scale=800:-1:flags=lanczos,${fade},mpdecimate,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle`,
		['-fps_mode', 'vfr', gif],
	);
	expect(statSync(gif).size, 'README GIF over 8 MB').toBeLessThan(8_000_000);
}
