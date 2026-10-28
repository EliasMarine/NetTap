<script lang="ts">
	import { getMonthlyUsage, getDailyUsage, getDeviceUsage, getHeatmap } from '$lib/api/bandwidth';
	import type { MonthlyUsage, DailyUsageEntry, DeviceUsage, HeatmapResponse } from '$lib/api/bandwidth';
	import TopConsumers from '$lib/components/TopConsumers.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let monthly = $state<MonthlyUsage | null>(null);
	let daily = $state<DailyUsageEntry[]>([]);
	let devices = $state<DeviceUsage[]>([]);
	let heatmap = $state<HeatmapResponse | null>(null);
	let loading = $state(false);
	let error = $state('');

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	}

	function formatGB(bytes: number): string {
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	}

	function progressPercent(current: number, cap: number): number {
		if (cap <= 0) return 0;
		return Math.min(100, Math.round(current / cap * 100));
	}

	function progressColor(percent: number): string {
		if (percent >= 90) return 'var(--red)';
		if (percent >= 75) return 'var(--amber)';
		return 'var(--accent)';
	}

	// Daily chart helpers
	function maxDailyBytes(): number {
		if (daily.length === 0) return 1;
		return Math.max(...daily.map(d => d.total_bytes), 1);
	}

	function barHeight(bytes: number): number {
		return Math.max(2, (bytes / maxDailyBytes()) * 200);
	}

	function formatDate(dateStr: string): string {
		try {
			const d = new Date(dateStr);
			return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
		} catch {
			return dateStr;
		}
	}

	// Heatmap helpers
	const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	function heatmapColor(value: number, maxVal: number): string {
		if (maxVal <= 0 || value <= 0) return 'var(--bg-tertiary)';
		const intensity = Math.min(1, value / maxVal);
		const alpha = 0.1 + intensity * 0.9;
		return `rgba(0, 212, 255, ${alpha.toFixed(2)})`;
	}

	function heatmapMax(): number {
		if (!heatmap?.matrix) return 1;
		let max = 0;
		for (const row of heatmap.matrix) {
			for (const val of row) {
				if (val > max) max = val;
			}
		}
		return max || 1;
	}

	// ---------------------------------------------------------------------------
	// Sort state for per-device table
	// ---------------------------------------------------------------------------

	type DeviceSortColumn = 'ip' | 'total_bytes' | 'orig_bytes' | 'resp_bytes' | 'connection_count' | 'percent_of_total';

	let sortColumn = $state<DeviceSortColumn>('total_bytes');
	let sortDirection = $state<'asc' | 'desc'>('desc');

	const deviceColumnDefs: { key: DeviceSortColumn; label: string }[] = [
		{ key: 'ip', label: 'Device' },
		{ key: 'total_bytes', label: 'Total' },
		{ key: 'orig_bytes', label: 'Upload' },
		{ key: 'resp_bytes', label: 'Download' },
		{ key: 'connection_count', label: 'Connections' },
		{ key: 'percent_of_total', label: '% of Total' },
	];

	function handleSort(column: DeviceSortColumn) {
		if (sortColumn === column) {
			sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			sortColumn = column;
			sortDirection = column === 'ip' ? 'asc' : 'desc';
		}
	}

	function getSortIndicator(column: DeviceSortColumn): string {
		if (sortColumn !== column) return '';
		return sortDirection === 'asc' ? ' \u2191' : ' \u2193';
	}

	let sortedDevices = $derived.by(() => {
		if (devices.length === 0) return [];
		return [...devices].sort((a, b) => {
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
	});

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		loading = true;
		error = '';
		try {
			const now = new Date();
			const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
			const from = monthStart.toISOString();
			const to = now.toISOString();

			const [monthlyData, dailyData, deviceData, heatmapData] = await Promise.all([
				getMonthlyUsage(),
				getDailyUsage({ from, to }),
				getDeviceUsage({ from, to, limit: 50 }),
				getHeatmap({ from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString(), to: to }),
			]);

			monthly = monthlyData;
			daily = dailyData.daily;
			devices = deviceData.devices;
			heatmap = heatmapData;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch bandwidth data';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>Bandwidth | NetTap</title>
</svelte:head>

<div class="bandwidth-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>Bandwidth</h2>
			<p class="text-muted">Monthly usage, per-device breakdown, and usage patterns</p>
		</div>
		<div class="header-actions">
			<button class="btn btn-primary btn-sm" onclick={fetchAll} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	{#if error}
		<div class="alert alert-danger">{error}</div>
	{/if}

	{#if loading && !monthly}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading bandwidth data...</p>
		</div>
	{:else}
		<!-- Hero card: Monthly usage -->
		{#if monthly}
			<div class="card hero-card">
				<div class="hero-content">
					<div class="hero-usage">
						<span class="hero-number">{formatGB(monthly.total_bytes)}</span>
						{#if monthly.projection.cap_bytes > 0}
							<span class="hero-cap">/ {formatGB(monthly.projection.cap_bytes)}</span>
						{/if}
					</div>
					<p class="text-muted">
						This month ({monthly.year}-{String(monthly.month).padStart(2, '0')})
						{#if monthly.projection.cap_bytes > 0}
							-- {monthly.projection.usage_percent}% used
						{/if}
					</p>
					{#if monthly.projection.cap_bytes > 0}
						<div class="progress-bar">
							<div
								class="progress-fill"
								style="width: {progressPercent(monthly.total_bytes, monthly.projection.cap_bytes)}%; background-color: {progressColor(monthly.projection.usage_percent)}"
							></div>
						</div>
					{/if}
				</div>
				<div class="hero-projection">
					<div class="projection-item">
						<span class="label">Projected</span>
						<span class="mono">{formatGB(monthly.projection.projected_bytes)}</span>
					</div>
					<div class="projection-item">
						<span class="label">Daily rate</span>
						<span class="mono">{formatGB(monthly.projection.daily_rate_bytes)}/day</span>
					</div>
					<div class="projection-item">
						<span class="label">Days remaining</span>
						<span class="mono">{monthly.projection.days_in_month - Math.floor(monthly.projection.days_elapsed)}</span>
					</div>
					{#if monthly.projection.exceeds_cap}
						<div class="alert alert-warning" style="margin-top: var(--space-sm);">
							Projected usage exceeds your monthly cap!
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Top consumers (reusable component) -->
		{#if devices.length > 0}
			<TopConsumers devices={devices.slice(0, 10)} />
		{/if}

		<!-- Daily usage bar chart -->
		{#if daily.length > 0}
			<div class="card">
				<h3 class="card-title">Daily Usage</h3>
				<div class="daily-chart">
					<div class="chart-bars">
						{#each daily as day}
							<div class="bar-column" title="{formatDate(day.date)}: {formatBytes(day.total_bytes)}">
								<div class="bar" style="height: {barHeight(day.total_bytes)}px"></div>
								<span class="bar-label">{formatDate(day.date)}</span>
							</div>
						{/each}
					</div>
				</div>
			</div>
		{/if}

		<!-- Per-device table -->
		{#if devices.length > 0}
			<div class="card">
				<h3 class="card-title">Per-Device Breakdown</h3>
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								{#each deviceColumnDefs as col}
									<th class="sortable">
										<button class="sort-btn" class:active-sort={sortColumn === col.key} onclick={() => handleSort(col.key)}>
											{col.label}{getSortIndicator(col.key)}
										</button>
									</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each sortedDevices as device}
								<tr>
									<td class="mono"><IPAddress ip={device.ip} /></td>
									<td class="mono">{formatBytes(device.total_bytes)}</td>
									<td class="mono">{formatBytes(device.orig_bytes)}</td>
									<td class="mono">{formatBytes(device.resp_bytes)}</td>
									<td class="mono">{device.connection_count.toLocaleString()}</td>
									<td>
										<div class="percent-bar">
											<div class="percent-fill" style="width: {device.percent_of_total}%"></div>
											<span class="percent-text">{device.percent_of_total}%</span>
										</div>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Heatmap -->
		{#if heatmap && heatmap.matrix}
			<div class="card">
				<h3 class="card-title">Time-of-Day Heatmap (Last 7 Days)</h3>
				<div class="heatmap-container">
					<div class="heatmap-grid">
						<!-- Hour labels -->
						<div class="heatmap-corner"></div>
						{#each Array.from({length: 24}, (_, i) => i) as hour}
							<div class="heatmap-hour-label">{hour}</div>
						{/each}
						<!-- Rows -->
						{#each DAYS as day, dayIdx}
							<div class="heatmap-day-label">{day}</div>
							{#each Array.from({length: 24}, (_, i) => i) as hour}
								<div
									class="heatmap-cell"
									style="background-color: {heatmapColor(heatmap.matrix[dayIdx]?.[hour] ?? 0, heatmapMax())}"
									title="{day} {hour}:00 - {formatBytes(heatmap.matrix[dayIdx]?.[hour] ?? 0)}"
								></div>
							{/each}
						{/each}
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.bandwidth-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

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

	/* Hero card */
	.hero-card {
		padding: var(--space-xl);
		display: flex;
		gap: var(--space-xl);
		align-items: center;
		flex-wrap: wrap;
	}

	.hero-content { flex: 1; min-width: 280px; }

	.hero-usage {
		display: flex;
		align-items: baseline;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.hero-number {
		font-size: var(--text-4xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.hero-cap {
		font-size: var(--text-xl);
		color: var(--text-muted);
	}

	.progress-bar {
		width: 100%;
		height: 12px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		margin-top: var(--space-sm);
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		transition: width var(--transition-normal);
	}

	.hero-projection {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		min-width: 200px;
	}

	.projection-item {
		display: flex;
		justify-content: space-between;
		gap: var(--space-md);
	}

	/* Card title */
	.card-title {
		font-size: var(--text-lg);
		font-weight: 600;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	/* Daily chart */
	.daily-chart {
		padding: var(--space-md) var(--space-lg);
		overflow-x: auto;
	}

	.chart-bars {
		display: flex;
		align-items: flex-end;
		gap: var(--space-xs);
		min-height: 220px;
	}

	.bar-column {
		display: flex;
		flex-direction: column;
		align-items: center;
		flex: 1;
		min-width: 24px;
	}

	.bar {
		width: 100%;
		max-width: 40px;
		background: var(--accent);
		border-radius: var(--radius-sm) var(--radius-sm) 0 0;
		transition: height var(--transition-normal);
	}

	.bar-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: var(--space-xs);
		white-space: nowrap;
		transform: rotate(-45deg);
		transform-origin: top left;
	}

	/* Table */
	.table-scroll { overflow-x: auto; }

	.percent-bar {
		position: relative;
		width: 100%;
		height: 20px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.percent-fill {
		height: 100%;
		background: var(--accent);
		opacity: 0.3;
		border-radius: var(--radius-sm);
	}

	.percent-text {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		font-size: var(--text-xs);
		font-weight: 600;
	}

	/* Heatmap */
	.heatmap-container {
		padding: var(--space-md) var(--space-lg);
		overflow-x: auto;
	}

	.heatmap-grid {
		display: grid;
		grid-template-columns: 40px repeat(24, 1fr);
		gap: 2px;
	}

	.heatmap-corner { }

	/* Sort button styles */
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

	.heatmap-hour-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: center;
	}

	.heatmap-day-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		display: flex;
		align-items: center;
	}

	.heatmap-cell {
		aspect-ratio: 1;
		min-width: 16px;
		min-height: 16px;
		border-radius: var(--radius-sm);
		cursor: default;
	}

	/* Loading */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: var(--radius-full);
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }

	@media (max-width: 768px) {
		.hero-card { flex-direction: column; }
		.page-header { flex-direction: column; }
	}
</style>
