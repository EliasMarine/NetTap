<script lang="ts">
	import { getSystemHealth, getStorageStatus, getSmartHealth } from '$api/system.js';
	import { getTSharkStatus } from '$api/tshark.js';
	import { getCyberChefStatus } from '$api/cyberchef.js';
	import type { SystemHealth, StorageStatus, SmartHealth } from '$api/system.js';
	import type { TSharkStatus } from '$api/tshark.js';
	import type { CyberChefStatus } from '$api/cyberchef.js';
	import BridgeStatus from '$lib/components/BridgeStatus.svelte';

	let systemHealth = $state<SystemHealth | null>(null);
	let storageStatus = $state<StorageStatus | null>(null);
	let smartHealth = $state<SmartHealth | null>(null);
	let tsharkStatus = $state<TSharkStatus | null>(null);
	let cyberchefStatus = $state<CyberChefStatus | null>(null);
	let loading = $state(true);

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	function formatUptime(seconds: number): string {
		if (seconds <= 0) return '--';
		const days = Math.floor(seconds / 86400);
		const hours = Math.floor((seconds % 86400) / 3600);
		const minutes = Math.floor((seconds % 3600) / 60);
		const parts: string[] = [];
		if (days > 0) parts.push(`${days}d`);
		if (hours > 0) parts.push(`${hours}h`);
		if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
		return parts.join(' ');
	}

	function diskUsageColor(percent: number): string {
		if (percent > 85) return 'var(--danger)';
		if (percent > 70) return 'var(--warning)';
		return 'var(--success)';
	}

	function tempColor(temp: number): string {
		if (temp > 70) return 'var(--danger)';
		if (temp > 55) return 'var(--warning)';
		return 'var(--success)';
	}

	async function fetchAll() {
		loading = true;
		try {
			const [health, storage, smart, tshark, cyberchef] = await Promise.all([
				getSystemHealth(),
				getStorageStatus(),
				getSmartHealth(),
				getTSharkStatus(),
				getCyberChefStatus(),
			]);
			systemHealth = health;
			storageStatus = storage;
			smartHealth = smart;
			tsharkStatus = tshark;
			cyberchefStatus = cyberchef;
		} catch {
			// Keep existing state on error
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>System | NetTap</title>
</svelte:head>

<div class="system-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>System</h2>
			<p class="text-muted">Hardware health, storage, and service status</p>
		</div>
		<div class="header-actions">
			<a href="/system/updates" class="btn btn-secondary btn-sm">
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" y1="15" x2="12" y2="3" />
				</svg>
				Software Updates
			</a>
			<button class="btn btn-primary btn-sm" onclick={fetchAll} disabled={loading}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10" />
					<polyline points="1 20 1 14 7 14" />
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
				</svg>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if loading && !systemHealth}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Fetching system status...</p>
		</div>
	{:else}
		<!-- Top cards: System Overview + OpenSearch -->
		<div class="grid grid-cols-2">
			<!-- System Overview -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">System Overview</span>
					{#if systemHealth}
						<span class={systemHealth.healthy ? 'badge badge-success' : 'badge badge-danger'}>
							{systemHealth.healthy ? 'Healthy' : 'Degraded'}
						</span>
					{:else}
						<span class="badge">Unknown</span>
					{/if}
				</div>
				<div class="info-grid">
					<div class="info-row">
						<span class="info-label">Uptime</span>
						<span class="info-value mono">{systemHealth ? formatUptime(systemHealth.uptime) : '--'}</span>
					</div>
					<div class="info-row">
						<span class="info-label">Last Check</span>
						<span class="info-value mono">
							{systemHealth ? new Date(systemHealth.timestamp).toLocaleString() : '--'}
						</span>
					</div>
				</div>
			</div>

			<!-- OpenSearch -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">OpenSearch</span>
					{#if systemHealth}
						<span class={systemHealth.opensearch_reachable ? 'badge badge-success' : 'badge badge-danger'}>
							{systemHealth.opensearch_reachable ? 'Reachable' : 'Unreachable'}
						</span>
					{:else}
						<span class="badge">Unknown</span>
					{/if}
				</div>
				<div class="info-grid">
					<div class="info-row">
						<span class="info-label">Status</span>
						<span class="info-value">
							{#if systemHealth?.opensearch_reachable}
								<span class="text-success">Connected</span>
							{:else}
								<span class="text-danger">Disconnected</span>
							{/if}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">Indices</span>
						<span class="info-value mono">
							{storageStatus?.index_summary?.count ?? '--'}
						</span>
					</div>
				</div>
			</div>
		</div>

		<!-- Bridge & Failover Status -->
		<BridgeStatus />

		<!-- Storage card (full width) -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Storage</span>
				{#if storageStatus}
					<span class="storage-percent mono" style="color: {diskUsageColor(storageStatus.disk_usage_percent)}">
						{storageStatus.disk_usage_percent.toFixed(1)}% used
					</span>
				{/if}
			</div>
			{#if storageStatus}
				<div class="storage-bar-container">
					<div
						class="storage-bar"
						style="width: {Math.min(storageStatus.disk_usage_percent, 100)}%; background-color: {diskUsageColor(storageStatus.disk_usage_percent)}"
					></div>
				</div>
				<div class="storage-details">
					<div class="storage-stat">
						<span class="info-label">Total</span>
						<span class="info-value mono">{formatBytes(storageStatus.disk_total_bytes)}</span>
					</div>
					<div class="storage-stat">
						<span class="info-label">Used</span>
						<span class="info-value mono">{formatBytes(storageStatus.disk_used_bytes)}</span>
					</div>
					<div class="storage-stat">
						<span class="info-label">Free</span>
						<span class="info-value mono">{formatBytes(storageStatus.disk_free_bytes)}</span>
					</div>
				</div>
				{#if storageStatus.retention}
					<div class="retention-section">
						<span class="info-label">Retention Policy</span>
						<div class="retention-details">
							{#if typeof storageStatus.retention === 'object'}
								{#each Object.entries(storageStatus.retention) as [key, val]}
									<div class="retention-item">
										<span class="retention-key">{key}:</span>
										<span class="retention-val mono">{val}</span>
									</div>
								{/each}
							{:else}
								<span class="mono">{storageStatus.retention}</span>
							{/if}
						</div>
					</div>
				{/if}
			{:else}
				<p class="text-muted">Storage data unavailable</p>
			{/if}
		</div>

		<!-- Bottom row: SMART + Services -->
		<div class="grid grid-cols-2">
			<!-- Drive Health (SMART) -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Drive Health</span>
					{#if smartHealth}
						<span class={smartHealth.healthy ? 'badge badge-success' : 'badge badge-danger'}>
							{smartHealth.healthy ? 'Healthy' : 'Degraded'}
						</span>
					{:else}
						<span class="badge">Unknown</span>
					{/if}
				</div>
				{#if smartHealth && smartHealth.device}
					<div class="info-grid">
						<div class="info-row">
							<span class="info-label">Model</span>
							<span class="info-value mono">{smartHealth.model || '--'}</span>
						</div>
						<div class="info-row">
							<span class="info-label">Temperature</span>
							<span class="info-value mono" style="color: {tempColor(smartHealth.temperature_c)}">
								{smartHealth.temperature_c}&deg;C
							</span>
						</div>
						<div class="info-row">
							<span class="info-label">Wear</span>
							<div class="wear-cell">
								<div class="wear-bar-container">
									<div
										class="wear-bar"
										style="width: {Math.min(smartHealth.percentage_used, 100)}%; background-color: {smartHealth.percentage_used > 80 ? 'var(--danger)' : smartHealth.percentage_used > 50 ? 'var(--warning)' : 'var(--success)'}"
									></div>
								</div>
								<span class="mono wear-text">{smartHealth.percentage_used}%</span>
							</div>
						</div>
						<div class="info-row">
							<span class="info-label">Power-On Hours</span>
							<span class="info-value mono">{smartHealth.power_on_hours.toLocaleString()}</span>
						</div>
					</div>
					{#if smartHealth.warnings && smartHealth.warnings.length > 0}
						<div class="smart-warnings">
							{#each smartHealth.warnings as warning}
								<div class="alert alert-warning">{warning}</div>
							{/each}
						</div>
					{/if}
				{:else}
					<p class="text-muted">SMART data unavailable. Drive health monitoring requires smartmontools.</p>
				{/if}
			</div>

			<!-- Services -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Services</span>
				</div>
				<div class="services-list">
					<!-- TShark -->
					<div class="service-item">
						<div class="service-info">
							<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 002 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0022 16z" />
								<polyline points="3.27 6.96 12 12.01 20.73 6.96" />
								<line x1="12" y1="22.08" x2="12" y2="12" />
							</svg>
							<div>
								<span class="service-name">TShark</span>
								{#if tsharkStatus?.version}
									<span class="service-version mono">{tsharkStatus.version}</span>
								{/if}
							</div>
						</div>
						{#if tsharkStatus}
							<span class={tsharkStatus.available ? 'badge badge-success' : 'badge badge-danger'}>
								{tsharkStatus.available ? 'Available' : 'Unavailable'}
							</span>
						{:else}
							<span class="badge">Checking...</span>
						{/if}
					</div>

					<!-- CyberChef -->
					<div class="service-item">
						<div class="service-info">
							<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<polyline points="16 18 22 12 16 6" />
								<polyline points="8 6 2 12 8 18" />
								<line x1="14" y1="4" x2="10" y2="20" />
							</svg>
							<div>
								<span class="service-name">CyberChef</span>
								{#if cyberchefStatus?.version}
									<span class="service-version mono">{cyberchefStatus.version}</span>
								{/if}
							</div>
						</div>
						{#if cyberchefStatus}
							<span class={cyberchefStatus.available ? 'badge badge-success' : 'badge badge-danger'}>
								{cyberchefStatus.available ? 'Available' : 'Unavailable'}
							</span>
						{:else}
							<span class="badge">Checking...</span>
						{/if}
					</div>
				</div>

				<div class="service-links">
					{#if cyberchefStatus?.available}
						<a href="/system/cyberchef" class="btn btn-secondary btn-sm">Open CyberChef</a>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.system-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	/* Loading */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Info grid (key-value rows) */
	.info-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
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
	}

	/* Storage bar */
	.storage-percent {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.storage-bar-container {
		width: 100%;
		height: 8px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
		margin-bottom: var(--space-md);
	}

	.storage-bar {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal);
	}

	.storage-details {
		display: flex;
		gap: var(--space-xl);
		flex-wrap: wrap;
	}

	.storage-stat {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.retention-section {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-muted);
	}

	.retention-details {
		margin-top: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.retention-item {
		display: flex;
		gap: var(--space-sm);
		font-size: var(--text-sm);
	}

	.retention-key {
		color: var(--text-secondary);
		text-transform: capitalize;
	}

	.retention-val {
		color: var(--text-primary);
	}

	/* Wear bar */
	.wear-cell {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.wear-bar-container {
		width: 80px;
		height: 6px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
	}

	.wear-bar {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal);
	}

	.wear-text {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		min-width: 36px;
		text-align: right;
	}

	/* SMART warnings */
	.smart-warnings {
		margin-top: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	/* Services */
	.services-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.service-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.service-item:last-child {
		border-bottom: none;
	}

	.service-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		color: var(--text-secondary);
	}

	.service-info div {
		display: flex;
		flex-direction: column;
	}

	.service-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.service-version {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.service-links {
		margin-top: var(--space-md);
		display: flex;
		gap: var(--space-sm);
	}

	@media (max-width: 640px) {
		.page-header {
			flex-direction: column;
		}

		.storage-details {
			flex-direction: column;
			gap: var(--space-sm);
		}
	}
</style>
