// @ts-nocheck -- three ships no types; this canvas engine has one caller (Globe.svelte)
// TSL node materials for the globe. Every colour arrives as a uniform read from the theme tokens.
import * as THREE from 'three/webgpu';
import {
	Fn, uniform, texture, vec2, vec3, vec4, float, positionLocal, positionGeometry, positionView, normalView, uv,
	mix, smoothstep, step, fract, floor, max, min, clamp, abs, length, normalize, dot, cross, sin, cos, asin, atan,
	acos, fwidth, select, PI, TWO_PI, attribute, modelViewMatrix, cameraProjectionMatrix, varying, pow, oneMinus,
	instancedDynamicBufferAttribute,
} from 'three/tsl';
import { DEG } from './geo.js';

export function createUniforms() {
	const colour = () => uniform(new THREE.Color());
	return {
		time: uniform(0), // simulation seconds: stops when paused or under reduced motion
		ocean: colour(), oceanEdge: colour(), dot: colour(), dotAlpha: uniform(0.22),
		accent: colour(), accentStrong: colour(), inbound: colour(), critical: colour(),
		text1: colour(), line: colour(), glow: colour(), glowAlpha: uniform(0.15),
		selectedId: uniform(0), hoverId: uniform(0),
		step: uniform(1.15 * DEG), trail: uniform(0.2), width: uniform(0.015), headSize: uniform(0.013),
		ringDur: uniform(1.1), motion: uniform(1), // motion 0 = reduced motion: no pulses
	};
}

const OFFSCREEN = vec4(0.0, 0.0, 2.0, 1.0); // outside the clip volume: a dead instance draws nothing

/** Ocean, dot-grid land, graticule, highlighted countries and the limb glow, all on one sphere. */
export function globeMaterial(U, maskTex) {
	const m = new THREE.MeshBasicNodeMaterial();
	m.colorNode = Fn(() => {
		const n = normalize(positionLocal);
		const lat = asin(n.y);
		const lon = atan(n.x, n.z);
		const halfPi = PI.mul(0.5);
		// Rows of constant latitude, each with as many dots as fit, so spacing is even on the sphere
		const row = floor(lat.add(halfPi).div(U.step));
		const latC = row.add(0.5).mul(U.step).sub(halfPi);
		const cols = max(floor(TWO_PI.mul(cos(latC)).div(U.step)), 1.0);
		const colW = TWO_PI.div(cols);
		const lonC = floor(lon.add(PI).div(colW)).add(0.5).mul(colW).sub(PI);
		const cell = texture(maskTex, vec2(lonC.add(PI).div(TWO_PI), latC.add(halfPi).div(PI)));
		const land = step(0.5, cell.r);
		const id = floor(cell.g.mul(255.0).add(0.5));
		const d = length(vec2(lon.sub(lonC).mul(cos(lat)), lat.sub(latC)));
		const r = U.step.mul(0.37);
		const aa = fwidth(d).add(0.00001);
		const dotMask = oneMinus(smoothstep(r.sub(aa), r.add(aa), d)).mul(land);
		const facing = clamp(normalView.z, 0.0, 1.0);
		const base = mix(U.oceanEdge, U.ocean, pow(facing, 0.7));
		// Graticule every 30 degrees, one pixel wide at any zoom
		const g = PI.div(6.0);
		const dLat = abs(fract(lat.div(g).add(0.5)).sub(0.5)).mul(g);
		const dLon = abs(fract(lon.div(g).add(0.5)).sub(0.5)).mul(g).mul(cos(lat));
		const gd = min(dLat, dLon);
		const grid = oneMinus(smoothstep(0.0, fwidth(gd).mul(1.2).add(0.00001), gd)).mul(0.4);
		const sel = step(0.5, U.selectedId).mul(step(abs(id.sub(U.selectedId)), 0.5));
		const hov = step(0.5, U.hoverId).mul(step(abs(id.sub(U.hoverId)), 0.5));
		const hi = max(sel, hov.mul(0.55));
		const dotColour = mix(U.dot, U.accent, hi);
		const dotAlpha = mix(U.dotAlpha, float(0.9), hi);
		const lit = mix(mix(base, U.line, grid), dotColour, dotMask.mul(dotAlpha));
		const rim = pow(oneMinus(facing), 3.5).mul(U.glowAlpha).mul(1.1);
		return mix(lit, U.glow, rim);
	})();
	return m;
}

