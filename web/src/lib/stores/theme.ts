/**
 * Theme variant store.
 *
 * Protocol (PLAN.md, PR 1):
 * - The inline script in app.html reads localStorage before first paint and sets
 *   <html data-variant>. Ember is the absence of the attribute.
 * - This store starts from that attribute and never reads storage itself, so it
 *   can't disagree with what is already painted. Nothing writes on init.
 * - setTheme is the only writer: attribute first, then the store (so subscribers
 *   that read computed tokens see the new values), then storage.
 */
import { writable, type Readable } from 'svelte/store';

export type ThemeVariant = 'ember' | 'graphite' | 'spectrum';

export const THEME_VARIANTS: readonly ThemeVariant[] = ['ember', 'graphite', 'spectrum'];
export const THEME_STORAGE_KEY = 'nettap-theme';

export function isThemeVariant(value: unknown): value is ThemeVariant {
	return typeof value === 'string' && (THEME_VARIANTS as readonly string[]).includes(value);
}

function initialVariant(): ThemeVariant {
	if (typeof document === 'undefined') return 'ember';
	const attr = document.documentElement.dataset.variant;
	return attr === 'graphite' || attr === 'spectrum' ? attr : 'ember';
}

const store = writable<ThemeVariant>(initialVariant());

export const theme: Readable<ThemeVariant> = { subscribe: store.subscribe };

export function setTheme(value: ThemeVariant): void {
	if (!isThemeVariant(value) || typeof document === 'undefined') return;

	const root = document.documentElement;
	if (value === 'ember') {
		delete root.dataset.variant;
	} else {
		root.dataset.variant = value;
	}

	store.set(value);

	try {
		localStorage.setItem(THEME_STORAGE_KEY, value);
	} catch {
		// Storage denied (private mode, policy): the theme still applies for this session.
	}
}
