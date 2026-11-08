<!--
  Globe: the Live page's 3D globe. three.js WebGPU (WebGL 2 when WebGPU is missing) with TSL
  materials, loaded only when this mounts, so no other page downloads three. Packets fly between
  home and each place: one per poll's new connection, more for big ones (globe/engine.js).

  The engine is told about every prop change (ingest, setSelected, setHome, …). When the renderer
  can't start, or the land outlines can't load, it calls onfail once and the caller shows DotMap.
-->
<script lang="ts" module>
	/** What the pointer (or the destinations list, kind 'list') is over. */
	export interface GlobeHover {
		kind: 'city' | 'country' | 'list';
		key: string;
		code: string;
		city: string;
		country: string;
		count: number;
		bytes: number;
	}

	export interface GlobeHome {
		lat: number;
		lon: number;
		label: string;
	}
</script>

<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import type { GeoArc, LiveConnection } from '$lib/api/live';
	import { formatBytes } from '$lib/api/logs';
	import { loadLandMask } from './globe/land.js';

	let {
		arcs,
		fresh,
		home,
		selected = null,
		highlight = null,
		paused = false,
		reduced = false,
		expanded = false,
		onselect,
		onfail,
		onready,
		ariaLabel,
	}: {
		arcs: GeoArc[];
		/** Connections new since the last poll; each launches packets. */
		fresh: LiveConnection[];
		home: GlobeHome | null;
		selected?: string | null;
		/** A country lit from outside the canvas (the destinations list). */
		highlight?: string | null;
		paused?: boolean;
		reduced?: boolean;
		expanded?: boolean;
		onselect?: (code: string) => void;
		onfail?: (reason: string) => void;
		onready?: (backend: string) => void;
		ariaLabel: string;
	} = $props();

	type Engine = Awaited<ReturnType<typeof import('./globe/engine.js').mountGlobe>>;

	let canvas: HTMLCanvasElement;
	let homeEl: HTMLDivElement;
	let tipEl: HTMLDivElement;
	let engine = $state.raw<Engine | null>(null);
	let ready = $state(false);
	let hover = $state<GlobeHover | null>(null);
	/** The country last picked on the canvas: picking it there doesn't fly the camera to it. */
	let pickedHere: string | null = null;

	onMount(() => {
		let gone = false;
		let mounted: Engine | null = null;
		const fail = (err: unknown) => {
			if (gone) return;
			gone = true;
			console.warn('NetTap globe: the renderer could not start, showing the flat map instead.', err);
			try {
				mounted?.destroy();
			} catch {
				// already torn down
			}
			engine = null;
			onfail?.(err instanceof Error ? err.message : String(err));
		};
		(async () => {
			try {
				const [{ mountGlobe }, mask] = await Promise.all([import('./globe/engine.js'), loadLandMask()]);
				if (gone) return;
				mounted = mountGlobe(canvas, {
					mask,
					home,
					paused,
					reduced,
					expanded,
					themeFrom: canvas.parentElement,
					homeLabelEl: homeEl,
					tooltipEl: tipEl,
					onHover: (info: GlobeHover | null) => {
						hover = info;
					},
					onSelect: (code: string) => {
						pickedHere = code;
						onselect?.(code);
					},
					onStatus: (st: { ready?: boolean; failed?: boolean; backend?: string; error?: string }) => {
						if (st.failed) return fail(new Error(st.error ?? 'renderer failed'));
						ready = true;
						onready?.(st.backend ?? '');
					},
				});
				engine = mounted;
			} catch (err) {
				fail(err);
			}
		})();
		return () => {
			gone = true;
			mounted?.destroy();
			engine = null;
		};
	});

	// The first snapshot primes the sky with packets already in flight
	let primed = false;
	$effect(() => {
		const snapshot = { geo_arcs: arcs, fresh };
		if (!engine) return;
		const target = engine;
		// The engine reads every row; only a new snapshot should re-run this
		untrack(() => target.ingest(snapshot, { prime: !primed }));
		primed = true;
	});
	$effect(() => {
		const code = selected ?? null;
		engine?.setSelected(code, { fly: code !== null && code !== pickedHere });
		pickedHere = null;
	});
	$effect(() => engine?.setHome(home));
	$effect(() => engine?.setPaused(paused));
	$effect(() => engine?.setReduced(reduced));
	$effect(() => engine?.setExpanded(expanded));
	$effect(() => engine?.highlight(highlight ?? null));

	let tip = $derived(
		hover && hover.kind !== 'list'
			? {
					title: hover.kind === 'city' && hover.city && hover.city !== hover.country ? `${hover.city}, ${hover.country}` : hover.country,
					line: `${hover.count.toLocaleString('en-GB')} connection${hover.count === 1 ? '' : 's'} · ${formatBytes(hover.bytes)}`,
				}
			: null,
	);
</script>

<div class="globe" role="img" aria-label={ariaLabel}>
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
	<div class="globe-home" bind:this={homeEl} aria-hidden="true">
		{#if home}<span class="globe-home-tag">Your network{#if home.label}<span>{home.label}</span>{/if}</span>{/if}
	</div>
	<div class="globe-tip" bind:this={tipEl} hidden={!tip} aria-hidden="true">
		{#if tip}<span class="globe-tip-pill"><b>{tip.title}</b><span>{tip.line}</span></span>{/if}
	</div>
	{#if !ready}
		<div class="globe-loading" role="status"><div class="skel"></div><p>Loading the globe…</p></div>
	{/if}
</div>

<style>
	.globe { position: absolute; inset: 0; }
	canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }

	.globe-loading { position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: var(--sp-4); pointer-events: none; }
	.globe-loading .skel { width: min(58%, 300px); aspect-ratio: 1; border-radius: 50%; }
	.globe-loading p { margin: 0; color: var(--text-3); font-size: var(--text-xs); }

	/* Tooltip: the system's light pill, held above the pointer (the engine moves .globe-tip) */
	.globe-tip { position: absolute; left: 0; top: 0; z-index: 3; pointer-events: none; }
	.globe-tip[hidden] { display: none; }
	.globe-tip-pill {
		display: inline-flex; flex-direction: column; gap: var(--sp-1); transform: translate(-50%, calc(-100% - var(--sp-3)));
		padding: var(--sp-2) var(--sp-3); border-radius: var(--r-md); white-space: nowrap;
		background: var(--pill-active-bg); color: var(--on-light); font-size: var(--text-xs); line-height: 1.3;
	}
	.globe-tip-pill b { font-weight: 700; font-size: var(--text-sm); }
	.globe-tip-pill span { font-variant-numeric: tabular-nums; }

	/* "Your network" beside the home ring (the engine places it and fades it on the far side) */
	.globe-home { position: absolute; left: 0; top: 0; z-index: 2; pointer-events: none; opacity: 0; transition: opacity var(--dur-fast); }
	.globe-home-tag {
		display: inline-flex; flex-direction: column; transform: translate(var(--sp-4), -50%);
		font-size: var(--text-micro); font-weight: 700; color: var(--text-1); line-height: 1.25; white-space: nowrap;
		text-shadow: 0 0 6px var(--bg), 0 0 2px var(--bg);
	}
	.globe-home-tag span { color: var(--text-3); font-weight: 500; }

	@media (prefers-reduced-motion: reduce) {
		.globe-home { transition: none; }
	}
</style>
