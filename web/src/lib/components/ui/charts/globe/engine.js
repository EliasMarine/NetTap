// @ts-nocheck -- three ships no types; this canvas engine has one caller (Globe.svelte)
// The Live monitor globe: WebGPU through three.js (WebGL 2 when WebGPU is missing), TSL materials.
import * as THREE from 'three/webgpu';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { DEG, toVec3, toLatLon, arcEnds, arcPoint } from './geo.js';
import { readTheme } from './tokens.js';
import { createUniforms, globeMaterial, atmosphereMaterial, arcMaterial, markerMaterial, packetMaterials, homeMaterial } from './materials.js';

const MAX_PACKETS = 4096;
const MAX_MARKERS = 160;
const ARC_COUNT = 14;
const IDLE_MS = 6000;
/** The Live page's poll: a poll's new packets launch spread over it. */
const TICK_MS = 3000;
// City-states sit inside a neighbour's outline at this scale, so they never claim one
const NO_OUTLINE = new Set(['HK', 'SG', 'MO']);

class ArcCurve extends THREE.Curve {
	constructor(ends) {
		super();
		this.ends = ends;
	}
	getPoint(t, out = new THREE.Vector3()) {
		return arcPoint(this.ends, t, out);
	}
}

function packetsFor(bytes) {
	return Math.max(1, Math.min(5, Math.round(Math.log10(Math.max(bytes, 1)) - 2.2)));
}

