<!--
  LiveGlobeCard: the Live page's "Where your traffic goes" card, full width. The 3D globe (Globe)
  with packets flying between your network and each place, or the flat DotMap when this browser
  picked it in Settings › Display or can't start WebGPU / WebGL 2. Beside it, the busiest
  destinations as buttons: the keyboard and screen-reader path to the same country filter.

  Expand turns the card into a full-window dialog with the live figures and the newest rows; the
  rest of the page is made inert while it is open (inertOthers), and Esc or Close shrinks it back.
-->
<script lang="ts" module>
	import type { GeoArc } from '$lib/api/live';

	export interface Destination {
		code: string;
		name: string;
		count: number;
		bytes: number;
		cities: string[];
	}

	/** geo_arcs merged per country, busiest first. */
	export function destinationsOf(arcs: GeoArc[]): Destination[] {
		const byCode = new Map<string, Destination>();
		for (const a of arcs) {
			const prev = byCode.get(a.country_code);
			const city = a.city && a.city !== a.country ? [a.city] : [];
			byCode.set(
				a.country_code,
				prev
					? { ...prev, count: prev.count + a.count, bytes: prev.bytes + a.bytes, cities: [...prev.cities, ...city] }
					: { code: a.country_code, name: a.country || a.country_code, count: a.count, bytes: a.bytes, cities: city },
			);
		}
		return [...byCode.values()].sort((a, b) => b.count - a.count);
	}

	/**
	 * Make every element outside `el` inert: the siblings of `el` and of each of its ancestors up to
	 * <body>. Returns the undo, which clears only what this call set.
	 */
	export function inertOthers(el: Element): () => void {
		const changed: Element[] = [];
		for (let node: Element | null = el; node && node !== document.body; node = node.parentElement) {
			for (const sibling of node.parentElement?.children ?? []) {
				if (sibling !== node && !sibling.hasAttribute('inert')) {
					sibling.setAttribute('inert', '');
					changed.push(sibling);
				}
			}
		}
		return () => changed.forEach((s) => s.removeAttribute('inert'));
	}
</script>

