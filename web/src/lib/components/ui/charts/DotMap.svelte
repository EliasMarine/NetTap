<!--
  DotMap (PLAN.md §5.4 contract): a dot grid of land computed once on mount from the bundled
  countries file, a hotspot per destination country sized by its share of connections, and,
  only when a real home location is given, a "Your network" ring with accent arcs to the
  busiest destinations. The arcs flow with the system's .arc animation, which the system CSS
  stops under reduced motion (so arc-scheduler, built for GeoMap's canvas loop, isn't needed).
  If the countries file fails to load, the hotspots still draw on a blank background.

  With onselect, each hotspot is a focusable button (click, Enter, Space) inside a labelled
  group, and the selected one gets an accent-strong ring. Without it the map is one image.

  Feeding it from Live (live/+page.svelte) with the data it already fetches:
    hotspots = (dashboard?.geo_arcs ?? []).map((a) => ({
      country: a.country || a.country_code, code: a.country_code, lat: a.lat, lng: a.lon, count: a.count,
    }))
    selected = countryFilter ?? undefined   // a country code, as GeoMap's activeCountry is
    onselect = setCountryFilter             // receives code ?? country, as GeoMap's onclick(country_code) did
    home = null                             // DEFAULT_HOME is a made-up centre of the US (§5.4)
  geo_arcs holds one entry per city, so hotspots that share a code (or country) are merged
  here: counts add up and the busiest city places the dot.
-->
<script lang="ts" module>
	export interface Hotspot {
		country: string;
		/** ISO code; the identity passed to onselect and matched by `selected` when present. */
		code?: string;
		lat: number;
		lng: number;
		count: number;
		/** Map label text; the country when absent. */
		label?: string;
	}
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { polygonsOf, landDots, project, arcPath, mapLabels, LABEL_FLIP, type Point } from './geometry';
	import { observeWidth } from './resize';

	let {
		hotspots,
		home,
		selected,
		onselect,
		ariaLabel,
	}: {
		hotspots: Hotspot[];
		home: { lat: number; lng: number } | null;
		selected?: string;
		onselect?: (country: string) => void;
		ariaLabel: string;
	} = $props();

	const GEO_URL = '/geo/countries-110m.geojson';
	const FALLBACK_WIDTH = 900;
	const ARCS = 6;
	const LABELS = 5;
	const uid = $props.id();

	let measured = $state(0);
	let land = $state<Point[]>([]);

	onMount(() => {
		let mounted = true;
		fetch(GEO_URL)
			.then((res) => {
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				return res.json();
			})
			.then((geo: unknown) => {
				if (mounted) land = landDots(polygonsOf(geo));
			})
			.catch((err) => console.warn('Map: country outlines unavailable, showing hotspots only', err));
		return () => {
			mounted = false;
		};
	});

	const w = $derived(Math.round(measured) || FALLBACK_WIDTH);
	const h = $derived(Math.round(w * 0.44));
	const k = $derived(w / 900);

	type Spot = Hotspot & { key: string; top: number; x: number; y: number; r: number };

	const spots = $derived.by((): Spot[] => {
		const byKey = new Map<string, Hotspot & { key: string; top: number }>();
		for (const s of hotspots) {
			if (!Number.isFinite(s.lat) || !Number.isFinite(s.lng) || !(s.count > 0)) continue;
			const key = s.code || s.country;
			const prev = byKey.get(key);
			const place = !prev || s.count > prev.top ? { ...s, top: s.count } : prev;
			byKey.set(key, { ...place, key, count: (prev?.count ?? 0) + s.count });
		}
		const merged = [...byKey.values()].sort((a, b) => b.count - a.count);
		const total = merged.reduce((a, s) => a + s.count, 0);
		return merged.map((s) => {
			const [x, y] = project(s.lng, s.lat, w, h);
			return { ...s, x, y, r: (4 + 12 * Math.sqrt(s.count / total)) * k };
		});
	});
	const labelText = (s: Spot) => `${s.label ?? s.country} ${s.count.toLocaleString('en-GB')}`;
	// busiest first; a label that would overlap one already placed is left off (NET-192)
	const labelled = $derived(mapLabels(spots.map((s) => ({ ...s, text: labelText(s) })), w, LABELS));
	const homeAt = $derived(home && Number.isFinite(home.lat) && Number.isFinite(home.lng) ? project(home.lng, home.lat, w, h) : null);
	const dotR = $derived(Math.max(1, w / 560).toFixed(2));

	const name = (s: Spot) => `${s.country}, ${s.count.toLocaleString('en-GB')} ${s.count === 1 ? 'connection' : 'connections'}`;

	function onkeydown(e: KeyboardEvent, key: string) {
		if (e.key !== 'Enter' && e.key !== ' ') return;
		e.preventDefault(); // Space would scroll the page
		onselect?.(key);
	}
