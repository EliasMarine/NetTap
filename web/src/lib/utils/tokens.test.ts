import { describe, it, expect, afterEach, vi } from 'vitest';
import { resolveToken, prefersReducedMotion } from './tokens';

describe('resolveToken', () => {
	afterEach(() => {
		document.head.querySelectorAll('style[data-test-tokens]').forEach((el) => el.remove());
		delete document.documentElement.dataset.variant;
		vi.unstubAllGlobals();
	});

	function addStyle(css: string) {
		const style = document.createElement('style');
		style.dataset.testTokens = '';
		style.textContent = css;
		document.head.appendChild(style);
	}

	it('reads a token from the root', () => {
		addStyle(':root { --accent: #ff7a1a; }');
		expect(resolveToken('--accent')).toBe('#ff7a1a');
	});

	it('follows the variant attribute', () => {
		addStyle(':root { --accent: #ff7a1a; } :root[data-variant="spectrum"] { --accent: #9b8cff; }');
		document.documentElement.dataset.variant = 'spectrum';
		expect(resolveToken('--accent')).toBe('#9b8cff');
	});

	it('returns an empty string for an unknown token', () => {
		expect(resolveToken('--not-a-token')).toBe('');
	});

	it('reports reduced motion from the media query', () => {
		vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce') }));
		expect(prefersReducedMotion()).toBe(true);
		vi.stubGlobal('matchMedia', () => ({ matches: false }));
		expect(prefersReducedMotion()).toBe(false);
	});
});
