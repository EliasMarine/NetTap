// NetTap hero scene. Packets stream in on the left, pass through a rotating scanner cube
// (each face sweeps a scan line up and down) and leave on the right in ordered lanes;
// a CPU die at its heart does the work; a copy of the traffic drops to the floor, where a hidden
// magnifying glass (hero-lens.js) reads sample records off the dots. WebGPURenderer falls back to WebGL 2 on its own;
// if both fail the CSS glow behind the canvas stays.
import * as THREE from 'three/webgpu';
import {
  Fn, uniform, vec3, color, hash, instanceIndex, positionLocal, positionWorld, uv,
  smoothstep, mix, fract, length, sin, cos, abs, step, oneMinus, floor, min, max, select,
  frontFacing, normalView, positionViewDirection, pass, varying, uniformArray, int
} from 'three/tsl';
import { bloom } from 'three/addons/tsl/display/BloomNode.js';
import { createLens } from './hero-lens.js';

const SPAN = 9;          // half-length of the packet stream
const LANES = 12;        // ordered lanes after the scanner
const CUBE = 2.1;        // scanner cube edge length
const CELLS = 8;         // tiles per face edge
const FLOOR_Y = -2.3;    // where the copies land
const DOTS = 1.7;        // floor dots per world unit
const PINS = 9;          // package pins per side of the CPU die
const TAU = Math.PI * 2;

const css = getComputedStyle(document.documentElement);
const tok = (name) => new THREE.Color(css.getPropertyValue(name).trim());

// Read a token from another theme: themes are [data-theme] blocks in tokens.css, so a hidden probe picks them up.
function themeTok(theme, name) {
  const probe = document.createElement('i');
  probe.dataset.theme = theme;
  probe.hidden = true;
  document.body.append(probe);
  const value = getComputedStyle(probe).getPropertyValue(name).trim();
  probe.remove();
  return new THREE.Color(value);
}

// One colour per output lane, drawn from all three themes: each lane reads as one device's traffic.
function lanePalette() {
  const ember = (n) => themeTok('ember', n);
  const graphite = (n) => themeTok('graphite', n);
  const spectrum = (n) => themeTok('spectrum', n);
  return [
    ember('--accent'), spectrum('--data-2'), graphite('--data-1'), spectrum('--data-1'),
    ember('--data-2'), spectrum('--data-4'), graphite('--data-2'), spectrum('--data-6'),
    ember('--accent'), spectrum('--data-5'), graphite('--data-5'), ember('--data-6'),
  ];   // no spectrum coral: too close to the red that flags a threat
}

const host = document.querySelector('[data-hero-scene]');
if (host) {
  init(host).catch((err) => {
    console.warn('NetTap hero: 3D scene unavailable, showing the static version.', err);
    host.dataset.state = 'static';
  });
}

