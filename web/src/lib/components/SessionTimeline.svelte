<!--
  SessionTimeline.svelte — Stacked bar chart showing session count over time,
  coloured by protocol (data-1..6, with a legend).
-->
<script lang="ts">
	import type { ConnectionTimelineBucket } from '$api/traffic';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	// OLD CODE START — NET-192: the page's Card now owns the title and the loading/empty/error states
	// let {
	// 	buckets = [],
	// 	loading = false,
	// 	emptyMessage = 'Sessions appear here once NetTap sees traffic in this time range.',
	// }: {
	// 	buckets: ConnectionTimelineBucket[];
	// 	loading?: boolean;
	// 	/** #96: lets the page say the request failed instead of "no data" */
	// 	emptyMessage?: string;
	// } = $props();
	// OLD CODE END
	let { buckets }: { buckets: ConnectionTimelineBucket[] } = $props();

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const PROTO_COLORS: Record<string, string> = {
		tcp: 'var(--data-1)',
		udp: 'var(--data-5)',
		tls: 'var(--data-4)',
		dns: 'var(--data-2)',
		icmp: 'var(--data-6)',
		http: 'var(--data-3)',
	};

	const PROTO_ORDER = ['tcp', 'udp', 'tls', 'dns', 'icmp', 'http'];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let chartWidth = $state(800);
	let hoveredIndex = $state<number | null>(null);

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let maxTotal = $derived(Math.max(1, ...buckets.map((b) => b.total)));

	/** All unique protocols in the data, sorted by known order. */
	let activeProtocols = $derived.by(() => {
		const set = new Set<string>();
		for (const b of buckets) {
			for (const p of Object.keys(b.protocols)) {
				set.add(p);
			}
		}
		return PROTO_ORDER.filter((p) => set.has(p)).concat(
			[...set].filter((p) => !PROTO_ORDER.includes(p)).sort()
		);
	});

	// ---------------------------------------------------------------------------
	// Formatting
	// ---------------------------------------------------------------------------

	function formatShortTimestamp(ts: string): string {
		if (!ts) return '';
		try {
			const d = new Date(ts);
			const h = d.getHours().toString().padStart(2, '0');
			const m = d.getMinutes().toString().padStart(2, '0');
			const mon = (d.getMonth() + 1).toString().padStart(2, '0');
			const day = d.getDate().toString().padStart(2, '0');
			return `${mon}/${day} ${h}:${m}`;
		} catch {
			return ts;
		}
	}

	function protoColor(proto: string): string {
		return PROTO_COLORS[proto.toLowerCase()] || 'var(--text-3)';
	}

	// The chart's headline for screen readers (design system: every chart states it)
	let headline = $derived.by(() => {
		if (buckets.length === 0) return 'Session volume';
		const peak = buckets.reduce((a, b) => (b.total > a.total ? b : a));
		return `Session volume, busiest at ${formatShortTimestamp(peak.timestamp)} with ${peak.total.toLocaleString()} sessions`;
	});
</script>