</script>

{#snippet spot(s: Spot, i: number)}
	{@const core = Math.max(2, s.r * 0.42)}
	<!-- the hover tooltip GeoMap had; only the busiest five carry a visible label -->
	<title>{name(s)}</title>
	<circle cx={s.x.toFixed(1)} cy={s.y.toFixed(1)} r={(s.r * 2.2).toFixed(1)} fill="url(#{uid}-hot)" />
	<circle class="hot-core" cx={s.x.toFixed(1)} cy={s.y.toFixed(1)} r={core.toFixed(1)} />
	{#if selected === s.key}
		<circle class="hot-sel" cx={s.x.toFixed(1)} cy={s.y.toFixed(1)} r={(core + 4).toFixed(1)} />
	{/if}
	<!-- OLD CODE: {#if i < LABELS} {@const left = s.x > w * 0.82} (NET-192: close countries' labels overlapped) -->
	{#if labelled[i]}
		{@const left = s.x > w * LABEL_FLIP}
		<text class="map-lbl" x={(left ? s.x - s.r - 6 : s.x + s.r + 6).toFixed(1)} y={(s.y + 4).toFixed(1)} text-anchor={left ? 'end' : 'start'}
			>{s.label ?? s.country} <tspan>{s.count.toLocaleString('en-GB')}</tspan></text
		>
	{/if}
{/snippet}

<div class="chart" {@attach observeWidth((v) => (measured = v))}>
	<svg viewBox="0 0 {w} {h}" width={w} height={h} role={onselect ? 'group' : 'img'} aria-label={ariaLabel}>
		<defs>
			<radialGradient id="{uid}-hot" class="g-hot"><stop offset="0" class="h0" /><stop offset="1" class="h1" /></radialGradient>
		</defs>
		<g class="land" aria-hidden="true">
			{#each land as [lng, lat], i (i)}
				{@const [x, y] = project(lng, lat, w, h)}
				<circle cx={x.toFixed(1)} cy={y.toFixed(1)} r={dotR} />
			{/each}
		</g>
		{#if homeAt}
			{#each spots.slice(0, ARCS) as s (s.key)}
				<path class="arc" d={arcPath(homeAt, [s.x, s.y])} />
			{/each}
		{/if}
		{#each spots as s, i (s.key)}
			{#if onselect}
				<g
					role="button"
					tabindex="0"
					aria-label={name(s)}
					aria-pressed={selected === s.key}
					onclick={() => onselect(s.key)}
					onkeydown={(e) => onkeydown(e, s.key)}
				>
					{@render spot(s, i)}
				</g>
			{:else}
				<g>{@render spot(s, i)}</g>
			{/if}
		{/each}
		{#if homeAt}
			{@const [hx, hy] = homeAt}
			<circle class="home-ring" cx={hx.toFixed(1)} cy={hy.toFixed(1)} r={(9 * Math.max(k, 0.6)).toFixed(1)} />
			<circle class="home-core" cx={hx.toFixed(1)} cy={hy.toFixed(1)} r="3" />
			<text class="map-lbl" x={hx.toFixed(1)} y={(hy - 14 * Math.max(k, 0.7)).toFixed(1)} text-anchor="middle">Your network</text>
		{/if}
	</svg>
</div>

<style>
	/* The system has no selected-hotspot style: PLAN.md §5.4 asks for an accent-strong ring */
	.hot-sel {
		fill: none;
		stroke: var(--accent-strong);
		stroke-width: 2;
	}
	g[role='button'] {
		cursor: pointer;
	}
</style>