<script lang="ts">
	import { onMount, tick } from 'svelte';
	import type { LiveConnection } from '$lib/api/live';
	import { directionLabel } from '$lib/api/live';
	import type { HomeLocation } from '$lib/api/home-location';
	import { formatBytes } from '$lib/api/logs';
	import { savedLiveMap } from '$lib/utils/drilldown';
	import { prefersReducedMotion } from '$lib/utils/tokens';
	import { formatTime } from '$lib/utils/time';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import DotMap, { type Hotspot } from '$lib/components/ui/charts/DotMap.svelte';
	import Globe from '$lib/components/ui/charts/Globe.svelte';
	import type { Stat } from '$lib/components/ui/StatStrip.svelte';

	let {
		arcs,
		fresh,
		rows,
		stats,
		home,
		homeState = 'ok',
		loaded,
		error = '',
		selected = null,
		paused = false,
		onselect,
		onretry,
	}: {
		arcs: GeoArc[];
		/** Rows new since the last poll: each launches packets. */
		fresh: LiveConnection[];
		/** The newest rows, for the expanded view's feed. */
		rows: (LiveConnection & { key: string })[];
		stats: Stat[];
		home: HomeLocation | null;
		/** Whether `home` has been read: 'failed' says so (never a made-up home); 'loading' says nothing yet. */
		homeState?: 'loading' | 'ok' | 'failed';
		/** A dashboard has loaded at least once. */
		loaded: boolean;
		error?: string;
		selected?: string | null;
		paused?: boolean;
		onselect: (code: string) => void;
		onretry: () => void;
	} = $props();

	const LIST = 9;
	const FEED = 14;
	const uid = $props.id();

	/** null until mounted: the choice lives in this browser's storage. */
	let mode = $state<'globe' | 'flat' | null>(null);
	let fellBack = $state(false);
	let backend = $state('');
	let reduced = $state(false);
	let expanded = $state(false);
	let hoverCode = $state<string | null>(null);
	let card: HTMLElement;
	let toggle: HTMLButtonElement;

	onMount(() => {
		mode = savedLiveMap();
		reduced = prefersReducedMotion();
	});

	let flat = $derived(mode === 'flat' || fellBack);
	let dests = $derived(destinationsOf(arcs));
	let shown = $derived(dests.slice(0, LIST));
	let maxCount = $derived(Math.max(1, ...shown.map((d) => d.count)));
	let hotspots = $derived<Hotspot[]>(arcs.map((a) => ({ country: a.country || a.country_code, code: a.country_code, lat: a.lat, lng: a.lon, count: a.count })));
	let feed = $derived(rows.filter((r) => r.direction !== 'local').slice(0, FEED));

	// OLD CODE: let sub = $derived(home ? 'Packets between your network and each destination · last 5 minutes' : 'Connections by destination · last 5 minutes'); (NET-237)
	let sub = $derived(home ? 'Packets between your network and each destination · connections that ended in the last 5 minutes' : 'Connections by destination · ended in the last 5 minutes');
	let ariaLabel = $derived(
		dests.length
			? `Connections from your network to ${dests.length} countries, most to ${dests[0].name}. Choose a country in the list to filter the feed.`
			: 'Where your traffic goes: no destinations yet',
	);
	let rendererNote = $derived(flat ? 'Flat map' : backend ? `Drawn with ${backend}` : '');

	function fail() {
		fellBack = true;
	}

	// Expanded: a modal over the whole window
	$effect(() => {
		if (!expanded || !card) return;
		const undo = inertOthers(card);
		const root = document.documentElement;
		const overflow = root.style.overflow;
		root.style.overflow = 'hidden';
		return () => {
			undo();
			root.style.overflow = overflow;
		};
	});

	async function setExpanded(next: boolean) {
		expanded = next;
		await tick();
		toggle?.focus();
	}

	const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

	function onkeydown(e: KeyboardEvent) {
		if (!expanded) return;
		if (e.key === 'Escape') {
			e.stopPropagation();
			void setExpanded(false);
		} else if (e.key === 'Tab') {
			// Wrap inside the dialog; read the list now, since rows come and go (and a narrow window hides the side list)
			const items = [...card.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.checkVisibility?.() ?? true);
			const first = items[0];
			const last = items[items.length - 1];
			if (e.shiftKey && document.activeElement === first) {
				e.preventDefault();
				last?.focus();
			} else if (!e.shiftKey && document.activeElement === last) {
				e.preventDefault();
				first?.focus();
			}
		}
	}

	function where(c: LiveConnection): string {
		const inbound = c.direction === 'in';
		const place = [c.dest_city, c.country_name || c.country].filter(Boolean).join(', ');
		return `${inbound ? 'In from' : 'Out to'} ${place || 'an unknown place'}`;
	}
</script>

<!-- On the window, not the card: a drag on the globe leaves focus on <body>, and Esc must still close -->
<svelte:window {onkeydown} />

<article
	bind:this={card}
	class={['card', 'hero', 'c-12', 'globe-card', expanded && 'is-expanded']}
	role={expanded ? 'dialog' : undefined}
	aria-modal={expanded ? 'true' : undefined}
	aria-labelledby="{uid}-title"
	data-backend={flat ? 'flat' : backend || undefined}
