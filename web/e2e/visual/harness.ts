/** Shared checks for the visual specs (PLAN.md §5.2 "Each spec"). */
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { DAEMON_URL } from '../../playwright.visual.config.ts';
import { knownIssue } from './known-issues.ts';
import { findTileSpills } from './severity-tiles.ts';

export const VARIANTS = ['ember', 'graphite', 'spectrum'] as const;
export const VIEWPORTS = [
	{ width: 1920, height: 1080 },
	{ width: 1440, height: 900 },
	{ width: 390, height: 844 },
] as const;

/** `slow` holds every daemon response until `releaseHeld()`. Stale data is a sequence: load in
 * `populated`, `setMode('error')`, press the top bar's Refresh, then check the old data is marked. */
export type FixtureMode = 'populated' | 'empty' | 'error' | 'slow';

// --accent per theme, from src/lib/styles/tokens.css: a theme-only value, so a screenshot can't be mislabelled
export const ACCENT = { ember: '#ff7a1a', graphite: '#f4f4f5', spectrum: '#9b8cff' } as const;
export type Variant = (typeof VARIANTS)[number];

export async function setMode(mode: FixtureMode): Promise<void> {
	const res = await fetch(`${DAEMON_URL}/__fixture/mode`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode }),
	});
	if (!res.ok) throw new Error(`fixture daemon refused mode ${mode}: ${res.status} ${await res.text()}`);
}

/** How many responses `slow` mode is holding. */
export async function heldCount(): Promise<number> {
	const res = await fetch(`${DAEMON_URL}/__fixture/health`);
	return ((await res.json()) as { held: number }).held;
}

/** Sends every response `slow` mode is holding; later requests are held again until the next call. */
export async function releaseHeld(): Promise<number> {
	const res = await fetch(`${DAEMON_URL}/__fixture/release`, { method: 'POST' });
	if (!res.ok) throw new Error(`fixture daemon refused release: ${res.status}`);
	return ((await res.json()) as { released: number }).released;
}

// Only the fixture daemon's 503: a 500 or 502 from the web server itself is a bug error mode must catch.
const SERVER_ERROR_RESOURCE = /^Failed to load resource: the server responded with a status of 503\b/;

/** Collects console errors and uncaught exceptions for the whole test. */
export function watchConsole(page: Page, opts: { allowServerErrors?: boolean } = {}): string[] {
	const errors: string[] = [];
	page.on('console', (msg) => {
		if (msg.type() !== 'error') return;
		const text = msg.text();
		// error mode: the 503 responses themselves are expected; anything else still fails
		if (opts.allowServerErrors && SERVER_ERROR_RESOURCE.test(text)) return;
		errors.push(`${text} (${msg.location().url})`);
	});
	page.on('pageerror', (err) => errors.push(`uncaught: ${err.message}`));
	return errors;
}

// The notification stream is an open EventSource for the life of the page; it never "finishes".
const LONG_LIVED = /\/api\/notifications\/stream/;

/** Counts the page's in-flight /api/ requests, so checks run after the page has its data (or its error). */
export function watchApi(page: Page): () => Promise<void> {
	const inFlight = new Set<object>();
	// Server-rendered headings appear before hydration, when no request has started yet, so wait for one.
	// Every page makes at least one: the root layout pings /api/system/ping on start.
	let seen = 0;
	const isApi = (url: string) => url.includes('/api/') && !LONG_LIVED.test(url);
	page.on('request', (r) => {
		if (!isApi(r.url())) return;
		seen++;
		inFlight.add(r);
	});
	page.on('requestfinished', (r) => inFlight.delete(r));
	page.on('requestfailed', (r) => inFlight.delete(r));
	return async () => {
		await expect
			.poll(() => seen > 0 && inFlight.size === 0, { timeout: 20_000, message: 'no API request yet, or some still in flight' })
			.toBe(true);
		await settle(page);
	};
}

/** Two frames (so Svelte renders and transitions start), then every running CSS transition ends.
 * Resizing and switching variants start width/colour transitions; measuring mid-way reads stale layout.
 * Transitions only: infinite keyframe animations (spinners, pulses) never finish. */
export async function settle(page: Page): Promise<void> {
	await page.evaluate(async () => {
		await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
		const transitions = document.getAnimations().filter((a) => a instanceof CSSTransition);
		await Promise.all(transitions.map((a) => a.finished.catch(() => undefined)));
	});
}

/** The page really is `path` (no redirect to Login or Setup) and shows its own marker:
 * a heading, or (`text`) visible text for an error state that has no heading. */
export async function expectReached(
	page: Page,
	path: string,
	marker: string | RegExp,
	opts: { scope?: string; text?: boolean } = {}
): Promise<void> {
	expect(new URL(page.url()).pathname, `expected ${path}, was redirected`).toBe(path);
	const scope = page.locator(opts.scope ?? 'main');
	const target = opts.text ? scope.getByText(marker) : scope.getByRole('heading', { name: marker });
	await expect(target.first()).toBeVisible();
}

