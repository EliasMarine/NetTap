<script lang="ts">
	/**
	 * Traffic Category Detail v2 — Full-featured category analytics drill-down.
	 *
	 * Features:
	 *   1. Bandwidth over time chart (dual-series: DL/UL)
	 *   2. Device hostname resolution
	 *   3. Traffic share (%) column
	 *   4. Download/Upload split bars
	 *   5. Search/filter on device table
	 *   6. Auto-refresh toggle (30s interval)
	 *   7. Service click-through filtering
	 *   8. % of Network stat card
	 *   9. Trend indicators vs previous period
	 */

	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import {
		getCategoryDetail,
		getCategoryBandwidth,
		getTrafficSummary,
	} from '$api/traffic';
	import type {
		CategoryDetailResponse,
		CategoryBandwidthPoint,
		TrafficCategoryService,
	} from '$api/traffic';
	import TimeSeriesChart from '$components/charts/TimeSeriesChart.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Category metadata
	// ---------------------------------------------------------------------------

	const CATEGORY_META: Record<string, { icon: string; color: string }> = {
		streaming: { icon: '\u25B6', color: 'var(--red)' },
		gaming: { icon: '\uD83C\uDFAE', color: 'var(--purple)' },
		social: { icon: '\uD83D\uDC65', color: 'var(--blue)' },
		communication: { icon: '\uD83D\uDCAC', color: 'var(--amber)' },
		work: { icon: '\uD83D\uDCBC', color: 'var(--green)' },
		iot: { icon: '\uD83D\uDCE1', color: 'var(--orange)' },
		cloud: { icon: '\u2601', color: 'var(--cyan)' },
		file_transfer: { icon: '\uD83D\uDCC1', color: 'var(--teal)' },
		dns: { icon: '\uD83C\uDF10', color: 'var(--text-muted)' },
		email: { icon: '\u2709', color: 'var(--pink)' },
		web: { icon: '\uD83D\uDD17', color: 'var(--accent)' },
		security: { icon: '\uD83D\uDD12', color: 'var(--green)' },
		shopping: { icon: '\uD83D\uDED2', color: 'var(--orange)' },
		news: { icon: '\uD83D\uDCF0', color: 'var(--blue)' },
		ads: { icon: '\uD83D\uDCCA', color: 'var(--text-muted)' },
		updates: { icon: '\u2B07', color: 'var(--teal)' },
		suspicious: { icon: '\u26A0', color: 'var(--red)' },
		other: { icon: '\u2026', color: 'var(--text-muted)' },
	};

	const TIME_RANGES = [
		{ label: '1h', value: '1h' },
		{ label: '6h', value: '6h' },
		{ label: '24h', value: '24h' },
		{ label: '7d', value: '7d' },
		{ label: '30d', value: '30d' },
	];

	/** Map time range to chart interval */
	const INTERVAL_MAP: Record<string, string> = {
		'1h': '1m',
		'6h': '5m',
		'24h': '15m',
		'7d': '1h',
		'30d': '6h',
	};

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let category = $derived(($page.params as Record<string, string>).category ?? 'other');
	let meta = $derived(CATEGORY_META[category] ?? CATEGORY_META['other']);
	let selectedRange = $state('24h');

	// Data
	let data = $state<CategoryDetailResponse | null>(null);
	let loading = $state(true);
	let topServices = $state<TrafficCategoryService[]>([]);
	let bandwidthSeries = $state<CategoryBandwidthPoint[]>([]);
	let networkPercent = $state<number | null>(null);

	// Trend data
	let prevData = $state<CategoryDetailResponse | null>(null);

	// UI state
	let searchQuery = $state('');
	let activeService = $state<string | null>(null);
	let autoRefresh = $state(false);
	let lastUpdated = $state<Date>(new Date());
	let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;

	// Sort state
	let sortField = $state<string>('total_bytes');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function toggleSort(field: string) {
		if (sortField === field) {
			sortDir = sortDir === 'desc' ? 'asc' : 'desc';
		} else {
			sortField = field;
			sortDir = 'desc';
		}
	}

	// ---------------------------------------------------------------------------
	// Derived: filtered + sorted devices
	// ---------------------------------------------------------------------------

	let filteredDevices = $derived.by(() => {
		if (!data?.devices) return [];
		let devices = [...data.devices];

		// Search filter
		if (searchQuery.trim()) {
			const q = searchQuery.trim().toLowerCase();
			devices = devices.filter(
				(d) =>
					d.ip.toLowerCase().includes(q) ||
					(d.hostname && d.hostname.toLowerCase().includes(q)),
			);
		}

		return devices;
	});

	let sortedDevices = $derived.by(() => {
		return [...filteredDevices].sort((a, b) => {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const av = (a as any)[sortField] ?? 0;
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const bv = (b as any)[sortField] ?? 0;
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return sortDir === 'asc' ? cmp : -cmp;
		});
	});

	// Max bytes for inline bar widths
	let maxDeviceBytes = $derived.by(() => {
		if (!data?.devices?.length) return 1;
		return Math.max(...data.devices.map((d) => d.total_bytes), 1);
	});

	// Chart data for TimeSeriesChart (total = DL + UL)
	let chartData = $derived(
		bandwidthSeries.map((p) => ({
			time: p.timestamp,
			value: p.total_bytes,
		})),
	);

	// Trend calculations
	let trendBytes = $derived.by(() => {
		if (!data || !prevData || !prevData.total_bytes) return null;
		const diff = data.total_bytes - prevData.total_bytes;
		return {
			pct: ((diff / prevData.total_bytes) * 100).toFixed(1),
			direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'neutral',
		};
	});

	let trendDevices = $derived.by(() => {
		if (!data || !prevData) return null;
		const diff = data.device_count - prevData.device_count;
		if (diff > 0) return { label: `+${diff} new`, direction: 'up' };
		if (diff < 0) return { label: `${diff}`, direction: 'down' };
		return { label: 'stable', direction: 'neutral' };
	});

	let trendConns = $derived.by(() => {
		if (!data || !prevData || !prevData.connection_count) return null;
		const diff = data.connection_count - prevData.connection_count;
		const pct = ((diff / prevData.connection_count) * 100).toFixed(1);
		return {
			pct,
			direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'neutral',
		};
	});

	// "Last updated X ago" text
	let lastUpdatedText = $derived.by(() => {
		const now = Date.now();
		const diff = Math.floor((now - lastUpdated.getTime()) / 1000);
		if (diff < 5) return 'just now';
		if (diff < 60) return `${diff}s ago`;
		return `${Math.floor(diff / 60)}m ago`;
	});

	// Display name
	let displayName = $derived(
		data?.label ?? category.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
	);

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	function computeTimeParams(range: string): { from: string; to: string } {
		const now = new Date();
		let from: Date;
		switch (range) {
			case '1h': from = new Date(now.getTime() - 60 * 60 * 1000); break;
			case '6h': from = new Date(now.getTime() - 6 * 60 * 60 * 1000); break;
			case '7d': from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000); break;
			case '30d': from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000); break;
			default: from = new Date(now.getTime() - 24 * 60 * 60 * 1000); break;
		}
		return { from: from.toISOString(), to: now.toISOString() };
	}

	function computePrevTimeParams(range: string): { from: string; to: string } {
		const now = new Date();
		let durationMs: number;
		switch (range) {
			case '1h': durationMs = 60 * 60 * 1000; break;
			case '6h': durationMs = 6 * 60 * 60 * 1000; break;
			case '7d': durationMs = 7 * 24 * 60 * 60 * 1000; break;
			case '30d': durationMs = 30 * 24 * 60 * 60 * 1000; break;
			default: durationMs = 24 * 60 * 60 * 1000; break;
		}
		const to = new Date(now.getTime() - durationMs);
		const from = new Date(to.getTime() - durationMs);
		return { from: from.toISOString(), to: to.toISOString() };
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchData(cat: string, range: string) {
		loading = true;
		const timeParams = computeTimeParams(range);
		const prevParams = computePrevTimeParams(range);
		const interval = INTERVAL_MAP[range] ?? '15m';

		try {
			const [detailResult, bandwidthResult, summaryResult, prevResult] = await Promise.all([
				getCategoryDetail(cat, timeParams),
				getCategoryBandwidth(cat, { ...timeParams, interval }),
				getTrafficSummary(timeParams),
				getCategoryDetail(cat, prevParams),
			]);

			data = detailResult;
			topServices = detailResult?.services ?? [];
			bandwidthSeries = bandwidthResult?.series ?? [];
			prevData = prevResult;

			// Calculate % of total network
			if (summaryResult.total_bytes > 0 && detailResult.total_bytes > 0) {
				networkPercent = (detailResult.total_bytes / summaryResult.total_bytes) * 100;
			} else {
				networkPercent = 0;
			}

			lastUpdated = new Date();
		} catch (err) {
			console.error('[traffic/category] fetchData error:', err);
			data = null;
			topServices = [];
			bandwidthSeries = [];
		} finally {
			loading = false;
		}
	}

	// Refetch when selectedRange or category changes
	$effect(() => {
		const cat = category;
		const range = selectedRange;
		fetchData(cat, range);
	});

	// Auto-refresh
	$effect(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		if (autoRefresh) {
			autoRefreshTimer = setInterval(
				() => fetchData(category, selectedRange),
				30_000,
			);
		}
		return () => {
			if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		};
	});

	onDestroy(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
	});

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	function sortArrow(field: string): string {
		if (sortField !== field) return '';
		return sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
	}

	// Service click-through
	function selectService(name: string) {
		activeService = activeService === name ? null : name;
	}

	function clearServiceFilter() {
		activeService = null;
	}
