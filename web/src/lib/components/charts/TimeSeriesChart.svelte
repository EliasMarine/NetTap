<script lang="ts">
	/**
	 * TimeSeriesChart — Pure SVG time series area chart with hover tooltip.
	 *
	 * Props:
	 *   data      — Array of {time, value} points
	 *   height    — Chart height in pixels
	 *   color     — Accent color for the line/fill
	 *   label     — Y-axis label
	 *   formatValue — Value formatter function
	 */

	interface DataPoint {
		time: string;
		value: number;
	}

	interface Props {
		data: DataPoint[];
		height?: number;
		color?: string;
		label?: string;
		formatValue?: (n: number) => string;
	}

	let { data = [], height = 240, color = 'var(--accent)', label = '', formatValue = (n: number) => String(n) }: Props = $props();

	// Chart layout constants
	const PADDING_LEFT = 60;
	const PADDING_RIGHT = 16;
	const PADDING_TOP = 16;
	const PADDING_BOTTOM = 40;

	// Internal state
	let containerEl: HTMLDivElement | undefined = $state(undefined);
	let containerWidth = $state(600);
	let hoverIndex = $state(-1);

	// Measure container width
	$effect(() => {
		if (!containerEl) return;
		const observer = new ResizeObserver((entries) => {
			for (const entry of entries) {
				containerWidth = entry.contentRect.width;
			}
		});
		observer.observe(containerEl);
		return () => observer.disconnect();
	});

	// Computed chart dimensions
	let chartWidth = $derived(containerWidth - PADDING_LEFT - PADDING_RIGHT);
	let chartHeight = $derived(height - PADDING_TOP - PADDING_BOTTOM);

	// Compute value bounds
	let minValue = $derived(data.length > 0 ? Math.min(...data.map((d) => d.value)) : 0);
	let maxValue = $derived(data.length > 0 ? Math.max(...data.map((d) => d.value)) : 1);
	let valueRange = $derived(maxValue - minValue || 1);

	// Scale helpers
	function xScale(index: number): number {
		if (data.length <= 1) return PADDING_LEFT + chartWidth / 2;
		return PADDING_LEFT + (index / (data.length - 1)) * chartWidth;
	}

	function yScale(value: number): number {
		// Add 10% padding above max
		const paddedRange = valueRange * 1.1;
		const paddedMin = minValue;
		return PADDING_TOP + chartHeight - ((value - paddedMin) / paddedRange) * chartHeight;
	}

	// Build polyline path
	let polylinePath = $derived.by(() => {
		if (data.length === 0) return '';
		return data.map((d, i) => `${xScale(i)},${yScale(d.value)}`).join(' ');
	});

	// Build area path (closed polygon for gradient fill)
	let areaPath = $derived.by(() => {
		if (data.length === 0) return '';
		const baseline = PADDING_TOP + chartHeight;
		const points = data.map((d, i) => `${xScale(i)},${yScale(d.value)}`);
		return `M${xScale(0)},${baseline} L${points.join(' L')} L${xScale(data.length - 1)},${baseline} Z`;
	});

	// Y-axis tick values (5 ticks)
	let yTicks = $derived.by(() => {
		const paddedMax = minValue + valueRange * 1.1;
		const ticks: number[] = [];
		const step = (paddedMax - minValue) / 4;
		for (let i = 0; i <= 4; i++) {
			ticks.push(minValue + step * i);
		}
		return ticks;
	});

	// X-axis labels (show ~6 evenly spaced time labels)
	let xLabels = $derived.by(() => {
		if (data.length === 0) return [];
		const count = Math.min(6, data.length);
		const step = Math.max(1, Math.floor((data.length - 1) / (count - 1)));
		const labels: { index: number; label: string }[] = [];
		for (let i = 0; i < data.length; i += step) {
			const d = new Date(data[i].time);
			labels.push({
				index: i,
				label: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
			});
		}
		// Always include last point
		if (labels.length > 0 && labels[labels.length - 1].index !== data.length - 1) {
			const d = new Date(data[data.length - 1].time);
			labels.push({
				index: data.length - 1,
				label: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
			});
		}
		return labels;
	});

	// Hover handling
	function handleMouseMove(e: MouseEvent) {
		if (data.length === 0 || !containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		const mouseX = e.clientX - rect.left;

		// Find closest data point
		let closestIdx = 0;
		let closestDist = Infinity;
		for (let i = 0; i < data.length; i++) {
			const dist = Math.abs(xScale(i) - mouseX);
			if (dist < closestDist) {
				closestDist = dist;
				closestIdx = i;
			}
		}
		hoverIndex = closestIdx;
	}

	function handleMouseLeave() {
		hoverIndex = -1;
	}

	// Unique gradient ID
	let gradientId = $derived(`ts-gradient-${label.replace(/\s+/g, '-').toLowerCase() || 'default'}`);
</script>

<div
	class="time-series-chart"
	bind:this={containerEl}
	role="img"
	aria-label={label ? `${label} time series chart` : 'Time series chart'}
>
	{#if data.length === 0}
		<div class="chart-empty" style:height="{height}px">
			<p>No data available</p>
		</div>
	{:else}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<svg
			width={containerWidth}
			{height}
			viewBox="0 0 {containerWidth} {height}"
			onmousemove={handleMouseMove}
			onmouseleave={handleMouseLeave}
		>
			<defs>
				<linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
					<stop offset="0%" stop-color={color} stop-opacity="0.3" />
					<stop offset="100%" stop-color={color} stop-opacity="0.02" />
				</linearGradient>
			</defs>

			<!-- Grid lines -->
			{#each yTicks as tick}
				<line
					x1={PADDING_LEFT}
					y1={yScale(tick)}
					x2={PADDING_LEFT + chartWidth}
					y2={yScale(tick)}
					class="grid-line"
				/>
			{/each}

			<!-- Filled area -->
			<path d={areaPath} fill="url(#{gradientId})" />

			<!-- Line -->
			<polyline
				points={polylinePath}
				fill="none"
				stroke={color}
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>

			<!-- Y-axis labels -->
			{#each yTicks as tick}
				<text
					x={PADDING_LEFT - 8}
					y={yScale(tick)}
					class="axis-label y-label"
					text-anchor="end"
					dominant-baseline="middle"
				>
					{formatValue(tick)}
				</text>
			{/each}

			<!-- X-axis labels -->
			{#each xLabels as xl}
				<text
					x={xScale(xl.index)}
					y={PADDING_TOP + chartHeight + 24}
					class="axis-label x-label"
					text-anchor="middle"
				>
					{xl.label}
				</text>
			{/each}

			<!-- Y-axis label text -->
			{#if label}
				<text
					x={14}
					y={PADDING_TOP + chartHeight / 2}
					class="axis-title"
					text-anchor="middle"
					transform="rotate(-90, 14, {PADDING_TOP + chartHeight / 2})"
				>
					{label}
				</text>
			{/if}

			<!-- Hover indicator -->
			{#if hoverIndex >= 0 && hoverIndex < data.length}
				<line
					x1={xScale(hoverIndex)}
					y1={PADDING_TOP}
					x2={xScale(hoverIndex)}
					y2={PADDING_TOP + chartHeight}
					class="hover-line"
				/>
				<circle
					cx={xScale(hoverIndex)}
					cy={yScale(data[hoverIndex].value)}
					r="5"
					fill={color}
					stroke="var(--bg-secondary)"
					stroke-width="2"
				/>
			{/if}
		</svg>

		<!-- Tooltip overlay -->
		{#if hoverIndex >= 0 && hoverIndex < data.length}
			<div
				class="chart-tooltip"
				style:left="{xScale(hoverIndex)}px"
				style:top="{yScale(data[hoverIndex].value) - 8}px"
			>
				<span class="tooltip-value">{formatValue(data[hoverIndex].value)}</span>
				<span class="tooltip-time">
					{new Date(data[hoverIndex].time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
				</span>
			</div>
		{/if}
	{/if}
</div>

<style>
	.time-series-chart {
		position: relative;
		width: 100%;
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

	.grid-line {
		stroke: var(--border-muted);
		stroke-width: 1;
		stroke-dasharray: 4 4;
		opacity: 0.5;
	}

	.axis-label {
		fill: var(--text-muted);
		font-size: 11px;
		font-family: var(--font-mono);
	}

	.y-label {
		font-variant-numeric: tabular-nums;
	}

	.x-label {
		font-variant-numeric: tabular-nums;
	}

	.axis-title {
		fill: var(--text-secondary);
		font-size: 11px;
		font-family: var(--font-sans);
		font-weight: 500;
	}

	.hover-line {
		stroke: var(--text-muted);
		stroke-width: 1;
		stroke-dasharray: 4 4;
		opacity: 0.6;
	}

	.chart-tooltip {
		position: absolute;
		transform: translate(-50%, -100%);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		padding: 4px 8px;
		pointer-events: none;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		z-index: 10;
	}

	.tooltip-value {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
		font-family: var(--font-mono);
	}

	.tooltip-time {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}
</style>
