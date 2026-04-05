<!--
  SessionTimeline.svelte — Stacked bar chart showing session count over time,
  colored by protocol (TCP=cyan, UDP=green, TLS=purple, DNS=amber).
-->
<script lang="ts">
	import type { ConnectionTimelineBucket } from '$api/traffic';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		buckets = [],
		loading = false,
	}: {
		buckets: ConnectionTimelineBucket[];
		loading?: boolean;
	} = $props();

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const PROTO_COLORS: Record<string, string> = {
		tcp: 'var(--cyan)',
		udp: 'var(--green)',
		tls: 'var(--purple)',
		dns: 'var(--amber)',
		icmp: 'var(--red)',
		http: 'var(--blue)',
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
		return PROTO_COLORS[proto.toLowerCase()] || 'var(--text-muted)';
	}
</script>

<div class="timeline-card">
	<div class="card-header">
		<h2>Session Volume</h2>
		<div class="legend-row">
			{#each activeProtocols as proto}
				<span class="legend-item">
					<span class="legend-dot" style="background: {protoColor(proto)};"></span>
					{proto.toUpperCase()}
				</span>
			{/each}
		</div>
	</div>

	<div class="chart-wrapper" bind:clientWidth={chartWidth}>
		{#if buckets.length > 0}
			<svg viewBox="0 0 {chartWidth} 200" width="100%" height="200">
				<!-- Grid lines + Y labels -->
				{#each [0, 0.25, 0.5, 0.75, 1] as frac}
					<line
						x1="50" y1={180 - frac * 160}
						x2={chartWidth} y2={180 - frac * 160}
						stroke="var(--border-default)" stroke-width="0.5" opacity="0.4"
					/>
					<text x="45" y={180 - frac * 160 + 4} text-anchor="end"
						fill="var(--text-muted)" font-size="10">
						{Math.round(maxTotal * frac)}
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
								fill="var(--border-default)" opacity="0.3" />
						{/if}
					</g>
				{/each}

				<!-- X-axis labels -->
				{#each Array(Math.min(6, buckets.length)) as _, li}
					{@const idx = Math.round(li * (buckets.length - 1) / Math.max(1, Math.min(5, buckets.length - 1)))}
					{@const stepW = (chartWidth - 60) / buckets.length}
					{@const lx = 55 + idx * stepW + Math.max(2, stepW - 2) / 2}
					<text x={lx} y="196" text-anchor="middle" fill="var(--text-muted)" font-size="10">
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
								<span class="legend-dot" style="background: {protoColor(proto)};"></span>
								{proto.toUpperCase()}: <strong>{hb.protocols[proto].toLocaleString()}</strong>
							</div>
						{/if}
					{/each}
				</div>
			{/if}
		{:else if !loading}
			<p class="text-muted" style="padding: 2rem; text-align: center;">No timeline data available</p>
		{/if}
	</div>
</div>

<style>
	.timeline-card {
		display: flex;
		flex-direction: column;
	}

	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-md) var(--space-sm);
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	.card-header h2 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.legend-row {
		display: flex;
		gap: var(--space-md);
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.legend-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.chart-wrapper {
		position: relative;
		padding: 0 var(--space-sm) var(--space-sm);
	}

	.bar-tooltip {
		position: absolute;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-xs) var(--space-sm);
		font-size: var(--text-xs);
		pointer-events: none;
		z-index: 10;
		white-space: nowrap;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
	}

	.tooltip-time {
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: 2px;
	}

	.tooltip-row {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		color: var(--text-secondary);
	}
</style>
