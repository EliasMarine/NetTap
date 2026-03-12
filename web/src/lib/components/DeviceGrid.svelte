<script lang="ts">
	/**
	 * DeviceGrid — Device-centric grid/list for mirror mode home page.
	 *
	 * Shows devices grouped by category (computers, phones, IoT, infrastructure)
	 * with friendly name, IP, MAC, manufacturer, traffic volume, active connections,
	 * and last seen timestamp.
	 */

	import type { RegistryDevice } from '$api/devices-registry';

	interface Props {
		devices: RegistryDevice[];
		loading?: boolean;
	}

	let { devices, loading = false }: Props = $props();

	// Category definitions with icons and order
	const CATEGORIES = [
		{ key: 'computer', label: 'Computers', icon: 'monitor' },
		{ key: 'phone', label: 'Phones & Tablets', icon: 'phone' },
		{ key: 'iot', label: 'IoT Devices', icon: 'cpu' },
		{ key: 'infrastructure', label: 'Infrastructure', icon: 'server' },
		{ key: 'unknown', label: 'Unknown', icon: 'help' },
	] as const;

	// Group devices by category
	let groupedDevices = $derived.by(() => {
		const groups: Record<string, RegistryDevice[]> = {};
		for (const cat of CATEGORIES) {
			groups[cat.key] = [];
		}
		for (const device of devices) {
			const cat = device.category || 'unknown';
			if (!groups[cat]) groups[cat] = [];
			groups[cat].push(device);
		}
		// Sort within each group by last_seen descending
		for (const key of Object.keys(groups)) {
			groups[key].sort((a, b) =>
				new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime()
			);
		}
		return groups;
	});

	// Only show categories that have devices
	let activeCategories = $derived(
		CATEGORIES.filter((c) => (groupedDevices[c.key]?.length ?? 0) > 0)
	);

	function formatBytes(bytes: number | undefined): string {
		if (!bytes || bytes <= 0) return '--';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
	}

	function timeAgo(iso: string): string {
		if (!iso) return '--';
		const diffMs = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diffMs / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days}d ago`;
	}
</script>

<div class="device-grid-container">
	{#if loading && devices.length === 0}
		<div class="skeleton-grid">
			{#each Array(6) as _}
				<div class="skeleton skeleton-card"></div>
			{/each}
		</div>
	{:else if devices.length === 0}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round">
					<rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
				</svg>
			</div>
			<p class="empty-text">No devices detected yet</p>
			<p class="empty-hint">Devices will appear as they are discovered on the network</p>
		</div>
	{:else}
		{#each activeCategories as category}
			<div class="category-section">
				<h3 class="category-heading">
					{category.label}
					<span class="category-count">{groupedDevices[category.key].length}</span>
				</h3>
				<div class="device-cards">
					{#each groupedDevices[category.key] as device}
						<a
							href="/devices/mac/{encodeURIComponent(device.mac)}"
							class="card device-card"
							class:is-new={device.is_new}
						>
							<div class="device-header">
								<span class="device-name">{device.display_name || device.mac}</span>
								{#if device.is_new}
									<span class="badge badge-info">New</span>
								{/if}
							</div>

							<div class="device-meta">
								{#if device.ips.length > 0}
									<span class="meta-item mono">{device.ips[0]}</span>
								{/if}
								<span class="meta-item mono text-muted">{device.mac}</span>
								{#if device.manufacturer}
									<span class="meta-item text-muted">{device.manufacturer}</span>
								{/if}
							</div>

							<div class="device-stats">
								<div class="device-stat">
									<span class="stat-label">Traffic</span>
									<span class="stat-value mono">{formatBytes(device.total_bytes)}</span>
								</div>
								<div class="device-stat">
									<span class="stat-label">Connections</span>
									<span class="stat-value mono">{device.connection_count?.toLocaleString() ?? '--'}</span>
								</div>
								<div class="device-stat">
									<span class="stat-label">Last Seen</span>
									<span class="stat-value">{timeAgo(device.last_seen)}</span>
								</div>
							</div>
						</a>
					{/each}
				</div>
			</div>
		{/each}
	{/if}
</div>

<style>
	.device-grid-container {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.category-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.category-heading {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-secondary);
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.category-count {
		font-size: var(--text-xs);
		color: var(--text-muted);
		background-color: var(--bg-tertiary);
		padding: 1px 8px;
		border-radius: var(--radius-full);
	}

	.device-cards {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-md);
	}

	.device-card {
		text-decoration: none;
		color: inherit;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.device-card:hover {
		border-color: var(--accent);
		color: inherit;
		text-decoration: none;
	}

	.device-card.is-new {
		border-color: var(--cyan);
		box-shadow: 0 0 8px rgba(0, 212, 255, 0.1);
	}

	.device-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.device-name {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.device-meta {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.meta-item {
		font-size: var(--text-xs);
	}

	.device-stats {
		display: flex;
		gap: var(--space-md);
		margin-top: var(--space-xs);
		padding-top: var(--space-sm);
		border-top: 1px solid var(--border-muted);
	}

	.device-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
	}

	.stat-label {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.stat-value {
		font-size: var(--text-xs);
		color: var(--text-primary);
	}

	.empty-state {
		text-align: center;
		padding: var(--space-3xl) var(--space-lg);
		color: var(--text-muted);
	}

	.empty-icon {
		margin-bottom: var(--space-md);
		opacity: 0.3;
	}

	.empty-text {
		font-size: var(--text-base);
		margin-bottom: var(--space-sm);
	}

	.empty-hint {
		font-size: var(--text-sm);
		color: var(--text-dim);
	}

	.skeleton-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-md);
	}

	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-md);
	}

	.skeleton-card {
		height: 160px;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}

	@media (max-width: 640px) {
		.device-cards {
			grid-template-columns: 1fr;
		}
	}
</style>
