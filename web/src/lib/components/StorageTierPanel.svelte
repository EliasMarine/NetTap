<script lang="ts">
	/**
	 * StorageTierPanel — Shows hot/warm/cold tier disk usage breakdown.
	 * Fetches from GET /api/storage/status and displays per-tier bars.
	 */

	import { getStorageStatus } from '$api/system';
	import type { StorageStatus } from '$api/system';

	let storage = $state<StorageStatus | null>(null);
	let loading = $state(true);

	// Tier configuration with colors
	const TIER_DEFS = [
		{ key: 'hot', label: 'Hot (Zeek Metadata)', color: 'var(--red)', defaultDays: 90, daysField: 'hot_days' as const },
		{ key: 'warm', label: 'Warm (Suricata Alerts)', color: 'var(--amber)', defaultDays: 180, daysField: 'warm_days' as const },
		{ key: 'cold', label: 'Cold (PCAP)', color: 'var(--blue)', defaultDays: 30, daysField: 'cold_days' as const },
	] as const;

	async function fetchData() {
		loading = true;
		try {
			storage = await getStorageStatus();
		} catch {
			// keep existing state
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchData();
	});

	function formatBytes(bytes: number): string {
		if (!bytes || bytes <= 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
	}

	function diskUsageColor(percent: number): string {
		if (percent > 85) return 'var(--danger)';
		if (percent > 70) return 'var(--warning)';
		return 'var(--success)';
	}

	// Derive tier data from index_counts + actual retention days from API
	let tierData = $derived.by(() => {
		if (!storage?.index_counts) return [];

		const counts = storage.index_counts;
		return TIER_DEFS.map((tier) => {
			const indexCount = counts[tier.key] ?? 0;
			const actualDays = (storage as unknown as Record<string, unknown>)?.[tier.daysField] as number | undefined;
			return {
				key: tier.key,
				label: tier.label,
				color: tier.color,
				days: `${actualDays ?? tier.defaultDays}d`,
				indexCount,
			};
		});
	});
</script>

<div class="card storage-tier-panel">
	<div class="card-header">
		<span class="card-title">Storage Tiers</span>
		{#if storage}
			<span class="usage-pct mono" style="color: {diskUsageColor(storage.disk_usage_percent)}">
				{storage.disk_usage_percent.toFixed(1)}% used
			</span>
		{/if}
	</div>

	{#if loading && !storage}
		<div class="skeleton-rows">
			<div class="skeleton skeleton-bar"></div>
			<div class="skeleton skeleton-bar"></div>
			<div class="skeleton skeleton-bar"></div>
		</div>
	{:else if storage}
		<!-- Overall disk bar -->
		<div class="disk-bar-container">
			<div
				class="disk-bar-fill"
				style="width: {Math.min(storage.disk_usage_percent, 100)}%; background-color: {diskUsageColor(storage.disk_usage_percent)}"
			></div>
		</div>

		<div class="disk-summary">
			<span class="disk-stat">
				<span class="disk-label">Total</span>
				<span class="mono">{formatBytes(storage.disk_total_bytes)}</span>
			</span>
			<span class="disk-stat">
				<span class="disk-label">Used</span>
				<span class="mono">{formatBytes(storage.disk_used_bytes)}</span>
			</span>
			<span class="disk-stat">
				<span class="disk-label">Free</span>
				<span class="mono">{formatBytes(storage.disk_free_bytes)}</span>
			</span>
		</div>

		<!-- Per-tier rows -->
		{#if tierData.length > 0}
			<div class="tier-section">
				{#each tierData as tier}
					<div class="tier-row">
						<div class="tier-info">
							<span class="tier-dot" style="background-color: {tier.color}"></span>
							<span class="tier-label">{tier.label}</span>
						</div>
						<div class="tier-meta">
							<span class="tier-retention mono">{tier.days}</span>
							<span class="tier-count text-muted">{tier.indexCount} indices</span>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Retention policy details -->
		{#if storage.retention && typeof storage.retention === 'object'}
			<div class="retention-section">
				<span class="section-label">Retention Policy</span>
				{#each Object.entries(storage.retention) as [key, val]}
					<div class="retention-item">
						<span class="retention-key">{key}</span>
						<span class="retention-val mono">{val}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<p class="text-muted">Storage data unavailable</p>
	{/if}
</div>

<style>
	.storage-tier-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.usage-pct {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.disk-bar-container {
		width: 100%;
		height: 8px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
	}

	.disk-bar-fill {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal);
	}

	.disk-summary {
		display: flex;
		gap: var(--space-xl);
		flex-wrap: wrap;
		margin-top: var(--space-xs);
	}

	.disk-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--text-sm);
	}

	.disk-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.tier-section {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-muted);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.tier-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.tier-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.tier-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.tier-label {
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	.tier-meta {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.tier-retention {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.tier-count {
		font-size: var(--text-xs);
	}

	.retention-section {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-muted);
	}

	.section-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		display: block;
		margin-bottom: var(--space-sm);
	}

	.retention-item {
		display: flex;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		margin-bottom: var(--space-xs);
	}

	.retention-key {
		color: var(--text-secondary);
		text-transform: capitalize;
	}

	.retention-val {
		color: var(--text-primary);
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

	.skeleton-bar {
		height: 24px;
		width: 100%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}
</style>
