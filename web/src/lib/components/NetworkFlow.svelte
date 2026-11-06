<!--
  NetworkFlow: data from the busiest devices, through their protocols, to their destinations
  (replaces SankeyDiagram, NET-151). All three columns share one scale; ribbons are coloured
  by protocol only; everything outside the top destinations is one "Other destinations" node.
  A device shows its name when NetTap knows one, else its IP.

  The component picks one view by its own width: the chart from FLOW_MIN_WIDTH up, else a
  table (also used when the endpoint's two searches don't add up, so no figure is adjusted).
  Labels are HTML buttons placed by flowLayout from their measured height, so they never
  overlap, even with larger text. The SVG under them is decoration (aria-hidden).
-->
<script lang="ts">
	import type { SankeyLink, SankeyNode } from '$api/traffic';
	import { formatBytes } from '$api/logs';
	import { observeWidth } from './ui/charts/resize';
	import NetworkFlowTable from './NetworkFlowTable.svelte';
	import {
		flowData,
		flowLayout,
		nodeKey,
		share,
		splitText,
		DEFAULT_SIZES,
		FLOW_MIN_WIDTH,
		type FlowEntry,
		type FlowKind,
		type PlacedNode,
		type PlacedRibbon,
	} from './ui/charts/flow';

	let {
		sources,
		protocols,
		destinations,
		links,
		names = new Map(),
		selected = null,
		onNodeClick,
	}: {
		sources: SankeyNode[];
		protocols: SankeyNode[];
		destinations: SankeyNode[];
		links: SankeyLink[];
		/** IP → device name, for devices NetTap knows a name for. */
		names?: Map<string, string>;
		/** The node filtering the sessions table, shown pressed. */
		selected?: { type: string; id: string } | null;
		onNodeClick?: (kind: FlowKind, id: string) => void;
	} = $props();

	let width = $state(0);
	let labelH = $state(0);
	let hover = $state<{ kind: 'node' | 'ribbon'; key: string } | null>(null);

	const data = $derived(flowData({ sources, protocols, destinations, links }));
	const layout = $derived(
		width >= FLOW_MIN_WIDTH && data.consistent && data.protocols.length > 0
			? flowLayout(data, width, labelH > 0 ? { labelH, chipH: labelH * 1.5 } : DEFAULT_SIZES)
			: null,
	);
	const hasOther = $derived(data.destinations.some((d) => d.other));
	const shown = $derived(data.destinations.filter((d) => !d.other).length);

	const isPressed = (kind: FlowKind, id: string) => selected?.type === kind && selected.id === id;
	const nameOf = (n: FlowEntry) => (n.kind === 'source' ? (names.get(n.id) ?? n.id) : n.label);

	const headline = $derived.by(() => {
		const total = data.protocols.reduce((a, p) => a + p.value, 0);
		const top = data.protocols[0];
		const dest = data.destinations.find((d) => !d.other);
		return [
			`Network flow: ${formatBytes(total)} from ${data.sources.length} ${data.sources.length === 1 ? 'device' : 'devices'}.`,
			top ? `${top.label} carries ${share(top.value, total)}.` : '',
			dest ? `${dest.label} is the largest destination at ${share(dest.value, total)}.` : '',
		]
			.filter(Boolean)
			.join(' ');
	});

	function ariaFor(n: FlowEntry): string {
		const who = n.kind === 'source' && names.has(n.id) ? `${names.get(n.id)} (${n.id})` : nameOf(n);
		const split = n.kind === 'protocol' ? '' : ` ${splitText(n, data.protocols)}.`;
		const action = n.kind === 'source' ? 'Opens the device.' : 'Filters the sessions below.';
		return `${who}, ${formatBytes(n.value)}, ${share(n.value, layout?.total ?? 0)} of the flow.${split} ${action}`;
	}

	// Focus: what the pointer or keyboard is on, else the node filtering the table. A focus no
	// ribbon touches (a filter on a destination that left the top 10) lights nothing, so it is dropped.
	type Focus = { kind: 'node' | 'ribbon'; key: string };
	const touches = (f: Focus, r: PlacedRibbon) => (f.kind === 'ribbon' ? r.key === f.key : r.from === f.key || r.to === f.key);
	const focus = $derived.by((): Focus | null => {
		const f: Focus | null = hover ?? (selected ? { kind: 'node', key: nodeKey(selected.type as FlowKind, selected.id) } : null);
		return f && layout?.ribbons.some((r) => touches(f, r)) ? f : null;
	});
	const isLit = (r: PlacedRibbon) => !!focus && touches(focus, r);
	const litNodes = $derived.by(() => {
		if (!focus || !layout) return null;
		const keys = layout.ribbons.filter(isLit).flatMap((r) => [r.from, r.to]);
		return new Set(focus.kind === 'node' ? [...keys, focus.key] : keys);
	});
	const dimmed = (key: string) => !!litNodes && !litNodes.has(key);

	const tip = $derived.by(() => {
		const h = hover;
		if (!h || !layout) return null;
		const all = [...layout.sources, ...layout.protocols, ...layout.destinations];
		const byKey = new Map(all.map((n) => [n.key, n]));
		if (h.kind === 'ribbon') {
			const r = layout.ribbons.find((x) => x.key === h.key);
			const from = r && byKey.get(r.from);
			const to = r && byKey.get(r.to);
			if (!r || !from || !to) return null;
			return {
				x: r.mx,
				y: r.my,
				place: r.my < 48 ? 'below' : 'above',
				title: `${nameOf(from)} → ${nameOf(to)}`,
				detail: `${formatBytes(r.value)} · ${share(r.value, from.value)} of ${nameOf(from)}`,
			};
		}
		const n = byKey.get(h.key);
		if (!n) return null;
		const title =
			n.kind === 'source' && names.has(n.id) ? `${nameOf(n)} · ${n.id}` : n.country ? `${n.label} · ${n.country}` : nameOf(n);
		const detail = [formatBytes(n.value), `${share(n.value, layout.total)} of the flow`, n.kind === 'protocol' ? '' : splitText(n, data.protocols)]
			.filter(Boolean)
			.join(' · ');
		const cy = n.y + n.h / 2;
		return n.kind === 'source'
			? { x: n.x + n.w + 12, y: cy, place: 'right', title, detail }
			: { x: n.x - 12, y: cy, place: 'left', title, detail };
	});

	const enter = (key: string) => () => (hover = { kind: 'node', key });
	const leave = () => (hover = null);

	function onRibbonOver(event: PointerEvent) {
		const key = (event.target as Element).getAttribute('data-ribbon');
		if (key) hover = { kind: 'ribbon', key };
	}

	const barClass = (n: PlacedNode) => (n.kind === 'protocol' ? `c-d${n.colour}` : n.other ? 'other' : 'neutral');
	const f = (v: number) => v.toFixed(1);