>
	<div class="card-head">
		<div>
			<h2 class="card-title" id="{uid}-title">Where your traffic goes</h2>
			<p class="card-sub">{sub}</p>
		</div>
		<button class="btn" type="button" bind:this={toggle} aria-expanded={expanded} onclick={() => setExpanded(!expanded)} disabled={!loaded}>
			{#if expanded}<Icon name="close" />Close{:else}Expand{/if}
		</button>
	</div>

	{#if expanded && stats.length}
		<div class="globe-stats" role="group" aria-label="Right now">
			{#each stats as s (s.key)}<div><span class="stat-k">{s.label}</span><p class="stat-v">{s.value}</p></div>{/each}
		</div>
	{/if}

	{#if !loaded && error}
		<CardState state="error" title={error} message="Check that NetTap is running on the System page, then try again." onaction={onretry} />
	{:else if !loaded}
		<CardState state="loading" title="Loading the globe" />
	{:else}
		<div class="globe-body">
			{#if expanded}
				<section class="globe-feed" aria-label="Newest connections">
					<!-- OLD CODE: <span class="eyebrow">Newest connections</span> (NET-237: listed by when they ended) -->
					<span class="eyebrow">Newest connections · by end time</span>
					<ul class="feed-rows">
						{#each feed as r (r.key)}
							<li class="feed-row">
								<!-- OLD CODE: <span class="mono">{formatTime(r.timestamp, 'clock')}</span> (NET-237: the start of a connection that just ended) -->
								<span class="mono" title="Ended">{r.ended_at ? formatTime(r.ended_at, 'clock') : '—'}</span>
								<span class="feed-what"><b>{r.device_name || (r.direction === 'in' ? r.dest_ip : r.source_ip)}</b><span>{where(r)}</span></span>
								<span class="feed-v">{formatBytes(r.bytes)}{#if r.has_alert}<span class="feed-alert">Alert</span>{/if}</span>
							</li>
						{:else}
							<!-- OLD CODE: <li class="dim">No connections to or from the internet right now.</li> (NET-237) -->
							<li class="dim">No connections to or from the internet ended in the last 5 minutes.</li>
						{/each}
					</ul>
				</section>
			{/if}

			<div class={['globe-stage', paused && 'is-paused', flat && 'is-flat']}>
				{#if mode === null}
					<div class="globe-loading" role="status"><div class="skel"></div><p>Loading the globe…</p></div>
				{:else if flat}
					<DotMap
						{hotspots}
						home={home ? { lat: home.lat, lng: home.lon } : null}
						selected={selected ?? undefined}
						{onselect}
						{ariaLabel}
					/>
				{:else}
					<Globe
						{arcs}
						{fresh}
						{home}
						{selected}
						highlight={shown.some((d) => d.code === hoverCode) ? hoverCode : null}
						{paused}
						{reduced}
						{expanded}
						{onselect}
						onfail={fail}
						onready={(b) => (backend = b)}
						{ariaLabel}
					/>
				{/if}

				{#if homeState === 'failed'}
					<p class="notice is-warn globe-notice" role="status"><Icon name="warn" /><span>Couldn't load your network's location, so the globe shows destinations only.</span></p>
				{:else if homeState === 'ok' && !home}
					<p class="notice globe-notice"><Icon name="home" /><span>Your network's location isn't set, so the globe shows destinations only. Set it in <a class="link" href="/settings?tab=network">Settings › Network</a>.</span></p>
				{:else if fellBack}
					<p class="notice globe-notice" role="status"><Icon name="warn" /><span>This browser can't draw the 3D globe, so the flat map is shown.</span></p>
				{/if}

				{#if !flat && mode !== null}
					<ul class="legend globe-legend" aria-label="Legend">
						{#if home}
							<li><span class="sw out"></span>Outbound</li>
							<li><span class="sw in"></span>Inbound</li>
						{:else}
							<li><span class="sw out"></span>Destination</li>
						{/if}
						<li><span class="sw alert"></span>Alert</li>
						{#if home}<li><span class="sw home"></span>Your network</li>{/if}
					</ul>
					<p class="globe-hint">
						{#if expanded}Drag to turn · scroll to zoom · <kbd>Esc</kbd> closes{:else}Drag to turn · <kbd>Ctrl</kbd> or <kbd>⌘</kbd> + scroll to zoom{/if}
					</p>
				{/if}
			</div>

			<aside class="globe-side" aria-label="Top destinations">
				<div class="globe-side-head"><span class="eyebrow">Top destinations</span><span class="dim">{dests.length.toLocaleString('en-GB')} {dests.length === 1 ? 'country' : 'countries'}</span></div>
				{#if shown.length}
					<ul class="dest-list">
						{#each shown as d (d.code)}
							<li>
								<button
									class={['dest-btn', hoverCode === d.code && 'is-hover']}
									type="button"
									aria-pressed={selected === d.code}
									aria-label="Filter by {d.name}: {d.count.toLocaleString('en-GB')} connections, {formatBytes(d.bytes)}"
									onclick={() => onselect(d.code)}
									onmouseenter={() => (hoverCode = d.code)}
									onmouseleave={() => (hoverCode = null)}
									onfocus={() => (hoverCode = d.code)}
									onblur={() => (hoverCode = null)}
								>
									<span class="tag">{d.code}</span>
									<span class="dest-name"><b>{d.name}</b>{#if d.cities.length}<span>{d.cities.join(', ')}</span>{/if}</span>
									<span class="dest-v">{d.count.toLocaleString('en-GB')}<span class="mini" aria-hidden="true"><span style:--w="{Math.round((d.count / maxCount) * 100)}%"></span></span></span>
								</button>
							</li>
						{/each}
					</ul>
				{:else}
					<CardState state="empty" title="No destinations yet" message="Places appear here once your devices connect to the internet." />
				{/if}
				<div class="globe-side-foot">
					<span>{selected ? 'Choose the country again to clear the filter.' : 'Choose a country to filter the feed.'}</span>
					{#if rendererNote}<span class="tag">{rendererNote}</span>{/if}
				</div>
			</aside>
		</div>
	{/if}
</article>

<style>
	.globe-card { display: flex; flex-direction: column; }
	.globe-card .card-head { margin-bottom: var(--sp-4); }
	.globe-card .card-head .btn { color: var(--text-1); }
	.globe-body { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: var(--sp-5); flex: 1; min-height: 0; }
	.globe-stage { position: relative; height: 640px; min-width: 0; border-radius: var(--r-md); overflow: hidden; }
	/* The flat map sizes itself from its width */
	.globe-stage.is-flat { height: auto; display: grid; align-content: center; min-height: 320px; }
	/* Pausing the page stops the flat map's flowing arcs too */
	.is-paused :global(.arc) { animation-play-state: paused; }

	.globe-loading { position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: var(--sp-4); }
	.globe-loading .skel { width: min(58%, 300px); aspect-ratio: 1; border-radius: 50%; }
	.globe-loading p { margin: 0; color: var(--text-3); font-size: var(--text-xs); }

	.globe-legend { position: absolute; left: var(--sp-4); bottom: var(--sp-4); z-index: 2; pointer-events: none; }
	.sw.out { --c: var(--accent-strong); }
	.sw.in { --c: var(--data-2); }
	.sw.alert { --c: var(--sev-critical); width: var(--sp-2); height: var(--sp-2); border-radius: 1px; transform: rotate(45deg); }
	.sw.home { background: none; box-shadow: inset 0 0 0 1.5px var(--text-1); width: 10px; height: 10px; }
	.globe-hint {
		position: absolute; right: var(--sp-4); bottom: var(--sp-4); z-index: 2; margin: 0; pointer-events: none;
		font-size: var(--text-xs); color: var(--text-3); text-align: right;
	}
	.globe-hint kbd { font: 500 var(--text-micro)/1 var(--font-mono); padding: 2px var(--sp-1); border-radius: var(--r-xs); background: var(--surface-3); color: var(--text-2); }
	.globe-notice {
		position: absolute; left: 50%; top: var(--sp-4); z-index: 2; transform: translateX(-50%);
		width: max-content; max-width: calc(100% - var(--sp-8)); margin: 0;
	}

	/* Destinations list: the keyboard and screen-reader path to the same filter */
	.globe-side { display: flex; flex-direction: column; gap: var(--sp-3); min-width: 0; min-height: 0; }
	.globe-side-head { display: flex; justify-content: space-between; align-items: baseline; gap: var(--sp-2); }
	.dest-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; min-height: 0; overflow-y: auto; }
	.dest-btn {
		display: grid; grid-template-columns: var(--sp-8) minmax(0, 1fr) auto; gap: var(--sp-3); align-items: center; width: 100%;
		padding: var(--sp-2); border: 0; border-radius: var(--r-md); background: none; color: var(--text-1); font: inherit; text-align: left;
		cursor: pointer; transition: background var(--dur-fast);
	}
	.dest-btn:hover, .dest-btn.is-hover { background: var(--row-hover); }
	.dest-btn[aria-pressed='true'] { background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--line-strong); }
	.dest-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.dest-btn .tag { justify-self: start; }
	.dest-name { display: flex; flex-direction: column; min-width: 0; }
	.dest-name b { font-weight: 700; font-size: var(--text-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.dest-name span { color: var(--text-3); font-size: var(--text-xs); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.dest-v { display: flex; flex-direction: column; align-items: flex-end; font-size: var(--text-sm); font-variant-numeric: tabular-nums; }
	.dest-v .mini { width: calc(var(--sp-8) * 2); margin-top: var(--sp-1); }
	.globe-side-foot {
		display: flex; align-items: center; gap: var(--sp-2); margin-top: auto; padding-top: var(--sp-3);
		border-top: 1px solid var(--line); font-size: var(--text-xs); color: var(--text-3);
	}
	.globe-side-foot .tag { margin-left: auto; flex: none; white-space: nowrap; }

	/* The newest rows: only in the expanded view */
	.globe-feed { display: flex; flex-direction: column; gap: var(--sp-3); min-height: 0; }
	.feed-rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; overflow: hidden; }
	.feed-row {
		display: grid; grid-template-columns: 58px minmax(0, 1fr) auto; gap: 2px var(--sp-3); align-items: center;
		padding: var(--sp-2); border-radius: var(--r-md); font-size: var(--text-xs);
	}
	.feed-row .mono { color: var(--text-3); }
	.feed-what { display: flex; flex-direction: column; min-width: 0; }
	.feed-what b { font-size: var(--text-sm); font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.feed-what span { color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.feed-v { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; font-variant-numeric: tabular-nums; }
	.feed-alert { display: inline-flex; align-items: center; gap: var(--sp-1); color: var(--sev-critical); font-weight: 700; }
	.feed-alert::before { content: ''; width: 7px; height: 7px; background: var(--sev-critical); transform: rotate(45deg); border-radius: 1px; }

	/* Expanded: the card takes the whole window */
	.globe-card.is-expanded { position: fixed; inset: 0; z-index: 40; border-radius: 0; border: 0; padding: var(--sp-5) var(--sp-6); }
	.globe-card.is-expanded .globe-body { grid-template-columns: 330px minmax(0, 1fr) 300px; }
	.globe-card.is-expanded .globe-stage:not(.is-flat) { height: auto; }
	.globe-stats { display: flex; gap: var(--sp-6); flex-wrap: wrap; margin-bottom: var(--sp-4); }
	.globe-stats div { display: flex; flex-direction: column; }
	.globe-stats .stat-k { white-space: nowrap; }
	.globe-stats .stat-v { font-size: var(--text-lg); margin: 0; }

	@container app (max-width: 1100px) {
		.globe-body { grid-template-columns: minmax(0, 1fr) 260px; }
		.globe-stage:not(.is-flat) { height: 520px; }
		.globe-card.is-expanded .globe-body { grid-template-columns: minmax(0, 1fr) 280px; }
		.globe-card.is-expanded .globe-feed { display: none; }
	}

	@container app (max-width: 760px) {
		.globe-body { grid-template-columns: minmax(0, 1fr); gap: var(--sp-4); }
		.globe-stage:not(.is-flat) { height: 380px; }
		.globe-hint { display: none; }
		.dest-list > li:nth-child(n + 6) { display: none; }
		.globe-card.is-expanded { padding: var(--sp-4); }
		.globe-card.is-expanded .globe-body { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) auto; }
		.globe-card.is-expanded .globe-side { display: none; }
		.globe-card.is-expanded .globe-feed { display: flex; order: 2; max-height: 32vh; }
		.globe-card.is-expanded .feed-rows > li:nth-child(n + 4) { display: none; }
		.globe-stats { gap: var(--sp-4); }
	}
</style>
