// @ts-nocheck -- three ships no types; this canvas engine has one caller (Globe.svelte)
// The land mask, rasterised once from the countries file DotMap also draws
// (/geo/countries-110m.geojson, Natural Earth, public domain). Equirectangular, 1024×512.
import { unwrapRing } from '../geometry';

const GEO_URL = '/geo/countries-110m.geojson';
const W = 1024;
const H = 512;
let cached = null;

/** Each feature as a list of polygons, each a list of [lon, lat] rings. */
function featureRings(geojson) {
	const features = Array.isArray(geojson?.features) ? geojson.features : [];
	return features.map((f) => {
		const g = f?.geometry;
		if (!Array.isArray(g?.coordinates)) return [];
		if (g.type === 'Polygon') return [g.coordinates];
		if (g.type === 'MultiPolygon') return g.coordinates;
		return [];
	});
}

function rasterise(features) {
	const c = document.createElement('canvas'); // offscreen, never attached
	c.width = W;
	c.height = H;
	const ctx = c.getContext('2d', { willReadFrequently: true });
	const trace = (ring, shift) => {
		ring.forEach(([lon, lat], k) => {
			const x = ((lon + shift + 180) / 360) * W;
			const y = ((90 - lat) / 180) * H;
			if (k === 0) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
		});
		ctx.closePath();
	};
	features.forEach((polys, i) => {
		// An outline id (1..255) in the red channel, read back below; not a colour
		// colour-gate: allow-next-line the fill encodes an outline id, never painted on screen
		ctx.fillStyle = `rgb(${(i % 255) + 1}, 0, 0)`;
		ctx.beginPath();
		for (const poly of polys) {
			for (const raw of poly) {
				if (!Array.isArray(raw) || raw.length < 3) continue;
				const ring = unwrapRing(raw);
				trace(ring, 0);
				if (ring !== raw) trace(ring, -360); // unwrapped: the part past 180° shows at the left edge
			}
		}
		ctx.fill('evenodd');
	});
	// getImageData is un-premultiplied: R is the id even on anti-aliased edges, A is the coverage
	const img = ctx.getImageData(0, 0, W, H).data;
	const tex = new Uint8Array(W * H * 4);
	const ids = new Uint8Array(W * H);
	for (let y = 0; y < H; y++) {
		for (let x = 0; x < W; x++) {
			const s = (y * W + x) * 4;
			const a = img[s + 3];
			const id = a > 96 ? img[s] : 0;
			ids[y * W + x] = id;
			const d = ((H - 1 - y) * W + x) * 4;
			tex[d] = a;
			tex[d + 1] = id;
			tex[d + 3] = 255;
		}
	}
	const idAt = (lat, lon) => {
		const x = Math.min(W - 1, Math.max(0, Math.floor(((lon + 180) / 360) * W)));
		const y = Math.min(H - 1, Math.max(0, Math.floor(((90 - lat) / 180) * H)));
		return ids[y * W + x];
	};
	return { W, H, tex, idAt };
}

/** The mask, fetched and drawn once per page load; a failed fetch rejects (the caller falls back). */
export function loadLandMask() {
	cached ??= fetch(GEO_URL)
		.then((res) => {
			if (!res.ok) throw new Error(`Country outlines: HTTP ${res.status}`);
			return res.json();
		})
		.then((geo) => rasterise(featureRings(geo)))
		.catch((err) => {
			cached = null; // let a later mount try again
			throw err;
		});
	return cached;
}