/** A soft halo just outside the limb, from the impact distance of each view ray. */
export function atmosphereMaterial(U) {
	const m = new THREE.MeshBasicNodeMaterial({ side: THREE.BackSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
	m.colorNode = U.glow;
	m.opacityNode = Fn(() => {
		const c = modelViewMatrix.mul(vec4(0.0, 0.0, 0.0, 1.0)).xyz;
		const b = length(cross(c, normalize(positionView)));
		const t = clamp(b.sub(1.0).div(0.11), 0.0, 1.0);
		return pow(oneMinus(t), 2.6).mul(U.glowAlpha).mul(1.1);
	})();
	return m;
}

/** Busiest-destination arcs: a faint path with accent dashes flowing from home outwards. */
export function arcMaterial(U) {
	const m = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
	const a = attribute('aArc', 'vec4'); // x dashes, y phase, z brightness, w unused
	m.colorNode = U.accent;
	m.opacityNode = Fn(() => {
		const t = uv().x;
		const flow = fract(t.mul(a.x).sub(U.time.mul(0.55)).add(a.y));
		const dash = smoothstep(0.0, 0.1, flow).mul(oneMinus(smoothstep(0.38, 0.55, flow)));
		const ends = smoothstep(0.0, 0.035, t).mul(oneMinus(smoothstep(0.97, 1.0, t)));
		return dash.mul(0.6).add(0.14).mul(ends).mul(a.z);
	})();
	return m;
}

/** Hotspot dots at each destination, sized by connections; the selected one gets a ring. */
export function markerMaterial(U, posAttr, stateAttr) {
	const m = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
	const p = instancedDynamicBufferAttribute(posAttr); // xyz direction, w radius
	const s = instancedDynamicBufferAttribute(stateAttr); // x 0 rest, 1 hover, 2 selected; y brightness
	m.positionNode = Fn(() => {
		const n = normalize(p.xyz);
		const up = select(abs(n.y).greaterThan(0.99), vec3(1.0, 0.0, 0.0), vec3(0.0, 1.0, 0.0));
		const t1 = normalize(cross(up, n));
		const t2 = cross(n, t1);
		return n.mul(1.0025).add(t1.mul(positionGeometry.x).add(t2.mul(positionGeometry.y)).mul(p.w));
	})();
	const vState = varying(s);
	m.colorNode = select(vState.x.greaterThan(0.5), U.accentStrong, U.accent);
	m.opacityNode = Fn(() => {
		const r = length(uv().mul(2.0).sub(1.0));
		const core = oneMinus(smoothstep(0.3, 0.38, r));
		const ring = oneMinus(smoothstep(0.03, 0.09, abs(r.sub(0.74)))).mul(step(1.5, vState.x));
		const halo = pow(oneMinus(smoothstep(0.25, 1.0, r)), 2.0).mul(0.3);
		return max(core, max(ring, halo)).mul(vState.y);
	})();
	return m;
}

/**
 * Packets: one ring buffer of instances drives three meshes (trail, head, landing ring), all
 * positioned on the GPU, so the CPU cost does not grow with the number in flight.
 */
export function packetMaterials(U, aAttr, bAttr, cAttr) {
	const iA = instancedDynamicBufferAttribute(aAttr); // xyz start, w launch time
	const iB = instancedDynamicBufferAttribute(bAttr); // xyz end, w duration
	const iC = instancedDynamicBufferAttribute(cAttr); // x lift, y kind (0 out, 1 in, 2 alert), z size, w seed
	const arcPos = Fn(([A, B, h, t]) => {
		const th = acos(clamp(dot(A, B), -0.9999, 0.9999));
		const p = A.mul(sin(th.mul(oneMinus(t)))).add(B.mul(sin(th.mul(t)))).div(sin(th));
		return p.mul(h.mul(sin(t.mul(PI))).add(1.0));
	});
	const age = U.time.sub(iA.w).div(iB.w);
	const alive = step(0.0, age).mul(step(age, 1.0)).mul(U.motion);
	const kind = iC.y;
	const vAge = varying(age);
	const vKind = varying(kind);
	const kindColour = select(vKind.greaterThan(1.5), U.critical, select(vKind.greaterThan(0.5), U.inbound, U.accentStrong));
	const fade = smoothstep(0.0, 0.05, vAge).mul(oneMinus(smoothstep(0.93, 1.0, vAge)));
	const view = (t) => modelViewMatrix.mul(vec4(arcPos(iA.xyz, iB.xyz, iC.x, t), 1.0)).xyz;

	const trail = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide });
	trail.vertexNode = Fn(() => {
		const head = view(clamp(age, 0.0, 1.0));
		const tail = view(clamp(age.sub(U.trail), 0.0, 1.0));
		const along = positionGeometry.x.add(0.5);
		const d2 = head.xy.sub(tail.xy);
		const dir = d2.div(max(length(d2), 0.00001));
		const perp = vec2(dir.y.negate(), dir.x);
		const w = iC.z.mul(U.width).mul(mix(0.2, 1.0, along));
		const p = mix(tail, head, along).add(vec3(perp.mul(positionGeometry.y.mul(w)), 0.0));
		return select(alive.greaterThan(0.5), cameraProjectionMatrix.mul(vec4(p, 1.0)), OFFSCREEN);
	})();
	const vAlong = varying(positionGeometry.x.add(0.5));
	const vAcross = varying(positionGeometry.y.mul(2.0));
	trail.colorNode = kindColour;
	trail.opacityNode = oneMinus(smoothstep(0.2, 1.0, abs(vAcross))).mul(pow(vAlong, 1.6)).mul(fade).mul(0.85);

	const head = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
	head.vertexNode = Fn(() => {
		const centre = view(clamp(age, 0.0, 1.0));
		const size = iC.z.mul(U.headSize).mul(select(kind.greaterThan(1.5), 1.8, 1.0));
		const p = centre.add(vec3(positionGeometry.xy.mul(size.mul(2.0)), 0.0));
		return select(alive.greaterThan(0.5), cameraProjectionMatrix.mul(vec4(p, 1.0)), OFFSCREEN);
	})();
	// Alerts get the system's critical shape, a diamond; everything else a round head
	const q = uv().mul(2.0).sub(1.0);
	const shape = select(vKind.greaterThan(1.5), abs(q.x).add(abs(q.y)), length(q));
	const core = oneMinus(smoothstep(0.4, 0.58, shape));
	head.colorNode = mix(kindColour, U.text1, core.mul(0.5));
	head.opacityNode = max(core, pow(oneMinus(smoothstep(0.0, 1.0, shape)), 2.0).mul(0.45)).mul(fade);

	const ring = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
	const phase = U.time.sub(iA.w.add(iB.w)).div(U.ringDur);
	ring.positionNode = Fn(() => {
		const n = normalize(iB.xyz);
		const up = select(abs(n.y).greaterThan(0.99), vec3(1.0, 0.0, 0.0), vec3(0.0, 1.0, 0.0));
		const t1 = normalize(cross(up, n));
		const t2 = cross(n, t1);
		const live = step(0.0, phase).mul(step(phase, 1.0)).mul(U.motion);
		const size = select(kind.greaterThan(1.5), 0.085, 0.04).mul(iC.z);
		return n.mul(1.003).add(t1.mul(positionGeometry.x).add(t2.mul(positionGeometry.y)).mul(size)).mul(live);
	})();
	const vPhase = varying(phase);
	ring.colorNode = kindColour;
	ring.opacityNode = Fn(() => {
		const r = length(uv().mul(2.0).sub(1.0));
		const radius = mix(0.12, 0.92, pow(clamp(vPhase, 0.0, 1.0), 0.6));
		const band = oneMinus(smoothstep(0.0, 0.09, abs(r.sub(radius))));
		return band.mul(pow(oneMinus(clamp(vPhase, 0.0, 1.0)), 1.4)).mul(select(vKind.greaterThan(1.5), 1.0, 0.7));
	})();

	return { trail, head, ring };
}

/** "Your network": a text-1 ring and dot, with the live pulse every 2 s. */
export function homeMaterial(U) {
	const m = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false });
	m.colorNode = U.text1;
	m.opacityNode = Fn(() => {
		const r = length(uv().mul(2.0).sub(1.0));
		const core = oneMinus(smoothstep(0.17, 0.24, r));
		const ring = oneMinus(smoothstep(0.03, 0.08, abs(r.sub(0.46))));
		const p = fract(U.time.mul(0.5));
		const pulse = oneMinus(smoothstep(0.02, 0.07, abs(r.sub(mix(0.46, 0.98, p))))).mul(oneMinus(p)).mul(0.6).mul(U.motion);
		return max(core, max(ring, pulse));
	})();
	return m;
}
