<script lang="ts">
	import IPAddress from '$components/IPAddress.svelte';

	interface DeviceUsageItem {
		ip: string;
		total_bytes: number;
		percent_of_total: number;
	}

	let { devices = [] }: { devices: DeviceUsageItem[] } = $props();

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	}
</script>

{#if devices.length > 0}
	<div class="card top-consumers">
		<h3 class="card-title">Top Bandwidth Consumers</h3>
		<div class="consumer-list">
			{#each devices as device, i}
				<div class="consumer-item">
					<span class="consumer-rank">{i + 1}</span>
					<span class="consumer-ip mono">
						<IPAddress ip={device.ip} />
					</span>
					<div class="consumer-bar-wrapper">
						<div
							class="consumer-bar"
							style="width: {Math.max(2, device.percent_of_total)}%"
						></div>
					</div>
					<span class="consumer-bytes mono">{formatBytes(device.total_bytes)}</span>
					<span class="consumer-percent">{device.percent_of_total}%</span>
				</div>
			{/each}
		</div>
	</div>
{/if}

<style>
	.top-consumers {
		overflow: hidden;
	}

	.card-title {
		font-size: var(--text-lg);
		font-weight: 600;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.consumer-list {
		padding: var(--space-md) var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.consumer-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.consumer-rank {
		width: 24px;
		text-align: right;
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-muted);
	}

	.consumer-ip {
		min-width: 120px;
		font-size: var(--text-sm);
	}

	.consumer-bar-wrapper {
		flex: 1;
		height: 8px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.consumer-bar {
		height: 100%;
		background: var(--accent, #3b82f6);
		border-radius: var(--radius-sm);
		transition: width 0.3s ease;
	}

	.consumer-bytes {
		min-width: 80px;
		text-align: right;
		font-size: var(--text-sm);
	}

	.consumer-percent {
		min-width: 45px;
		text-align: right;
		font-size: var(--text-sm);
		color: var(--text-muted);
	}
</style>
