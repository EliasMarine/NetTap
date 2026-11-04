<!--
  GeoMap.svelte — Interactive Leaflet world map with animated canvas arc overlay.
  Shows home network location, destination markers sized by connection count,
  and animated pulse dots traveling along bezier arcs from home to each destination.
  Alert countries are highlighted in red; active country is brighter.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { GeoArc } from '$lib/api/live';
	import L from 'leaflet';
	import 'leaflet/dist/leaflet.css';
	import { theme } from '$lib/stores/theme';
	import { resolveToken, prefersReducedMotion } from '$lib/utils/tokens';
	import { createArcScheduler, type ArcScheduler } from './arc-scheduler';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		destinations,
		homeLocation,
		activeCountry,
		paused,
		hasAlertCountries,
		onclick,
	}: {
		destinations: GeoArc[];
		homeLocation: { lat: number; lng: number } | null;
		activeCountry: string | null;
		paused: boolean;
		hasAlertCountries: Set<string>;
		onclick: (countryCode: string) => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// Element refs
	// ---------------------------------------------------------------------------

	let wrapper: HTMLDivElement;
	let mapEl: HTMLDivElement;
	let canvasEl: HTMLCanvasElement;

	// ---------------------------------------------------------------------------
	// Internal state
	// ---------------------------------------------------------------------------

	let map: L.Map | null = null;
	let homeMarkerGroup: L.LayerGroup | null = null;
	let destLayerGroup: L.LayerGroup | null = null;
	let scheduler: ArcScheduler | null = null;

	// OLD CODE START — 2026-11-03: literal colours and a single rAF loop replaced by
	// theme tokens (resolveToken) and arc-scheduler, which keeps static arcs under reduced motion.
	// let animFrameId: number | null = null;
	// let arcPhase = 0;
	// const COLOR_ACCENT = '#00d4ff';
	// const COLOR_GREEN = '#00e676';
	// const COLOR_RED = '#ff4757';
	// OLD CODE END

	// Canvas and Leaflet markers can't use var(), so token values are read here
	// and re-read whenever the theme changes.
	let colors = $state({ accent: '', ok: '', alert: '' });

	function readColors() {
		return {
			accent: resolveToken('--accent'),
			ok: resolveToken('--ok'),
			alert: resolveToken('--sev-critical'),
		};
	}

	// ---------------------------------------------------------------------------
	// Map initialization
	// ---------------------------------------------------------------------------

	onMount(() => {
		map = L.map(mapEl, {
			center: [20, 10],
			zoom: 2,
			minZoom: 2,
			maxZoom: 6,
			zoomControl: false,
			attributionControl: false,
			preferCanvas: true,
			maxBounds: [
				[-85, -180],
				[85, 180],
			],
			maxBoundsViscosity: 1.0,
		});

		// OLD CODE START — 2026-11-02: CARTO now answers every tile with an "API KEY
		// REQUIRED" image, and remote tiles break NetTap's no-cloud-dependency rule.
		// L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
		// 	subdomains: 'abcd',
		// 	maxZoom: 19,
		// }).addTo(map);
		// OLD CODE END
		addCountryOutlines(map);

		homeMarkerGroup = L.layerGroup().addTo(map);
		destLayerGroup = L.layerGroup().addTo(map);

		// OLD CODE START — 2026-11-03: resizing clears the canvas, and the static frame
		// under reduced motion must be redrawn after it, so these now go through the scheduler.
		// syncCanvasSize();
		// map.on('moveend', syncCanvasSize);
		// map.on('zoomend', syncCanvasSize);
		// map.on('resize', syncCanvasSize);
		// window.addEventListener('resize', syncCanvasSize);
		// animFrameId = requestAnimationFrame(animationLoop);
		// ...cleanup: if (animFrameId !== null) cancelAnimationFrame(animFrameId);
		// window.removeEventListener('resize', syncCanvasSize);
		// OLD CODE END

		// The store notifies after <html data-variant> changes, so this reads the new values
		const unsubscribeTheme = theme.subscribe(() => {
			colors = readColors();
		});

		scheduler = createArcScheduler({
			draw: drawFrame,
			reduceMotion: prefersReducedMotion(),
			isPaused: () => paused,
		});

		// Keep canvas sized to the map container. Resizing clears it, so redraw after.
		const onViewportSettled = () => {
			syncCanvasSize();
			scheduler?.redraw();
		};
		const onViewportMove = () => scheduler?.redraw();
		syncCanvasSize();
		map.on('moveend zoomend resize', onViewportSettled);
		map.on('move zoom', onViewportMove);
		window.addEventListener('resize', onViewportSettled);

		scheduler.start();

		return () => {
			scheduler?.stop();
			scheduler = null;
			unsubscribeTheme();
			window.removeEventListener('resize', onViewportSettled);
			if (map) {
				map.remove();
				map = null;
			}
		};
	});

	// ---------------------------------------------------------------------------
	// Base map — bundled country outlines, no tile server
	// ---------------------------------------------------------------------------

	// Natural Earth 1:110m countries (public domain), from world-atlas 2.0.2 (ISC),
	// converted to GeoJSON and served from web/static/geo.
	const COUNTRY_OUTLINES_URL = '/geo/countries-110m.geojson';

	async function addCountryOutlines(target: L.Map) {
		try {
			const res = await fetch(COUNTRY_OUTLINES_URL);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const outlines = await res.json();
			if (map !== target) return; // unmounted while loading
			target.createPane('countries').style.zIndex = '250'; // above tiles, below markers
			L.geoJSON(outlines, {
				pane: 'countries',
				interactive: false,
				// SVG, not the map's canvas renderer, so CSS theme variables can style it
				style: { className: 'geo-country', renderer: L.svg({ pane: 'countries' }) },
			}).addTo(target);
		} catch (err) {
			// Arcs and markers still work on the plain background
			console.warn('Live map: country outlines unavailable', err);
		}
	}

	// ---------------------------------------------------------------------------
	// Canvas sizing — retina-aware
	// ---------------------------------------------------------------------------

	function syncCanvasSize() {
		if (!canvasEl || !mapEl) return;
		const rect = mapEl.getBoundingClientRect();
		const dpr = window.devicePixelRatio || 1;
		canvasEl.width = rect.width * dpr;
		canvasEl.height = rect.height * dpr;
		canvasEl.style.width = `${rect.width}px`;
		canvasEl.style.height = `${rect.height}px`;
	}

	// ---------------------------------------------------------------------------
	// Home marker — react to homeLocation changes
	// ---------------------------------------------------------------------------

	$effect(() => {
		if (!map || !homeMarkerGroup) return;

		homeMarkerGroup.clearLayers();

		if (!homeLocation) return;

		const { lat, lng } = homeLocation;

		// Outer glow ring
		L.circleMarker([lat, lng], {
			radius: 16,
			color: colors.ok,
			weight: 1,
			opacity: 0.15,
			fillColor: colors.ok,
			fillOpacity: 0.06,
			interactive: false,
		}).addTo(homeMarkerGroup);

		// Solid home dot
		const homeMarker = L.circleMarker([lat, lng], {
			radius: 7,
			color: colors.ok,
			weight: 2,
			opacity: 0.9,
			fillColor: colors.ok,
			fillOpacity: 1,
			interactive: false,
		}).addTo(homeMarkerGroup);

		homeMarker.bindTooltip('HOME NETWORK', {
			permanent: true,
			direction: 'top',
			offset: [0, -12],
			className: 'home-tooltip',
		});
	});

	// ---------------------------------------------------------------------------
	// Destination markers — react to destinations / activeCountry / hasAlertCountries
	// ---------------------------------------------------------------------------

	$effect(() => {
		if (!map || !destLayerGroup) return;

		destLayerGroup.clearLayers();

		// Depend on reactive values so this re-runs when they change
		const _active = activeCountry;
		const _alerts = hasAlertCountries;

		for (const dest of destinations) {
			if (dest.lat == null || dest.lon == null) continue;

			const isAlert = _alerts.has(dest.country_code);
			const isActive = _active === dest.country_code;
			const color = isAlert ? colors.alert : colors.accent;
			const radius = Math.min(4 + Math.sqrt(dest.count) * 2, 14);

			const marker = L.circleMarker([dest.lat, dest.lon], {
				radius,
				color,
				weight: isActive ? 2 : 1,
				opacity: isActive ? 1 : 0.7,
				fillColor: color,
				fillOpacity: isActive ? 0.95 : 0.6,
			}).addTo(destLayerGroup);

			const label = [dest.city, dest.country].filter(Boolean).join(', ');
			marker.bindTooltip(`${label}: ${dest.count} connections`, {
				direction: 'top',
				offset: [0, -radius],
			});

			marker.on('click', () => {
				onclick(dest.country_code);
			});
		}
	});

	// ---------------------------------------------------------------------------
	// Animated canvas arc layer
	// ---------------------------------------------------------------------------

	// Static frame redraw under reduced motion: data, alert set or theme changed
	$effect(() => {
		void destinations;
		void homeLocation;
		void hasAlertCountries;
		void colors.accent;
		void colors.alert;
		scheduler?.redraw();
	});

	// OLD CODE START — 2026-11-03: drawing and scheduling were one function, so skipping the
	// loop under reduced motion would also remove the static arcs. Split into drawFrame (below)
	// and arc-scheduler.ts.
	// function animationLoop() {
	// 	animFrameId = requestAnimationFrame(animationLoop);
	//
	// 	if (paused || !map || !canvasEl || !homeLocation) return;
	//
	// 	const ctx = canvasEl.getContext('2d');
	// 	if (!ctx) return;
	//
	// 	const dpr = window.devicePixelRatio || 1;
	// 	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	// 	ctx.clearRect(0, 0, canvasEl.width / dpr, canvasEl.height / dpr);
	//
	// 	const homePixel = map.latLngToContainerPoint([homeLocation.lat, homeLocation.lng]);
	//
	// 	arcPhase = (arcPhase + 0.005) % 1;
	//
	// 	for (let i = 0; i < destinations.length; i++) {
	// 		const dest = destinations[i];
	// 		if (dest.lat == null || dest.lon == null) continue;
	//
	// 		const destPixel = map.latLngToContainerPoint([dest.lat, dest.lon]);
	// 		const isAlert = hasAlertCountries.has(dest.country_code);
	// 		const color = isAlert ? COLOR_RED : COLOR_ACCENT;
	//
	// 		// Quadratic bezier control point — arcs upward
	// 		const midX = (homePixel.x + destPixel.x) / 2;
	// 		const minY = Math.min(homePixel.y, destPixel.y);
	// 		const dx = destPixel.x - homePixel.x;
	// 		const dy = destPixel.y - homePixel.y;
	// 		const distance = Math.sqrt(dx * dx + dy * dy);
	// 		const cpX = midX;
	// 		const cpY = minY - 40 - distance * 0.12;
	//
	// 		// Draw static arc with glow
	// 		ctx.beginPath();
	// 		ctx.moveTo(homePixel.x, homePixel.y);
	// 		ctx.quadraticCurveTo(cpX, cpY, destPixel.x, destPixel.y);
	// 		ctx.strokeStyle = color;
	// 		ctx.globalAlpha = 0.07;
	// 		ctx.lineWidth = 6;
	// 		ctx.stroke();
	//
	// 		ctx.beginPath();
	// 		ctx.moveTo(homePixel.x, homePixel.y);
	// 		ctx.quadraticCurveTo(cpX, cpY, destPixel.x, destPixel.y);
	// 		ctx.strokeStyle = color;
	// 		ctx.globalAlpha = 0.3;
	// 		ctx.lineWidth = 1.5;
	// 		ctx.stroke();
	//
	// 		// Animated pulse dots — more pulses for higher connection counts
	// 		const pulseCount = Math.min(1 + Math.floor(Math.sqrt(dest.count)), 3);
	//
	// 		for (let p = 0; p < pulseCount; p++) {
	// 			const t = (arcPhase + i * 0.11 + p * (1 / pulseCount)) % 1;
	//
	// 			// Position along the quadratic bezier at parameter t
	// 			const px = (1 - t) * (1 - t) * homePixel.x + 2 * (1 - t) * t * cpX + t * t * destPixel.x;
	// 			const py = (1 - t) * (1 - t) * homePixel.y + 2 * (1 - t) * t * cpY + t * t * destPixel.y;
	//
	// 			// Outer glow
	// 			ctx.beginPath();
	// 			ctx.arc(px, py, 8, 0, Math.PI * 2);
	// 			ctx.fillStyle = color;
	// 			ctx.globalAlpha = 0.25;
	// 			ctx.fill();
	//
	// 			// Solid dot
	// 			ctx.beginPath();
	// 			ctx.arc(px, py, 3.5, 0, Math.PI * 2);
	// 			ctx.fillStyle = color;
	// 			ctx.globalAlpha = 0.95;
	// 			ctx.fill();
	// 		}
	// 	}
	//
	// 	// Reset alpha for next frame
	// 	ctx.globalAlpha = 1;
	// }
	// OLD CODE END

	/** Draws every arc, plus pulse dots at `pulsePhase` (none when null: reduced motion). */
	function drawFrame(pulsePhase: number | null) {
		if (!map || !canvasEl || !homeLocation) return;

		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;

		const dpr = window.devicePixelRatio || 1;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, canvasEl.width / dpr, canvasEl.height / dpr);

		const homePixel = map.latLngToContainerPoint([homeLocation.lat, homeLocation.lng]);

		for (let i = 0; i < destinations.length; i++) {
			const dest = destinations[i];
			if (dest.lat == null || dest.lon == null) continue;

			const destPixel = map.latLngToContainerPoint([dest.lat, dest.lon]);
			const isAlert = hasAlertCountries.has(dest.country_code);
			const color = isAlert ? colors.alert : colors.accent;

			// Quadratic bezier control point — arcs upward
			const midX = (homePixel.x + destPixel.x) / 2;
			const minY = Math.min(homePixel.y, destPixel.y);
			const dx = destPixel.x - homePixel.x;
			const dy = destPixel.y - homePixel.y;
			const distance = Math.sqrt(dx * dx + dy * dy);
			const cpX = midX;
			const cpY = minY - 40 - distance * 0.12;

			// Static arc with glow
			ctx.beginPath();
			ctx.moveTo(homePixel.x, homePixel.y);
			ctx.quadraticCurveTo(cpX, cpY, destPixel.x, destPixel.y);
			ctx.strokeStyle = color;
			ctx.globalAlpha = 0.07;
			ctx.lineWidth = 6;
			ctx.stroke();

			ctx.beginPath();
			ctx.moveTo(homePixel.x, homePixel.y);
			ctx.quadraticCurveTo(cpX, cpY, destPixel.x, destPixel.y);
			ctx.strokeStyle = color;
			ctx.globalAlpha = 0.3;
			ctx.lineWidth = 1.5;
			ctx.stroke();

			if (pulsePhase === null) continue;

			// Animated pulse dots — more pulses for higher connection counts
			const pulseCount = Math.min(1 + Math.floor(Math.sqrt(dest.count)), 3);

			for (let p = 0; p < pulseCount; p++) {
				const t = (pulsePhase + i * 0.11 + p * (1 / pulseCount)) % 1;

				// Position along the quadratic bezier at parameter t
				const px = (1 - t) * (1 - t) * homePixel.x + 2 * (1 - t) * t * cpX + t * t * destPixel.x;
				const py = (1 - t) * (1 - t) * homePixel.y + 2 * (1 - t) * t * cpY + t * t * destPixel.y;

				// Outer glow
				ctx.beginPath();
				ctx.arc(px, py, 8, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.globalAlpha = 0.25;
				ctx.fill();

				// Solid dot
				ctx.beginPath();
				ctx.arc(px, py, 3.5, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.globalAlpha = 0.95;
				ctx.fill();
			}
		}

		ctx.globalAlpha = 1;
	}
</script>

<div class="geo-map-wrapper" bind:this={wrapper}>
	<div class="geo-map" bind:this={mapEl}></div>
	<canvas class="arc-canvas" bind:this={canvasEl}></canvas>
</div>

<style>
	.geo-map-wrapper {
		position: relative;
		width: 100%;
		height: 100%;
		overflow: hidden;
		isolation: isolate;
	}

	.geo-map {
		width: 100%;
		height: 100%;
		background: var(--bg-void);
		/* Create stacking context so Leaflet panes are contained within */
		z-index: 0;
	}

	.arc-canvas {
		position: absolute;
		inset: 0;
		pointer-events: none;
		z-index: 450;
	}

	/* ----- Base map: bundled country outlines (CSS overrides Leaflet's SVG attributes) ----- */

	:global(.geo-map .geo-country) {
		fill: var(--bg-elevated);
		fill-opacity: 1;
		stroke: var(--border-bright);
		stroke-width: 0.6;
		stroke-opacity: 1;
	}

	/* ----- Leaflet control overrides ----- */

	:global(.geo-map .leaflet-control-attribution) {
		display: none;
	}

	:global(.geo-map .leaflet-control-zoom) {
		display: none;
	}

	/* ----- Leaflet tooltip — dark SIEM theme ----- */

	:global(.geo-map .leaflet-tooltip) {
		background: var(--bg-elevated);
		border: 1px solid var(--border-bright);
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: 12px;
		padding: 4px 8px;
		border-radius: var(--radius-sm);
		box-shadow: var(--shadow-md);
		white-space: nowrap;
	}

	:global(.geo-map .leaflet-tooltip-top::before) {
		border-top-color: var(--border-bright);
	}

	:global(.geo-map .leaflet-tooltip-bottom::before) {
		border-bottom-color: var(--border-bright);
	}

	:global(.geo-map .leaflet-tooltip-left::before) {
		border-left-color: var(--border-bright);
	}

	:global(.geo-map .leaflet-tooltip-right::before) {
		border-right-color: var(--border-bright);
	}

	/* Home tooltip — green accent */

	:global(.geo-map .home-tooltip) {
		background: var(--green-dim);
		border-color: var(--green);
		color: var(--green);
		font-weight: 600;
		font-size: 11px;
		letter-spacing: 0.06em;
	}

	:global(.geo-map .home-tooltip.leaflet-tooltip-top::before) {
		border-top-color: var(--green);
	}

	/* Leaflet container must participate in z-index stacking */

	:global(.geo-map .leaflet-pane) {
		z-index: auto;
	}

	:global(.geo-map .leaflet-tile-pane) {
		z-index: 200;
	}

	:global(.geo-map .leaflet-overlay-pane) {
		z-index: 400;
	}

	:global(.geo-map .leaflet-marker-pane) {
		z-index: 600;
	}

	:global(.geo-map .leaflet-tooltip-pane) {
		z-index: 650;
	}

	:global(.geo-map .leaflet-popup-pane) {
		z-index: 700;
	}
</style>
