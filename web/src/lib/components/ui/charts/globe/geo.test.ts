import { describe, it, expect } from 'vitest';
import { toVec3, toLatLon, arcEnds, arcPoint } from './geo.js';
import { unwrapRing } from '../geometry';

describe('globe maths', () => {
	it('places latitude and longitude on the unit sphere, y up, and back', () => {
		const north = toVec3(90, 0);
		expect(north.y).toBeCloseTo(1);
		const lonLat = toLatLon(toVec3(51.5, -0.13));
		expect(lonLat.lat).toBeCloseTo(51.5);
		expect(lonLat.lon).toBeCloseTo(-0.13);
	});

	it('has no arc between two points in the same city', () => {
		expect(arcEnds(toVec3(51.5, -0.13), toVec3(51.51, -0.12))).toBeNull();
	});

	it('runs an arc from end to end, higher for longer hauls', () => {
		const london = toVec3(51.5, -0.13);
		const tokyo = toVec3(35.68, 139.69);
		const paris = toVec3(48.86, 2.35);
		const far = arcEnds(london, tokyo)!;
		const near = arcEnds(london, paris)!;
		expect(far.h).toBeGreaterThan(near.h);
		expect(arcPoint(far, 0).distanceTo(london)).toBeLessThan(1e-6);
		expect(arcPoint(far, 1).distanceTo(tokyo)).toBeLessThan(1e-6);
		// lifted above the surface in the middle
		expect(arcPoint(far, 0.5).length()).toBeCloseTo(1 + far.h);
	});

	it('still draws an arc between antipodes', () => {
		const ends = arcEnds(toVec3(0, 0), toVec3(0, 180));
		expect(ends).not.toBeNull();
		expect(Number.isFinite(ends!.theta)).toBe(true);
		expect(arcPoint(ends!, 0.5).toArray().every(Number.isFinite)).toBe(true);
	});
});

describe('land outlines across the date line', () => {
	it('moves a ring that crosses 180° onto 0..360, so it fills no band across the map', () => {
		const fiji = [[-180, -16.07], [-179.79, -16.02], [179.36, -16.8], [180, -16.07], [-180, -16.07]];
		const ring = unwrapRing(fiji as [number, number][]);
		expect(ring).not.toBe(fiji);
		expect(Math.max(...ring.map((p) => p[0])) - Math.min(...ring.map((p) => p[0]))).toBeLessThan(2);
	});

	// land.js draws the copy past 180° only for a ring that came back as a new array
	it('returns an ordinary ring itself', () => {
		const square: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]];
		expect(unwrapRing(square)).toBe(square);
	});
});
