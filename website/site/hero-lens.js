// Hero Easter egg: hover the floor and a small zoomed view shows the scene up close (a second,
// narrow-FOV render of the same scene), with a sample network record for the dot under the crosshair.
// Mouse and pen only; touch screens never see it.
import * as THREE from 'three/webgpu';
import { texture, uv, length, smoothstep, oneMinus } from 'three/tsl';

const LENS_PX = 140;          // zoom view diameter on screen
const ZOOM = 2.4;             // true magnification of the zoom view
const MAX_RADIUS = 11;        // only where the floor dots are visible
const BEHIND = 2.5;           // floor further back than this sits behind the scanner on screen

// Sample data only: documentation addresses (RFC 5737, RFC 3849), documentation ASNs (RFC 5398)
// and example.* names, plus the device names from NetTap's demo data.
const RECORDS = [
  ['DNS', 'cdn.example-media.net', 'A 203.0.113.45 · TTL 300'],
  ['DNS', 'time.example.org', 'AAAA 2001:db8::7b · TTL 3600'],
  ['DNS', 'updates.example.com', 'CNAME edge-02.example.net'],
  ['DNS', 'example.com', 'MX 10 mx1.example.com'],
  ['GeoIP', '198.51.100.23', 'Frankfurt, Germany · AS64500'],
  ['GeoIP', '203.0.113.88', 'Tokyo, Japan · AS64501'],
  ['GeoIP', '192.0.2.140', 'Ashburn, United States · AS64502'],
  ['GeoIP', '198.51.100.201', 'Amsterdam, Netherlands · AS64503'],
  ['Connection', '192.168.1.22 → 203.0.113.45:443', 'TCP · 1.4 MB · 34 s'],
  ['Connection', '192.168.1.50 → 198.51.100.7:123', 'UDP · NTP · 90 B'],
  ['Connection', '192.168.1.20 → 192.0.2.10:53', 'UDP · DNS · 12 queries'],
  ['TLS', 'api.example.com', 'SNI · TLS 1.3 · certificate valid 61 days'],
  ['TLS', 'video.example-media.net', 'SNI · QUIC · TLS 1.3'],
  ['DHCP', 'thermostat-01', '192.168.1.31 · lease 24 h'],
  ['DHCP', 'laptop-01', '192.168.1.20 · lease 12 h'],
  ['Device', 'tv-livingroom', 'IoT · Example Electronics · 24.7 GB today'],
  ['Device', 'camera-01', 'IoT · Example Cameras Inc · 2 alerts'],
];

const FORWARD = new THREE.Vector3(0, 0, -1);

