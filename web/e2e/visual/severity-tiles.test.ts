import { describe, it, expect, afterEach } from 'vitest';
import { findTileSpills } from './severity-tiles.ts';

/** A tile at `left`..`right` on row `top`, whose count ends at `countRight`. */
function tile(label: string, left: number, right: number, countRight: number, top = 0): void {
	const el = document.createElement('div');
	el.className = 'sev-count';
	const name = document.createElement('span');
	name.textContent = label;
	const count = document.createElement('b');
	count.textContent = '1';
	el.append(name, count);
	el.getBoundingClientRect = () => ({ left, right, top }) as DOMRect;
	el.querySelector('b')!.getBoundingClientRect = () => ({ right: countRight }) as DOMRect;
	document.body.append(el);
}

afterEach(() => document.body.replaceChildren());

describe('findTileSpills', () => {
	it('passes tiles whose counts fit and that sit side by side', () => {
		tile('High', 0, 100, 90);
		tile('Low', 108, 208, 200);
		expect(findTileSpills()).toEqual([]);
	});

	it('names a count that spills out of its tile', () => {
		tile('Low', 0, 100, 130);
		expect(findTileSpills()).toEqual(['Low1: the count spills out of its tile']);
	});

	it('names a tile that runs into the next one on the same row, not one on the next row', () => {
		tile('Medium', 0, 120, 110);
		tile('Low', 100, 200, 190);
		tile('Info', 0, 100, 50, 80);
		expect(findTileSpills()).toEqual(['Medium1: the tile overlaps the next one']);
	});
});
