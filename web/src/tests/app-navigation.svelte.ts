/**
 * A small stand-in for SvelteKit's client router, for page tests that follow the URL (NET-273).
 * Use it for both modules:
 *
 *   vi.mock('$app/state', () => import('../../tests/app-navigation.svelte'));
 *   vi.mock('$app/navigation', () => import('../../tests/app-navigation.svelte'));
 *
 * `page.url` is reactive. `goto` and `followLink` push a history entry and `traverse` moves through
 * them, as Back and Forward do; each runs the registered `beforeNavigate` callbacks first and stays
 * put when one cancels, as SvelteKit does (it undoes a cancelled Back or Forward itself). The
 * `afterNavigate` callbacks run after a navigation that went ahead.
 */
import { onDestroy } from 'svelte';
import { fromStore, type Readable } from 'svelte/store';
import { vi } from 'vitest';
// OLD CODE: import type { BeforeNavigate, NavigationType } from '@sveltejs/kit'; (kit 3 moved the navigation types to $app/navigation; NET-315)
import type { BeforeNavigate, NavigationType } from '$app/navigation';

type Callback = (navigation: BeforeNavigate) => void;

const callbacks = new Set<Callback>();
const afterCallbacks = new Set<() => void>();
const history = { entries: [] as URL[], index: 0 };

// OLD CODE: export const page = $state({ url: new URL('http://localhost/settings') }); (NET-357: route pages read their params too; NET-358: Settings › Account reads page.data.username)
export const page = $state({ url: new URL('http://localhost/settings'), params: {} as Record<string, string>, data: { username: 'admin' } as Record<string, unknown> });

// OLD CODE: /** Start a test at `href` with a one-entry history. */ export function resetNavigation(href = 'http://localhost/settings'): void { (NET-357)
/** Start a test at `href` with a one-entry history, and the route's `params` for a page that reads them. */
export function resetNavigation(href = 'http://localhost/settings', params: Record<string, string> = {}): void {
	page.url = new URL(href);
	page.params = params;
	history.entries = [page.url];
	history.index = 0;
}

/** The history's query strings and where the page is in it. */
export function historyState(): { entries: string[]; index: number } {
	return { entries: history.entries.map((u) => u.pathname + u.search), index: history.index };
}

function attempt(type: NavigationType, url: URL, delta?: number): boolean {
	let cancelled = false;
	const navigation = {
		type,
		from: { url: page.url, params: {}, route: { id: '/settings' } },
		to: { url, params: {}, route: { id: url.pathname === '/settings' ? '/settings' : null } },
		willUnload: false,
		delta,
		complete: Promise.resolve(),
		cancel: () => {
			cancelled = true;
		},
	} as unknown as BeforeNavigate;
	for (const callback of [...callbacks]) callback(navigation);
	if (cancelled) return false;
	page.url = url;
	for (const callback of [...afterCallbacks]) callback();
	return true;
}

function push(type: NavigationType, href: string | URL): void {
	const url = new URL(String(href), page.url);
	if (!attempt(type, url)) return;
	history.entries = [...history.entries.slice(0, history.index + 1), url];
	history.index += 1;
}

// OLD CODE: export const goto = vi.fn(async (href: string | URL) => push('goto', href)); (NET-357: `replace` swaps the current entry, as SvelteKit does)
export const goto = vi.fn(async (href: string | URL, opts?: { replace?: boolean }) => {
	if (!opts?.replace) return push('goto', href);
	const url = new URL(String(href), page.url);
	if (attempt('goto', url)) history.entries = history.entries.map((u, i) => (i === history.index ? url : u));
});

/** A click on an in-app link, as SvelteKit's router handles it. */
export function followLink(link: HTMLAnchorElement): void {
	push('link', link.getAttribute('href') ?? '');
}

/** Back (-1) or Forward (+1). */
export function traverse(delta: number): void {
	const url = history.entries[history.index + delta];
	if (url && attempt('popstate', url, delta)) history.index += delta;
}

/** The browser leaving the app (a reload, closing the tab): true when a callback asked it to prompt. */
export function unload(): boolean {
	let prompted = false;
	const navigation = {
		type: 'leave',
		from: { url: page.url, params: {}, route: { id: '/settings' } },
		to: null,
		willUnload: true,
		complete: Promise.resolve(),
		cancel: () => {
			prompted = true;
		},
	} as unknown as BeforeNavigate;
	for (const callback of [...callbacks]) callback(navigation);
	return prompted;
}

export const beforeNavigate = vi.fn((callback: Callback) => {
	callbacks.add(callback);
	onDestroy(() => callbacks.delete(callback));
});

// OLD CODE: export const afterNavigate = vi.fn(); (review L2: the page clears its Discard pass here)
export const afterNavigate = vi.fn((callback: () => void) => {
	afterCallbacks.add(callback);
	onDestroy(() => afterCallbacks.delete(callback));
});

/** What the store-backed `$app/state` page below exposes: all the pages read. */
// OLD CODE: type PageLike = { url: URL; params?: Record<string, string> }; (NET-358 review: the shell test renders Settings › Account, which reads page.data)
type PageLike = { url: URL; params?: Record<string, string>; data?: Record<string, unknown> };
// Test stores are typed loosely (unknown values, hand-written subscribe); the pages read only url and params
type StoresModule = { page: Readable<unknown> };

/**
 * kit 3 (NET-315) removed `$app/stores`. Page tests written against a `$app/stores` mock keep that
 * mock's store, and its driver code, and hand it here for the `$app/state` mock:
 *
 *   vi.mock('$app/state', async () => (await import('../../tests/app-navigation.svelte')).stateFromStores(() => ({ page: readable(…) })));
 *
 * `page.url`, `page.params` and `page.data` follow the store, reactively.
 */
export async function stateFromStores(factory: () => StoresModule | Promise<StoresModule>): Promise<{ page: Required<PageLike> }> {
	const store = fromStore((await factory()).page as Readable<PageLike>);
	return {
		page: {
			get url() {
				return store.current.url;
			},
			get params() {
				return store.current.params ?? {};
			},
			get data() {
				return store.current.data ?? {};
			},
		},
	};
}
