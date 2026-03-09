<script lang="ts">
	/**
	 * CaptureHealthPanel — Mode-agnostic capture health overview.
	 *
	 * Shows capture mode badge, interface name, link status,
	 * drop counters, drop rate %, and NIC speed.
	 */

	import { getCaptureHealth, getCaptureStats } from '$api/capture';
	import type { CaptureHealthResponse, CaptureStatsResponse } from '$api/capture';

	let health = $state<CaptureHealthResponse | null>(null);
	let stats = $state<CaptureStatsResponse | null>(null);
	let loading = $state(true);

	async function fetchData() {
		loading = true;
		try {
			const [h, s] = await Promise.all([getCaptureHealth(), getCaptureStats()]);
			health = h;
			stats = s;
		} catch {
			// keep existing state
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchData();
	});

	// Helpers
	function statusBadgeClass(status: string): string {
		switch (status) {
			case 'normal': return 'badge badge-success';
			case 'degraded': return 'badge badge-warning';
			case 'down': return 'badge badge-danger';
			case 'not_configured': return 'badge badge-muted';
			default: return 'badge';
		}
	}

	function statusLabel(status: string): string {
		switch (status) {
			case 'normal': return 'Normal';
			case 'degraded': return 'Degraded';
			case 'down': return 'Down';
			case 'not_configured': return 'Not Configured';
			default: return 'Unknown';
		}
	}

	function modeBadgeClass(mode: string): string {
		return mode === 'mirror' ? 'badge badge-info' : 'badge badge-accent';
	}

	function modeLabel(mode: string): string {
		return mode === 'mirror' ? 'Mirror / SPAN' : 'Inline Bridge';
	}

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
	}

	function formatNumber(n: number): string {
		return n.toLocaleString();
	}
</script>

<div class="card capture-health-panel">
	<div class="card-header">
		<span class="card-title">Capture Health</span>
		{#if health}
			<span class={modeBadgeClass(health.mode)}>{modeLabel(health.mode)}</span>
		{/if}
	</div>

	{#if loading && !health}
		<div class="skeleton-rows">
			<div class="skeleton skeleton-row"></div>
			<div class="skeleton skeleton-row"></div>
			<div class="skeleton skeleton-row"></div>
		</div>
	{:else if health}
		<div class="info-grid">
			<div class="info-row">
				<span class="info-label">Status</span>
				<span class={statusBadgeClass(health.status)}>{statusLabel(health.status)}</span>
			</div>
			<div class="info-row">
				<span class="info-label">Interface</span>
				<span class="info-value mono">{health.capture_interface || '--'}</span>
			</div>
			<div class="info-row">
				<span class="info-label">Link</span>
				<span class="info-value">
					<span class="health-dot" class:green={health.link_up} class:red={!health.link_up}></span>
					{health.link_up ? 'Up' : 'Down'}
				</span>
			</div>
			<div class="info-row">
				<span class="info-label">Promiscuous</span>
				<span class="info-value">
					{health.promisc_enabled ? 'Enabled' : 'Disabled'}
				</span>
			</div>
		</div>

		{#if stats}
			<div class="stats-section">
				<div class="stat-row">
					<span class="stat-label">RX Packets</span>
					<span class="stat-value mono">{formatNumber(stats.rx_packets)}</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">TX Packets</span>
					<span class="stat-value mono">{formatNumber(stats.tx_packets)}</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">RX Bytes</span>
					<span class="stat-value mono">{formatBytes(stats.rx_bytes)}</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">Dropped</span>
					<span class="stat-value mono" class:text-danger={stats.rx_dropped > 0}>
						{formatNumber(stats.rx_dropped)}
					</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">Drop Rate</span>
					<span class="stat-value mono" class:text-danger={stats.drop_rate_pct > 0.1}>
						{stats.drop_rate_pct.toFixed(3)}%
					</span>
				</div>
				{#if stats.link_speed_mbps > 0}
					<div class="stat-row">
						<span class="stat-label">NIC Speed</span>
						<span class="stat-value mono">{stats.link_speed_mbps} Mbps</span>
					</div>
				{/if}
			</div>
		{/if}

		{#if health.issues.length > 0}
			<div class="issues-section">
				{#each health.issues as issue}
					<div class="alert alert-warning issue-item">{issue}</div>
				{/each}
			</div>
		{/if}
	{:else}
		<p class="text-muted">Capture health data unavailable</p>
	{/if}
</div>

<style>
	.capture-health-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.info-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.info-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-xs) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.info-row:last-child {
		border-bottom: none;
	}

	.info-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.info-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 500;
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.stats-section {
		margin-top: var(--space-sm);
		padding-top: var(--space-sm);
		border-top: 1px solid var(--border-muted);
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.stat-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.stat-value {
		font-size: var(--text-xs);
		color: var(--text-primary);
	}

	.issues-section {
		margin-top: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.issue-item {
		font-size: var(--text-xs);
		padding: var(--space-xs) var(--space-sm);
	}

	.skeleton-rows {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
	}

	.skeleton-row {
		height: 24px;
		width: 100%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}
</style>
