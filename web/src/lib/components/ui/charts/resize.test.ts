import { describe, it, expect, vi, afterEach } from 'vitest';
import { observeWidth } from './resize';

afterEach(() => vi.unstubAllGlobals());

describe('observeWidth', () => {
	it('reports once and does nothing else without ResizeObserver (jsdom)', () => {
		vi.stubGlobal('ResizeObserver', undefined);
		const seen: number[] = [];
		const cleanup = observeWidth((w) => seen.push(w))(document.createElement('div'));
		expect(seen).toEqual([0]);
		expect(cleanup).toBeUndefined();
	});

	it('reports every resize and disconnects on cleanup', () => {
		let fire: (width: number) => void = () => {};
		const disconnect = vi.fn();
		vi.stubGlobal(
			'ResizeObserver',
			class {
				constructor(cb: ResizeObserverCallback) {
					fire = (width) => cb([{ contentRect: { width } } as ResizeObserverEntry], this as never);
				}
				observe() {}
				disconnect = disconnect;
			},
		);
		const seen: number[] = [];
		const cleanup = observeWidth((w) => seen.push(w))(document.createElement('div'));
		fire(640);
		fire(390);
		expect(seen).toEqual([0, 640, 390]);
		(cleanup as () => void)();
		expect(disconnect).toHaveBeenCalledOnce();
	});
});
