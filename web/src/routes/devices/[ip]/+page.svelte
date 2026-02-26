<script lang="ts">
	/**
	 * Per-Device Activity — Detailed view for a single network device.
	 *
	 * Layout:
	 *   - Back button, device header with IP, hostname, MAC, manufacturer, OS
	 *   - Stat cards row: Bandwidth, Connections, Alerts, First Seen
	 *   - Bandwidth over time chart (TimeSeriesChart)
	 *   - Top destinations table
	 *   - DNS queries table
	 *   - Recent connections table (paginated)
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import TimeSeriesChart from '$components/charts/TimeSeriesChart.svelte';
	import { getDeviceDetail, getDeviceConnections } from '$api/devices';
	import type {
		DeviceDetail,
		DeviceDetailResponse,
		DeviceConnection,
		DeviceConnectionsResponse,
	} from '$api/devices';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let deviceIp = $derived(decodeURIComponent($page.params.ip ?? ''));

	let loading = $state(true);
	let device = $state<DeviceDetail | null>(null);

	let connections = $state<DeviceConnection[]>([]);
	let connectionsLoading = $state(false);
	let connectionsPage = $state(1);
	let connectionsTotalPages = $state(0);
	let connectionsTotal = $state(0);
	const connectionsPageSize = 25;

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchDevice() {
		loading = true;
		try {
			const response: DeviceDetailResponse = await getDeviceDetail(deviceIp);
			device = response.device;
		} catch {
			device = null;
		} finally {
			loading = false;
		}
	}

	async function fetchConnections(pageNum: number = 1) {
		connectionsLoading = true;
		try {
			const response: DeviceConnectionsResponse = await getDeviceConnections(deviceIp, {
				page: pageNum,
				size: connectionsPageSize,
			});
			connections = response.connections;
			connectionsPage = response.page;
			connectionsTotalPages = response.total_pages;
			connectionsTotal = response.total;
		} catch {
			connections = [];
		} finally {
			connectionsLoading = false;
		}
	}

	// Initial fetch
	$effect(() => {
		fetchDevice();
		fetchConnections(1);
	});

	// ---------------------------------------------------------------------------
	// Pagination
	// ---------------------------------------------------------------------------

	function goToPage(pageNum: number) {
		if (pageNum < 1 || pageNum > connectionsTotalPages) return;
		fetchConnections(pageNum);
	}

	// ---------------------------------------------------------------------------
	// Chart data
	// ---------------------------------------------------------------------------

	let bandwidthChartData = $derived(
		device?.bandwidth_series?.map((p) => ({
			time: p.timestamp,
			value: p.bytes,
		})) ?? []
	);

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

	function formatBytesShort(bytes: number): string {
		if (bytes === 0) return '0';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const value = bytes / Math.pow(1024, i);
		return `${value.toFixed(value >= 10 ? 0 : 1)}${units[i]}`;
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

	function formatDate(dateStr: string): string {
		if (!dateStr) return '--';
		try {
			return new Date(dateStr).toLocaleDateString(undefined, {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
			});
		} catch {
			return dateStr;
		}
	}

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '--';
		try {
			return new Date(ts).toLocaleString();
		} catch {
			return ts;
		}
	}
</script>

<svelte:head>
	<title>{deviceIp} | Devices | NetTap</title>
</svelte:head>

<div class="device-detail-page">
	<!-- Back button -->
	<div class="back-nav">
		<button class="btn btn-secondary btn-sm" onclick={() => goto('/devices')}>
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
			</svg>
			Back to Devices
		</button>
	</div>

	{#if loading && !device}
		<!-- Loading state -->
		<div class="loading-state">
			<div class="skeleton skeleton-header-block"></div>
			<div class="grid grid-cols-4 stat-grid">
				{#each Array(4) as _}
					<div class="skeleton skeleton-stat"></div>
				{/each}
			</div>
			<div class="skeleton skeleton-chart-block"></div>
		</div>
	{:else if !device || (!device.ip && !device.hostname)}
		<!-- Error / not found -->
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
				</svg>
			</div>
			<h3>Device Not Found</h3>
			<p class="text-muted">
				No data available for {deviceIp}. The device may not have been seen on the network yet.
			</p>
			<button class="btn btn-secondary btn-sm" onclick={() => goto('/devices')}>Return to Device Inventory</button>
		</div>
	{:else}
		<!-- Device header -->
		<div class="device-header card">
			<div class="device-header-main">
				<div class="device-ip-row">
					<h2 class="mono">{device.ip}</h2>
					{#if device.alert_count > 0}
						<span class="badge badge-danger">{device.alert_count} alert{device.alert_count !== 1 ? 's' : ''}</span>
					{/if}
				</div>
				<div class="device-meta">
					{#if device.hostname}
						<span class="meta-item">
							<span class="meta-label">Hostname</span>
							<span class="meta-value">{device.hostname}</span>
						</span>
					{/if}
					{#if device.manufacturer}
						<span class="meta-item">
							<span class="meta-label">Manufacturer</span>
							<span class="meta-value">{device.manufacturer}</span>
						</span>
					{/if}
					{#if device.mac}
						<span class="meta-item">
							<span class="meta-label">MAC</span>
							<span class="meta-value mono">{device.mac}</span>
						</span>
					{/if}
					{#if device.os_hint}
						<span class="meta-item">
							<span class="meta-label">OS</span>
							<span class="meta-value">{device.os_hint}</span>
						</span>
					{/if}
					{#if device.protocols && device.protocols.length > 0}
						<span class="meta-item">
							<span class="meta-label">Protocols</span>
							<span class="meta-value protocols-list">
								{#each device.protocols.slice(0, 8) as proto}
									<span class="badge">{proto}</span>
								{/each}
								{#if device.protocols.length > 8}
									<span class="text-muted">+{device.protocols.length - 8} more</span>
								{/if}
							</span>
						</span>
					{/if}
				</div>
			</div>
		</div>

		<!-- Stat cards -->
		<div class="grid grid-cols-4 stat-grid">
			<div class="card stat-card">
				<div class="card-header">
					<span class="card-subtitle">Total Bandwidth</span>
					<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
					</svg>
				</div>
				<div class="card-value">{formatBytes(device.total_bytes)}</div>
			</div>

			<div class="card stat-card">
				<div class="card-header">
					<span class="card-subtitle">Connections</span>
					<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
					</svg>
				</div>
				<div class="card-value">{formatNumber(device.connection_count)}</div>
			</div>

			<div class="card stat-card">
				<div class="card-header">
					<span class="card-subtitle">Alerts</span>
					<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--warning)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" />
					</svg>
				</div>
				<div class="card-value">
					{#if device.alert_count > 0}
						<span class="text-danger">{formatNumber(device.alert_count)}</span>
					{:else}
						<span class="text-success">0</span>
					{/if}
				</div>
			</div>

			<div class="card stat-card">
				<div class="card-header">
					<span class="card-subtitle">First Seen</span>
					<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--text-secondary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
					</svg>
				</div>
				<div class="card-value first-seen-value">{formatDate(device.first_seen)}</div>
			</div>
		</div>

		<!-- Bandwidth chart -->
		<div class="card chart-card">
			<div class="card-header">
				<span class="card-title">Bandwidth Over Time</span>
				<span class="card-subtitle">Traffic volume trend</span>
			</div>
			{#if bandwidthChartData.length === 0}
				<div class="chart-empty">
					<p class="text-muted">No bandwidth data available for this device.</p>
				</div>
			{:else}
				<TimeSeriesChart
					data={bandwidthChartData}
					height={260}
					color="var(--accent)"
					label="Bytes"
					formatValue={formatBytesShort}
				/>
			{/if}
		</div>

		<!-- Top destinations + DNS queries -->
		<div class="grid grid-cols-2 tables-grid">
			<!-- Top destinations -->
			<div class="card table-card">
				<div class="card-header">
					<span class="card-title">Top Destinations</span>
					<span class="card-subtitle">By traffic volume</span>
				</div>
				{#if !device.top_destinations || device.top_destinations.length === 0}
					<div class="table-empty">
						<p class="text-muted">No destination data available.</p>
					</div>
				{:else}
					<div class="table-scroll">
						<table class="data-table">
							<thead>
								<tr>
									<th>Destination IP</th>
									<th>Bytes</th>
									<th>Connections</th>
								</tr>
							</thead>
							<tbody>
								{#each device.top_destinations as dest}
									<tr>
										<td class="mono ip-cell">{dest.ip}</td>
										<td class="mono">{formatBytes(dest.bytes)}</td>
										<td class="mono">{formatNumber(dest.connections)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>

			<!-- DNS queries -->
			<div class="card table-card">
				<div class="card-header">
					<span class="card-title">DNS Queries</span>
					<span class="card-subtitle">Domains queried by this device</span>
				</div>
				{#if !device.dns_queries || device.dns_queries.length === 0}
					<div class="table-empty">
						<p class="text-muted">No DNS query data available.</p>
					</div>
				{:else}
					<div class="table-scroll">
						<table class="data-table">
							<thead>
								<tr>
									<th>Domain</th>
									<th>Count</th>
								</tr>
							</thead>
							<tbody>
								{#each device.dns_queries as query}
									<tr>
										<td class="mono domain-cell">{query.domain}</td>
										<td class="mono">{formatNumber(query.count)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</div>
		</div>

		<!-- Recent connections -->
		<div class="card table-card connections-card">
			<div class="card-header">
				<div>
					<span class="card-title">Recent Connections</span>
					{#if connectionsTotal > 0}
						<span class="card-subtitle">{connectionsTotal.toLocaleString()} total connections</span>
					{/if}
				</div>
				{#if connectionsLoading}
					<span class="text-muted" style="font-size: var(--text-xs);">Loading...</span>
				{/if}
			</div>

			{#if connectionsLoading && connections.length === 0}
				<div class="skeleton-table">
					{#each Array(5) as _}
						<div class="skeleton skeleton-row"></div>
					{/each}
				</div>
			{:else if connections.length === 0}
				<div class="table-empty">
					<p class="text-muted">No connection records found for this device.</p>
				</div>
			{:else}
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th>Timestamp</th>
								<th>Protocol</th>
								<th>Service</th>
								<th>Destination</th>
							</tr>
						</thead>
						<tbody>
							{#each connections as conn (conn._id)}
								<tr>
									<td class="mono timestamp-cell">{formatTimestamp(conn.ts)}</td>
									<td>
										{#if conn.proto}
											<span class="badge">{conn.proto}</span>
										{:else}
											<span class="text-muted">--</span>
										{/if}
									</td>
									<td>{conn.service || '--'}</td>
									<td class="mono ip-cell">{conn['id.resp_h'] as string || conn['dest_ip'] as string || '--'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- Pagination -->
				{#if connectionsTotalPages > 1}
					<div class="pagination">
						<button
							class="btn btn-secondary btn-sm"
							disabled={connectionsPage <= 1 || connectionsLoading}
							onclick={() => goToPage(connectionsPage - 1)}
						>
							Previous
						</button>
						<span class="pagination-info">
							Page {connectionsPage} of {connectionsTotalPages}
						</span>
						<button
							class="btn btn-secondary btn-sm"
							disabled={connectionsPage >= connectionsTotalPages || connectionsLoading}
							onclick={() => goToPage(connectionsPage + 1)}
						>
							Next
						</button>
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.device-detail-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Back nav */
	.back-nav {
		display: flex;
	}

	/* Device header */
	.device-header {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.device-ip-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.device-ip-row h2 {
		font-size: var(--text-3xl);
		font-weight: 700;
		color: var(--accent);
	}

	.device-meta {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-lg);
	}

	.meta-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.meta-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.meta-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
	}

	.protocols-list {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
		align-items: center;
	}

	/* Stat cards */
	.stat-grid {
		margin-top: var(--space-xs);
	}

	.stat-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.stat-icon {
		flex-shrink: 0;
		opacity: 0.7;
	}

	.first-seen-value {
		font-size: var(--text-lg);
	}

	/* Chart */
	.chart-card {
		min-height: 320px;
	}

	.chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
	}

	/* Tables */
	.tables-grid {
		margin-top: var(--space-xs);
	}

	.table-card {
		padding: 0;
	}

	.table-card .card-header {
		padding: var(--space-lg) var(--space-lg) var(--space-sm) var(--space-lg);
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
		white-space: nowrap;
	}

	.data-table td {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-muted);
		color: var(--text-primary);
	}

	.data-table tbody tr:hover {
		background-color: var(--bg-tertiary);
	}

	.data-table tbody tr:last-child td {
		border-bottom: none;
	}

	.ip-cell {
		font-size: var(--text-sm);
		color: var(--accent);
		white-space: nowrap;
	}

	.domain-cell {
		font-size: var(--text-sm);
		word-break: break-all;
	}

	.timestamp-cell {
		font-size: var(--text-xs);
		white-space: nowrap;
		color: var(--text-secondary);
	}

	.table-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 120px;
		padding: var(--space-lg);
	}

	/* Connections card */
	.connections-card .card-header {
		flex-direction: row;
		align-items: center;
	}

	.connections-card .card-header > div {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	/* Pagination */
	.pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-md);
		border-top: 1px solid var(--border-muted);
	}

	.pagination-info {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	/* Loading & empty states */
	.loading-state {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

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
	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
	}

	.skeleton-header-block {
		height: 120px;
		width: 100%;
		border-radius: var(--radius-lg);
	}

	.skeleton-stat {
		height: 100px;
		width: 100%;
		border-radius: var(--radius-lg);
	}

	.skeleton-chart-block {
		height: 320px;
		width: 100%;
		border-radius: var(--radius-lg);
	}

	.skeleton-table {
		padding: var(--space-md);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.skeleton-row {
		height: 36px;
		width: 100%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}

	/* Responsive */
	@media (max-width: 1024px) {
		.device-meta {
			gap: var(--space-md);
		}
	}

	@media (max-width: 768px) {
		.device-ip-row h2 {
			font-size: var(--text-2xl);
		}

		.device-meta {
			flex-direction: column;
			gap: var(--space-sm);
		}
	}
</style>
