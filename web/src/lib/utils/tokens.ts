/**
 * Read a design token's current value, for code that can't use var() (canvas).
 * Re-read after the theme changes: the value follows <html data-theme>.
 * Returns '' when the token isn't defined.
 */
export function resolveToken(name: string, el: Element = document.documentElement): string {
	return getComputedStyle(el).getPropertyValue(name).trim();
}

export function prefersReducedMotion(): boolean {
	return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}
