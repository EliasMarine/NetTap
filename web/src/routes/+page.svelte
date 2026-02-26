<script lang="ts">
	/**
	 * Dashboard Home — Live network visibility overview.
	 *
	 * Row 1: Stat cards (bandwidth, connections, alerts, system health)
	 * Row 2: Bandwidth time series chart + Protocol distribution donut
	 * Row 3: Top talkers table + Recent alerts table
	 *
	 * Auto-refresh toggle (30s interval), loading skeletons, error fallback.
	 */

	import TimeSeriesChart from '$components/charts/TimeSeriesChart.svelte';
	import DonutChart from '$components/charts/DonutChart.svelte';
	import { getTrafficSummary, getBandwidthTimeSeries, getProtocolDistribution, getTopTalkers } from '$api/traffic';
	import type { TrafficSummary, BandwidthPoint, ProtocolEntry, TopTalker } from '$api/traffic';
	import { getAlertCount, getAlerts } from '$api/alerts';
	import type { AlertCountResponse, Alert } from '$api/alerts';
	import { getSystemHealth } from '$api/system';
	import type { SystemHealth } from '$api/system';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let autoRefresh = $state(true);
	let loading = $state(true);
	let error = $state(false);
	let lastUpdated = $state('');

	// Data stores
	let trafficSummary = $state<TrafficSummary | null>(null);
	let bandwidthData = $state<BandwidthPoint[]>([]);
	let protocols = $state<ProtocolEntry[]>([]);
	let topTalkers = $state<TopTalker[]>([]);
	let alertCount = $state<AlertCountResponse | null>(null);
	let recentAlerts = $state<Alert[]>([]);
	let systemHealth = $state<SystemHealth | null>(null);

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAllData() {
		loading = true;
		error = false;

		try {
			const [summaryRes, bandwidthRes, protocolsRes, talkersRes, alertCountRes, alertsRes, healthRes] =
				await Promise.allSettled([
					getTrafficSummary(),
					getBandwidthTimeSeries({ interval: '1h' }),
					getProtocolDistribution(),
					getTopTalkers({ limit: 10 }),
					getAlertCount(),
					getAlerts({ size: 10 }),
					getSystemHealth(),
				]);

			trafficSummary = summaryRes.status === 'fulfilled' ? summaryRes.value : null;
			bandwidthData = bandwidthRes.status === 'fulfilled' ? bandwidthRes.value.series : [];
			protocols = protocolsRes.status === 'fulfilled' ? protocolsRes.value.protocols : [];
			topTalkers = talkersRes.status === 'fulfilled' ? talkersRes.value.top_talkers : [];
			alertCount = alertCountRes.status === 'fulfilled' ? alertCountRes.value : null;
			recentAlerts = alertsRes.status === 'fulfilled' ? alertsRes.value.alerts : [];
			systemHealth = healthRes.status === 'fulfilled' ? healthRes.value : null;

			lastUpdated = new Date().toLocaleTimeString();

			// Check if all failed (daemon unreachable)
			const allFailed = [summaryRes, bandwidthRes, protocolsRes, talkersRes, alertCountRes, alertsRes, healthRes]
				.every((r) => r.status === 'rejected');
			if (allFailed) {
				error = true;
			}
		} catch {
			error = true;
		} finally {
			loading = false;
		}
	}

	// Auto-refresh effect
	$effect(() => {
		fetchAllData();

		if (autoRefresh) {
			const interval = setInterval(fetchAllData, 30_000);
			return () => clearInterval(interval);
		}
	});

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

	// Protocol colors for donut chart
	const PROTOCOL_COLORS = [
		'#58a6ff', // accent blue
		'#3fb950', // green
		'#d29922', // amber
		'#f85149', // red
		'#bc8cff', // purple
		'#79c0ff', // light blue
		'#8b949e', // grey (other)
	];

	// Severity badge helper
	function severityBadge(severity: number | undefined): { label: string; class: string } {
		switch (severity) {
			case 1:
				return { label: 'HIGH', class: 'badge badge-danger' };
			case 2:
				return { label: 'MEDIUM', class: 'badge badge-warning' };
			case 3:
				return { label: 'LOW', class: 'badge badge-accent' };
			default:
				return { label: 'INFO', class: 'badge' };
		}
	}

	// Derived data for charts
	let chartData = $derived(
		bandwidthData.map((p) => ({
			time: p.timestamp,
			value: p.total_bytes,
		}))
	);

	let donutSegments = $derived(
		protocols.slice(0, 6).map((p, i) => ({
			label: p.name || 'unknown',
			value: p.count,
			color: PROTOCOL_COLORS[i] || PROTOCOL_COLORS[PROTOCOL_COLORS.length - 1],
		}))
	);

	// Health status
	let healthStatus = $derived.by(() => {
		if (!systemHealth) return { label: '--', class: 'badge', healthy: false };
		if (systemHealth.healthy) return { label: 'Healthy', class: 'badge badge-success', healthy: true };
		return { label: 'Degraded', class: 'badge badge-warning', healthy: false };
	});

	// Total alert count with fallback
	let totalAlerts = $derived(alertCount?.counts?.total ?? 0);