export function mountGlobe(canvas, opts) {
	const state = {
		home: opts.home ?? null, paused: !!opts.paused, reduced: !!opts.reduced, expanded: !!opts.expanded,
		selected: null, hover: null, visible: true, ready: false, destroyed: false, needsRender: true,
	};
	const cleanups = [];
	const on = (target, type, fn, o) => {
		target.addEventListener(type, fn, o);
		cleanups.push(() => target.removeEventListener(type, fn, o));
	};
	const rnd = Math.random;
	const U = createUniforms();
	const mask = opts.mask; // loadLandMask(), resolved by the caller

	const renderer = new THREE.WebGPURenderer({ canvas, antialias: true, alpha: true });
	renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // token colours pass through as CSS paints them
	renderer.setClearAlpha(0);
	renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

	const scene = new THREE.Scene();
	const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 60);
	const controls = new OrbitControls(camera, canvas);
	Object.assign(controls, { enableDamping: true, dampingFactor: 0.08, enablePan: false, rotateSpeed: 0.5, zoomSpeed: 0.7, minPolarAngle: 0.3, maxPolarAngle: Math.PI - 0.3 });

	const maskTex = new THREE.DataTexture(mask.tex, mask.W, mask.H, THREE.RGBAFormat);
	maskTex.magFilter = THREE.NearestFilter;
	maskTex.minFilter = THREE.NearestFilter;
	maskTex.generateMipmaps = false;
	maskTex.needsUpdate = true;

	const globe = new THREE.Mesh(new THREE.SphereGeometry(1, 128, 96), globeMaterial(U, maskTex));
	const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), atmosphereMaterial(U));
	atmosphere.scale.setScalar(1.12);
	const arcMat = arcMaterial(U);
	let arcMesh = null;

	const markerPos = new THREE.InstancedBufferAttribute(new Float32Array(MAX_MARKERS * 4), 4).setUsage(THREE.DynamicDrawUsage);
	const markerState = new THREE.InstancedBufferAttribute(new Float32Array(MAX_MARKERS * 4), 4).setUsage(THREE.DynamicDrawUsage);
	const markers = new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2), markerMaterial(U, markerPos, markerState), MAX_MARKERS);
	markers.count = 0;

	const pA = new THREE.InstancedBufferAttribute(new Float32Array(MAX_PACKETS * 4), 4).setUsage(THREE.DynamicDrawUsage);
	const pB = new THREE.InstancedBufferAttribute(new Float32Array(MAX_PACKETS * 4), 4).setUsage(THREE.DynamicDrawUsage);
	const pC = new THREE.InstancedBufferAttribute(new Float32Array(MAX_PACKETS * 4), 4).setUsage(THREE.DynamicDrawUsage);
	for (let i = 0; i < MAX_PACKETS; i++) {
		pA.array[i * 4 + 3] = -1e9;
		pB.array[i * 4 + 3] = 1;
	}
	const pm = packetMaterials(U, pA, pB, pC);
	const quad = new THREE.PlaneGeometry(1, 1);
	const trails = new THREE.InstancedMesh(quad, pm.trail, MAX_PACKETS);
	const heads = new THREE.InstancedMesh(quad, pm.head, MAX_PACKETS);
	const rings = new THREE.InstancedMesh(new THREE.PlaneGeometry(2, 2), pm.ring, MAX_PACKETS);
	const homeMesh = new THREE.Mesh(new THREE.PlaneGeometry(0.1, 0.1), homeMaterial(U));

	[globe, atmosphere, markers, rings, trails, heads, homeMesh].forEach((o, i) => {
		o.renderOrder = i === 0 ? 0 : i + 2;
		o.frustumCulled = false;
		scene.add(o);
	});

	// ---------- data ----------
	let destinations = [];
	let markerList = [];
	let countries = new Map(); // code → { code, country, count, bytes, cities: [] }
	const codeToId = new Map();
	const idToCode = new Map();
	let arcKey = '';
	let nextSlot = 0;
	let homeVec = null;

	function idNear(lat, lon) {
		for (let r = 0; r <= 3; r++) {
			for (let dy = -r; dy <= r; dy++) {
				for (let dx = -r; dx <= r; dx++) {
					const id = mask.idAt(lat + dy * 0.35, lon + dx * 0.35);
					if (id) return id;
				}
			}
		}
		return 0;
	}

	function setHome(home) {
		state.home = home;
		homeVec = home ? toVec3(home.lat, home.lon) : null;
		homeMesh.visible = !!homeVec;
		if (homeVec) {
			homeMesh.position.copy(homeVec).multiplyScalar(1.004);
			homeMesh.lookAt(homeVec.clone().multiplyScalar(2));
		}
		arcKey = '';
		buildArcs();
		state.needsRender = true;
	}

	function buildArcs() {
		const top = homeVec ? [...destinations].sort((a, b) => b.count - a.count).slice(0, ARC_COUNT) : [];
		const key = top.map((d) => d.key).join('|') + (homeVec ? homeVec.toArray().join() : '');
		if (key === arcKey) return applyArcState();
		arcKey = key;
		if (arcMesh) {
			scene.remove(arcMesh);
			arcMesh.geometry.dispose();
			arcMesh = null;
		}
		const max = Math.max(1, ...top.map((d) => d.count));
		const parts = [];
		for (const d of top) {
			const ends = arcEnds(homeVec, d.vec);
			if (!ends) continue;
			const g = new THREE.TubeGeometry(new ArcCurve(ends), 80, 0.0016 + 0.0026 * (d.count / max), 5, false);
			parts.push({ g, d, dashes: 3 + 18 * (ends.theta / Math.PI), phase: rnd() });
		}
		if (!parts.length) return;
		const total = parts.reduce((s, p) => s + p.g.attributes.position.count, 0);
		const pos = new Float32Array(total * 3);
		const uvs = new Float32Array(total * 2);
		const arc = new Float32Array(total * 4);
		const index = [];
		let base = 0;
		for (const p of parts) {
			const n = p.g.attributes.position.count;
			pos.set(p.g.attributes.position.array, base * 3);
			uvs.set(p.g.attributes.uv.array, base * 2);
			for (let i = 0; i < n; i++) arc.set([p.dashes, p.phase, 1, 0], (base + i) * 4);
			for (const ix of p.g.index.array) index.push(ix + base);
			p.start = base;
			p.count = n;
			base += n;
			p.g.dispose();
		}
		const geo = new THREE.BufferGeometry();
		geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
		geo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
		geo.setAttribute('aArc', new THREE.BufferAttribute(arc, 4));
		geo.setIndex(index);
		arcMesh = new THREE.Mesh(geo, arcMat);
		arcMesh.renderOrder = 1;
		arcMesh.frustumCulled = false;
		arcMesh.userData.parts = parts.map(({ d, start, count }) => ({ code: d.code, start, count }));
		scene.add(arcMesh);
		applyArcState();
	}

	function applyArcState() {
		if (!arcMesh) return;
		const attr = arcMesh.geometry.attributes.aArc;
		for (const p of arcMesh.userData.parts) {
			const level = !state.selected ? 1 : p.code === state.selected ? 1.7 : 0.3;
			for (let i = 0; i < p.count; i++) attr.array[(p.start + i) * 4 + 2] = level;
		}
		attr.needsUpdate = true;
	}

	function applyMarkerState() {
		const hoverCode = state.hover?.code ?? null;
		const hoverKey = state.hover?.kind === 'city' ? state.hover.key : null;
		markerList.forEach((m, i) => {
			const selected = state.selected === m.code;
			const level = state.selected && !selected ? 0.4 : 1;
			const hovered = m.key === hoverKey || (state.hover?.kind !== 'city' && m.code === hoverCode);
			markerState.array.set([selected ? 2 : hovered ? 1 : 0, level, 0, 0], i * 4);
		});
		markerState.needsUpdate = true;
		U.selectedId.value = codeToId.get(state.selected) ?? 0;
		U.hoverId.value = hoverCode && hoverCode !== state.selected ? codeToId.get(hoverCode) ?? 0 : 0;
		state.needsRender = true;
	}

	function setDestinations(list) {
		destinations = list
			.filter((d) => d.lat != null && d.lon != null)
			.slice(0, MAX_MARKERS)
			.map((d) => ({ ...d, key: d.country_code + '/' + d.city, code: d.country_code, vec: toVec3(d.lat, d.lon) }));
		const max = Math.max(1, ...destinations.map((d) => d.count));
		markerList = destinations.map((d) => ({ ...d, radius: 0.011 + 0.016 * Math.sqrt(d.count / max) }));
		markerList.forEach((m, i) => markerPos.array.set([m.vec.x, m.vec.y, m.vec.z, m.radius], i * 4));
		markers.count = markerList.length;
		markerPos.needsUpdate = true;
		countries = new Map();
		for (const d of destinations) {
			const c = countries.get(d.code) ?? { code: d.code, country: d.country, count: 0, bytes: 0, cities: [] };
			c.count += d.count;
			c.bytes += d.bytes;
			c.cities.push(d);
			countries.set(d.code, c);
			if (!codeToId.has(d.code) && !NO_OUTLINE.has(d.code)) {
				const id = idNear(d.lat, d.lon);
				if (id && !idToCode.has(id)) {
					codeToId.set(d.code, id);
					idToCode.set(id, d.code);
				}
			}
		}
		buildArcs();
		applyMarkerState();
	}

	function spawn(conns, { prime = false } = {}) {
		if (!homeVec || state.reduced) return;
		const now = U.time.value;
		const far = new THREE.Vector3();
		let wrote = false;
		for (const c of conns) {
			if (c.dest_lat == null || (c.direction !== 'out' && c.direction !== 'in')) continue;
			toVec3(c.dest_lat, c.dest_lon, far);
			const out = c.direction === 'out';
			const ends = out ? arcEnds(homeVec, far) : arcEnds(far, homeVec);
			if (!ends) continue;
			const kind = c.has_alert ? 2 : out ? 0 : 1;
			const size = 0.75 + 0.25 * Math.min(1, Math.log10(Math.max(c.bytes, 1)) / 8);
			const n = c.has_alert ? 1 : packetsFor(c.bytes);
			for (let k = 0; k < n; k++) {
				const slot = nextSlot;
				nextSlot = (nextSlot + 1) % MAX_PACKETS;
				const launch = now + (prime ? -1.5 : 0) + rnd() * (TICK_MS / 1000);
				const duration = (1.5 + 2.4 * (ends.theta / Math.PI)) * (0.85 + 0.3 * rnd());
				pA.array.set([ends.A.x, ends.A.y, ends.A.z, launch], slot * 4);
				pB.array.set([ends.B.x, ends.B.y, ends.B.z, duration], slot * 4);
				pC.array.set([ends.h, kind, size, rnd()], slot * 4);
				wrote = true;
			}
		}
		if (wrote) {
			pA.needsUpdate = true;
			pB.needsUpdate = true;
			pC.needsUpdate = true;
		}
	}

	// ---------- camera ----------
	let baseDistance = 5;
	let tween = null;
	let lastInteraction = -1e9;
	let interacting = false;
	let idleClock = 0;

	function fitDistance() {
		const vHalf = (camera.fov / 2) * DEG;
		const hHalf = Math.atan(Math.tan(vHalf) * camera.aspect);
		return 1.32 / Math.sin(Math.min(vHalf, hHalf));
	}

	function startView() {
		const anchor = homeVec ? homeVec.clone() : toVec3(30, 0);
		const { lat, lon } = toLatLon(anchor);
		const dir = toVec3(Math.max(-35, Math.min(42, lat - 8)), lon - 22);
		camera.position.copy(dir).multiplyScalar(baseDistance);
		camera.lookAt(0, 0, 0);
	}

	function flyTo(code) {
		const c = countries.get(code);
		if (!c) return;
		const v = new THREE.Vector3();
		c.cities.forEach((d) => v.addScaledVector(d.vec, d.count));
		const { lat, lon } = toLatLon(v);
		const to = toVec3(Math.max(-55, Math.min(55, lat)), lon);
		const from = camera.position.clone().normalize();
		tween = { from, q: new THREE.Quaternion().setFromUnitVectors(from, to), t: 0, dist: camera.position.length(), dur: state.reduced ? 0.0001 : 0.9 };
		lastInteraction = performance.now();
		state.needsRender = true;
	}

	function resize() {
		const w = Math.max(1, canvas.clientWidth);
		const h = Math.max(1, canvas.clientHeight);
		const ratio = camera.position.length() / baseDistance || 1;
		renderer.setSize(w, h, false);
		camera.aspect = w / h;
		camera.updateProjectionMatrix();
		baseDistance = fitDistance();
		controls.minDistance = baseDistance * 0.42;
		controls.maxDistance = baseDistance * 1.25;
		if (state.ready) camera.position.setLength(Math.min(controls.maxDistance, Math.max(controls.minDistance, baseDistance * ratio)));
		state.needsRender = true;
	}

	function applyInputMode() {
		const coarse = window.matchMedia('(pointer: coarse)').matches;
		// In the page a touch drag must still scroll it; the expanded view takes every gesture
		controls.enableRotate = state.expanded || !coarse;
		canvas.style.touchAction = state.expanded || !coarse ? 'none' : 'pan-y';
	}

	controls.addEventListener('start', () => {
		interacting = true;
		tween = null;
		lastInteraction = performance.now();
	});
	controls.addEventListener('end', () => {
		interacting = false;
		lastInteraction = performance.now();
	});
	controls.addEventListener('change', () => {
		state.needsRender = true;
	});
	// Plain scrolling keeps scrolling the page; zoom needs ⌘/Ctrl (or a trackpad pinch) until expanded
	on(canvas, 'wheel', (e) => {
		controls.enableZoom = state.expanded || e.ctrlKey || e.metaKey;
	}, { capture: true, passive: true });

	// ---------- pointer ----------
	const pointer = { x: 0, y: 0, inside: false, dirty: false, downX: 0, downY: 0, downT: 0 };
	const raycaster = new THREE.Raycaster();
	const sphere = new THREE.Sphere(new THREE.Vector3(), 1);
	const ndc = new THREE.Vector2();
	const tmp = new THREE.Vector3();

	on(canvas, 'pointermove', (e) => {
		const r = canvas.getBoundingClientRect();
		pointer.x = e.clientX - r.left;
		pointer.y = e.clientY - r.top;
		pointer.inside = true;
		pointer.dirty = true;
		if (opts.tooltipEl) opts.tooltipEl.style.transform = `translate(${pointer.x}px, ${pointer.y}px)`;
	});
	on(canvas, 'pointerleave', () => {
		pointer.inside = false;
		setHover(null);
	});
	on(canvas, 'pointerdown', (e) => {
		pointer.downX = e.clientX;
		pointer.downY = e.clientY;
		pointer.downT = performance.now();
	});
	on(canvas, 'pointerup', (e) => {
		const moved = Math.hypot(e.clientX - pointer.downX, e.clientY - pointer.downY);
		if (moved < 6 && performance.now() - pointer.downT < 500 && state.hover && state.hover.kind !== 'list') opts.onSelect?.(state.hover.code);
	});

	function hitTest() {
		const w = canvas.clientWidth;
		const h = canvas.clientHeight;
		const camDir = camera.position.clone().normalize();
		const pxPerUnit = h / (2 * Math.tan((camera.fov / 2) * DEG) * camera.position.length());
		let best = null;
		let bestD = 10;
		for (const m of markerList) {
			if (m.vec.dot(camDir) < 0.15) continue;
			tmp.copy(m.vec).multiplyScalar(1.003).project(camera);
			const d = Math.hypot((tmp.x * 0.5 + 0.5) * w - pointer.x, (-tmp.y * 0.5 + 0.5) * h - pointer.y) - m.radius * pxPerUnit;
			if (d < bestD) {
				bestD = d;
				best = m;
			}
		}
		if (best) return { kind: 'city', key: best.key, code: best.code, city: best.city, country: best.country, count: best.count, bytes: best.bytes };
		ndc.set((pointer.x / w) * 2 - 1, -(pointer.y / h) * 2 + 1);
		raycaster.setFromCamera(ndc, camera);
		if (!raycaster.ray.intersectSphere(sphere, tmp)) return null;
		const { lat, lon } = toLatLon(tmp);
		const code = idToCode.get(mask.idAt(lat, lon));
		const c = code && countries.get(code);
		return c ? { kind: 'country', key: 'country/' + code, code, city: '', country: c.country, count: c.count, bytes: c.bytes } : null;
	}

	function setHover(info, notify = true) {
		if ((info?.key ?? null) === (state.hover?.key ?? null)) return;
		state.hover = info;
		canvas.style.cursor = info?.kind === 'city' || info?.kind === 'country' ? 'pointer' : '';
		applyMarkerState();
		if (notify) opts.onHover?.(info);
	}

	// ---------- frame ----------
	let last = performance.now();
	let themeCheck = 0;
	let themeSig = '';

	function applyTheme(force = false) {
		const { colours: k, signature } = readTheme(opts.themeFrom ?? canvas);
		if (!force && signature === themeSig) return;
		themeSig = signature;
		const set = (u, c) => u.value.setRGB(c.r, c.g, c.b);
		set(U.ocean, k['surface-2']);
		set(U.oceanEdge, k['card-bottom']);
		set(U.dot, k['map-dot']);
		U.dotAlpha.value = k['map-dot'].a;
		set(U.accent, k.accent);
		set(U.accentStrong, k['accent-strong']);
		set(U.inbound, k['data-2']);
		set(U.critical, k['sev-critical']);
		set(U.text1, k['text-1']);
		set(U.line, k.line);
		set(U.glow, k['hero-glow']);
		U.glowAlpha.value = k['hero-glow'].a;
		state.needsRender = true;
	}

	function positionLabel() {
		const el = opts.homeLabelEl;
		if (!el) return;
		if (!homeVec) {
			el.style.opacity = '0';
			return;
		}
		const facing = homeVec.dot(camera.position.clone().normalize());
		tmp.copy(homeVec).multiplyScalar(1.004).project(camera);
		const x = (tmp.x * 0.5 + 0.5) * canvas.clientWidth;
		const y = (-tmp.y * 0.5 + 0.5) * canvas.clientHeight;
		el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
		el.style.opacity = facing > 0.1 ? '1' : '0';
	}

	function frame() {
		const t = performance.now();
		const dt = Math.min(0.1, (t - last) / 1000);
		last = t;
		const moving = !state.paused && !state.reduced;
		if (moving) U.time.value += dt;
		if (t - themeCheck > 500) {
			themeCheck = t;
			applyTheme();
		}
		if (tween) {
			tween.t = Math.min(1, tween.t + dt / tween.dur);
			const k = tween.t < 0.5 ? 2 * tween.t * tween.t : 1 - Math.pow(-2 * tween.t + 2, 2) / 2;
			const q = new THREE.Quaternion().slerp(tween.q, k);
			camera.position.copy(tween.from).applyQuaternion(q).multiplyScalar(tween.dist);
			if (tween.t >= 1) tween = null;
			lastInteraction = t;
			state.needsRender = true;
		}
		const idle = !interacting && !tween && !state.reduced && !state.paused && t - lastInteraction > IDLE_MS;
		controls.autoRotate = idle;
		if (idle) {
			idleClock += dt;
			controls.autoRotateSpeed = 0.32 * Math.cos(idleClock * 0.13); // sways about ±35° so home stays in view
		}
		if (controls.update(dt)) state.needsRender = true;
		if (pointer.dirty && pointer.inside) {
			pointer.dirty = false;
			setHover(hitTest());
		}
		if (moving || state.needsRender) {
			positionLabel();
			renderer.render(scene, camera);
			state.needsRender = false;
		}
	}

	function syncLoop() {
		// three's setAnimationLoop starts init() itself; before init succeeded that would be a second,
		// unhandled rejection on a browser with no WebGPU or WebGL 2
		if (!state.ready) return;
		const run = state.visible && !document.hidden && !state.destroyed;
		renderer.setAnimationLoop(run ? frame : null);
		if (run) last = performance.now();
	}

	const io = new IntersectionObserver((entries) => {
		state.visible = entries.some((e) => e.isIntersecting);
		syncLoop();
	});
	io.observe(canvas);
	const ro = new ResizeObserver(() => resize());
	ro.observe(canvas);
	on(document, 'visibilitychange', syncLoop);

	let pending = null;
	/** renderer.init() succeeded: only then is there a backend for dispose() to release. */
	let started = false;

	(async () => {
		try {
			await renderer.init();
			started = true;
			if (state.destroyed) {
				// destroyed while starting: destroy() had nothing to release yet, so release it now
				renderer.dispose().catch((err) => console.warn('NetTap globe: renderer cleanup failed.', err));
				return;
			}
			applyTheme(true);
			setHome(state.home);
			resize();
			startView();
			applyInputMode();
			if (pending) {
				setDestinations(pending.geo_arcs);
				spawn(pending.fresh ?? [], { prime: true });
				pending = null;
			}
			await renderer.compileAsync(scene, camera);
			if (state.destroyed) return;
			state.ready = true;
			opts.onStatus?.({ ready: true, backend: renderer.backend.isWebGPUBackend ? 'WebGPU' : 'WebGL 2' });
			syncLoop();
		} catch (err) {
			console.warn('NetTap globe: the renderer could not start, showing the flat map instead.', err);
			opts.onStatus?.({ ready: false, failed: true, error: String(err?.message ?? err) });
		}
	})();

	return {
		ingest(snapshot, { prime = false } = {}) {
			if (!snapshot) return;
			if (!state.ready) {
				pending = snapshot;
				return;
			}
			setDestinations(snapshot.geo_arcs);
			spawn(snapshot.fresh ?? [], { prime });
		},
		setSelected(code, { fly = false } = {}) {
			state.selected = code || null;
			applyArcState();
			applyMarkerState();
			if (fly && code && state.ready) flyTo(code);
		},
		setHome(home) {
			if (state.ready) setHome(home);
			else state.home = home;
		},
		/** Light a country from outside the canvas (the destinations list), with no tooltip. */
		highlight(code) {
			if (state.ready) setHover(code ? { kind: 'list', key: 'list/' + code, code } : null, false);
		},
		setPaused(value) {
			state.paused = !!value;
			state.needsRender = true;
		},
		setReduced(value) {
			state.reduced = !!value;
			U.motion.value = state.reduced ? 0 : 1;
			state.needsRender = true;
		},
		setExpanded(value) {
			state.expanded = !!value;
			applyInputMode();
			resize();
		},
		destroy() {
			if (state.destroyed) return;
			const wasReady = state.ready;
			state.destroyed = true;
			state.ready = false;
			if (wasReady) renderer.setAnimationLoop(null);
			io.disconnect();
			ro.disconnect();
			cleanups.forEach((fn) => fn());
			controls.dispose();
			scene.traverse((o) => {
				o.geometry?.dispose();
				o.material?.dispose();
			});
			maskTex.dispose();
			// dispose() is async and re-enters init() through setAnimationLoop(null): on a renderer
			// that never started, that is an unhandled rejection, and there is nothing to release
			if (started) renderer.dispose().catch((err) => console.warn('NetTap globe: renderer cleanup failed.', err));
		},
	};
}