async function init(host) {
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const narrow = matchMedia('(max-width: 760px)');

  const renderer = new THREE.WebGPURenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
  renderer.setClearColor(tok('--bg'), 1);
  await renderer.init();
  host.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  const rig = new THREE.Group();
  scene.add(rig);

  const uTime = uniform(0);
  const uCore = uniform(new THREE.Vector2());
  const uLens = uniform(new THREE.Vector3());   // floor point under the lens (x, z) and its strength
  const uZoom = uniform(0);                      // 1 only while the lens view renders

  const core = makeCube(uTime);
  rig.add(makeStream(uTime, narrow.matches ? 1100 : 1900), makeCopyColumn(uTime), makeLanding(uTime), core);
  scene.add(makeFloor(uTime, uCore, uLens, uZoom));

  const pipeline = new THREE.RenderPipeline(renderer);
  const sceneColor = pass(scene, camera).getTextureNode('output');
  pipeline.outputNode = sceneColor.add(bloom(sceneColor, 0.55, 0.35, 0.22));

  const anchors = {
    core: new THREE.Vector3(-0.3, 1.9, 0),
    floor: new THREE.Vector3(0.6, FLOOR_Y, 0.5),
    out: new THREE.Vector3(2.6, 1.25, 0),
  };
  const labels = [...host.querySelectorAll('[data-anchor]')];
  const baseCam = new THREE.Vector3();
  const pointer = { x: 0, y: 0 };
  const projected = new THREE.Vector3();

  function layout() {
    const w = host.clientWidth;
    const h = host.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const wide = camera.aspect > 1.25;
    rig.position.set(wide ? 2.75 : 0, wide ? 0 : 0.35, 0);
    baseCam.set(0, wide ? 1.5 : 1.9, wide ? 11.5 : 11.8);
    camera.position.copy(baseCam);
    camera.updateProjectionMatrix();
    uCore.value.set(rig.position.x, rig.position.z);
    lens.resize(renderer.getPixelRatio());
  }

  function aim() {
    camera.lookAt(rig.position.x * 0.55, -0.35, 0);
  }

  function placeLabels() {
    const w = host.clientWidth;
    const h = host.clientHeight;
    for (const el of labels) {
      projected.copy(anchors[el.dataset.anchor]).add(rig.position).project(camera);
      const x = Math.min(((projected.x + 1) / 2) * w, w - el.offsetWidth - 32);
      el.style.transform = `translate(${x}px, ${((1 - projected.y) / 2) * h}px)`;
    }
  }

  let t = 6.5;
  let last = 0;
  let running = false;
  let visible = true;
  const lens = createLens({
    renderer, scene, camera, host, floorY: FLOOR_Y, dots: DOTS, uLens, uZoom, uCore,
    onMove: () => { if (!running) renderStill(); },
  });

  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    t += dt;
    uTime.value = t;
    spin(core, t, dt);
    camera.position.x += (baseCam.x + pointer.x * 0.8 - camera.position.x) * 0.035;
    camera.position.y += (baseCam.y - pointer.y * 0.4 - camera.position.y) * 0.035;
    aim();
    lens.prepare(dt);
    pipeline.render();
    placeLabels();
    host.dataset.state = 'live';
  }

  function renderStill() {
    uTime.value = t;
    spin(core, t, 0);
    camera.position.copy(baseCam);
    aim();
    lens.prepare(0);
    pipeline.render();
    placeLabels();
    host.dataset.state = 'live';
  }

  function update() {
    const shouldRun = visible && !reduceMotion.matches;
    if (shouldRun === running) {
      if (!shouldRun) renderStill();
      return;
    }
    running = shouldRun;
    last = performance.now();
    renderer.setAnimationLoop(running ? frame : null);
    if (!running) renderStill();
  }

  layout();
  new ResizeObserver(() => { layout(); if (!running) renderStill(); }).observe(host);
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); }).observe(host);
  reduceMotion.addEventListener('change', update);
  window.addEventListener('pointermove', (e) => {
    pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
  }, { passive: true });
  update();
}

function additive(opts = {}) {
  return new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...opts });
}

// The tap line: packets flow left to right, squeezed through the tap; after it they are lit, a few flagged.
function makeStream(uTime, count) {
  const mat = additive();
  const h1 = hash(instanceIndex);
  const h2 = hash(instanceIndex.add(101));
  const h3 = hash(instanceIndex.add(202));
  const h4 = hash(instanceIndex.add(303));
  const h5 = hash(instanceIndex.add(404));

  const progress = fract(uTime.mul(h4.mul(0.04).add(0.035)).add(h1));
  const x = progress.mul(2).sub(1).mul(SPAN);
  const inspected = smoothstep(-0.4, CUBE / 2, x);
  const flagged = step(0.982, h5).mul(inspected);

  // Before the tap: a loose cloud. After it: tidy lanes (12 angles x 2 rings), the traffic made sense of.
  const funnel = smoothstep(0.0, 2.8, abs(x)).mul(0.92).add(0.08);
  const cloudAngle = h2.mul(TAU).add(x.mul(0.16)).add(uTime.mul(0.1));
  const laneAngle = h2.mul(LANES).floor().div(LANES).mul(TAU);
  const cloudRadius = h3.sqrt().mul(1.35);
  const laneRadius = h3.mul(2).floor().mul(0.42).add(0.55);
  const angle = mix(cloudAngle, laneAngle, inspected);
  const radius = mix(cloudRadius, laneRadius, inspected).mul(funnel);

  const len = mix(0.07, 0.2, inspected);
  const thick = mix(0.022, 0.02, inspected).add(flagged.mul(0.028));
  mat.positionNode = positionLocal.mul(vec3(len, thick, thick)).add(vec3(x, sin(angle).mul(radius), cos(angle).mul(radius)));

  const nearTap = oneMinus(smoothstep(0.0, 1.1, abs(x)));
  // OLD CODE START: every inspected packet was ember orange; now each lane has its own colour (owner, 2026-11-15)
  // const lit = mix(color(tok('--accent')), color(tok('--data-2')), h3.mul(0.35));
  // OLD CODE END
  const lit = uniformArray(lanePalette(), 'color').element(int(h2.mul(LANES).floor()));
  const base = mix(color(tok('--data-5')).mul(0.35), lit.mul(0.8), inspected);
  const hot = mix(base, color(tok('--data-3')), nearTap.mul(0.55));
  mat.colorNode = varying(mix(hot, color(tok('--sev-critical')).mul(1.3), flagged));
  const edgeFade = oneMinus(smoothstep(SPAN * 0.55, SPAN * 0.96, abs(x)));
  mat.opacityNode = varying(edgeFade.mul(mix(0.5, 0.7, inspected)));

  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, count);
  mesh.frustumCulled = false;
  return mesh;
}