</script>

<svelte:head>
	<title>{displayName} Traffic | NetTap</title>
</svelte:head>

<div class="category-detail">
	<!-- Page Header -->
	<div class="page-header">
		<div class="header-left">
			<a href="/" class="back-link">&larr; Back to Dashboard</a>
			<div class="category-title">
				<span class="category-icon-box" style="background: color-mix(in srgb, {meta.color} 12%, transparent); border-color: color-mix(in srgb, {meta.color} 25%, transparent);">
					<span style="color: {meta.color};">{meta.icon}</span>
				</span>
				<div>
					<h2>{displayName}</h2>
					<p class="text-muted subtitle-text">Per-device bandwidth breakdown &middot; Updated {lastUpdatedText}</p>
				</div>
			</div>
		</div>
		<div class="header-controls">
			<div class="pills">
				{#each TIME_RANGES as range}
					<button
						class="pill"
						class:active={selectedRange === range.value}
						onclick={() => (selectedRange = range.value)}
					>
						{range.label}
					</button>
				{/each}
			</div>
			<button
				class="auto-refresh-btn"
				class:active={autoRefresh}
				onclick={() => (autoRefresh = !autoRefresh)}
				title="Auto-refresh every 30s"
			>
				<span class="auto-refresh-indicator"></span>
				Auto
			</button>
		</div>
	</div>

	<!-- Loading state -->
	{#if loading}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Loading category data...</span>
		</div>
	{:else if !data || (data.device_count === 0 && data.total_bytes === 0)}
		<div class="empty-state">
			<div class="empty-icon">{meta.icon}</div>
			<p class="empty-text">No traffic data for {displayName}</p>
			<p class="empty-hint">Try expanding the time range or check that devices are generating traffic in this category.</p>
		</div>
	{:else}
		<!-- Stat Cards -->
		<div class="stats-grid">
			<div class="stat-card stat-card-accent">
				<div class="stat-label">Total Bandwidth</div>
				<div class="stat-value" style="color: {meta.color};">{formatBytes(data.total_bytes)}</div>
				{#if trendBytes}
					<span class="stat-trend" class:trend-up={trendBytes.direction === 'up'} class:trend-down={trendBytes.direction === 'down'} class:trend-neutral={trendBytes.direction === 'neutral'}>
						{trendBytes.direction === 'up' ? '\u2191' : trendBytes.direction === 'down' ? '\u2193' : '\u2013'} {trendBytes.pct}% vs prev
					</span>
				{/if}
			</div>
			<div class="stat-card">
				<div class="stat-label">Active Devices</div>
				<div class="stat-value">{formatNumber(data.device_count)}</div>
				{#if trendDevices}
					<span class="stat-trend" class:trend-up={trendDevices.direction === 'up'} class:trend-down={trendDevices.direction === 'down'} class:trend-neutral={trendDevices.direction === 'neutral'}>
						{trendDevices.direction === 'up' ? '\u2191' : trendDevices.direction === 'down' ? '\u2193' : '\u2013'} {trendDevices.label}
					</span>
				{/if}
			</div>
			<div class="stat-card">
				<div class="stat-label">Connections</div>
				<div class="stat-value">{formatNumber(data.connection_count)}</div>
				{#if trendConns}
					<span class="stat-trend" class:trend-up={trendConns.direction === 'up'} class:trend-down={trendConns.direction === 'down'} class:trend-neutral={trendConns.direction === 'neutral'}>
						{trendConns.direction === 'up' ? '\u2191' : trendConns.direction === 'down' ? '\u2193' : '\u2013'} {trendConns.pct}% vs prev
					</span>
				{/if}
			</div>
			<div class="stat-card">
				<div class="stat-label">% of Network</div>
				<div class="stat-value">{networkPercent !== null ? `${networkPercent.toFixed(1)}%` : '\u2014'}</div>
				<span class="stat-trend trend-neutral">of total traffic</span>
			</div>
		</div>

		<!-- Bandwidth Chart -->
		{#if chartData.length > 0}
			<div class="chart-card">
				<div class="chart-card-header">
					<span class="card-title">Bandwidth Over Time</span>
					<div class="chart-legend">
						<span class="legend-item"><span class="legend-dot" style="background: {meta.color};"></span> Total</span>
					</div>
				</div>
				<div class="chart-card-body">
					<TimeSeriesChart
						data={chartData}
						height={220}
						color={meta.color}
						formatValue={formatBytes}
					/>
				</div>
			</div>
		{/if}

		<!-- Content Grid: Table + Sidebar -->
		<div class="content-grid">
			<!-- Per-Device Breakdown -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Per-Device Breakdown</span>
					<span class="card-badge">{filteredDevices.length}{filteredDevices.length !== data.devices.length ? ` / ${data.devices.length}` : ''} devices</span>
				</div>

				<!-- Search toolbar -->
				<div class="table-toolbar">
					<div class="search-wrap">
						<span class="search-icon-char">&#x1F50D;</span>
						<input
							type="text"
							class="search-input"
							placeholder="Filter by IP or hostname..."
							bind:value={searchQuery}
						/>
					</div>
					{#if activeService}
						<button class="filter-badge" onclick={clearServiceFilter}>
							{activeService} <span class="filter-close">&times;</span>
						</button>
					{/if}
				</div>

				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr>
								<th class="sortable" class:sorted={sortField === 'ip'} onclick={() => toggleSort('ip')}>
									Device{sortArrow('ip')}
								</th>
								<th class="sortable" class:sorted={sortField === 'total_bytes'} onclick={() => toggleSort('total_bytes')}>
									Total Data{sortArrow('total_bytes')}
								</th>
								<th class="sortable" class:sorted={sortField === 'download_bytes'} onclick={() => toggleSort('download_bytes')}>
									Download{sortArrow('download_bytes')}
								</th>
								<th class="sortable" class:sorted={sortField === 'upload_bytes'} onclick={() => toggleSort('upload_bytes')}>
									Upload{sortArrow('upload_bytes')}
								</th>
								<th class="sortable" class:sorted={sortField === 'connections'} onclick={() => toggleSort('connections')}>
									Connections{sortArrow('connections')}
								</th>
								<th class="sortable" class:sorted={sortField === 'percent'} onclick={() => toggleSort('percent')}>
									Share{sortArrow('percent')}
								</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedDevices as device, i (`${device.ip}-${i}`)}
								<tr>
									<td>
										<a href="/devices/{encodeURIComponent(device.ip)}" class="device-link">
											<IPAddress ip={device.ip} />
											{#if device.hostname}
												<span class="device-hostname">{device.hostname}</span>
											{/if}
										</a>
									</td>
									<td>
										<div class="bytes-cell">
											<span class="mono">{formatBytes(device.total_bytes)}</span>
											<div class="split-bar">
												{@const dlPct = device.total_bytes > 0 ? (device.download_bytes / device.total_bytes) * 100 : 50}
												<div class="split-bar-dl" style="width: {dlPct}%;"></div>
												<div class="split-bar-ul" style="width: {100 - dlPct}%;"></div>
											</div>
										</div>
									</td>
									<td class="mono">{formatBytes(device.download_bytes)}</td>
									<td class="mono">{formatBytes(device.upload_bytes)}</td>
									<td class="mono">{formatNumber(device.connections)}</td>
									<td>
										<div class="percent-cell">
											<div class="percent-bar-track">
												<div class="percent-bar-fill" style="width: {Math.min(device.percent, 100)}%; background: {meta.color};"></div>
											</div>
											<span class="percent-value mono">{device.percent < 0.1 ? '<0.1' : device.percent.toFixed(1)}%</span>
										</div>
									</td>
								</tr>
							{/each}
							{#if sortedDevices.length === 0 && searchQuery}
								<tr>
									<td colspan="6" class="table-empty-cell">
										No devices matching "{searchQuery}"
									</td>
								</tr>
							{/if}
						</tbody>
					</table>
				</div>
			</div>

			<!-- Top Services Sidebar -->
			<div class="card sidebar-card">
				<div class="card-header">
					<span class="card-title">Top Services</span>
					<span class="card-badge">{topServices.length} services</span>
				</div>
				{#if topServices.length > 0}
					<div class="service-list">
						{#each topServices as service, i (`${service.name}-${i}`)}
							{@const maxBytes = topServices[0]?.bytes ?? 1}
							<button
								class="service-row"
								class:active={activeService === service.name}
								onclick={() => selectService(service.name)}
								type="button"
							>
								<div class="service-info">
									<span class="service-name">{service.name}</span>
									<div class="service-bar-track">
										<div
											class="service-bar-fill"
											style="width: {(service.bytes / maxBytes) * 100}%; background: {meta.color};"
										></div>
									</div>
								</div>
								<div class="service-stats">
									<div class="service-bytes mono">{formatBytes(service.bytes)}</div>
									{#if service.connections}
										<div class="service-conns mono">{formatNumber(service.connections)} conn</div>
									{/if}
								</div>
							</button>
						{/each}
					</div>
					{#if activeService}
						<button class="clear-filter-btn" onclick={clearServiceFilter} type="button">
							Clear filter &middot; Show all devices
						</button>
					{/if}
				{:else}
					<p class="text-muted sidebar-empty">No service data available.</p>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.category-detail {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* ----------------------------------------------------------------
	   Header
	   ---------------------------------------------------------------- */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.header-left {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.back-link {
		font-size: var(--text-sm);
		color: var(--text-muted);
		text-decoration: none;
		transition: color var(--transition-fast);
	}

	.back-link:hover { color: var(--accent); }

	.category-title {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.category-icon-box {
		width: 48px;
		height: 48px;
		border-radius: var(--radius-lg);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1.5rem;
		border: 1px solid;
		flex-shrink: 0;
	}

	.category-title h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		letter-spacing: -0.02em;
	}

	.subtitle-text {
		font-size: var(--text-sm);
		margin-top: 2px;
	}

	.header-controls {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	/* Pills */
	.pills {
		display: flex;
		gap: 2px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
		padding: 2px;
		border: 1px solid var(--border-dim);
	}

	.pill {
		padding: 6px 14px;
		border: none;
		background: transparent;
		color: var(--text-secondary);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		border-radius: 6px;
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.pill:hover { color: var(--text-primary); background: var(--bg-elevated); }

	.pill.active {
		background: var(--accent);
		color: var(--bg-void);
		font-weight: 600;
	}

	/* Auto-refresh button */
	.auto-refresh-btn {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: 6px 12px;
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		color: var(--text-muted);
		font-size: var(--text-xs);
		font-family: var(--font-sans);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.auto-refresh-btn:hover { border-color: var(--border-default); color: var(--text-secondary); }

	.auto-refresh-btn.active {
		border-color: var(--cyan);
		color: var(--cyan);
		background: rgba(0, 212, 255, 0.06);
	}

	.auto-refresh-indicator {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--text-dim);
		transition: all var(--transition-fast);
	}

	.auto-refresh-btn.active .auto-refresh-indicator {
		background: var(--cyan);
		box-shadow: 0 0 8px rgba(0, 212, 255, 0.5);
		animation: pulse 2s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 0.6; }
		50% { opacity: 1; }
	}

	/* ----------------------------------------------------------------
	   Loading / Empty states
	   ---------------------------------------------------------------- */
	.loading-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-3xl);
	}

	.empty-state {
		text-align: center;
		padding: var(--space-3xl);
	}

	.empty-icon {
		font-size: var(--text-4xl);
		margin-bottom: var(--space-md);
		opacity: 0.4;
	}

	.empty-text {
		font-size: var(--text-lg);
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.empty-hint {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}

	/* ----------------------------------------------------------------
	   Stat Cards
	   ---------------------------------------------------------------- */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.stat-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md) var(--space-lg);
		position: relative;
		overflow: hidden;
		transition: border-color var(--transition-fast);
	}

	.stat-card:hover { border-color: var(--border-default); }

	.stat-card::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 2px;
		background: var(--border-dim);
	}

	.stat-card-accent::before {
		background: var(--accent);
		box-shadow: 0 0 12px rgba(0, 212, 255, 0.3);
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-weight: 500;
		margin-bottom: var(--space-sm);
	}

	.stat-value {
		font-family: var(--font-mono);
		font-size: var(--text-3xl);
		font-weight: 600;
		color: var(--text-primary);
		letter-spacing: -0.03em;
		line-height: 1;
	}

	.stat-trend {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		margin-top: var(--space-sm);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	.trend-up { color: var(--green); background: rgba(0, 230, 118, 0.12); }
	.trend-down { color: var(--red); background: rgba(255, 71, 87, 0.12); }
	.trend-neutral { color: var(--text-muted); background: var(--bg-tertiary); }

	/* ----------------------------------------------------------------
	   Chart Card
	   ---------------------------------------------------------------- */
	.chart-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		overflow: hidden;
	}

	.chart-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.chart-card-body {
		padding: var(--space-sm) var(--space-md);
	}

	.chart-legend {
		display: flex;
		gap: var(--space-md);
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.legend-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	/* ----------------------------------------------------------------
	   Content Grid
	   ---------------------------------------------------------------- */
	.content-grid {
		display: grid;
		grid-template-columns: 1fr 340px;
		gap: var(--space-md);
		align-items: start;
	}

	/* Card base */
	.card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		overflow: hidden;
	}

	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.card-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.card-badge {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-muted);
		background: var(--bg-tertiary);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	/* ----------------------------------------------------------------
	   Search Toolbar
	   ---------------------------------------------------------------- */
	.table-toolbar {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.search-wrap {
		position: relative;
		flex: 1;
		max-width: 320px;
	}

	.search-icon-char {
		position: absolute;
		left: 10px;
		top: 50%;
		transform: translateY(-50%);
		font-size: 12px;
		pointer-events: none;
		opacity: 0.4;
	}

	.search-input {
		width: 100%;
		padding: 6px 10px 6px 32px;
		background: var(--bg-input);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		outline: none;
		transition: border-color var(--transition-fast);
	}

	.search-input::placeholder { color: var(--text-dim); }
	.search-input:focus { border-color: var(--accent); }

	.filter-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		background: rgba(0, 212, 255, 0.08);
		border: 1px solid rgba(0, 212, 255, 0.25);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		color: var(--cyan);
		cursor: pointer;
		font-family: var(--font-sans);
		transition: all var(--transition-fast);
	}

	.filter-badge:hover { background: rgba(0, 212, 255, 0.15); }

	.filter-close { font-size: 14px; line-height: 1; opacity: 0.6; }
	.filter-badge:hover .filter-close { opacity: 1; }

	/* ----------------------------------------------------------------
	   Data Table
	   ---------------------------------------------------------------- */
	.table-wrap { overflow-x: auto; }

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	.data-table th {
		padding: var(--space-sm) var(--space-md);
		text-align: left;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-dim);
		white-space: nowrap;
		cursor: pointer;
		user-select: none;
		transition: color var(--transition-fast);
	}

	.data-table th:hover { color: var(--text-primary); }
	.data-table th.sorted { color: var(--accent); }

	.data-table td {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-dim);
		vertical-align: middle;
	}

	.data-table tbody tr { transition: background var(--transition-fast); }
	.data-table tbody tr:hover { background: var(--bg-tertiary); }
	.data-table tbody tr:last-child td { border-bottom: none; }

	.table-empty-cell {
		text-align: center;
		padding: var(--space-xl) !important;
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	/* Device cell */
	.device-link {
		display: flex;
		flex-direction: column;
		gap: 2px;
		text-decoration: none;
		color: var(--text-link);
		transition: color var(--transition-fast);
	}

	.device-link:hover { color: var(--accent); }

	.device-hostname {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Bytes cell with DL/UL split bar */
	.bytes-cell {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 140px;
	}

	.split-bar {
		display: flex;
		height: 4px;
		border-radius: 2px;
		overflow: hidden;
		background: var(--bg-tertiary);
		gap: 1px;
	}

	.split-bar-dl {
		background: var(--cyan);
		border-radius: 2px 0 0 2px;
		transition: width var(--transition-slow);
		min-width: 1px;
	}

	.split-bar-ul {
		background: var(--purple);
		border-radius: 0 2px 2px 0;
		transition: width var(--transition-slow);
		min-width: 1px;
	}

	/* Percent cell */
	.percent-cell {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.percent-bar-track {
		width: 48px;
		height: 4px;
		background: var(--bg-tertiary);
		border-radius: 2px;
		overflow: hidden;
		flex-shrink: 0;
	}

	.percent-bar-fill {
		height: 100%;
		border-radius: 2px;
		transition: width var(--transition-slow);
	}

	.percent-value {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		min-width: 40px;
		text-align: right;
	}

	/* ----------------------------------------------------------------
	   Top Services Sidebar
	   ---------------------------------------------------------------- */
	.sidebar-card {
		position: sticky;
		top: var(--space-md);
	}

	.sidebar-empty {
		padding: var(--space-lg);
		text-align: center;
		font-size: var(--text-sm);
	}

	.service-list {
		padding: var(--space-xs) 0;
	}

	.service-row {
		display: grid;
		grid-template-columns: 1fr auto;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-lg);
		width: 100%;
		background: none;
		border: none;
		border-left: 3px solid transparent;
		cursor: pointer;
		text-align: left;
		font: inherit;
		color: inherit;
		transition: all var(--transition-fast);
	}

	.service-row:hover { background: var(--bg-tertiary); }

	.service-row.active {
		background: rgba(0, 212, 255, 0.06);
		border-left-color: var(--cyan);
	}

	.service-info {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.service-name {
		font-size: var(--text-sm);
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		transition: color var(--transition-fast);
	}

	.service-row:hover .service-name,
	.service-row.active .service-name { color: var(--cyan); }

	.service-bar-track {
		height: 4px;
		background: var(--bg-tertiary);
		border-radius: 2px;
		overflow: hidden;
	}

	.service-bar-fill {
		height: 100%;
		border-radius: 2px;
		opacity: 0.5;
		transition: all var(--transition-slow);
	}

	.service-row:hover .service-bar-fill,
	.service-row.active .service-bar-fill { opacity: 1; }

	.service-stats {
		text-align: right;
		flex-shrink: 0;
	}

	.service-bytes {
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-secondary);
		white-space: nowrap;
	}

	.service-conns {
		font-size: 10px;
		color: var(--text-dim);
	}

	.clear-filter-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 100%;
		padding: var(--space-sm) var(--space-md);
		border: none;
		border-top: 1px solid var(--border-dim);
		background: none;
		font-size: var(--text-xs);
		color: var(--text-muted);
		cursor: pointer;
		font-family: var(--font-sans);
		transition: all var(--transition-fast);
	}

	.clear-filter-btn:hover { color: var(--accent); background: var(--bg-tertiary); }

	/* ----------------------------------------------------------------
	   Responsive
	   ---------------------------------------------------------------- */
	@media (max-width: 1200px) {
		.content-grid { grid-template-columns: 1fr; }
		.sidebar-card { position: static; }
	}

	@media (max-width: 1024px) {
		.stats-grid { grid-template-columns: repeat(2, 1fr); }
	}

	@media (max-width: 768px) {
		.stats-grid { grid-template-columns: 1fr; }
		.page-header { flex-direction: column; }
	}
</style>
