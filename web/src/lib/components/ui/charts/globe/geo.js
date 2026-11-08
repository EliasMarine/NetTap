// @ts-nocheck -- three ships no types; this canvas engine has one caller (Globe.svelte)
// Sphere maths shared by the 3D globe and the flat fallback. Unit sphere, y is north.
import { Vector3 } from 'three/webgpu';

export const DEG = Math.PI / 180;

export function toVec3(lat, lon, out = new Vector3()) {
	const p = lat * DEG;
	const l = lon * DEG;
	return out.set(Math.cos(p) * Math.sin(l), Math.sin(p), Math.cos(p) * Math.cos(l));
}

export function toLatLon(v) {
	const n = v.clone().normalize();
	return { lat: Math.asin(Math.max(-1, Math.min(1, n.y))) / DEG, lon: Math.atan2(n.x, n.z) / DEG };
}

const AXIS = new Vector3(0, 1, 0);

/**
 * The two ends of an arc, ready for slerp. A pair less than 0.3° apart has no arc (same city).
 * A near-antipodal pair is nudged so its great circle is defined.
 */
export function arcEnds(from, to) {
	const A = from.clone().normalize();
	const B = to.clone().normalize();
	let cos = A.dot(B);
	if (cos > Math.cos(0.3 * DEG)) return null;
	if (cos < -0.995) {
		const side = new Vector3().crossVectors(A, AXIS);
		if (side.lengthSq() < 1e-6) side.set(1, 0, 0);
		B.addScaledVector(side.normalize(), 0.08).normalize();
		cos = A.dot(B);
	}
	const theta = Math.acos(cos);
	// Long-haul arcs rise higher, so they read as distance
	return { A, B, theta, h: 0.05 + 0.3 * (theta / Math.PI) };
}

/** Point t (0..1) along the arc: slerp between the ends, lifted by h at the middle. */
export function arcPoint(ends, t, out = new Vector3()) {
	const { A, B, theta, h } = ends;
	const s = Math.sin(theta);
	const a = Math.sin((1 - t) * theta) / s;
	const b = Math.sin(t * theta) / s;
	out.set(A.x * a + B.x * b, A.y * a + B.y * b, A.z * a + B.z * b);
	return out.multiplyScalar(1 + h * Math.sin(Math.PI * t));
}
