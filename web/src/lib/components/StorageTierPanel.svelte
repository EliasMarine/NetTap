<script lang="ts">
	/**
	 * StorageTierPanel — Shows hot/warm/cold tier disk usage breakdown.
	 * Fetches from GET /api/storage/status and displays per-tier bars.
	 */

	import { getStorageStatus } from '$api/system';
	import type { StorageStatus } from '$api/system';
	import Icon from '$lib/components/ui/Icon.svelte';

	let storage = $state<StorageStatus | null>(null);
	let loading = $state(true);

	// Tier configuration: decorative series colours, always shown beside the tier's label
	const TIER_DEFS = [
		{ key: 'hot', label: 'Hot (Zeek metadata)', color: 'var(--data-1)', defaultDays: 90, daysField: 'hot_days' as const },
		{ key: 'warm', label: 'Warm (Suricata alerts)', color: 'var(--data-2)', defaultDays: 180, daysField: 'warm_days' as const },
		{ key: 'cold', label: 'Cold (PCAP)', color: 'var(--data-3)', defaultDays: 30, daysField: 'cold_days' as const },
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
		if (percent > 85) return 'var(--sev-critical)';
		if (percent > 70) return 'var(--sev-medium)';
		return 'var(--ok)';
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
	<div class="card-head">
		<span class="card-title">Storage tiers</span>
		{#if storage}
			<span class="usage-pct num" style="color: {diskUsageColor(storage.disk_usage_percent)}">
				{#if storage.disk_usage_percent > 70}<Icon name="warn" />{/if}
				{storage.disk_usage_percent.toFixed(1)}% used
			</span>
		{/if}
	</div>

	{#if loading && !storage}
		<div class="skeleton-rows">
			<div class="skel skeleton-bar"></div>
			<div class="skel skeleton-bar"></div>
			<div class="skel skeleton-bar"></div>
		</div>
	{:else if storage}
		<!-- Overall disk bar -->
		<div class="meter">
			<span
				class="disk-bar-fill"
				style="width: {Math.min(storage.disk_usage_percent, 100)}%; background-color: {diskUsageColor(storage.disk_usage_percent)}"
			></span>
		</div>

		<div class="disk-summary">
			<span class="disk-stat">
				<span class="disk-label">Total</span>
				<span class="num">{formatBytes(storage.disk_total_bytes)}</span>
			</span>
			<span class="disk-stat">
				<span class="disk-label">Used</span>
				<span class="num">{formatBytes(storage.disk_used_bytes)}</span>
			</span>
			<span class="disk-stat">
				<span class="disk-label">Free</span>
				<span class="num">{formatBytes(storage.disk_free_bytes)}</span>
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
							<span class="tier-retention num">{tier.days}</span>
							<span class="tier-count dim">{tier.indexCount} indices</span>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Retention policy details -->
		{#if storage.retention && typeof storage.retention === 'object'}
			<div class="retention-section">
				<span class="eyebrow section-label">Retention policy</span>
				{#each Object.entries(storage.retention) as [key, val]}
					<div class="retention-item">
						<span class="retention-key">{key}</span>
						<span class="retention-val mono">{val}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<p class="dim">Couldn't load storage status.</p>
	{/if}
</div>

<style>
	.storage-tier-panel {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.storage-tier-panel .card-head {
		margin-bottom: var(--sp-2);
	}

	.usage-pct {
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.usage-pct :global(.ic) {
		width: 16px;
		height: 16px;
	}

	.disk-bar-fill {
		transition: width 250ms var(--ease);
	}

	.disk-summary {
		display: flex;
		gap: var(--sp-8);
		flex-wrap: wrap;
		margin-top: var(--sp-1);
	}

	.disk-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--text-sm);
	}

	.disk-label {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.tier-section {
		margin-top: var(--sp-4);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.tier-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.tier-info {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}

	.tier-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.tier-label {
		font-size: var(--text-sm);
		color: var(--text-1);
	}

	.tier-meta {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
	}

	.tier-retention {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.tier-count {
		font-size: var(--text-xs);
	}

	.retention-section {
		margin-top: var(--sp-4);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	.section-label {
		display: block;
		margin-bottom: var(--sp-2);
	}

	.retention-item {
		display: flex;
		gap: var(--sp-2);
		font-size: var(--text-sm);
		margin-bottom: var(--sp-1);
	}

	.retention-key {
		color: var(--text-2);
		text-transform: capitalize;
	}

	.retention-val {
		color: var(--text-1);
	}

	.skeleton-rows {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
	}

	.skeleton-bar {
		height: 24px;
		width: 100%;
	}
</style>
