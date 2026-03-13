<script lang="ts">
	/**
	 * Device Inventory — Sortable, searchable table of all discovered network devices.
	 *
	 * Features:
	 *   - Search by IP, hostname, or manufacturer
	 *   - Sortable columns (click header to toggle asc/desc)
	 *   - Inline expandable detail panel with recent connections
	 *   - Risk score badges (green/amber/red)
	 *   - "NEW" badge for devices first seen < 24h ago
	 *   - Auto-refresh toggle (30s interval)
	 *   - Loading skeletons, empty state, device count badge
	 */

	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getDevices, getDeviceConnections } from '$api/devices';
	import type { Device, DeviceListResponse, DeviceConnection, DeviceConnectionsResponse } from '$api/devices';
	import { getRiskScores } from '$api/risk';
	import type { DeviceRiskScore } from '$api/risk';
	import IPAddress from '$components/IPAddress.svelte';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import DeviceDrawerContent from '$components/drawer/content/DeviceDrawerContent.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	let devices = $state<Device[]>([]);
	let riskScores = $state<Map<string, DeviceRiskScore>>(new Map());
	let searchQuery = $state('');
	let sortColumn = $state<string>('last_seen');
	let sortDirection = $state<'asc' | 'desc'>('desc');
	let autoRefresh = $state(false);
	let lastUpdated = $state('');
	// OLD CODE START — replaced by DetailDrawer
	// let expandedIp = $state<string | null>(null);
	// let expandedConnections = $state<DeviceConnection[]>([]);
	// let expandedLoading = $state(false);
	// OLD CODE END

	// Detail drawer state
	let drawerDevice = $state<Device | null>(null);
	let drawerTab = $state('overview');
	const DEVICE_DRAWER_TABS = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'connections', label: 'Connections' },
		{ id: 'traffic', label: 'Traffic' },
	];

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchDevices() {
		loading = true;
		try {
			const [deviceRes, riskRes] = await Promise.all([
				getDevices({ sort: sortColumn, order: sortDirection, limit: 500 }),
				getRiskScores()
			]);
			devices = deviceRes.devices;

			const scoreMap = new Map<string, DeviceRiskScore>();
			for (const s of riskRes.scores) {
				scoreMap.set(s.ip, s);
			}
			riskScores = scoreMap;

			lastUpdated = new Date().toLocaleTimeString();
		} catch {
			devices = [];
		} finally {
			loading = false;
		}
	}

	// OLD CODE START — fetchConnections moved to DeviceDrawerContent
	// async function fetchConnections(ip: string) { ... }
	// OLD CODE END

	// Initial fetch + auto-refresh
	onMount(() => {
		fetchDevices();
	});

	$effect(() => {
		if (autoRefresh) {
			const interval = setInterval(fetchDevices, 30_000);
			return () => clearInterval(interval);
		}
	});

	// ---------------------------------------------------------------------------
	// Expand/collapse
	// ---------------------------------------------------------------------------

	// OLD CODE START — replaced by DetailDrawer
	// function toggleExpand(ip: string) { ... }
	// OLD CODE END

	function openDrawer(device: Device) {
		drawerDevice = device;
		drawerTab = 'overview';
	}

	function closeDrawer() {
		drawerDevice = null;
		drawerTab = 'overview';
	}

	// ---------------------------------------------------------------------------
	// Filtering & sorting
	// ---------------------------------------------------------------------------

	let filteredDevices = $derived.by(() => {
		let result = devices;

		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase().trim();
			result = result.filter(
				(d) =>
					d.ip.toLowerCase().includes(q) ||
					(d.hostname && d.hostname.toLowerCase().includes(q)) ||
					(d.manufacturer && d.manufacturer.toLowerCase().includes(q))
			);
		}

		result = [...result].sort((a, b) => {
			let aVal: unknown;
			let bVal: unknown;

			// Special case: risk_score is from the riskScores map
			if (sortColumn === 'risk_score') {
				aVal = riskScores.get(a.ip)?.score ?? -1;
				bVal = riskScores.get(b.ip)?.score ?? -1;
			} else {
				aVal = a[sortColumn as keyof Device];
				bVal = b[sortColumn as keyof Device];
			}

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

	type SortableColumn = 'ip' | 'hostname' | 'mac' | 'manufacturer' | 'first_seen' | 'last_seen' | 'total_bytes' | 'connection_count' | 'risk_score';

	const columnDefs: { key: SortableColumn; label: string }[] = [
		{ key: 'ip', label: 'IP Address' },
		{ key: 'hostname', label: 'Hostname' },
		{ key: 'mac', label: 'MAC' },
		{ key: 'manufacturer', label: 'Manufacturer' },
		{ key: 'first_seen', label: 'First Seen' },
		{ key: 'last_seen', label: 'Last Seen' },
		{ key: 'total_bytes', label: 'Total Bytes' },
		{ key: 'connection_count', label: 'Connections' },
		{ key: 'risk_score', label: 'Risk Score' },
	];

	function handleSort(column: SortableColumn) {
		if (sortColumn === column) {
			sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			sortColumn = column;
			sortDirection = column === 'last_seen' || column === 'first_seen' || column === 'total_bytes' || column === 'connection_count' || column === 'risk_score' ? 'desc' : 'asc';
		}
	}

	function getSortIndicator(column: SortableColumn): string {
		if (sortColumn !== column) return '';
		return sortDirection === 'asc' ? ' \u2191' : ' \u2193';
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function isNewDevice(firstSeen: string): boolean {
		if (!firstSeen) return false;
		const diff = Date.now() - new Date(firstSeen).getTime();
		return diff < 24 * 60 * 60 * 1000;
	}

	function getRiskBadgeClass(score: number): string {
		if (score <= 30) return 'badge-success';
		if (score <= 60) return 'badge-warning';
		return 'badge-danger';
	}

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

	/**
	 * Safely access nested ECS fields (e.g. "destination.ip", "network.transport").
	 * OpenSearch returns ECS data as nested objects, not flat Zeek field names.
	 */
	function getField(obj: Record<string, unknown>, path: string): unknown {
		const parts = path.split('.');
		let current: unknown = obj;
		for (const part of parts) {
			if (current == null || typeof current !== 'object') return undefined;
			current = (current as Record<string, unknown>)[part];
		}
		return current;
	}

	/**
	 * Coerce an ECS field value to a string. In Arkime/Malcolm OpenSearch data,
	 * fields like network.transport and network.protocol are arrays (e.g. ["tcp"]),
	 * not plain strings. This helper safely extracts the first element.
	 */
	function asString(val: unknown): string {
		if (Array.isArray(val)) return String(val[0] ?? '');
		if (typeof val === 'string') return val;
		if (val != null) return String(val);
		return '';
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
			<p class="text-muted">All discovered devices on the network, with traffic and risk summaries.</p>
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
							{@const risk = riskScores.get(device.ip)}
							{@const isNew = isNewDevice(device.first_seen)}
							{@const isExpanded = drawerDevice?.ip === device.ip}
							<tr
								class="device-row"
								class:expanded={isExpanded}
								onclick={() => goto(`/devices/${encodeURIComponent(device.ip)}`)}
								role="button"
								tabindex="0"
								onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goto(`/devices/${encodeURIComponent(device.ip)}`); } }}
							>
								<td class="mono ip-cell">
									<IPAddress ip={device.ip} />
									{#if isNew}
										<span class="badge badge-info badge-inline">NEW</span>
									{/if}
								</td>
								<td class="hostname-cell">{device.hostname || '--'}</td>
								<td class="mono mac-cell">{device.mac || '--'}</td>
								<td>{device.manufacturer || '--'}</td>
								<td class="time-cell" title={device.first_seen ? new Date(device.first_seen).toLocaleString() : ''}>
									{timeAgo(device.first_seen)}
								</td>
								<td class="time-cell" title={device.last_seen ? new Date(device.last_seen).toLocaleString() : ''}>
									{timeAgo(device.last_seen)}
								</td>
								<td class="mono">{formatBytes(device.total_bytes)}</td>
								<td class="mono">{formatNumber(device.connection_count)}</td>
								<td>
									{#if risk}
										<span class="badge {getRiskBadgeClass(risk.score)}">{risk.score}</span>
									{:else}
										<span class="text-muted">--</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerDevice !== null}
	title={drawerDevice ? (drawerDevice.hostname || drawerDevice.ip) : ''}
	subtitle={drawerDevice ? (drawerDevice.manufacturer || drawerDevice.mac || '') : ''}
	tabs={DEVICE_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => drawerTab = t}
>
	{#snippet children()}
		{#if drawerDevice}
			<DeviceDrawerContent device={drawerDevice} activeTab={drawerTab} />
		{/if}
	{/snippet}
	{#snippet actions()}
		{#if drawerDevice}
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(drawerDevice!.ip)}`)}>
				View Full Device Page
			</button>
			<button class="btn btn-secondary btn-sm" onclick={() => goto(`/logs?filter=${encodeURIComponent(drawerDevice!.ip)}`)}>
				View in Log Explorer
			</button>
		{/if}
	{/snippet}
</DetailDrawer>

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
		width: 100%;
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

	.device-row.expanded {
		background-color: var(--bg-tertiary);
	}

	.ip-cell {
		font-size: var(--text-sm);
		color: var(--accent);
		font-weight: 500;
	}

	.badge-inline {
		margin-left: var(--space-xs);
		font-size: 0.625rem;
		vertical-align: middle;
	}

	.hostname-cell {
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.mac-cell {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.time-cell {
		color: var(--text-secondary);
	}

	/* Detail panel */
	.detail-row td {
		padding: 0 !important;
		border-bottom: 1px solid var(--border-default) !important;
	}

	.detail-panel {
		padding: var(--space-lg);
		background-color: var(--bg-primary);
		border-top: 1px solid var(--border-default);
	}

	.detail-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-xl);
	}

	.detail-section h4 {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-bottom: var(--space-md);
		padding-bottom: var(--space-xs);
		border-bottom: 1px solid var(--border-dim);
	}

	.detail-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.detail-item {
		display: flex;
		align-items: baseline;
		gap: var(--space-md);
	}

	.detail-item dt {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		min-width: 100px;
		flex-shrink: 0;
	}

	.detail-item dd {
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	.protocol-badge {
		margin-right: var(--space-xs);
	}

	.detail-link {
		margin-top: var(--space-sm);
	}

	.detail-loading {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md) 0;
	}

	.connections-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.connection-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
	}

	.connection-item:hover {
		background-color: var(--bg-secondary);
	}

	.conn-time {
		color: var(--text-muted);
		min-width: 60px;
	}

	.conn-id {
		color: var(--text-secondary);
		font-size: var(--text-xs);
		margin-left: auto;
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
			width: 100%;
		}

		.detail-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