</script>

<div class="flow" {@attach observeWidth((w) => (width = w))}>
	<!-- A hidden label row, measured so the layout spaces labels by their real height (larger text included) -->
	<span class="lab probe" aria-hidden="true" {@attach observeWidth((_, h) => (labelH = h))}>Ag</span>

	{#if layout}
		<div class="flow-chart">
			<div class="cols" aria-hidden="true">
				<span class="eyebrow">Sources · {data.sources.length} {data.sources.length === 1 ? 'device' : 'devices'}</span>
				<span class="eyebrow" style:left="{width / 2}px" style:translate="-50% 0">Protocols</span>
				<span class="eyebrow" style:left="{layout.dstLabelX}px" style:max-width="{layout.dstLabelW}px">Destinations · top {shown}{hasOther ? ' and other' : ''}</span>
			</div>
			<div class="plot" role="group" aria-label={headline} style:height="{layout.height}px" onpointerleave={leave}>
				<svg width={layout.width} height={layout.height} viewBox="0 0 {layout.width} {layout.height}" aria-hidden="true" onpointerover={onRibbonOver}>
					{#each layout.ribbons as r (r.key)}
						<path class="rib c-d{r.colour}" class:lit={isLit(r)} class:dim={!!focus && !isLit(r)} d={r.d} data-ribbon={r.key} />
					{/each}
					{#each [layout.sources, layout.protocols, layout.destinations] as column, c (c)}
						{#each column as n (n.key)}
							{@const h = Math.max(1, n.h)}
							<rect class="bar {barClass(n)}" class:faded={dimmed(n.key)} x={f(n.x)} y={f(n.y + n.h / 2 - h / 2)} width={n.w} height={f(h)} rx="3" />
						{/each}
					{/each}
					{#each layout.sources.filter((n) => n.moved) as n (n.key)}
						<line class="conn" x1={f(layout.srcLabelW + 2)} y1={f(n.labelY)} x2={f(n.x - 2)} y2={f(n.y + n.h / 2)} />
					{/each}
					{#each layout.protocols.filter((n) => n.moved) as n (n.key)}
						<line class="conn" x1={f(n.x + n.w + 2)} y1={f(n.y + n.h / 2)} x2={f(layout.chipX - 2)} y2={f(n.labelY)} />
					{/each}
					{#each layout.destinations.filter((n) => n.moved) as n (n.key)}
						<line class="conn" x1={f(n.x + n.w + 2)} y1={f(n.y + n.h / 2)} x2={f(layout.dstLabelX - 2)} y2={f(n.labelY)} />
					{/each}
				</svg>

				{#each layout.sources as n (n.key)}
					<button
						type="button"
						class="lab src"
						class:faded={dimmed(n.key)}
						style:top="{n.labelY}px"
						style:width="{layout.srcLabelW}px"
						aria-label={ariaFor(n)}
						onpointerenter={enter(n.key)}
						onfocus={enter(n.key)}
						onblur={leave}
						onclick={() => onNodeClick?.('source', n.id)}
					>
						<span class="who">
							{#if names.has(n.id)}
								<span class="name">{names.get(n.id)}</span><span class="ip mono">{n.id}</span>
							{:else}
								<span class="name mono">{n.id}</span>
							{/if}
						</span>
						<span class="val">{formatBytes(n.value)}</span>
					</button>
				{/each}

				{#each layout.protocols as n (n.key)}
					<button
						type="button"
						class="lab chip c-d{n.colour}"
						class:faded={dimmed(n.key)}
						style:top="{n.labelY}px"
						style:left="{layout.chipX}px"
						style:max-width="{layout.chipMaxW}px"
						aria-label={ariaFor(n)}
						aria-pressed={isPressed('protocol', n.id)}
						onpointerenter={enter(n.key)}
						onfocus={enter(n.key)}
						onblur={leave}
						onclick={() => onNodeClick?.('protocol', n.id)}
					>
						<span class="sw"></span><span class="mono">{n.label}</span><span class="val">{formatBytes(n.value)} · {share(n.value, layout.total)}</span>
					</button>
				{/each}

				{#each layout.destinations as n (n.key)}
					{#if n.other}
						<span
							class="lab dst other"
							class:faded={dimmed(n.key)}
							style:top="{n.labelY}px"
							style:left="{layout.dstLabelX}px"
							style:width="{layout.dstLabelW}px"
							role="presentation"
							onpointerenter={enter(n.key)}
						>
							<span class="name">{n.label}</span><span class="val">{formatBytes(n.value)}</span><span class="pct">{share(n.value, layout.total)}</span>
						</span>
					{:else}
						<button
							type="button"
							class="lab dst"
							class:faded={dimmed(n.key)}
							style:top="{n.labelY}px"
							style:left="{layout.dstLabelX}px"
							style:width="{layout.dstLabelW}px"
							aria-label={ariaFor(n)}
							aria-pressed={isPressed('destination', n.id)}
							onpointerenter={enter(n.key)}
							onfocus={enter(n.key)}
							onblur={leave}
							onclick={() => onNodeClick?.('destination', n.id)}
						>
							<span class="name">{n.label}</span><span class="val">{formatBytes(n.value)}</span><span class="pct">{share(n.value, layout.total)}</span>
						</button>
					{/if}
				{/each}

				{#if tip}
					<div class="tip {tip.place}" style:left="{tip.x}px" style:top="{tip.y}px" aria-hidden="true">
						<b>{tip.title}</b>
						<span>{tip.detail}</span>
					</div>
				{/if}
			</div>
			<p class="note">Band width is data volume.{hasOther ? ' Other destinations is everything these devices reached outside the top 10.' : ''}</p>
		</div>
	{:else}
		<div class="flow-table-wrap">
			{#if !data.consistent}
				<p class="note">
					These figures come from two searches a few milliseconds apart, so they don't add up exactly. The chart returns on the
					next refresh.
				</p>
			{/if}
			<NetworkFlowTable {data} {names} {isPressed} {onNodeClick} />
			{#if hasOther}
				<p class="note">Other destinations is everything these devices reached outside the top 10.</p>
			{/if}
		</div>
	{/if}
</div>

<style>
	.flow {
		position: relative;
		min-width: 0;
	}
	.flow-chart,
	.flow-table-wrap {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
	}
	.cols {
		position: relative;
		height: var(--sp-4);
	}
	.cols .eyebrow {
		position: absolute;
		top: 0;
		left: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.plot {
		position: relative;
	}
	.plot svg {
		position: absolute;
		inset: 0;
		overflow: visible;
	}

	/* Ribbons and bars: colour is the protocol; source and destination bars stay neutral */
	.rib {
		fill: var(--c);
		opacity: 0.3;
		transition: opacity var(--dur-fast);
	}
	.rib.lit {
		opacity: 0.7;
	}
	.rib.dim {
		opacity: 0.06;
	}
	.bar {
		fill: var(--c);
		transition: opacity var(--dur-fast);
	}
	.bar.neutral {
		fill: var(--text-2);
	}
	.bar.other {
		fill: var(--text-3);
	}
	.conn {
		stroke: var(--line-strong);
		stroke-width: 1;
	}
	.faded {
		opacity: 0.28;
	}

	/* Labels: one row tall, measured by the probe; 1.3334em is 16 px at the default text size */
	.lab {
		position: absolute;
		translate: 0 -50%;
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		box-sizing: border-box;
		height: 1.3334em;
		padding: 0;
		border: 0;
		background: none;
		color: var(--text-1);
		font-family: var(--font-body);
		font-size: var(--text-xs);
		line-height: 1.3334;
		white-space: nowrap;
		cursor: pointer;
		transition: opacity var(--dur-fast);
	}
	.lab.probe {
		visibility: hidden;
		pointer-events: none;
		top: 0;
		translate: none;
	}
	.lab:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
		border-radius: var(--r-xs);
	}
	.lab .val,
	.lab .pct {
		flex: none;
		color: var(--text-2);
		font-variant-numeric: tabular-nums;
	}
	.lab .pct {
		width: 3.2em;
		text-align: right;
		color: var(--text-3);
	}
	.lab .name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		font-weight: 600;
	}

	.src {
		left: 0;
		justify-content: space-between;
	}
	/* The name wins: when name and IP don't both fit, the IP wraps onto a hidden second line
	   (it is still in the tooltip and the button's name) */
	.src .who {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		column-gap: var(--sp-2);
		height: 1.3334em;
		min-width: 0;
		overflow: hidden;
	}
	.src .name {
		max-width: 100%;
	}
	.src .name.mono {
		font-weight: 400;
	}
	.src .ip {
		flex: none;
		font-size: var(--text-micro);
		color: var(--text-3);
	}
	.src .val {
		color: var(--text-3);
	}

	.dst {
		container-type: inline-size;
	}
	.dst .name {
		flex: 1;
		text-align: left;
	}
	/* A narrow label keeps the name and the figure; the share is in the tooltip */
	@container (width < 13rem) {
		.dst .pct {
			display: none;
		}
	}
	.dst.other {
		cursor: default;
	}
	.dst.other .name {
		color: var(--text-3);
	}
	.lab[aria-pressed='true'] .name,
	.lab[aria-pressed='true'] .mono {
		color: var(--accent-strong);
	}

	/* Protocol chip: 2em tall, so 1.5 label rows at any text size */
	.chip {
		height: 2em;
		padding: 0 var(--sp-3);
		border: 1px solid var(--line);
		border-radius: var(--r-pill);
		background: var(--surface-2);
	}
	.chip[aria-pressed='true'] {
		border-color: var(--accent-strong);
	}
	.chip .sw {
		width: var(--sp-2);
		height: var(--sp-2);
		border-radius: 2px;
		background: var(--c);
	}
	.chip .sw,
	.chip .mono {
		flex: none;
	}
	.chip .mono {
		font-size: var(--text-micro);
		font-weight: 500;
	}
	.chip .val {
		flex: 0 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* Tooltip: the system's light pill */
	.tip {
		position: absolute;
		z-index: 2;
		display: flex;
		flex-direction: column;
		max-width: 45%;
		padding: var(--sp-2) var(--sp-3);
		border-radius: var(--r-md);
		background: var(--pill-active-bg);
		color: var(--on-light);
		font-size: var(--text-xs);
		line-height: 1.4;
		pointer-events: none;
		font-variant-numeric: tabular-nums;
	}
	.tip.right {
		translate: 0 -50%;
	}
	.tip.left {
		translate: -100% -50%;
	}
	.tip.above {
		translate: -50% calc(-100% - var(--sp-2));
	}
	.tip.below {
		translate: -50% var(--sp-2);
	}

	.note {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--text-3);
	}
</style>
