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
	let animFrameId: number | null = null;
	let arcPhase = 0;

	// Colors — pulled from the design system token values for canvas drawing.
	// Canvas cannot read CSS vars at draw time, so we resolve the actual values.
	const COLOR_ACCENT = '#00d4ff';
	const COLOR_GREEN = '#00e676';
	const COLOR_RED = '#ff4757';

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

		L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
			subdomains: 'abcd',
			maxZoom: 19,
		}).addTo(map);

		homeMarkerGroup = L.layerGroup().addTo(map);
		destLayerGroup = L.layerGroup().addTo(map);

		// Keep canvas sized to the map container
		syncCanvasSize();
		map.on('moveend', syncCanvasSize);
		map.on('zoomend', syncCanvasSize);
		map.on('resize', syncCanvasSize);
		window.addEventListener('resize', syncCanvasSize);

		// Start animation loop
		animFrameId = requestAnimationFrame(animationLoop);

		return () => {
			if (animFrameId !== null) {
				cancelAnimationFrame(animFrameId);
			}
			window.removeEventListener('resize', syncCanvasSize);
			if (map) {
				map.remove();
				map = null;
			}
		};
	});

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
			color: COLOR_GREEN,
			weight: 1,
			opacity: 0.15,
			fillColor: COLOR_GREEN,
			fillOpacity: 0.06,
			interactive: false,
		}).addTo(homeMarkerGroup);

		// Solid home dot
		const homeMarker = L.circleMarker([lat, lng], {
			radius: 7,
			color: COLOR_GREEN,
			weight: 2,
			opacity: 0.9,
			fillColor: COLOR_GREEN,
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
			if (!dest.lat || !dest.lon) continue;

			const isAlert = _alerts.has(dest.country_code);
			const isActive = _active === dest.country_code;
			const color = isAlert ? COLOR_RED : COLOR_ACCENT;
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

	function animationLoop() {
		animFrameId = requestAnimationFrame(animationLoop);

		if (paused || !map || !canvasEl || !homeLocation) return;

		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;

		const dpr = window.devicePixelRatio || 1;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, canvasEl.width / dpr, canvasEl.height / dpr);

		const homePixel = map.latLngToContainerPoint([homeLocation.lat, homeLocation.lng]);

		arcPhase = (arcPhase + 0.003) % 1;

		for (let i = 0; i < destinations.length; i++) {
			const dest = destinations[i];
			if (!dest.lat || !dest.lon) continue;

			const destPixel = map.latLngToContainerPoint([dest.lat, dest.lon]);
			const isAlert = hasAlertCountries.has(dest.country_code);
			const color = isAlert ? COLOR_RED : COLOR_ACCENT;

			// Quadratic bezier control point — arcs upward
			const midX = (homePixel.x + destPixel.x) / 2;
			const minY = Math.min(homePixel.y, destPixel.y);
			const dx = destPixel.x - homePixel.x;
			const dy = destPixel.y - homePixel.y;
			const distance = Math.sqrt(dx * dx + dy * dy);
			const cpX = midX;
			const cpY = minY - 40 - distance * 0.12;

			// Draw dim static arc
			ctx.beginPath();
			ctx.moveTo(homePixel.x, homePixel.y);
			ctx.quadraticCurveTo(cpX, cpY, destPixel.x, destPixel.y);
			ctx.strokeStyle = color;
			ctx.globalAlpha = 0.12;
			ctx.lineWidth = 1;
			ctx.stroke();

			// Animated pulse dots — more pulses for higher connection counts
			const pulseCount = Math.min(1 + Math.floor(Math.sqrt(dest.count)), 3);

			for (let p = 0; p < pulseCount; p++) {
				const t = (arcPhase + i * 0.11 + p * (1 / pulseCount)) % 1;

				// Position along the quadratic bezier at parameter t
				const px = (1 - t) * (1 - t) * homePixel.x + 2 * (1 - t) * t * cpX + t * t * destPixel.x;
				const py = (1 - t) * (1 - t) * homePixel.y + 2 * (1 - t) * t * cpY + t * t * destPixel.y;

				// Outer glow
				ctx.beginPath();
				ctx.arc(px, py, 6, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.globalAlpha = 0.2;
				ctx.fill();

				// Solid dot
				ctx.beginPath();
				ctx.arc(px, py, 2.5, 0, Math.PI * 2);
				ctx.fillStyle = color;
				ctx.globalAlpha = 0.9;
				ctx.fill();
			}
		}

		// Reset alpha for next frame
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
	}

	.geo-map {
		width: 100%;
		height: 100%;
		background: var(--bg-void);
	}

	.arc-canvas {
		position: absolute;
		inset: 0;
		pointer-events: none;
		z-index: 450;
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
		background: rgba(0, 230, 118, 0.12);
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