// The stem: a copy of the traffic falls from the tap to the floor.
function makeCopyColumn(uTime) {
  const mat = additive();
  const fall = fract(uTime.mul(0.3).add(hash(instanceIndex)));
  const angle = hash(instanceIndex.add(77)).mul(TAU);
  const radius = hash(instanceIndex.add(88)).mul(0.14);
  mat.positionNode = positionLocal.mul(vec3(0.016, 0.11, 0.016))
    .add(vec3(cos(angle).mul(radius), mix(-CUBE / 2, FLOOR_Y + 0.05, fall), sin(angle).mul(radius)));
  mat.colorNode = color(tok('--accent'));
  mat.opacityNode = varying(smoothstep(0.0, 0.12, fall).mul(oneMinus(smoothstep(0.82, 1.0, fall))).mul(0.55));
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, 120);
  mesh.frustumCulled = false;
  return mesh;
}

// The dot: where the copies land.
function makeLanding(uTime) {
  const mat = additive();
  const d = length(uv().sub(0.5)).mul(2);
  const glow = oneMinus(smoothstep(0.0, 1.0, d)).pow(2.2);
  const pulse = sin(uTime.mul(2.4)).mul(0.15).add(1.0);
  mat.colorNode = color(tok('--accent')).mul(glow.mul(pulse).mul(0.9));
  const mesh = new THREE.Mesh(new THREE.CircleGeometry(0.7, 64), mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = FLOOR_Y + 0.01;
  return mesh;
}

function edgeLines(geo, opacity) {
  return new THREE.LineSegments(
    new THREE.EdgesGeometry(geo),
    new THREE.LineBasicNodeMaterial({ color: tok('--accent-strong'), transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false })
  );
}

// The scanner: a glass cube on a turntable. Each face has its own scan line sweeping up and down
// over a tile grid; tiles light as the line passes, and a rare one flags red.
function makeCube(uTime) {
  const group = new THREE.Group();
  const geo = new THREE.BoxGeometry(CUBE, CUBE, CUBE);
  const shell = new THREE.Group();
  shell.name = 'shell';
  shell.add(new THREE.Mesh(geo, Array.from({ length: 6 }, (_, face) => makeFaceMaterial(uTime, face))), edgeLines(geo, 0.8));

  group.add(shell, makeCrystal(uTime));
  group.rotation.x = 0.32;   // tip the top face toward the viewer so the cube always reads as 3D
  return group;
}

function makeFaceMaterial(uTime, face) {
  const mat = additive({ side: THREE.DoubleSide });
  const speed = 0.5 + (face % 3) * 0.13;
  const phase = face * 1.7;
  mat.colorNode = Fn(() => {
    const p = uv();
    const scanY = sin(uTime.mul(speed).add(phase)).mul(0.5).add(0.5);
    const g = fract(p.mul(CELLS));
    const toLine = min(g, oneMinus(g));
    const toEdge = min(min(p.x, oneMinus(p.x)), min(p.y, oneMinus(p.y)));
    const grid = oneMinus(smoothstep(0.0, 0.04, min(toLine.x, toLine.y)));
    const frame = oneMinus(smoothstep(0.0, 0.035, toEdge));

    const d = abs(p.y.sub(scanY));
    const line = oneMinus(smoothstep(0.0, 0.012, d));
    const halo = oneMinus(smoothstep(0.0, 0.22, d));

    const cell = floor(p.mul(CELLS));
    const h = hash(cell.x.add(cell.y.mul(CELLS)).add(face * 64));
    const near = oneMinus(smoothstep(0.0, 0.17, abs(cell.y.add(0.5).div(CELLS).sub(scanY))));
    const tileBody = step(0.14, min(toLine.x, toLine.y)).mul(near);
    const flagged = step(0.965, h);
    const tile = step(0.6, h).mul(oneMinus(flagged)).mul(tileBody);

    const accent = color(tok('--accent'));
    const lit = accent.mul(grid.mul(0.1).add(frame.mul(0.3)).add(halo.mul(0.07)).add(tile.mul(0.42)))
      .add(color(tok('--sev-critical')).mul(flagged.mul(tileBody).mul(0.9)))
      .add(color(tok('--data-3')).mul(line));
    return lit.mul(select(frontFacing, 1.0, 0.35));
  })();
  return mat;
}

// Inside the scanner: a faceted glass crystal (fresnel-lit, glowing edges) around the CPU die.
function makeCrystal(uTime) {
  const group = new THREE.Group();
  const geo = new THREE.IcosahedronGeometry(0.78, 0);
  const shellMat = additive({ side: THREE.DoubleSide });
  const fresnel = oneMinus(abs(normalView.dot(positionViewDirection))).pow(2.2);
  shellMat.colorNode = color(tok('--accent')).mul(fresnel.mul(0.9).add(0.04));
  const crystal = new THREE.Group();
  crystal.name = 'crystal';
  crystal.add(new THREE.Mesh(geo, shellMat), edgeLines(geo, 0.7));

  // OLD CODE START: the gold heart sphere, replaced by the CPU die (owner, 2026-11-15)
  // const heartMat = new THREE.MeshBasicNodeMaterial();
  // heartMat.colorNode = mix(color(tok('--data-2')), color(tok('--data-3')), 0.35).mul(sin(uTime.mul(2.4)).mul(0.08).add(0.62));
  // const heart = new THREE.Mesh(new THREE.SphereGeometry(0.15, 32, 16), heartMat);
  // group.add(crystal, heart);
  // OLD CODE END

  group.add(crystal, makeChip(uTime));
  return group;
}

const gold = () => mix(color(tok('--data-2')), color(tok('--data-3')), 0.35);
const toEdgeOf = (p) => min(min(p.x, oneMinus(p.x)), min(p.y, oneMinus(p.y)));

// The CPU die the packets pass through: a dark package with contact pads and pins,
// and a 4x4 grid of cores that flare with work while pulses run along the traces between them.
function makeChip(uTime) {
  const chip = new THREE.Group();
  chip.name = 'chip';
  const dark = new THREE.MeshBasicNodeMaterial({ color: tok('--surface-2') });

  const pkgFace = new THREE.MeshBasicNodeMaterial();
  pkgFace.colorNode = Fn(() => {
    const p = uv();
    const e = toEdgeOf(p);
    const band = step(0.035, e).mul(oneMinus(step(0.115, e)));
    const pad = step(0.42, fract(p.x.mul(18))).mul(step(0.42, fract(p.y.mul(18))));
    return color(tok('--surface-2')).add(gold().mul(band.mul(pad).mul(0.5)));
  })();
  const pkgGeo = new THREE.BoxGeometry(0.6, 0.6, 0.05);
  chip.add(new THREE.Mesh(pkgGeo, [dark, dark, dark, dark, pkgFace, dark]), edgeLines(pkgGeo, 0.45));

  const dieFace = new THREE.MeshBasicNodeMaterial();
  dieFace.colorNode = Fn(() => {
    const p = uv();
    const f = fract(p.mul(4));
    const cell = floor(p.mul(4));
    const toLine = toEdgeOf(f);
    const h = hash(cell.x.add(cell.y.mul(4)).add(11));
    const busy = sin(uTime.mul(h.mul(2.5).add(1.2)).add(h.mul(TAU))).mul(0.5).add(0.5).pow(4);
    const coreBody = step(0.16, toLine);
    const trace = oneMinus(smoothstep(0.0, 0.035, toLine));
    const pulse = oneMinus(smoothstep(0.0, 0.12, abs(fract(p.x.add(p.y).mul(1.5).sub(uTime.mul(0.6))).sub(0.5))));
    const rim = oneMinus(smoothstep(0.0, 0.03, toEdgeOf(p)));
    return color(tok('--surface-1'))
      .add(color(tok('--accent')).mul(coreBody.mul(busy.mul(0.95).add(0.14))))
      .add(gold().mul(trace.mul(pulse.mul(0.9).add(0.15)).add(rim.mul(0.8))));
  })();
  const dieGeo = new THREE.BoxGeometry(0.34, 0.34, 0.03);
  const die = new THREE.Group();
  die.position.z = 0.04;
  die.add(new THREE.Mesh(dieGeo, [dark, dark, dark, dark, dieFace, dark]), edgeLines(dieGeo, 0.9));
  chip.add(die, makePins());
  chip.scale.setScalar(0.6);    // small heart inside the crystal (owner: 1.25 read as too big)
  return chip;
}

function makePins() {
  const mat = new THREE.MeshBasicNodeMaterial({ color: tok('--data-2').lerp(tok('--data-3'), 0.35).multiplyScalar(0.55) });
  const pins = new THREE.InstancedMesh(new THREE.BoxGeometry(0.018, 0.07, 0.012), mat, PINS * 4);
  const m = new THREE.Matrix4();
  const at = new THREE.Vector3();
  const z = new THREE.Vector3(0, 0, 1);
  for (let side = 0; side < 4; side++) {
    for (let k = 0; k < PINS; k++) {
      const angle = side * Math.PI / 2;
      at.set((k - (PINS - 1) / 2) * 0.058, 0.325, 0).applyAxisAngle(z, angle);
      pins.setMatrixAt(side * PINS + k, m.makeRotationZ(angle).setPosition(at));
    }
  }
  return pins;
}

// Turntable spin for the scanner; the crystal turns the other way, slower, with a gentle nod.
// The die faces the viewer (undoing the cube's tip) and sways enough to show its edge and pins.
function spin(core, t, dt) {
  core.getObjectByName('shell').rotation.y += dt * 0.3;
  const crystal = core.getObjectByName('crystal');
  crystal.rotation.y -= dt * 0.22;
  crystal.rotation.x = Math.sin(t * 0.3) * 0.15;
  core.getObjectByName('chip').rotation.set(-0.32 + Math.sin(t * 0.31) * 0.12, Math.sin(t * 0.43) * 0.42, 0);
}

// A dot-grid floor; rings ripple out from where the copies land. Under the lens, nearby dots
// brighten and the one under the crosshair grows, turns gold and gets a ring. Only the lens sees
// the fine detail: each cell is a grid of stored-data blocks (too small to draw at normal scale).
function makeFloor(uTime, uCore, uLens, uZoom) {
  const mat = additive();
  mat.colorNode = Fn(() => {
    const xz = positionWorld.xz;
    const r = length(xz.sub(uCore));
    const d = length(fract(xz.mul(DOTS)).sub(0.5));
    const picked = oneMinus(step(0.5, length(floor(xz.mul(DOTS)).sub(floor(uLens.xy.mul(DOTS)))))).mul(uLens.z);
    const near = oneMinus(smoothstep(0.0, 1.4, length(xz.sub(uLens.xy)))).mul(uLens.z);
    const dotR = mix(0.1, 0.17, picked);
    const dotMask = oneMinus(smoothstep(dotR.sub(0.05), dotR, d));
    const halo = smoothstep(0.25, 0.27, d).mul(oneMinus(smoothstep(0.29, 0.31, d))).mul(picked);
    const fade = oneMinus(smoothstep(2.0, 15.0, r));
    const k = fract(r.mul(0.15).sub(uTime.mul(0.2)));
    const ring = smoothstep(0.0, 0.04, k).mul(oneMinus(smoothstep(0.04, 0.2, k)));
    const lit = color(tok('--accent')).mul(ring.mul(0.85).mul(oneMinus(smoothstep(1.0, 12.0, r))).add(near.mul(0.45)));
    const dots = color(tok('--text-2')).mul(0.09).add(lit).mul(dotMask).mul(fade);

    const blockAt = xz.mul(DOTS * 6);
    const bc = floor(blockAt);
    const bh = hash(bc.x.add(bc.y.mul(977)));
    const bp = abs(fract(blockAt).sub(0.5));
    const blink = step(0.6, fract(bh.mul(7.3).add(uTime.mul(bh.mul(0.3).add(0.06)))));
    const block = step(max(bp.x, bp.y), 0.3).mul(step(0.45, bh)).mul(mix(0.1, 0.42, blink));
    const blocks = color(tok('--accent')).mul(block.mul(uZoom).mul(oneMinus(dotMask)).mul(fade));

    return dots.add(blocks).add(color(tok('--data-3')).mul(dotMask.add(halo).mul(picked).mul(0.6)));
  })();
  const geo = new THREE.PlaneGeometry(60, 40);
  geo.rotateX(-Math.PI / 2);
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.y = FLOOR_Y;
  return mesh;
}