</script>

<svelte:head>
	<title>Dashboard | NetTap</title>
</svelte:head>

<div class="dashboard">
	<!-- Error banner -->
	{#if error}
		<div class="alert alert-warning error-banner">
			<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
			</svg>
			<span>Unable to reach the monitoring daemon. Data may be stale or unavailable.</span>
		</div>
	{/if}

	<!-- Dashboard header -->
	<div class="dashboard-header">
		<div class="header-left">
			<h2>Network Overview</h2>
			<p class="text-muted">Real-time traffic, alerts, and system health.</p>
		</div>
		<div class="header-controls">
			{#if lastUpdated}
				<span class="last-updated">Updated {lastUpdated}</span>
			{/if}
			<button
				class="btn btn-sm refresh-btn"
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
			<button class="btn btn-sm btn-secondary" onclick={fetchAllData} disabled={loading}>
				Refresh
			</button>
		</div>
	</div>

	<!-- Row 1: Stat Cards -->
	<div class="grid grid-cols-4 stat-grid">
		<!-- Total Bandwidth (24h) -->
		<div class="card stat-card">
			<div class="card-header">
				<span class="card-subtitle">Total Bandwidth (24h)</span>
				<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
				</svg>
			</div>
			{#if loading && !trafficSummary}
				<div class="skeleton skeleton-value"></div>
			{:else}
				<div class="card-value">
					{trafficSummary ? formatBytes(trafficSummary.total_bytes) : '--'}
				</div>
			{/if}
			<p class="card-description">
				{#if trafficSummary}
					{formatBytesShort(trafficSummary.orig_bytes)} in / {formatBytesShort(trafficSummary.resp_bytes)} out
				{:else}
					Inbound + outbound traffic
				{/if}
			</p>
		</div>

		<!-- Active Connections -->
		<div class="card stat-card">
			<div class="card-header">
				<span class="card-subtitle">Connections (24h)</span>
				<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
				</svg>
			</div>
			{#if loading && !trafficSummary}
				<div class="skeleton skeleton-value"></div>
			{:else}
				<div class="card-value">
					{trafficSummary ? formatNumber(trafficSummary.connection_count) : '--'}
				</div>
			{/if}
			<p class="card-description">
				{#if trafficSummary}
					Top protocol: {trafficSummary.top_protocol}
				{:else}
					Total observed connections
				{/if}
			</p>
		</div>

		<!-- Active Alerts (24h) -->
		<div class="card stat-card">
			<div class="card-header">
				<span class="card-subtitle">Alerts (24h)</span>
				<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--warning)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" />
				</svg>
			</div>
			{#if loading && !alertCount}
				<div class="skeleton skeleton-value"></div>
			{:else}
				<div class="card-value">
					{totalAlerts > 0 ? formatNumber(totalAlerts) : '--'}
				</div>
			{/if}
			<p class="card-description">
				{#if alertCount?.counts}
					{alertCount.counts.high} high, {alertCount.counts.medium} med, {alertCount.counts.low} low
				{:else}
					Suricata IDS detections
				{/if}
			</p>
		</div>

		<!-- System Health -->
		<div class="card stat-card">
			<div class="card-header">
				<span class="card-subtitle">System Health</span>
				<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="{healthStatus.healthy ? 'var(--success)' : 'var(--warning)'}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" />
				</svg>
			</div>
			{#if loading && !systemHealth}
				<div class="skeleton skeleton-value"></div>
			{:else}
				<div class="card-value">
					<span class={healthStatus.class}>{healthStatus.label}</span>
				</div>
			{/if}
			<p class="card-description">
				{#if systemHealth}
					OpenSearch {systemHealth.opensearch_reachable ? 'connected' : 'unreachable'}
				{:else}
					Daemon + OpenSearch status
				{/if}
			</p>
		</div>
	</div>

	<!-- Row 2: Charts -->
	<div class="grid grid-cols-2 charts-grid">
		<!-- Bandwidth Over Time -->
		<div class="card chart-card">
			<div class="card-header">
				<span class="card-title">Bandwidth Over Time</span>
				<span class="card-subtitle">Last 24 hours (1h buckets)</span>
			</div>
			{#if loading && bandwidthData.length === 0}
				<div class="skeleton skeleton-chart"></div>
			{:else}
				<TimeSeriesChart
					data={chartData}
					height={260}
					color="var(--accent)"
					label="Bytes"
					formatValue={formatBytesShort}
				/>
			{/if}
		</div>

		<!-- Protocol Distribution -->
		<div class="card chart-card">
			<div class="card-header">
				<span class="card-title">Protocol Distribution</span>
				<span class="card-subtitle">By connection count</span>
			</div>
			{#if loading && protocols.length === 0}
				<div class="skeleton skeleton-chart"></div>
			{:else}
				<div class="donut-wrapper">
					<DonutChart
						segments={donutSegments}
						size={200}
						formatValue={formatNumber}
					/>
				</div>
			{/if}
		</div>
	</div>

	<!-- Row 3: Tables -->
	<div class="grid grid-cols-2 tables-grid">
		<!-- Top Talkers -->
		<div class="card table-card">
			<div class="card-header">
				<span class="card-title">Top Talkers</span>
				<span class="card-subtitle">Source IPs by bandwidth</span>
			</div>
			{#if loading && topTalkers.length === 0}
				<div class="skeleton-table">
					{#each Array(5) as _}
						<div class="skeleton skeleton-row"></div>
					{/each}
				</div>
			{:else if topTalkers.length === 0}
				<div class="table-empty">
					<p class="text-muted">No traffic data available.</p>
				</div>
			{:else}
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th>#</th>
								<th>Source IP</th>
								<th>Bandwidth</th>
								<th>Connections</th>
							</tr>
						</thead>
						<tbody>
							{#each topTalkers.slice(0, 10) as talker, i}
								<tr>
									<td class="row-num">{i + 1}</td>
									<td class="mono ip-cell">{talker.ip}</td>
									<td>{formatBytes(talker.total_bytes)}</td>
									<td>{talker.connection_count.toLocaleString()}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<!-- Recent Alerts -->
		<div class="card table-card">
			<div class="card-header">
				<span class="card-title">Recent Alerts</span>
				<a href="/alerts" class="card-action">View all</a>
			</div>
			{#if loading && recentAlerts.length === 0}
				<div class="skeleton-table">
					{#each Array(5) as _}
						<div class="skeleton skeleton-row"></div>
					{/each}
				</div>
			{:else if recentAlerts.length === 0}
				<div class="table-empty">
					<p class="text-muted">No alerts detected. All clear.</p>
				</div>
			{:else}
				<div class="table-scroll">
					<table class="data-table alerts-table">
						<thead>
							<tr>
								<th>Severity</th>
								<th>Signature</th>
								<th>Source</th>
								<th>Dest</th>
							</tr>
						</thead>
						<tbody>
							{#each recentAlerts.slice(0, 10) as alert}
								{@const sev = severityBadge(alert.alert?.severity)}
								<tr>
									<td>
										<span class={sev.class}>{sev.label}</span>
									</td>
									<td class="signature-cell" title={alert.alert?.signature || 'Unknown'}>
										{alert.alert?.signature || 'Unknown signature'}
									</td>
									<td class="mono ip-cell">{alert.src_ip || '--'}</td>
									<td class="mono ip-cell">{alert.dest_ip || '--'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.dashboard {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Error banner */
	.error-banner {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.error-banner svg {
		flex-shrink: 0;
	}

	/* Header */
	.dashboard-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.header-controls {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.last-updated {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.refresh-btn {
		display: flex;
		align-items: center;
		gap: 4px;
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

	.card-description {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Charts */
	.charts-grid {
		margin-top: var(--space-xs);
	}

	.chart-card {
		min-height: 340px;
	}

	.donut-wrapper {
		display: flex;
		justify-content: center;
		padding: var(--space-md) 0;
	}

	/* Tables */
	.tables-grid {
		margin-top: var(--space-xs);
	}

	.table-card {
		min-height: 280px;
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
		padding: var(--space-sm) var(--space-sm);
		border-bottom: 1px solid var(--border-default);
	}

	.data-table td {
		padding: var(--space-sm) var(--space-sm);
		border-bottom: 1px solid var(--border-muted);
		color: var(--text-primary);
	}

	.data-table tbody tr:hover {
		background-color: var(--bg-tertiary);
	}

	.data-table tbody tr:last-child td {
		border-bottom: none;
	}

	.row-num {
		color: var(--text-muted);
		font-size: var(--text-xs);
		width: 30px;
	}

	.ip-cell {
		font-size: var(--text-xs);
		white-space: nowrap;
	}

	.signature-cell {
		max-width: 220px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.card-action {
		font-size: var(--text-xs);
		font-weight: 500;
	}

	.table-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 120px;
	}

	/* Skeleton loading */
	.skeleton {
		background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--border-muted) 50%, var(--bg-tertiary) 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
	}

	.skeleton-value {
		height: 36px;
		width: 120px;
	}

	.skeleton-chart {
		height: 220px;
		width: 100%;
		border-radius: var(--radius-md);
	}

	.skeleton-table {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.skeleton-row {
		height: 32px;
		width: 100%;
	}

	@keyframes shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}

	/* Responsive */
	@media (max-width: 768px) {
		.dashboard-header {
			flex-direction: column;
		}

		.signature-cell {
			max-width: 140px;
		}
	}
</style>