/** What the page reaches that the fixture daemon doesn't serve:
 * - upstreams nginx proxies on the device: /infrastructure probes Grafana (an optional compose
 *   profile) at /grafana/api/health, and CyberChef pages frame /cyberchef/ once it reports running
 * - other hosts (the GeoIP page's OpenStreetMap embed): the harness never uses the internet */
export async function stubUpstreams(page: Page, mode: FixtureMode): Promise<void> {
	await page.route(/^https?:\/\/(?!127\.0\.0\.1[:/])/, (route) => route.fulfill({ contentType: 'text/html', body: '' }));
	await page.route('**/grafana/api/health', (route) =>
		mode === 'error'
			? route.fulfill({ status: 503, json: { error: 'fixture error mode' } })
			: route.fulfill({ json: { database: 'ok', version: '10.4.0' } })
	);
	await page.route('**/cyberchef/', (route) => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>CyberChef</title>' }));
}

export async function setVariant(page: Page, variant: Variant): Promise<void> {
	await page.evaluate((v) => {
		if (v === 'ember') delete document.documentElement.dataset.theme;
		else document.documentElement.dataset.theme = v;
	}, variant);
}

/** Which page and fixture mode a check ran on, so known issues match narrowly. */
export interface CheckContext {
	route: string;
	mode: FixtureMode;
}

function annotate(testInfo: TestInfo, type: string, description: string): void {
	testInfo.annotations.push({ type, description });
}

/** Horizontal overflow fails unless it is a known issue for this route. */
function checkOverflow(testInfo: TestInfo, ctx: CheckContext, variant: Variant, width: number, scrollWidth: number): void {
	if (scrollWidth <= width) return;
	const where = `${ctx.route} ${scrollWidth} [${ctx.mode}, ${variant}]`;
	const known = knownIssue(ctx.route, ctx.mode, `horizontal scroll @ ${width}`);
	if (known) return annotate(testInfo, 'known-issue', `${known.note}: ${where} @ ${width}`);
	expect.soft(scrollWidth, `horizontal scroll, ${variant} @ ${width}`).toBeLessThanOrEqual(width);
}

/** A severity count stays inside its tile, and a tile never runs into the one beside it. */
async function checkSeverityTiles(page: Page, variant: Variant, width: number): Promise<void> {
	expect.soft(await page.evaluate(findTileSpills), `severity tiles, ${variant} @ ${width}`).toEqual([]);
}

/** The shell (PLAN.md §7): the sidebar on desktop, the phone bar at 390, and the page's own h1. */
async function checkShell(page: Page, variant: Variant, width: number): Promise<void> {
	const at = `${variant} @ ${width}`;
	if (width >= 1100) await expect.soft(page.locator('nav.sidebar'), `sidebar, ${at}`).toBeVisible();
	if (width <= 760) await expect.soft(page.locator('.m-top'), `phone bar, ${at}`).toBeVisible();
	await expect.soft(page.locator('main h1.page-title'), `one h1.page-title, ${at}`).toHaveCount(1);
}

/** Every variant at every viewport: the theme really applied, black body, no horizontal scroll,
 * the shell (unless `shell: false`, for Login and Setup), a screenshot. */
export async function sweep(
	page: Page,
	testInfo: TestInfo,
	ctx: CheckContext,
	opts: { variants?: readonly Variant[]; viewports?: readonly { width: number; height: number }[]; shell?: boolean } = {}
): Promise<void> {
	for (const variant of opts.variants ?? VARIANTS) {
		await setVariant(page, variant);
		const accent = await page.evaluate(() =>
			getComputedStyle(document.documentElement).getPropertyValue('--accent').trim().toLowerCase(),
		);
		expect(accent, `--accent after switching to ${variant}`).toBe(ACCENT[variant]);
		for (const viewport of opts.viewports ?? VIEWPORTS) {
			await page.setViewportSize(viewport);
			await settle(page);
			const metrics = await page.evaluate(() => ({
				bg: getComputedStyle(document.body).backgroundColor,
				scrollWidth: document.documentElement.scrollWidth,
			}));
			expect.soft(metrics.bg, `body background, ${variant} @ ${viewport.width}`).toBe('rgb(0, 0, 0)');
			checkOverflow(testInfo, ctx, variant, viewport.width, metrics.scrollWidth);
			await checkSeverityTiles(page, variant, viewport.width);
			if (opts.shell ?? true) await checkShell(page, variant, viewport.width);
			await page.screenshot({ path: testInfo.outputPath(`${variant}-${viewport.width}.png`), fullPage: true });
		}
	}
}

/** Fails on any console error that is not a known issue for this route and mode. */
export function expectNoConsoleErrors(errors: string[], ctx: CheckContext): void {
	const unknown = errors.filter((text) => {
		const known = knownIssue(ctx.route, ctx.mode, text);
		if (known) annotate(test.info(), 'known-issue', `${known.note}: ${ctx.route} [${ctx.mode}] ${text}`);
		return !known;
	});
	expect(unknown, 'console errors').toEqual([]);
}
