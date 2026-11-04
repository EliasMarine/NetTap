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
	// #96: a failed request must not read as link down / 0% drops
	let healthFailed = $state(false);
	let statsFailed = $state(false);

	async function fetchData() {
		loading = true;
		// OLD CODE START — #96: the getters faked "down"/zeros on failure; they now throw
		// try {
		// 	const [h, s] = await Promise.all([getCaptureHealth(), getCaptureStats()]);
		// 	health = h;
		// 	stats = s;
		// } catch {
		// 	// keep existing state
		// } finally {
		// 	loading = false;
		// }
		// OLD CODE END
		const [h, s] = await Promise.allSettled([getCaptureHealth(), getCaptureStats()]);
		if (h.status === 'fulfilled') health = h.value;
		if (s.status === 'fulfilled') stats = s.value;
		healthFailed = h.status === 'rejected';
		statsFailed = s.status === 'rejected';
		loading = false;
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
		if (mode === 'dhcp_gateway') return 'DHCP Gateway'; // CR-212: was labelled Inline Bridge
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

		{#if statsFailed}
			<p class="text-muted">Couldn't load capture counters: the request failed.</p>
		{:else if stats}
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
	{:else if healthFailed}
		<p class="text-muted">Couldn't check capture health: the request failed.</p>
	{:else}
		<p class="text-muted">Capture health data unavailable</p>
	{/if}
</div>

<style>
	.capture-health-panel {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.info-grid {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}

	.info-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--sp-1) 0;
		border-bottom: 1px solid var(--line);
	}

	.info-row:last-child {
		border-bottom: none;
	}

	.info-label {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.info-value {
		font-size: var(--text-sm);
		color: var(--text-1);
		font-weight: 500;
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.stats-section {
		margin-top: var(--sp-2);
		padding-top: var(--sp-2);
		border-top: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}

	.stat-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.stat-value {
		font-size: var(--text-xs);
		color: var(--text-1);
	}

	.issues-section {
		margin-top: var(--sp-2);
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}

	.issue-item {
		font-size: var(--text-xs);
		padding: var(--sp-1) var(--sp-2);
	}

	.skeleton-rows {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.skeleton {
		background: linear-gradient(90deg, var(--surface-2) 25%, var(--line) 50%, var(--surface-2) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--r-sm);
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
