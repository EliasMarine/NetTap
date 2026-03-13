<!--
  HorizontalBarList.svelte — Standardized horizontal bar graph component.

  Used across Dashboard, Alerts, Logs, DNS, Bandwidth pages for consistent
  bar alignment, sizing, and drill-down behavior.

  Layout: CSS grid with fixed-width label column so bars always start at
  the same horizontal position regardless of label content.
-->
<script lang="ts">
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	export interface BarItem {
		/** Unique key for keyed each block */
		key: string;
		/** Display label */
		label: string;
		/** Numeric value for bar width calculation */
		value: number;
		/** Formatted string to display as the count (e.g., "1.2K", "3.5 GB") */
		formattedValue: string;
		/** Bar color — CSS value (e.g., "var(--cyan)") */
		color?: string;
		/** Gradient — CSS background value (overrides color) */
		gradient?: string;
		/** Optional secondary value (e.g., "142 conn", "12.3%") */
		secondaryValue?: string;
		/** Navigation href — row becomes an <a> tag */
		href?: string;
		/** If true, label renders with mono font */
		mono?: boolean;
		/** If true, label is rendered inside IPAddress component */
		isIp?: boolean;
		/** Optional badge text displayed between rank and label */
		badgeText?: string;
		/** Optional badge CSS class */
		badgeClass?: string;
	}

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		items = [],
		maxValue,
		showRank = false,
		showDot = false,
		labelWidth = 140,
		barHeight = 12,
		activeKey,
		onclick,
		emptyMessage = 'No data available.',
	}: {
		items: BarItem[];
		maxValue?: number;
		showRank?: boolean;
		showDot?: boolean;
		labelWidth?: number;
		barHeight?: number;
		activeKey?: string;
		onclick?: (item: BarItem, index: number) => void;
		emptyMessage?: string;
	} = $props();

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let computedMax = $derived(maxValue ?? Math.max(...items.map((d) => d.value), 1));
	let hasSecondary = $derived(items.some((d) => d.secondaryValue));

	function barWidth(value: number): number {
		if (computedMax <= 0) return 0;
		return (value / computedMax) * 100;
	}

	function handleClick(item: BarItem, index: number, event: MouseEvent) {
		if (onclick) {
			event.preventDefault();
			onclick(item, index);
		}
	}

	function fillStyle(item: BarItem): string {
		const w = barWidth(item.value);
		if (item.gradient) return `width: ${w}%; background: ${item.gradient};`;
		return `width: ${w}%; background: ${item.color || 'var(--accent)'};`;
	}
</script>

<!--
  Row inner content — extracted as a snippet to avoid triplicating
  the a/button/div variants.
-->
{#snippet rowContent(item: BarItem, i: number)}
	<div class="hbar-label-area">
		{#if showRank}
			<span class="hbar-rank">{i + 1}</span>
		{/if}
		{#if item.badgeText}
			<span class={item.badgeClass || 'hbar-badge'}>{item.badgeText}</span>
		{/if}
		{#if showDot}
			<span class="hbar-dot" style="background: {item.color || 'var(--accent)'};"></span>
		{/if}
		<span class="hbar-label-text" class:mono={item.mono || item.isIp} title={item.label}>
			{#if item.isIp}
				<IPAddress ip={item.label} />
			{:else}
				{item.label}
			{/if}
		</span>
	</div>
	<div class="hbar-track">
		<div class="hbar-fill" style={fillStyle(item)}></div>
	</div>
	<span class="hbar-value mono">{item.formattedValue}</span>
	{#if hasSecondary}
		<span class="hbar-secondary">{item.secondaryValue || ''}</span>
	{/if}
{/snippet}

{#if items.length === 0}
	<div class="hbar-empty">
		<p class="text-muted">{emptyMessage}</p>
	</div>
{:else}
	<div
		class="hbar-list"
		class:hbar-has-secondary={hasSecondary}
		style="--hbar-label-width: {labelWidth}px; --hbar-bar-height: {barHeight}px;"
	>
		{#each items as item, i (item.key)}
			{@const isActive = activeKey != null && activeKey === item.key}

			{#if item.href && !onclick}
				<a
					href={item.href}
					class="hbar-row hbar-row-interactive"
					class:hbar-row-active={isActive}
				>
					{@render rowContent(item, i)}
				</a>
			{:else if onclick}
				<button
					type="button"
					class="hbar-row hbar-row-interactive"
					class:hbar-row-active={isActive}
					onclick={(e) => handleClick(item, i, e)}
				>
					{@render rowContent(item, i)}
				</button>
			{:else}
				<div class="hbar-row" class:hbar-row-active={isActive}>
					{@render rowContent(item, i)}
				</div>
			{/if}
		{/each}
	</div>
{/if}

<style>
	/* ------------------------------------------------------------------ */
	/* HorizontalBarList — standardized bar graph layout                  */
	/* ------------------------------------------------------------------ */

	.hbar-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	/*
	 * Row layout: CSS grid with fixed label column width.
	 * This ensures all bars start at the exact same horizontal position.
	 *
	 * Columns: [label-area: fixed] [bar: 1fr] [value: auto]
	 * When hasSecondary: adds a 4th auto column.
	 */
	.hbar-row {
		display: grid;
		grid-template-columns:
			var(--hbar-label-width, 140px)
			1fr
			auto;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
		border: 1px solid transparent;
		transition: all var(--transition-fast);
		text-align: left;
		width: 100%;
		text-decoration: none;
		color: inherit;
		font: inherit;
		background: none;
	}

	/* Add a 4th column when secondary values exist */
	.hbar-has-secondary .hbar-row {
		grid-template-columns:
			var(--hbar-label-width, 140px)
			1fr
			auto
			auto;
	}

	/* Interactive rows get cursor + hover */
	.hbar-row-interactive {
		cursor: pointer;
	}

	.hbar-row-interactive:hover {
		background: var(--bg-tertiary);
		border-color: var(--border-dim);
	}

	/* Active/selected state */
	.hbar-row-active {
		background: var(--accent-muted) !important;
		border-color: var(--accent) !important;
	}

	/* Label area — flex container for rank + dot + badge + text */
	.hbar-label-area {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		min-width: 0;
		overflow: hidden;
	}

	/* Rank number */
	.hbar-rank {
		font-size: var(--text-xs);
		color: var(--text-muted);
		font-weight: 500;
		min-width: 16px;
		text-align: right;
		flex-shrink: 0;
	}

	/* Colored dot */
	.hbar-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	/* Label text */
	.hbar-label-text {
		font-size: var(--text-sm);
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}

	/* Bar track */
	.hbar-track {
		height: var(--hbar-bar-height, 12px);
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
		min-width: 40px;
	}

	.hbar-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		transition: width 0.4s ease-out;
		min-width: 2px;
	}

	/* Value display */
	.hbar-value {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		text-align: right;
		white-space: nowrap;
	}

	/* Secondary value (conn count, percentage, etc) */
	.hbar-secondary {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
		white-space: nowrap;
		min-width: 50px;
	}

	/* Empty state */
	.hbar-empty {
		padding: var(--space-lg);
		text-align: center;
	}
</style>
