import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// The live map draws bundled country outlines: no tile server, no API key, no cloud
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('GeoMap base map', () => {
	it('ships a valid world outline', () => {
		const outlines = JSON.parse(read('static/geo/countries-110m.geojson'));
		expect(outlines.type).toBe('FeatureCollection');
		expect(outlines.features.length).toBeGreaterThan(150);
		for (const f of outlines.features) {
			expect(['Polygon', 'MultiPolygon']).toContain(f.geometry.type);
		}
	});

	it('loads the bundled outline instead of remote tiles', () => {
		const code = read('src/lib/components/live/GeoMap.svelte')
			.split('\n')
			.filter((line) => !line.trim().startsWith('//'))
			.join('\n');
		expect(code).toContain('/geo/countries-110m.geojson');
		expect(code).not.toMatch(/L\.tileLayer\(/);
		expect(code).not.toContain('cartocdn');
	});
});