<div class="timeline-card">
	<!-- OLD CODE START — NET-192: title and sub moved to the page's Card
	<div class="card-head">
		<div>
			<h2 class="card-title">Session volume</h2>
			<p class="card-sub">Sessions over time, by protocol</p>
		</div>
	OLD CODE END -->
	<div class="legend-row">
		<ul class="legend">
			{#each activeProtocols as proto}
				<li>
					<span class="sw" style="--c: {protoColor(proto)};"></span>
					{proto.toUpperCase()}
				</li>
			{/each}
		</ul>
	</div>

	<div class="chart-wrapper" bind:clientWidth={chartWidth}>
		{#if buckets.length > 0}
			<svg viewBox="0 0 {chartWidth} 200" width="100%" height="200" role="img" aria-label={headline}>
				<!-- Grid lines + Y labels -->
				{#each [0, 0.25, 0.5, 0.75, 1] as frac}
					<line
						class="gl"
						class:dash={frac > 0}
						x1="50" y1={180 - frac * 160}
						x2={chartWidth} y2={180 - frac * 160}
					/>
					<!-- OLD CODE: {Math.round(maxTotal * frac)} (NET-192: no thousands separator) -->
					<text class="ax" x="45" y={180 - frac * 160 + 4} text-anchor="end">
						{Math.round(maxTotal * frac).toLocaleString('en-GB')}
					</text>
				{/each}

				<!-- Stacked bars -->
				{#each buckets as bucket, i}
					{@const barW = Math.max(2, (chartWidth - 60) / buckets.length - 2)}
					{@const x = 55 + i * ((chartWidth - 60) / buckets.length)}
					{@const isHovered = hoveredIndex === i}

					<g
						role="img"
						onmouseenter={() => (hoveredIndex = i)}
						onmouseleave={() => (hoveredIndex = null)}
						style="cursor: pointer;"
					>
						<!-- Hit area -->
						<rect x={x} y="20" width={barW} height="160" fill="transparent" />

						<!-- Protocol stacks (bottom to top) -->
						{#each activeProtocols.filter((p) => (bucket.protocols[p] || 0) > 0) as proto, pi}
							{@const count = bucket.protocols[proto] || 0}
							{@const prevH = activeProtocols.slice(0, activeProtocols.indexOf(proto)).reduce((s, pp) => s + ((bucket.protocols[pp] || 0) / maxTotal) * 160, 0)}
							{@const h = (count / maxTotal) * 160}
							<rect
								x={x}
								y={180 - prevH - h}
								width={barW}
								height={Math.max(1, h)}
								rx="2"
								fill={protoColor(proto)}
								opacity={hoveredIndex !== null && !isHovered ? 0.3 : 0.8}
							/>
						{/each}

						<!-- Zero baseline -->
						{#if bucket.total === 0}
							<rect x={x} y={178} width={barW} height={2} rx="1"
								fill="var(--line)" opacity="0.3" />
						{/if}
					</g>
				{/each}

				<!-- X-axis labels -->
				{#each Array(Math.min(6, buckets.length)) as _, li}
					{@const idx = Math.round(li * (buckets.length - 1) / Math.max(1, Math.min(5, buckets.length - 1)))}
					{@const stepW = (chartWidth - 60) / buckets.length}
					{@const lx = 55 + idx * stepW + Math.max(2, stepW - 2) / 2}
					{@const last = idx === buckets.length - 1}
					<!-- OLD CODE: x={lx} text-anchor="middle" (NET-192: the last label ran past the right edge) -->
					<text class="ax" x={last ? chartWidth - 2 : lx} y="196" text-anchor={last ? 'end' : 'middle'}>
						{formatShortTimestamp(buckets[idx]?.timestamp || '')}
					</text>
				{/each}
			</svg>

			<!-- Hover tooltip -->
			{#if hoveredIndex !== null && buckets[hoveredIndex]}
				{@const hb = buckets[hoveredIndex]}
				{@const tooltipX = 55 + hoveredIndex * ((chartWidth - 60) / buckets.length)}
				<div class="bar-tooltip" style="left: {Math.min(tooltipX, chartWidth - 200)}px; top: 10px;">
					<div class="tooltip-time">{formatShortTimestamp(hb.timestamp)}</div>
					<div class="tooltip-row"><strong>{hb.total.toLocaleString()}</strong> total</div>
					{#each activeProtocols as proto}
						{#if hb.protocols[proto]}
							<div class="tooltip-row">
								<span class="sw" style="--c: {protoColor(proto)};"></span>
								{proto.toUpperCase()}: <strong>{hb.protocols[proto].toLocaleString()}</strong>
							</div>
						{/if}
					{/each}
				</div>
			{/if}
		<!-- OLD CODE START — NET-192: the page's CardState shows loading, empty and failed
		{:else if !loading}
			<p class="dim timeline-empty">{emptyMessage}</p>
		OLD CODE END -->
		{/if}
	</div>
</div>

<style>
	.timeline-card {
		display: flex;
		flex-direction: column;
	}

	.chart-wrapper {
		position: relative;
	}

	/* OLD CODE START — NET-192: the empty line moved to the page's CardState
	.timeline-empty {
		padding: var(--sp-8);
		text-align: center;
	}
	OLD CODE END */

	.legend-row {
		margin-bottom: var(--sp-3);
	}

	/* Chart tooltip: the system's light pill (pill-active-bg, on-light) */
	.bar-tooltip {
		position: absolute;
		background: var(--pill-active-bg);
		color: var(--on-light);
		border-radius: var(--r-md);
		padding: var(--sp-1) var(--sp-3);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
		pointer-events: none;
		z-index: 10;
		white-space: nowrap;
	}

	.tooltip-time {
		font-weight: 700;
		margin-bottom: 2px;
	}

	.tooltip-row {
		display: flex;
		align-items: center;
		gap: var(--sp-1);
	}
</style>
