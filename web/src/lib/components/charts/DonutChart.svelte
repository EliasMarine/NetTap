<script lang="ts">
	/**
	 * DonutChart — Pure SVG donut chart using stroke-dasharray/dashoffset.
	 *
	 * Props:
	 *   segments — Array of {label, value, color} entries
	 *   size    — Width/height of the SVG in pixels
	 *   formatValue — Optional value formatter for the center total
	 */

	interface Segment {
		label: string;
		value: number;
		color: string;
	}

	interface Props {
		segments: Segment[];
		size?: number;
		formatValue?: (n: number) => string;
	}

	let { segments = [], size = 200, formatValue = (n: number) => n.toLocaleString() }: Props = $props();

	// Donut geometry
	const CENTER = 100; // viewBox center
	const RADIUS = 80;
	const STROKE_WIDTH = 24;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

	// Total value
	let total = $derived(segments.reduce((sum, s) => sum + s.value, 0));

	// Computed segment arcs
	let arcs = $derived.by(() => {
		if (total === 0) return [];
		let offset = 0;
		return segments.map((seg) => {
			const fraction = seg.value / total;
			const dashLength = fraction * CIRCUMFERENCE;
			const dashOffset = -offset;
			offset += dashLength;
			return {
				...seg,
				fraction,
				dashLength,
				dashOffset,
				percentage: (fraction * 100).toFixed(1),
			};
		});
	});
</script>

<div class="donut-chart" role="img" aria-label="Protocol distribution donut chart">
	{#if segments.length === 0 || total === 0}
		<div class="chart-empty" style:width="{size}px" style:height="{size}px">
			<p>No data</p>
		</div>
	{:else}
		<svg width={size} height={size} viewBox="0 0 200 200">
			<!-- Background ring -->
			<circle
				cx={CENTER}
				cy={CENTER}
				r={RADIUS}
				fill="none"
				stroke="var(--border-muted)"
				stroke-width={STROKE_WIDTH}
				opacity="0.3"
			/>

			<!-- Segment arcs, rotated -90deg so first segment starts at top -->
			{#each arcs as arc}
				<circle
					cx={CENTER}
					cy={CENTER}
					r={RADIUS}
					fill="none"
					stroke={arc.color}
					stroke-width={STROKE_WIDTH}
					stroke-dasharray="{arc.dashLength} {CIRCUMFERENCE - arc.dashLength}"
					stroke-dashoffset={arc.dashOffset}
					stroke-linecap="butt"
					transform="rotate(-90 {CENTER} {CENTER})"
					class="donut-segment"
				>
					<title>{arc.label}: {arc.percentage}%</title>
				</circle>
			{/each}

			<!-- Center text -->
			<text
				x={CENTER}
				y={CENTER - 8}
				text-anchor="middle"
				dominant-baseline="middle"
				class="center-value"
			>
				{formatValue(total)}
			</text>
			<text
				x={CENTER}
				y={CENTER + 12}
				text-anchor="middle"
				dominant-baseline="middle"
				class="center-label"
			>
				total
			</text>
		</svg>

		<!-- Legend -->
		<div class="donut-legend">
			{#each arcs as arc}
				<div class="legend-item">
					<span class="legend-swatch" style:background-color={arc.color}></span>
					<span class="legend-label">{arc.label}</span>
					<span class="legend-value">{arc.percentage}%</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.donut-chart {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-md);
	}

	.chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	svg {
		display: block;
	}

	.donut-segment {
		transition: opacity var(--transition-fast);
	}

	.donut-segment:hover {
		opacity: 0.8;
	}

	.center-value {
		fill: var(--text-primary);
		font-size: 20px;
		font-weight: 700;
		font-family: var(--font-sans);
	}

	.center-label {
		fill: var(--text-muted);
		font-size: 12px;
		font-family: var(--font-sans);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.donut-legend {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: var(--space-sm) var(--space-md);
		width: 100%;
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-xs);
	}

	.legend-swatch {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		flex-shrink: 0;
	}

	.legend-label {
		color: var(--text-secondary);
	}

	.legend-value {
		color: var(--text-muted);
		font-family: var(--font-mono);
	}
</style>
