<script lang="ts">
	/**
	 * Device Inventory — Sortable, searchable table of all discovered network devices.
	 *
	 * Features:
	 *   - Search by IP, hostname, or manufacturer
	 *   - Sortable columns (click header to toggle asc/desc)
	 *   - Click row to navigate to /devices/{ip}
	 *   - Auto-refresh toggle (30s interval)
	 *   - Loading skeletons, empty state, device count badge
	 */

	import { goto } from '$app/navigation';
	import { getDevices } from '$api/devices';
	import type { Device, DeviceListResponse } from '$api/devices';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	let devices = $state<Device[]>([]);
	let searchQuery = $state('');
	let sortColumn = $state<keyof Device>('last_seen');
	let sortDirection = $state<'asc' | 'desc'>('desc');
	let autoRefresh = $state(false);
	let lastUpdated = $state('');

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchDevices() {
		loading = true;
		try {
			const response: DeviceListResponse = await getDevices({
				sort: sortColumn,
				order: sortDirection,
				limit: 500,
			});
			devices = response.devices;
			lastUpdated = new Date().toLocaleTimeString();
		} catch {
			devices = [];
		} finally {
			loading = false;
		}
	}

	// Initial fetch + auto-refresh
	$effect(() => {
		fetchDevices();

		if (autoRefresh) {
			const interval = setInterval(fetchDevices, 30_000);
			return () => clearInterval(interval);
		}
	});

	// ---------------------------------------------------------------------------
	// Filtering & sorting
	// ---------------------------------------------------------------------------

	let filteredDevices = $derived.by(() => {
		let result = devices;

		// Search filter
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase().trim();
			result = result.filter(
				(d) =>
					d.ip.toLowerCase().includes(q) ||
					(d.hostname && d.hostname.toLowerCase().includes(q)) ||
					(d.manufacturer && d.manufacturer.toLowerCase().includes(q))
			);
		}

		// Client-side sort
		result = [...result].sort((a, b) => {
			const aVal = a[sortColumn];
			const bVal = b[sortColumn];

			if (aVal == null && bVal == null) return 0;
			if (aVal == null) return 1;
			if (bVal == null) return -1;

			let cmp = 0;
			if (typeof aVal === 'number' && typeof bVal === 'number') {
				cmp = aVal - bVal;
			} else {
				cmp = String(aVal).localeCompare(String(bVal));
			}

			return sortDirection === 'asc' ? cmp : -cmp;
		});

		return result;
	});

	// ---------------------------------------------------------------------------
	// Sort handler
	// ---------------------------------------------------------------------------

	type SortableColumn = 'ip' | 'hostname' | 'manufacturer' | 'os_hint' | 'total_bytes' | 'connection_count' | 'alert_count' | 'last_seen';

	const columnDefs: { key: SortableColumn; label: string }[] = [
		{ key: 'ip', label: 'IP Address' },
		{ key: 'hostname', label: 'Hostname' },
		{ key: 'manufacturer', label: 'Manufacturer' },
		{ key: 'os_hint', label: 'OS' },
		{ key: 'total_bytes', label: 'Bandwidth' },
		{ key: 'connection_count', label: 'Connections' },
		{ key: 'alert_count', label: 'Alerts' },
		{ key: 'last_seen', label: 'Last Seen' },
	];

	function handleSort(column: SortableColumn) {
		if (sortColumn === column) {
			sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			sortColumn = column;
			sortDirection = column === 'last_seen' || column === 'total_bytes' || column === 'connection_count' || column === 'alert_count' ? 'desc' : 'asc';
		}
	}

	function getSortIndicator(column: SortableColumn): string {
		if (sortColumn !== column) return '';
		return sortDirection === 'asc' ? ' \u2191' : ' \u2193';
	}

	// ---------------------------------------------------------------------------
	// Navigation
	// ---------------------------------------------------------------------------

	function navigateToDevice(ip: string) {
		goto(`/devices/${encodeURIComponent(ip)}`);
	}

	// ---------------------------------------------------------------------------
	// Formatting helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	function timeAgo(dateStr: string): string {
		if (!dateStr) return '--';
		const d = new Date(dateStr);
		const now = new Date();
		const diffMs = now.getTime() - d.getTime();
		const mins = Math.floor(diffMs / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}
</script>

<svelte:head>
	<title>Devices | NetTap</title>
</svelte:head>

