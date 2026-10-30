<!--
  LiveStatsRibbon.svelte — 4-card responsive stat ribbon for the Live Network Monitor.
  Displays connections/sec, bandwidth, active devices, and top country.
  Each card has a colored 2px top accent border matching the value color.
-->
<script lang="ts">
	let {
		connectionsPerSecond,
		bandwidthBytesPerSecond,
		activeDevices,
		topCountry,
	}: {
		connectionsPerSecond: number;
		bandwidthBytesPerSecond: number;
		activeDevices: number;
		topCountry: string;
	} = $props();

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	function formatBandwidth(bytesPerSec: number): { value: string; unit: string } {
		if (bytesPerSec >= 1_000_000) {
			return { value: (bytesPerSec / 1_000_000).toFixed(1), unit: 'MB/s' };
		}
		if (bytesPerSec >= 1_000) {
			return { value: (bytesPerSec / 1_000).toFixed(1), unit: 'KB/s' };
		}
		return { value: String(Math.round(bytesPerSec)), unit: 'B/s' };
	}

	function formatRate(rate: number): string {
		return rate.toFixed(1);
	}

	// ---------------------------------------------------------------------------
	// Derived values
	// ---------------------------------------------------------------------------

	let bandwidth = $derived(formatBandwidth(bandwidthBytesPerSecond));
</script>

<div class="stats-grid">
	<!-- Connections per Second -->
	<div class="stat-card accent-cyan">
		<span class="stat-label">Connections / sec</span>
		<span class="stat-value color-cyan">{formatRate(connectionsPerSecond)}</span>
		<span class="stat-desc">new connections per second</span>
	</div>

	<!-- Bandwidth -->
	<div class="stat-card accent-green">
		<span class="stat-label">Bandwidth</span>
		<span class="stat-value color-green">{bandwidth.value}<span class="stat-unit">{bandwidth.unit}</span></span>
		<span class="stat-desc">current throughput</span>
	</div>

	<!-- Active Devices -->
	<div class="stat-card accent-purple">
		<span class="stat-label">Active Devices</span>
		<span class="stat-value color-purple">{activeDevices}</span>
		<span class="stat-desc">devices seen in window</span>
	</div>

	<!-- Top Country -->
	<div class="stat-card accent-amber">
		<span class="stat-label">Top Country</span>
		<span class="stat-value color-amber">{topCountry || '--'}</span>
		<span class="stat-desc">most connected destination</span>
	</div>
</div>

<style>
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	@media (max-width: 1024px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}

	@media (max-width: 768px) {
		.stats-grid {
			grid-template-columns: 1fr;
		}
	}

	.stat-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md) var(--space-lg);
		transition: all var(--transition-fast);
		border-top-width: 2px;
		border-top-style: solid;
	}

	.stat-card:hover {
		border-color: var(--border-bright);
		background: var(--bg-tertiary);
	}

	/* Top border accent colors */
	.stat-card.accent-cyan {
		border-top-color: var(--cyan);
	}
	.stat-card.accent-cyan:hover {
		border-top-color: var(--cyan);
	}

	.stat-card.accent-green {
		border-top-color: var(--green);
	}
	.stat-card.accent-green:hover {
		border-top-color: var(--green);
	}

	.stat-card.accent-purple {
		border-top-color: var(--purple);
	}
	.stat-card.accent-purple:hover {
		border-top-color: var(--purple);
	}

	.stat-card.accent-amber {
		border-top-color: var(--amber);
	}
	.stat-card.accent-amber:hover {
		border-top-color: var(--amber);
	}

	.stat-label {
		display: block;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin-bottom: var(--space-xs);
	}

	.stat-value {
		display: block;
		font-size: var(--text-3xl);
		font-weight: 700;
		font-family: var(--font-mono);
		line-height: 1;
		margin-bottom: var(--space-xs);
	}

	.stat-unit {
		font-size: var(--text-base);
		font-weight: 500;
		margin-left: var(--space-xs);
		opacity: 0.7;
	}

	.stat-desc {
		display: block;
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Value colors matching the top border accent */
	.color-cyan { color: var(--cyan); }
	.color-green { color: var(--green); }
	.color-purple { color: var(--purple); }
	.color-amber { color: var(--amber); }
</style>
