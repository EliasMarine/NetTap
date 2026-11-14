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
import { vi } from 'vitest';
import type { BeforeNavigate, NavigationType } from '@sveltejs/kit';

type Callback = (navigation: BeforeNavigate) => void;

const callbacks = new Set<Callback>();
const afterCallbacks = new Set<() => void>();
const history = { entries: [] as URL[], index: 0 };

export const page = $state({ url: new URL('http://localhost/settings') });

/** Start a test at `href` with a one-entry history. */
export function resetNavigation(href = 'http://localhost/settings'): void {
	page.url = new URL(href);
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

export const goto = vi.fn(async (href: string | URL) => push('goto', href));

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