export function createLens({ renderer, scene, camera, host, floorY, dots, uLens, uZoom, uCore, onMove }) {
  const section = host.parentElement;
  const chrome = host.querySelector('[data-lens]');
  const card = chrome.querySelector('[data-lens-card]');
  const field = (name) => card.querySelector(`[data-${name}]`);
  const fields = { type: field('type'), main: field('main'), sub: field('sub') };
  const canHover = matchMedia('(hover: hover) and (pointer: fine)');
  host.style.setProperty('--lens-r', `${LENS_PX / 2}px`);

  const target = new THREE.RenderTarget(1, 1, { samples: 4 });
  const lensCam = new THREE.PerspectiveCamera(10, 1, 0.1, 100);
  const mat = new THREE.MeshBasicNodeMaterial({ transparent: true, depthTest: false, depthWrite: false });
  mat.colorNode = texture(target.texture).rgb.mul(1.15);
  mat.opacityNode = oneMinus(smoothstep(0.46, 0.5, length(uv().sub(0.5))));   // soft edge
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
  glass.layers.set(1);              // the main camera sees layer 1; the lens camera doesn't see itself
  glass.renderOrder = 10;
  glass.frustumCulled = false;
  glass.visible = false;
  camera.layers.enable(1);
  camera.add(glass);
  scene.add(camera);

  const caster = new THREE.Raycaster();
  const floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), -floorY);
  const hit = new THREE.Vector3();
  const ndc = new THREE.Vector2();
  const dir = new THREE.Vector3();
  const turn = new THREE.Quaternion();
  const pointer = { x: 0, y: 0, wanted: false };
  let strength = 0;
  let cellKey = '';

  section.addEventListener('pointermove', (e) => {
    const r = host.getBoundingClientRect();
    pointer.x = e.clientX - r.left;
    pointer.y = e.clientY - r.top;
    pointer.wanted = canHover.matches && e.pointerType !== 'touch' && !e.target.closest('.hero__copy, a, button');
    onMove();
  }, { passive: true });
  section.addEventListener('pointerleave', () => { pointer.wanted = false; onMove(); });

  function resize(pixelRatio) {
    const size = Math.round(LENS_PX * pixelRatio);
    target.setSize(size, size);
  }

  function findFloor(w, h) {
    if (!pointer.wanted) return false;
    ndc.set((pointer.x / w) * 2 - 1, 1 - (pointer.y / h) * 2);
    caster.setFromCamera(ndc, camera);
    if (!caster.ray.intersectPlane(floor, hit)) return false;
    const dz = hit.z - uCore.value.y;
    return dz > -BEHIND && Math.hypot(hit.x - uCore.value.x, dz) < MAX_RADIUS;
  }

  // Aim the lens camera down the pointer ray with the main camera's roll, at the magnified FOV.
  function renderZoomed(h) {
    const fov = THREE.MathUtils.degToRad(camera.fov);
    lensCam.fov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(fov / 2) * (LENS_PX / ZOOM) / h));
    lensCam.updateProjectionMatrix();
    lensCam.position.copy(camera.position);
    dir.copy(caster.ray.direction).applyQuaternion(turn.copy(camera.quaternion).invert());
    lensCam.quaternion.copy(camera.quaternion).multiply(turn.setFromUnitVectors(FORWARD, dir));
    uZoom.value = 1;
    renderer.setRenderTarget(target);
    renderer.render(scene, lensCam);
    renderer.setRenderTarget(null);
    uZoom.value = 0;

    const half = Math.tan(fov / 2);   // half-height of the view one unit in front of the camera
    glass.position.set(ndc.x * half * camera.aspect, ndc.y * half, -1);
    const size = (LENS_PX / h) * 2 * half;
    glass.scale.set(size, size, 1);
  }

  function showRecord(w) {
    const cx = Math.floor(hit.x * dots);
    const cz = Math.floor(hit.z * dots);
    const key = `${cx}:${cz}`;
    chrome.classList.toggle('is-left', pointer.x + LENS_PX / 2 + 360 > w);   // keep the card on screen
    chrome.style.transform = `translate(${pointer.x}px, ${pointer.y}px)`;
    if (key === cellKey) return;
    cellKey = key;
    const [type, main, sub] = RECORDS[(((cx * 73856093) ^ (cz * 19349663)) >>> 0) % RECORDS.length];
    fields.type.textContent = type;
    fields.main.textContent = main;
    fields.sub.textContent = sub;
    card.classList.remove('is-fresh');
    void card.offsetWidth;            // restart the fade for the new record
    card.classList.add('is-fresh');
  }

  // Call after the main camera has moved and before the main render.
  function prepare(dt) {
    const w = host.clientWidth;
    const h = host.clientHeight;
    camera.updateMatrixWorld();
    const active = findFloor(w, h);
    strength += ((active ? 1 : 0) - strength) * (dt > 0 ? Math.min(1, dt * 10) : 1);
    uLens.value.set(hit.x, hit.z, strength);
    glass.visible = active;
    chrome.hidden = !active;
    section.classList.toggle('hero--lens', active);
    if (!active) return;
    host.style.setProperty('--lens-x', `${pointer.x}px`);
    host.style.setProperty('--lens-y', `${pointer.y}px`);
    renderZoomed(h);
    showRecord(w);
  }

  return { resize, prepare };
}
