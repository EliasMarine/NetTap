<script lang="ts">
	/**
	 * CaptureHealthPanel — Mode-agnostic capture health overview.
	 *
	 * Shows capture mode badge, interface name, link status,
	 * drop counters, drop rate %, and NIC speed.
	 */

	import { getCaptureHealth, getCaptureStats } from '$api/capture';
	import type { CaptureHealthResponse, CaptureStatsResponse } from '$api/capture';
	import Icon from '$lib/components/ui/Icon.svelte';

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
			case 'normal': return 'chip is-ok';
			case 'degraded': return 'chip is-warn';
			case 'down': return 'chip is-bad';
			case 'not_configured': return 'chip';
			default: return 'chip';
		}
	}

	function statusLabel(status: string): string {
		switch (status) {
			case 'normal': return 'Normal';
			case 'degraded': return 'Degraded';
			case 'down': return 'Down';
			case 'not_configured': return 'Not configured';
			default: return 'Unknown';
		}
	}

	// Every mode is neutral metadata; the label tells them apart.
	function modeBadgeClass(_mode: string): string {
		return 'chip';
	}

	function modeLabel(mode: string): string {
		if (mode === 'dhcp_gateway') return 'DHCP gateway'; // CR-212: was labelled Inline bridge
		return mode === 'mirror' ? 'Mirror / SPAN' : 'Inline bridge';
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
	<div class="card-head">
		<span class="card-title">Capture health</span>
		{#if health}
			<span class={modeBadgeClass(health.mode)}>{modeLabel(health.mode)}</span>
		{/if}
	</div>

	{#if loading && !health}
		<div class="skeleton-rows">
			<div class="skel skeleton-row"></div>
			<div class="skel skeleton-row"></div>
			<div class="skel skeleton-row"></div>
		</div>
	{:else if health}
		<div class="info-grid">
			<div class="info-row">
				<span class="info-label">Status</span>
				<span class={statusBadgeClass(health.status)}>
					{#if health.status === 'normal'}<Icon name="check" />{:else if health.status === 'degraded' || health.status === 'down'}<Icon name="warn" />{/if}
					{statusLabel(health.status)}
				</span>
			</div>
			<div class="info-row">
				<span class="info-label">Interface</span>
				<span class="info-value mono">{health.capture_interface || '--'}</span>
			</div>
			<div class="info-row">
				<span class="info-label">Link</span>
				<span class="res" class:is-live={health.link_up} class:is-high={!health.link_up}>
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
			<p class="dim">Couldn't load capture counters: the request failed.</p>
		{:else if stats}
			<div class="stats-section">
				<div class="stat-row">
					<span class="stat-label">RX packets</span>
					<span class="stat-value num">{formatNumber(stats.rx_packets)}</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">TX packets</span>
					<span class="stat-value num">{formatNumber(stats.tx_packets)}</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">RX bytes</span>
					<span class="stat-value num">{formatBytes(stats.rx_bytes)}</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">Dropped</span>
					<span class="stat-value num" class:bad={stats.rx_dropped > 0}>
						{#if stats.rx_dropped > 0}<Icon name="warn" />{/if}
						{formatNumber(stats.rx_dropped)}
					</span>
				</div>
				<div class="stat-row">
					<span class="stat-label">Drop rate</span>
					<span class="stat-value num" class:bad={stats.drop_rate_pct > 0.1}>
						{#if stats.drop_rate_pct > 0.1}<Icon name="warn" />{/if}
						{stats.drop_rate_pct.toFixed(3)}%
					</span>
				</div>
				{#if stats.link_speed_mbps > 0}
					<div class="stat-row">
						<span class="stat-label">NIC speed</span>
						<span class="stat-value num">{stats.link_speed_mbps} Mbps</span>
					</div>
				{/if}
			</div>
		{/if}

		{#if health.issues.length > 0}
			<div class="issues-section">
				{#each health.issues as issue}
					<div class="notice issue-item"><Icon name="warn" />{issue}</div>
				{/each}
			</div>
		{/if}
	{:else if healthFailed}
		<p class="dim">Couldn't check capture health: the request failed.</p>
	{:else}
		<p class="dim">No capture health data yet.</p>
	{/if}
</div>

<style>
	.capture-health-panel {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.capture-health-panel .card-head {
		margin-bottom: var(--sp-2);
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
		font-weight: 600;
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
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
		font-size: var(--text-xs);
		color: var(--text-1);
	}

	.stat-value :global(.ic) {
		width: 13px;
		height: 13px;
	}

	.bad {
		color: var(--sev-critical);
	}

	.chip.is-bad {
		color: var(--sev-critical);
		background: color-mix(in srgb, var(--sev-critical) 12%, transparent);
	}

	.issues-section {
		margin-top: var(--sp-2);
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}

	.notice {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-2);
		padding: var(--sp-2) var(--sp-3);
		border-radius: var(--r-md);
		font-size: var(--text-xs);
		color: var(--text-1);
		background: color-mix(in srgb, var(--sev-medium) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--sev-medium) 26%, transparent);
	}

	.notice :global(.ic) {
		width: 14px;
		height: 14px;
		color: var(--sev-medium);
	}

	.skeleton-rows {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.skeleton-row {
		height: 24px;
		width: 100%;
	}
</style>