<div class="devices-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<div class="header-title-row">
				<h2>Device Inventory</h2>
				{#if !loading}
					<span class="badge badge-accent">{filteredDevices.length} device{filteredDevices.length !== 1 ? 's' : ''}</span>
				{/if}
			</div>
			<p class="text-muted">All discovered devices on the network, with traffic and alert summaries.</p>
		</div>
		<div class="header-actions">
			{#if lastUpdated}
				<span class="last-updated">Updated {lastUpdated}</span>
			{/if}
			<button
				class="btn btn-sm"
				class:btn-primary={autoRefresh}
				class:btn-secondary={!autoRefresh}
				onclick={() => (autoRefresh = !autoRefresh)}
				title={autoRefresh ? 'Auto-refresh ON (30s)' : 'Auto-refresh OFF'}
			>
				<svg class="refresh-icon" class:spinning={autoRefresh && loading} viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
					<path d="M8 2.002a5.998 5.998 0 103.906 10.531.75.75 0 01.984 1.131A7.5 7.5 0 118 .5a7.47 7.47 0 015.217 2.118l.146-.152a.75.75 0 011.072 1.046l-2.038 2.094a.75.75 0 01-1.072.009L9.287 3.508a.75.75 0 011.07-1.05l.206.208A5.97 5.97 0 008 2.002z" />
				</svg>
				{autoRefresh ? 'Auto' : 'Paused'}
			</button>
			<button class="btn btn-sm btn-secondary" onclick={fetchDevices} disabled={loading}>
				Refresh
			</button>
		</div>
	</div>

	<!-- Search input -->
	<div class="search-bar">
		<div class="search-input-wrapper">
			<svg class="search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
			</svg>
			<input
				type="text"
				class="input search-input"
				placeholder="Search by IP, hostname, or manufacturer..."
				bind:value={searchQuery}
			/>
			{#if searchQuery}
				<button class="search-clear" onclick={() => (searchQuery = '')} aria-label="Clear search">
					<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
					</svg>
				</button>
			{/if}
		</div>
	</div>

	<!-- Device table -->
	{#if loading && devices.length === 0}
		<!-- Loading skeletons -->
		<div class="card table-card">
			<div class="skeleton-table">
				<div class="skeleton skeleton-header"></div>
				{#each Array(8) as _}
					<div class="skeleton skeleton-row"></div>
				{/each}
			</div>
		</div>
	{:else if filteredDevices.length === 0}
		<!-- Empty state -->
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
				</svg>
			</div>
			{#if searchQuery}
				<h3>No Matching Devices</h3>
				<p class="text-muted">
					No devices match "{searchQuery}". Try adjusting your search terms.
				</p>
				<button class="btn btn-secondary btn-sm" onclick={() => (searchQuery = '')}>Clear Search</button>
			{:else}
				<h3>No Devices Found</h3>
				<p class="text-muted">
					Devices will appear here once the network bridge is configured and traffic is flowing
					through the appliance. Make sure Zeek is running and generating connection logs.
				</p>
			{/if}
		</div>
	{:else}
		<div class="card table-card">
			<div class="table-scroll">
				<table class="data-table">
					<thead>
						<tr>
							{#each columnDefs as col}
								<th>
									<button class="sort-btn" class:active-sort={sortColumn === col.key} onclick={() => handleSort(col.key)}>
										{col.label}{getSortIndicator(col.key)}
									</button>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each filteredDevices as device (device.ip)}
							<tr class="device-row" onclick={() => navigateToDevice(device.ip)} role="link" tabindex="0" onkeydown={(e) => { if (e.key === 'Enter') navigateToDevice(device.ip); }}>
								<td class="mono ip-cell">{device.ip}</td>
								<td class="hostname-cell">{device.hostname || '--'}</td>
								<td>{device.manufacturer || '--'}</td>
								<td>{device.os_hint || '--'}</td>
								<td class="mono">{formatBytes(device.total_bytes)}</td>
								<td class="mono">{formatNumber(device.connection_count)}</td>
								<td>
									{#if device.alert_count > 0}
										<span class="badge badge-danger">{formatNumber(device.alert_count)}</span>
									{:else}
										<span class="text-muted">0</span>
									{/if}
								</td>
								<td class="last-seen-cell" title={device.last_seen ? new Date(device.last_seen).toLocaleString() : ''}>
									{timeAgo(device.last_seen)}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>

<style>
	.devices-page {
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

	.header-title-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
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

	.last-updated {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.refresh-icon {
		flex-shrink: 0;
	}

	.refresh-icon.spinning {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Search */
	.search-bar {
		max-width: 480px;
	}

	.search-input-wrapper {
		position: relative;
		display: flex;
		align-items: center;
	}

	.search-icon {
		position: absolute;
		left: var(--space-sm);
		color: var(--text-muted);
		pointer-events: none;
	}

	.search-input {
		padding-left: calc(var(--space-sm) + 16px + var(--space-sm));
		padding-right: calc(var(--space-sm) + 14px + var(--space-sm));
	}

	.search-clear {
		position: absolute;
		right: var(--space-sm);
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: 2px;
		display: flex;
		align-items: center;
	}

	.search-clear:hover {
		color: var(--text-primary);
	}

	/* Table */
	.table-card {
		padding: 0;
	}

	.table-scroll {
		overflow-x: auto;
	}

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	.data-table th {
		text-align: left;
		font-weight: 600;
		color: var(--text-secondary);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-default);
		background-color: var(--bg-secondary);
		position: sticky;
		top: 0;
		white-space: nowrap;
	}

	.data-table td {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-muted);
		color: var(--text-primary);
		white-space: nowrap;
	}

	.data-table tbody tr:last-child td {
		border-bottom: none;
	}

	/* Sortable headers */
	.sort-btn {
		background: none;
		border: none;
		color: var(--text-secondary);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		cursor: pointer;
		padding: 0;
		white-space: nowrap;
		transition: color var(--transition-fast);
	}

	.sort-btn:hover {
		color: var(--text-primary);
	}

	.sort-btn.active-sort {
		color: var(--accent);
	}

	/* Clickable rows */
	.device-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.device-row:hover {
		background-color: var(--bg-tertiary);
	}

	.device-row:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.ip-cell {
		font-size: var(--text-sm);
		color: var(--accent);
		font-weight: 500;
	}

	.hostname-cell {
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.last-seen-cell {
		color: var(--text-secondary);
	}

	/* Empty state */
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		text-align: center;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
	}

	.empty-icon {
		color: var(--text-muted);
		margin-bottom: var(--space-md);
	}

	.empty-state h3 {
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.empty-state p {
		max-width: 480px;
		line-height: var(--leading-relaxed);
		margin-bottom: var(--space-md);
	}

	/* Skeleton loading */
	.skeleton-table {
		padding: var(--space-md);
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

	.skeleton-header {
		height: 36px;
		width: 100%;
	}

	.skeleton-row {
		height: 40px;
		width: 100%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}

	/* Responsive */
	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.header-actions {
			width: 100%;
			justify-content: flex-end;
		}

		.search-bar {
			max-width: 100%;
		}
	}
</style>
