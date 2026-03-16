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
	import { getTrafficSummary, getBandwidthTimeSeries, getProtocolDistribution, getTopTalkers, getTrafficCategories } from '$api/traffic';
	import type { TrafficSummary, BandwidthPoint, ProtocolEntry, TopTalker, TrafficCategory } from '$api/traffic';
	import { getAlertCount, getAlerts } from '$api/alerts';
	import type { AlertCountResponse, Alert } from '$api/alerts';
	import { getSystemHealth } from '$api/system';
	import type { SystemHealth } from '$api/system';
	import { getDeviceCount } from '$api/devices';
	import IPAddress from '$components/IPAddress.svelte';
	import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	import DashboardFilters from '$components/DashboardFilters.svelte';
	import type { FilterState } from '$components/DashboardFilters.svelte';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';

	// Mirror mode components
	import { getCaptureMode } from '$api/capture';
	import type { CaptureMode } from '$api/capture';
	import { getRegistryDevices } from '$api/devices-registry';
	import type { RegistryDevice } from '$api/devices-registry';
	import DeviceGrid from '$components/DeviceGrid.svelte';
	import NewDeviceBanner from '$components/NewDeviceBanner.svelte';
	import CaptureHealthPanel from '$components/CaptureHealthPanel.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// Capture mode detection
	let captureMode = $state<CaptureMode | null>(null);
	let isMirrorMode = $derived(captureMode?.mode === 'mirror');
	let registryDevices = $state<RegistryDevice[]>([]);

	let autoRefresh = $state(true);
	let loading = $state(true);
	let error = $state(false);
	let lastUpdated = $state('');

	// Data stores
	let trafficSummary = $state<TrafficSummary | null>(null);
	let bandwidthData = $state<BandwidthPoint[]>([]);
	let protocols = $state<ProtocolEntry[]>([]);
	let services = $state<ProtocolEntry[]>([]);
	let topTalkers = $state<TopTalker[]>([]);
	let alertCount = $state<AlertCountResponse | null>(null);
	let recentAlerts = $state<Alert[]>([]);
	let systemHealth = $state<SystemHealth | null>(null);
	let categories = $state<TrafficCategory[]>([]);
	let deviceCount = $state(0);

	// Previous-period data for trend indicators
	let prevTrafficSummary = $state<TrafficSummary | null>(null);
	let prevAlertCount = $state<AlertCountResponse | null>(null);

	// Alert detail panel state
	let selectedAlert = $state<Alert | null>(null);

	// Alert table sort state
	let alertSortField = $state<'severity' | 'signature' | 'src_ip' | 'dest_ip'>('severity');
	let alertSortDir = $state<'asc' | 'desc'>('asc');

	function toggleAlertSort(field: typeof alertSortField) {
		if (alertSortField === field) {
			alertSortDir = alertSortDir === 'asc' ? 'desc' : 'asc';
		} else {
			alertSortField = field;
			alertSortDir = 'asc';
		}
	}

	// Filter bar state
	let activeFilters = $state<FilterState>({
		timeRange: '24h',
		from: '',
		to: '',
		device: '',
		protocol: '',
	});

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	/**
	 * Compute the previous-period time range for trend comparison.
	 * E.g., if current range is 24h ago to now, previous is 48h ago to 24h ago.
	 */
	function computePreviousPeriod(from: string, to: string): { from: string; to: string } {
		const fromMs = new Date(from).getTime();
		const toMs = new Date(to).getTime();
		const duration = toMs - fromMs;
		return {
			from: new Date(fromMs - duration).toISOString(),
			to: new Date(fromMs).toISOString(),
		};
	}

	async function fetchAllData() {
		loading = true;
		error = false;

		// Fetch capture mode first (or in parallel)
		try {
			captureMode = await getCaptureMode();
		} catch {
			captureMode = { mode: 'bridge', interface: '' };
		}

		// If mirror mode, also fetch registry devices
		if (captureMode?.mode === 'mirror') {
			try {
				const regResult = await getRegistryDevices({ limit: 200 });
				registryDevices = regResult.devices;
			} catch {
				registryDevices = [];
			}
		}

		// Build time range params from active filters
		const timeParams: { from?: string; to?: string } = {};
		if (activeFilters.from && activeFilters.to) {
			timeParams.from = activeFilters.from;
			timeParams.to = activeFilters.to;
		}

		// Compute the previous period for trend comparison
		let prevTimeParams: { from?: string; to?: string } = {};
		if (timeParams.from && timeParams.to) {
			prevTimeParams = computePreviousPeriod(timeParams.from, timeParams.to);
		}

		try {
			const [
				summaryRes, bandwidthRes, protocolsRes, talkersRes,
				alertCountRes, alertsRes, healthRes, categoriesRes,
				deviceCountRes, prevSummaryRes, prevAlertCountRes,
			] = await Promise.allSettled([
				getTrafficSummary(timeParams),
				getBandwidthTimeSeries({ ...timeParams, interval: '1h' }),
				getProtocolDistribution(timeParams),
				getTopTalkers({ ...timeParams, limit: 10 }),
				getAlertCount(timeParams),
				getAlerts({ ...timeParams, size: 10 }),
				getSystemHealth(),
				getTrafficCategories(timeParams),
				getDeviceCount(timeParams),
				getTrafficSummary(prevTimeParams),
				getAlertCount(prevTimeParams),
			]);

			trafficSummary = summaryRes.status === 'fulfilled' ? summaryRes.value : null;
			bandwidthData = bandwidthRes.status === 'fulfilled' ? bandwidthRes.value.series : [];
			protocols = protocolsRes.status === 'fulfilled' ? protocolsRes.value.protocols : [];
			services = protocolsRes.status === 'fulfilled' ? protocolsRes.value.services : [];
			topTalkers = talkersRes.status === 'fulfilled' ? talkersRes.value.top_talkers : [];
			alertCount = alertCountRes.status === 'fulfilled' ? alertCountRes.value : null;
			recentAlerts = alertsRes.status === 'fulfilled' ? alertsRes.value.alerts : [];
			systemHealth = healthRes.status === 'fulfilled' ? healthRes.value : null;
			categories = categoriesRes.status === 'fulfilled' ? categoriesRes.value.categories : [];
			deviceCount = deviceCountRes.status === 'fulfilled' ? deviceCountRes.value.count : 0;
			prevTrafficSummary = prevSummaryRes.status === 'fulfilled' ? prevSummaryRes.value : null;
			prevAlertCount = prevAlertCountRes.status === 'fulfilled' ? prevAlertCountRes.value : null;

			lastUpdated = new Date().toLocaleTimeString();

			// Check if all core fetches failed (daemon unreachable)
			const coreFetches = [summaryRes, bandwidthRes, protocolsRes, talkersRes, alertCountRes, alertsRes, healthRes];
			const allFailed = coreFetches.every((r) => r.status === 'rejected');
			if (allFailed) {
				error = true;
			}
		} catch {
			error = true;
		} finally {
			loading = false;
		}
	}

	/**
	 * Handle filter bar changes. Updates active filters and re-fetches data.
	 */
	function handleFilterChange(filters: FilterState) {
		activeFilters = filters;
		fetchAllData();
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

	// Protocol total for percentages
	let protocolTotal = $derived(protocols.reduce((s, p) => s + p.count, 0));

	// Service bar colors
	const SERVICE_COLORS = ['var(--cyan)', 'var(--green)', 'var(--blue)', 'var(--purple)', 'var(--teal)', 'var(--amber)', 'var(--orange)', 'var(--red)'];
	let maxServiceCount = $derived(services.length > 0 ? services[0].count : 1);

	// Health status
	let healthStatus = $derived.by(() => {
		if (!systemHealth) return { label: '--', class: 'badge', healthy: false };
		if (systemHealth.healthy) return { label: 'Healthy', class: 'badge badge-success', healthy: true };
		return { label: 'Degraded', class: 'badge badge-warning', healthy: false };
	});

	// Total alert count with fallback
	let totalAlerts = $derived(alertCount?.counts?.total ?? 0);

	// Sorted recent alerts for the table
	let sortedAlerts = $derived.by(() => {
		const alerts = recentAlerts.slice(0, 10);
		const dir = alertSortDir === 'asc' ? 1 : -1;
		return [...alerts].sort((a, b) => {
			switch (alertSortField) {
				case 'severity':
					return ((a.alert?.severity ?? 99) - (b.alert?.severity ?? 99)) * dir;
				case 'signature':
					return (a.alert?.signature ?? '').localeCompare(b.alert?.signature ?? '') * dir;
				case 'src_ip':
					return (a.src_ip ?? '').localeCompare(b.src_ip ?? '') * dir;
				case 'dest_ip':
					return (a.dest_ip ?? '').localeCompare(b.dest_ip ?? '') * dir;
				default:
					return 0;
			}
		});
	});

	// ---------------------------------------------------------------------------
	// Trend indicators (compare current vs previous period)
	// ---------------------------------------------------------------------------

	function trendPercent(current: number, previous: number): { arrow: string; pct: string; direction: 'up' | 'down' | 'flat' } {
		if (previous === 0 && current === 0) return { arrow: '', pct: '', direction: 'flat' };
		if (previous === 0) return { arrow: '\u25B2', pct: 'new', direction: 'up' };
		const change = ((current - previous) / previous) * 100;
		if (Math.abs(change) < 0.5) return { arrow: '', pct: '', direction: 'flat' };
		return {
			arrow: change > 0 ? '\u25B2' : '\u25BC',
			pct: `${Math.abs(change).toFixed(1)}%`,
			direction: change > 0 ? 'up' : 'down',
		};
	}

	let bandwidthTrend = $derived(
		trendPercent(
			trafficSummary?.total_bytes ?? 0,
			prevTrafficSummary?.total_bytes ?? 0,
		)
	);

	let connectionTrend = $derived(
		trendPercent(
			trafficSummary?.connection_count ?? 0,
			prevTrafficSummary?.connection_count ?? 0,
		)
	);

	let alertTrend = $derived(
		trendPercent(
			alertCount?.counts?.total ?? 0,
			prevAlertCount?.counts?.total ?? 0,
		)
	);

	// ---------------------------------------------------------------------------
	// Traffic categories (horizontal bar chart data)
	// ---------------------------------------------------------------------------

	/** Maximum bytes across all categories, used for bar width scaling. */
	let maxCategoryBytes = $derived(
		categories.length > 0 ? Math.max(...categories.map((c) => c.total_bytes)) : 1
	);

	/** Split categories into two columns for the 2-column layout. */
	let categoriesLeft = $derived(categories.slice(0, Math.ceil(categories.length / 2)));
	let categoriesRight = $derived(categories.slice(Math.ceil(categories.length / 2)));

	// OLD CODE START — color keys didn't match backend category keys (social_media vs social, etc.)
	// const CATEGORY_COLORS: Record<string, string> = {
	// 	streaming: '#f85149',
	// 	social_media: '#58a6ff',
	// 	gaming: '#bc8cff',
	// 	productivity: '#3fb950',
	// 	cloud: '#79c0ff',
	// 	messaging: '#d29922',
	// 	news: '#8b949e',
	// 	shopping: '#f0883e',
	// 	email: '#56d4dd',
	// 	other: '#6e7681',
	// };
	// OLD CODE END

	// Category color palette — keys match backend CATEGORIES dict in traffic_classifier.py
	const CATEGORY_COLORS: Record<string, string> = {
		streaming: 'var(--red)',
		gaming: 'var(--purple)',
		social: 'var(--blue)',
		communication: 'var(--amber)',
		work: 'var(--green)',
		iot: 'var(--orange)',
		cloud: 'var(--cyan)',
		file_transfer: 'var(--teal)',
		dns: 'var(--text-muted)',
		email: 'var(--pink)',
		web: 'var(--accent)',
		security: 'var(--green)',
		shopping: 'var(--orange)',
		news: 'var(--blue)',
		ads: 'var(--text-muted)',
		updates: 'var(--teal)',
		suspicious: 'var(--red)',
		other: 'var(--text-muted)',
	};

	function categoryColor(name: string): string {
		return CATEGORY_COLORS[name.toLowerCase()] || CATEGORY_COLORS['other'];
	}

	// ---------------------------------------------------------------------------
	// Top talkers bar chart data
	// ---------------------------------------------------------------------------

	let maxTalkerBytes = $derived(
		topTalkers.length > 0 ? Math.max(...topTalkers.map((t) => t.total_bytes)) : 1
	);

	// ---------------------------------------------------------------------------
	// Alert sparkline data (severity breakdown over time)
	// ---------------------------------------------------------------------------

	let alertSparklinePoints = $derived.by(() => {
		if (recentAlerts.length === 0) return { high: '', medium: '', low: '' };
		// Group alerts into ~12 time buckets for sparkline
		const sorted = [...recentAlerts].sort((a, b) =>
			new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
		);
		const bucketCount = Math.min(12, sorted.length);
		const bucketSize = Math.ceil(sorted.length / bucketCount);

		const highCounts: number[] = [];
		const medCounts: number[] = [];
		const lowCounts: number[] = [];

		for (let i = 0; i < bucketCount; i++) {
			const slice = sorted.slice(i * bucketSize, (i + 1) * bucketSize);
			highCounts.push(slice.filter((a) => a.alert?.severity === 1).length);
			medCounts.push(slice.filter((a) => a.alert?.severity === 2).length);
			lowCounts.push(slice.filter((a) => a.alert?.severity === 3).length);
		}

		const maxCount = Math.max(1, ...highCounts.map((h, i) => h + medCounts[i] + lowCounts[i]));
		const sparkW = 200;
		const sparkH = 40;

		function toPath(counts: number[], baseline: number[]): string {
			return counts.map((c, i) => {
				const x = (i / (bucketCount - 1 || 1)) * sparkW;
				const y = sparkH - ((c + baseline[i]) / maxCount) * sparkH;
				return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
			}).join(' ');
		}

		const zeros = new Array(bucketCount).fill(0);
		return {
			high: toPath(highCounts, medCounts.map((m, i) => m + lowCounts[i])),
			medium: toPath(medCounts, lowCounts),
			low: toPath(lowCounts, zeros),
		};
	});
</script>

<svelte:head>
	<title>Dashboard | NetTap</title>
</svelte:head>

<div class="dashboard">
	<!-- Error / status banners -->
	{#if error}
		<div class="alert alert-warning error-banner">
			<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
			</svg>
			<span>Unable to reach the monitoring daemon. Check that the NetTap daemon container is running.</span>
		</div>
	{:else if systemHealth && !systemHealth.opensearch_reachable}
		<div class="alert alert-info error-banner">
			<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
			</svg>
			<span>OpenSearch is not reachable. The daemon is running but cannot connect to OpenSearch. Traffic data will be unavailable until the connection is restored.</span>
		</div>
	{:else if !loading && systemHealth?.opensearch_reachable && !trafficSummary && bandwidthData.length === 0}
		<div class="alert alert-info error-banner">
			<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
			</svg>
			<span>No traffic data yet. OpenSearch is connected but no network logs have been indexed. Traffic will appear once Zeek and Suricata start capturing.</span>
		</div>
	{/if}

	<!-- New device detection banner (mirror mode) -->
	{#if isMirrorMode && registryDevices.length > 0}
		<NewDeviceBanner devices={registryDevices} />
	{/if}

	<!-- Dashboard header -->
	<div class="dashboard-header">
		<div class="header-left">
			<h2>{isMirrorMode ? 'Device Overview' : 'Network Overview'}</h2>
			<p class="text-muted">
				{isMirrorMode
					? 'Devices on your network, organized by type.'
					: 'Real-time traffic, alerts, and system health.'}
			</p>
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

	<!-- Filter Bar -->
	<DashboardFilters
		timeRange={activeFilters.timeRange}
		device={activeFilters.device}
		protocol={activeFilters.protocol}
		onchange={handleFilterChange}
	/>

	<!-- Mirror mode: Device grid + capture health -->
	{#if isMirrorMode}
		<div class="grid grid-cols-2 mirror-mode-grid">
			<div class="mirror-main">
				<DeviceGrid devices={registryDevices} loading={loading} />
			</div>
			<div class="mirror-sidebar">
				<CaptureHealthPanel />
			</div>
		</div>
	{/if}

	<!-- Row 1: Stat Cards (always shown) -->
	<div class="grid stat-grid stat-grid-5">
		<!-- Total Bandwidth (24h) -->
		<a href="/logs" class="card stat-card stat-card-link">
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
					{#if bandwidthTrend.arrow}
						<span class="trend-indicator trend-{bandwidthTrend.direction}" title="vs previous period">
							{bandwidthTrend.arrow} {bandwidthTrend.pct}
						</span>
					{/if}
				</div>
			{/if}
			<p class="card-description">
				{#if trafficSummary}
					{formatBytesShort(trafficSummary.orig_bytes)} in / {formatBytesShort(trafficSummary.resp_bytes)} out
				{:else}
					Inbound + outbound traffic
				{/if}
			</p>
		</a>

		<!-- Active Connections -->
		<a href="/logs" class="card stat-card stat-card-link">
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
					{#if connectionTrend.arrow}
						<span class="trend-indicator trend-{connectionTrend.direction}" title="vs previous period">
							{connectionTrend.arrow} {connectionTrend.pct}
						</span>
					{/if}
				</div>
			{/if}
			<p class="card-description">
				{#if trafficSummary}
					Top protocol: {trafficSummary.top_protocol}
				{:else}
					Total observed connections
				{/if}
			</p>
		</a>

		<!-- Active Alerts (24h) -->
		<a href="/alerts" class="card stat-card stat-card-link">
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
					{#if alertTrend.arrow}
						<span class="trend-indicator trend-{alertTrend.direction}" title="vs previous period">
							{alertTrend.arrow} {alertTrend.pct}
						</span>
					{/if}
				</div>
			{/if}
			<p class="card-description">
				{#if alertCount?.counts}
					{alertCount.counts.high} high, {alertCount.counts.medium} med, {alertCount.counts.low} low
				{:else}
					Suricata IDS detections
				{/if}
			</p>
		</a>

		<!-- System Health -->
		<a href="/infrastructure" class="card stat-card stat-card-link">
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
		</a>

		<!-- Device Count -->
		<a href="/iot" class="card stat-card stat-card-link">
			<div class="card-header">
				<span class="card-subtitle">Devices</span>
				<svg class="stat-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
				</svg>
			</div>
			{#if loading && deviceCount === 0}
				<div class="skeleton skeleton-value"></div>
			{:else}
				<div class="card-value">
					{deviceCount > 0 ? formatNumber(deviceCount) : '--'}
				</div>
			{/if}
			<p class="card-description">
				DHCP-leased devices on network
			</p>
		</a>
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

		<!-- Network Protocols — Dual Panel -->
		<div class="card chart-card">
			<div class="card-header">
				<span class="card-title">Network Protocols</span>
				<span class="card-subtitle">Transport + Application layer</span>
			</div>
			{#if loading && protocols.length === 0}
				<div class="skeleton skeleton-chart"></div>
			{:else}
				<div class="protocol-dual-panel">
					<!-- Left: Transport donut -->
					<div class="transport-panel">
						<span class="panel-label">Transport</span>
						<DonutChart
							segments={donutSegments}
							size={150}
							formatValue={formatNumber}
						/>
					</div>
					<!-- Right: Application services -->
					<div class="services-panel">
						<div class="panel-label services-label-bar">Application Layer</div>
						{#if services.length > 0}
							<div class="service-bar-list">
								{#each services.slice(0, 8) as svc, i (`${svc.name}-${i}`)}
									<div class="svc-bar-row">
										<span class="svc-bar-name">{(svc.name || 'unknown').toUpperCase()}</span>
										<div class="svc-bar-track">
											<div class="svc-bar-fill" style="width: {(svc.count / maxServiceCount) * 100}%; background: {SERVICE_COLORS[i] ?? SERVICE_COLORS[SERVICE_COLORS.length - 1]};"></div>
										</div>
										<span class="svc-bar-value mono">{formatNumber(svc.count)}</span>
									</div>
								{/each}
							</div>
						{:else}
							<p class="text-muted" style="padding: var(--space-lg); text-align: center; font-size: var(--text-sm);">No service data available.</p>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>

	<!-- Row 2.5: Traffic Categories (2-column layout) -->
	<div class="card categories-card">
		<div class="card-header">
			<span class="card-title">Traffic Categories</span>
			<span class="card-subtitle">Bandwidth by category</span>
		</div>
		{#if loading && categories.length === 0}
			<div class="skeleton-table">
				{#each Array(4) as _}
					<div class="skeleton skeleton-row"></div>
				{/each}
			</div>
		{:else if categories.length === 0}
			<div class="table-empty">
				<p class="text-muted">No category data yet. Traffic will appear once Zeek captures ASN-tagged connections.</p>
			</div>
		{:else}
			<div class="categories-columns">
				<div class="categories-col">
					<HorizontalBarList
						items={categoriesLeft.map(cat => ({
							key: cat.name,
							label: cat.label,
							value: cat.total_bytes,
							formattedValue: formatBytesShort(cat.total_bytes),
							color: categoryColor(cat.name),
							href: '/traffic/' + cat.name,
						}))}
						maxValue={maxCategoryBytes}
						showRank={false}
						labelWidth={120}
						barHeight={12}
					/>
				</div>
				<div class="categories-col">
					<HorizontalBarList
						items={categoriesRight.map(cat => ({
							key: cat.name,
							label: cat.label,
							value: cat.total_bytes,
							formattedValue: formatBytesShort(cat.total_bytes),
							color: categoryColor(cat.name),
							href: '/traffic/' + cat.name,
						}))}
						maxValue={maxCategoryBytes}
						showRank={false}
						labelWidth={120}
						barHeight={12}
					/>
				</div>
			</div>
		{/if}
	</div>

	<!-- Row 3: Top Talkers + Alert Sparkline + Recent Alerts -->
	<div class="grid grid-cols-2 tables-grid">
		<!-- Top Talkers (horizontal bar chart) -->
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
				<HorizontalBarList
					items={topTalkers.slice(0, 5).map((talker, i) => ({
						key: talker.ip,
						label: talker.ip,
						isIp: true,
						value: talker.total_bytes,
						formattedValue: formatBytesShort(talker.total_bytes),
						gradient: 'linear-gradient(90deg, var(--cyan), var(--blue))',
						secondaryValue: talker.connection_count.toLocaleString() + ' conn',
						href: '/devices/' + talker.ip,
					}))}
					showRank={true}
					labelWidth={130}
					barHeight={12}
				/>
			{/if}
		</div>

		<!-- Recent Alerts + Sparkline -->
		<div class="card table-card">
			<div class="card-header">
				<span class="card-title">Recent Alerts</span>
				<a href="/alerts" class="card-action">View all</a>
			</div>

			<!-- Alert Trend Sparkline -->
			{#if recentAlerts.length > 1}
				<div class="alert-sparkline-container">
					<div class="sparkline-legend">
						<span class="sparkline-legend-item"><span class="sparkline-dot" style="background: var(--red);"></span> High</span>
						<span class="sparkline-legend-item"><span class="sparkline-dot" style="background: var(--amber);"></span> Medium</span>
						<span class="sparkline-legend-item"><span class="sparkline-dot" style="background: var(--blue);"></span> Low</span>
					</div>
					<svg class="alert-sparkline" viewBox="0 0 200 40" preserveAspectRatio="none">
						{#if alertSparklinePoints.high}
							<path d={alertSparklinePoints.high} fill="none" stroke="var(--red)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
						{/if}
						{#if alertSparklinePoints.medium}
							<path d={alertSparklinePoints.medium} fill="none" stroke="var(--amber)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
						{/if}
						{#if alertSparklinePoints.low}
							<path d={alertSparklinePoints.low} fill="none" stroke="var(--blue)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
						{/if}
					</svg>
				</div>
			{/if}
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
								<th class="sortable-th" onclick={() => toggleAlertSort('severity')}>
									Severity {alertSortField === 'severity' ? (alertSortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
								</th>
								<th class="sortable-th" onclick={() => toggleAlertSort('signature')}>
									Signature {alertSortField === 'signature' ? (alertSortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
								</th>
								<th class="sortable-th" onclick={() => toggleAlertSort('src_ip')}>
									Source {alertSortField === 'src_ip' ? (alertSortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
								</th>
								<th class="sortable-th" onclick={() => toggleAlertSort('dest_ip')}>
									Dest {alertSortField === 'dest_ip' ? (alertSortDir === 'asc' ? '\u25B2' : '\u25BC') : ''}
								</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedAlerts as alertItem}
								{@const sev = severityBadge(alertItem.alert?.severity)}
								<tr
									class="alert-row-clickable"
									onclick={() => (selectedAlert = alertItem)}
									role="button"
									tabindex="0"
									onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectedAlert = alertItem; } }}
								>
									<td>
										<span class={sev.class}>{sev.label}</span>
									</td>
									<td class="signature-cell" title={alertItem.alert?.signature || 'Unknown'}>
										{alertItem.alert?.signature || 'Unknown signature'}
									</td>
									<td class="ip-cell">
										{#if alertItem.src_ip}
											<IPAddress ip={alertItem.src_ip} />
										{:else}
											<span class="text-muted">--</span>
										{/if}
									</td>
									<td class="ip-cell">
										{#if alertItem.dest_ip}
											<IPAddress ip={alertItem.dest_ip} />
										{:else}
											<span class="text-muted">--</span>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</div>
</div>

<!-- Alert Detail Panel (slides in from right) -->
<AlertDetailPanel
	alert={selectedAlert}
	onclose={() => (selectedAlert = null)}
/>

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
		gap: var(--space-xs);
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

	/* Stat cards — 5-column grid */
	.stat-grid {
		margin-top: var(--space-xs);
	}

	.stat-grid-5 {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--space-md);
	}

	.stat-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.stat-card-link {
		text-decoration: none;
		color: inherit;
		cursor: pointer;
		transition: border-color 0.15s, box-shadow 0.15s;
	}

	.stat-card-link:hover {
		border-color: var(--accent);
		box-shadow: 0 0 0 1px var(--accent);
	}

	.stat-icon {
		flex-shrink: 0;
		opacity: 0.7;
	}

	.card-description {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* Trend indicators */
	.trend-indicator {
		font-size: var(--text-xs);
		font-weight: 600;
		margin-left: var(--space-sm);
		white-space: nowrap;
	}

	.trend-up {
		color: var(--success);
	}

	.trend-down {
		color: var(--danger);
	}

	/* Traffic Categories */
	.categories-card {
		margin-top: var(--space-xs);
	}

	.categories-columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-lg);
	}

	.categories-col {
		min-width: 0;
	}

	/* OLD CODE START — replaced by HorizontalBarList component */
	/*
	.categories-chart {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
	}

	.category-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.category-label {
		flex-shrink: 0;
		width: 100px;
		font-size: var(--text-sm);
		color: var(--text-secondary);
		text-align: right;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.category-bar-track {
		flex: 1;
		height: 20px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.category-bar-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		transition: width 0.4s ease-out;
		min-width: 2px;
	}

	.category-value {
		flex-shrink: 0;
		width: 60px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}
	*/
	/* OLD CODE END */

	/* OLD CODE START — replaced by HorizontalBarList component */
	/*
	.top-talkers-bars {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.talker-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
		text-decoration: none;
		color: inherit;
		transition: background-color var(--transition-fast);
	}

	.talker-row:hover {
		background-color: var(--bg-tertiary);
		color: inherit;
	}

	.talker-rank {
		flex-shrink: 0;
		width: 20px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	.talker-ip {
		flex-shrink: 0;
		width: 120px;
		font-size: var(--text-xs);
	}

	.talker-bar-track {
		flex: 1;
		height: 18px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.talker-bar-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		background: linear-gradient(90deg, var(--cyan), var(--blue));
		transition: width 0.4s ease-out;
		min-width: 2px;
	}

	.talker-value {
		flex-shrink: 0;
		width: 60px;
		font-size: var(--text-xs);
		color: var(--text-primary);
		text-align: right;
	}

	.talker-conns {
		flex-shrink: 0;
		width: 70px;
		font-size: var(--text-xs);
		text-align: right;
	}
	*/
	/* OLD CODE END */

	/* Alert sparkline */
	.alert-sparkline-container {
		padding: var(--space-sm) 0;
		margin-bottom: var(--space-sm);
		border-bottom: 1px solid var(--border-dim);
	}

	.sparkline-legend {
		display: flex;
		gap: var(--space-md);
		margin-bottom: var(--space-xs);
	}

	.sparkline-legend-item {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.sparkline-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		display: inline-block;
	}

	.alert-sparkline {
		width: 100%;
		height: 40px;
	}

	/* Clickable alert rows */
	.alert-row-clickable {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.alert-row-clickable:hover {
		background-color: var(--bg-tertiary);
	}

	.alert-row-clickable:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	/* Charts */
	.charts-grid {
		margin-top: var(--space-xs);
	}

	.chart-card {
		min-height: 340px;
	}

	/* OLD CODE START — donut-wrapper replaced by protocol-dual-panel */
	/* .donut-wrapper {
		display: flex;
		justify-content: center;
		padding: var(--space-md) 0;
	} */
	/* OLD CODE END */

	/* Protocol Dual Panel */
	.protocol-dual-panel {
		display: grid;
		grid-template-columns: 180px 1fr;
		min-height: 280px;
	}

	.transport-panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-md);
		border-right: 1px solid var(--border-dim);
		gap: var(--space-sm);
	}

	.panel-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-dim);
	}

	.services-panel {
		display: flex;
		flex-direction: column;
	}

	.services-label-bar {
		padding: var(--space-sm) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.service-bar-list {
		flex: 1;
		padding: var(--space-xs) 0;
	}

	.svc-bar-row {
		display: grid;
		grid-template-columns: 65px 1fr auto;
		align-items: center;
		gap: var(--space-sm);
		padding: 4px var(--space-lg);
		transition: background var(--transition-fast);
	}

	.svc-bar-row:hover { background: var(--bg-tertiary); }

	.svc-bar-name {
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-primary);
	}

	.svc-bar-track {
		height: 8px;
		background: var(--bg-tertiary);
		border-radius: 4px;
		overflow: hidden;
	}

	.svc-bar-fill {
		height: 100%;
		border-radius: 4px;
		opacity: 0.7;
		transition: all 0.4s ease;
	}

	.svc-bar-row:hover .svc-bar-fill { opacity: 1; }

	.svc-bar-value {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		text-align: right;
		min-width: 45px;
		white-space: nowrap;
	}

	@media (max-width: 768px) {
		.protocol-dual-panel { grid-template-columns: 1fr; }
		.transport-panel { border-right: none; border-bottom: 1px solid var(--border-dim); }
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

	.sortable-th {
		cursor: pointer;
		user-select: none;
		transition: color var(--transition-fast);
	}

	.sortable-th:hover {
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
	@media (max-width: 1024px) {
		.stat-grid-5 {
			grid-template-columns: repeat(3, 1fr);
		}
	}

	@media (max-width: 768px) {
		.dashboard-header {
			flex-direction: column;
		}

		.stat-grid-5 {
			grid-template-columns: repeat(2, 1fr);
		}

		.signature-cell {
			max-width: 140px;
		}

		/* OLD CODE START — replaced by HorizontalBarList component */
		/*
		.category-label {
			width: 70px;
			font-size: var(--text-xs);
		}

		.category-value {
			width: 50px;
		}
		*/
		/* OLD CODE END */
	}

	@media (max-width: 480px) {
		.stat-grid-5 {
			grid-template-columns: 1fr;
		}
	}

	/* Mirror mode layout */
	.mirror-mode-grid {
		grid-template-columns: 2fr 1fr;
	}

	.mirror-main {
		min-width: 0;
	}

	.mirror-sidebar {
		min-width: 0;
	}

	@media (max-width: 1024px) {
		.mirror-mode-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
