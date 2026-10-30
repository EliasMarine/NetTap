<!--
  Live Network Monitor — Full SIEM-style real-time dashboard.
  Stats ribbon + Leaflet geo map + protocol donut + top talkers + sortable table + detail drawer.
  All widgets cross-filter: click map/chart/bar → filters table + other widgets.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { getLiveDashboard, getLiveConnectionDetail } from '$lib/api/live';
	import type {
		LiveConnection,
		LiveDashboardResponse,
		ConnectionDetailResponse,
		GeoArc,
		TopTalker,
	} from '$lib/api/live';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import type { DrawerTab } from '$components/DetailDrawer.svelte';
	import LiveStatsRibbon from '$components/live/LiveStatsRibbon.svelte';
	import LiveConnectionTable from '$components/live/LiveConnectionTable.svelte';
	import LiveConnectionDrawerContent from '$components/drawer/content/LiveConnectionDrawerContent.svelte';
	import ProtocolDonut from '$components/live/ProtocolDonut.svelte';
	import TopTalkersChart from '$components/live/TopTalkersChart.svelte';
	import GeoMap from '$components/live/GeoMap.svelte';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const REFRESH_INTERVAL_MS = 3000;
	const PAGE_SIZE = 200;

	// Default home location (center of continental US).
	// TODO: auto-detect from appliance WAN IP GeoIP or user settings.
	const DEFAULT_HOME = { lat: 39.8, lng: -98.6 };

	// ---------------------------------------------------------------------------
	// State — raw data
	// ---------------------------------------------------------------------------

	let dashboard = $state<LiveDashboardResponse | null>(null);
	let loading = $state(false);
	let error = $state('');
	let paused = $state(false);

	// ---------------------------------------------------------------------------
	// State — cross-filtering
	// ---------------------------------------------------------------------------

	let countryFilter = $state<string | null>(null);
	let protocolFilter = $state<string | null>(null);
	let deviceFilter = $state<string | null>(null);

	// ---------------------------------------------------------------------------
	// State — drawer
	// ---------------------------------------------------------------------------

	let drawerConn = $state<LiveConnection | null>(null);
	let drawerTab = $state('details');
	let drawerDetail = $state<ConnectionDetailResponse | null>(null);
	let drawerDetailLoading = $state(false);

	// ---------------------------------------------------------------------------
	// Derived — filtered connections
	// ---------------------------------------------------------------------------

	let filteredConnections = $derived.by(() => {
		if (!dashboard) return [];
		let result = dashboard.connections;
		if (countryFilter) {
			result = result.filter(
				(c) => c.country?.toUpperCase() === countryFilter!.toUpperCase()
			);
		}
		if (protocolFilter) {
			result = result.filter(
				(c) => c.protocol?.toLowerCase() === protocolFilter!.toLowerCase()
			);
		}
		if (deviceFilter) {
			result = result.filter(
				(c) => c.source_ip === deviceFilter || c.dest_ip === deviceFilter
			);
		}
		return result;
	});

	let hasActiveFilter = $derived(
		countryFilter !== null || protocolFilter !== null || deviceFilter !== null
	);

	let alertCountrySet = $derived.by(() => {
		if (!dashboard) return new Set<string>();
		const s = new Set<string>();
		for (const conn of dashboard.connections) {
			if (conn.has_alert && conn.country) s.add(conn.country.toUpperCase());
		}
		return s;
	});

	// Derive protocol distribution from filtered connections for cross-filter feedback
	let filteredProtocols = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const c of filteredConnections) {
			const p = (c.protocol || 'other').toLowerCase();
			map[p] = (map[p] || 0) + 1;
		}
		return map;
	});

	// Derive top talkers from filtered connections
	let filteredTopTalkers = $derived.by((): TopTalker[] => {
		const map = new Map<string, { bytes: number; connections: number }>();
		for (const c of filteredConnections) {
			const existing = map.get(c.source_ip) || { bytes: 0, connections: 0 };
			existing.bytes += c.bytes;
			existing.connections += 1;
			map.set(c.source_ip, existing);
		}
		return [...map.entries()]
			.sort((a, b) => b[1].bytes - a[1].bytes)
			.slice(0, 10)
			.map(([ip, data]) => ({ ip, bytes: data.bytes, connections: data.connections }));
	});

	// Connection ID for drawer highlight
	let selectedConnId = $derived(
		drawerConn ? `${drawerConn.timestamp}${drawerConn.source_ip}${drawerConn.dest_ip}` : null
	);

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchData() {
		if (paused) return;
		loading = true;
		error = '';
		try {
			dashboard = await getLiveDashboard({ limit: PAGE_SIZE });
			if (dashboard._error) {
				error = dashboard._error;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch live data';
		} finally {
			loading = false;
		}
	}

	function togglePause() {
		paused = !paused;
		if (!paused) fetchData();
	}

	// ---------------------------------------------------------------------------
	// Cross-filter handlers (toggle behavior)
	// ---------------------------------------------------------------------------

	function setCountryFilter(code: string) {
		countryFilter = countryFilter === code ? null : code;
	}

	function setProtocolFilter(proto: string) {
		protocolFilter = protocolFilter === proto ? null : proto;
	}

	function setDeviceFilter(ip: string) {
		deviceFilter = deviceFilter === ip ? null : ip;
	}

	function clearAllFilters() {
		countryFilter = null;
		protocolFilter = null;
		deviceFilter = null;
	}

	// ---------------------------------------------------------------------------
	// Drawer
	// ---------------------------------------------------------------------------

	function openDrawer(conn: LiveConnection) {
		drawerConn = conn;
		drawerTab = 'details';
		drawerDetail = null;
		drawerDetailLoading = true;
		getLiveConnectionDetail(conn.source_ip, conn.dest_ip, conn.dest_port)
			.then((d) => { drawerDetail = d; })
			.catch(() => { drawerDetail = null; })
			.finally(() => { drawerDetailLoading = false; });
	}

	function closeDrawer() {
		drawerConn = null;
		drawerDetail = null;
	}

	// Update drawer alert badge
	let drawerTabs = $derived.by((): DrawerTab[] => {
		const alertCount = drawerDetail?.alert_count ?? 0;
		return [
			{ id: 'details', label: 'Details' },
			{ id: 'alerts', label: 'Alerts', badge: alertCount > 0 ? alertCount : undefined },
		];
	});

	// ---------------------------------------------------------------------------
	// Auto-refresh lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		fetchData();
		const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
		return () => clearInterval(timer);
	});
</script>

<svelte:head>
	<title>Live Monitor | NetTap</title>
</svelte:head>

<div class="live-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>
				Live Network Monitor
				{#if !paused}
					<span class="live-badge">
						<span class="live-dot"></span>
						LIVE
					</span>
				{/if}
			</h2>
			<p class="text-muted">Real-time connections from your network to the world</p>
		</div>
		<div class="header-actions">
			<button
				class="btn btn-sm"
				class:btn-primary={paused}
				class:btn-secondary={!paused}
				onclick={togglePause}
			>
				{paused ? 'Resume' : 'Pause'}
			</button>
		</div>
	</div>

	<!-- Stats Ribbon -->
	{#if dashboard}
		<LiveStatsRibbon
			connectionsPerSecond={dashboard.stats.connections_per_second}
			bandwidthBytesPerSecond={dashboard.stats.bandwidth_bytes_per_second}
			activeDevices={dashboard.stats.active_devices}
			topCountry={dashboard.stats.top_country}
		/>
	{/if}

	<!-- Geo Map -->
	<div class="map-section">
		<div class="map-chrome">
			<span class="section-label">Connection Geography</span>
			<div class="map-legend">
				<span class="legend-item"><span class="legend-dot legend-dot-home"></span> Home</span>
				<span class="legend-item"><span class="legend-dot legend-dot-active"></span> Active</span>
				<span class="legend-item"><span class="legend-dot legend-dot-alert"></span> Alert</span>
			</div>
		</div>
		<div class="map-wrapper">
			<GeoMap
				destinations={dashboard?.geo_arcs ?? []}
				homeLocation={DEFAULT_HOME}
				activeCountry={countryFilter}
				{paused}
				hasAlertCountries={alertCountrySet}
				onclick={setCountryFilter}
			/>
		</div>
	</div>

	<!-- Charts Row -->
	<div class="charts-row">
		<div class="card">
			<div class="card-header">
				<h3 class="card-title">Protocol Distribution</h3>
				<span class="card-meta mono">Last 5m</span>
			</div>
			<div class="card-body">
				<ProtocolDonut
					protocols={hasActiveFilter ? filteredProtocols : (dashboard?.protocols ?? {})}
					activeProtocol={protocolFilter}
					onclick={setProtocolFilter}
				/>
			</div>
		</div>
		<div class="card">
			<div class="card-header">
				<h3 class="card-title">Top Talkers</h3>
				<span class="card-meta mono">By bytes transferred</span>
			</div>
			<div class="card-body">
				<TopTalkersChart
					talkers={hasActiveFilter ? filteredTopTalkers : (dashboard?.top_talkers ?? [])}
					activeDevice={deviceFilter}
					onclick={setDeviceFilter}
				/>
			</div>
		</div>
	</div>

	<!-- Active Filter Pills -->
	{#if hasActiveFilter}
		<div class="filter-pills">
			{#if countryFilter}
				<button class="filter-pill" onclick={() => { countryFilter = null; }}>
					Country: {countryFilter} <span class="pill-x">&times;</span>
				</button>
			{/if}
			{#if protocolFilter}
				<button class="filter-pill" onclick={() => { protocolFilter = null; }}>
					Protocol: {protocolFilter.toUpperCase()} <span class="pill-x">&times;</span>
				</button>
			{/if}
			{#if deviceFilter}
				<button class="filter-pill" onclick={() => { deviceFilter = null; }}>
					Device: {deviceFilter} <span class="pill-x">&times;</span>
				</button>
			{/if}
			<button class="clear-btn" onclick={clearAllFilters}>Clear All</button>
		</div>
	{/if}

	<!-- Connections Table -->
	{#if loading && !dashboard}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading live connections...</p>
		</div>
	{:else if error && !dashboard}
		<div class="alert alert-danger">{error}</div>
	{:else}
		<div class="table-section card">
			<div class="table-chrome">
				<h3 class="card-title">Live Connections</h3>
				<span class="card-meta mono">
					{filteredConnections.length}
					{#if hasActiveFilter}
						of {dashboard?.count ?? 0} (filtered)
					{/if}
					connections
				</span>
			</div>
			<LiveConnectionTable
				connections={filteredConnections}
				selectedId={selectedConnId}
				onrowclick={openDrawer}
			/>
		</div>
	{/if}

	<!-- Status bar -->
	<div class="status-bar">
		<span class="text-muted">
			{#if paused}
				Paused
			{:else}
				Auto-refreshing every {REFRESH_INTERVAL_MS / 1000}s
			{/if}
			{#if error}
				 — <span class="text-warning">{error}</span>
			{/if}
		</span>
	</div>
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerConn !== null}
	title={drawerConn ? `${drawerConn.source_ip} → ${drawerConn.dest_ip}` : ''}
	subtitle={drawerConn ? `${(drawerConn.protocol || '').toUpperCase()} : ${drawerConn.dest_port}` : ''}
	tabs={drawerTabs}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => { drawerTab = t; }}
>
	{#snippet children()}
		{#if drawerConn}
			<LiveConnectionDrawerContent
				connection={drawerConn}
				detail={drawerDetail}
				detailLoading={drawerDetailLoading}
				activeTab={drawerTab}
			/>
		{/if}
	{/snippet}
	{#snippet actions()}
		{#if drawerConn}
			<div class="drawer-actions-row">
				<button class="btn btn-secondary btn-sm" onclick={() => { if (drawerConn) setDeviceFilter(drawerConn.source_ip); closeDrawer(); }}>
					Filter by Source
				</button>
				<button class="btn btn-secondary btn-sm" onclick={() => { if (drawerConn) setCountryFilter(drawerConn.country?.toUpperCase()); closeDrawer(); }}>
					Filter by Country
				</button>
			</div>
		{/if}
	{/snippet}
</DetailDrawer>

<style>
	.live-page {
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

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.live-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 2px 10px;
		background: var(--green-dim);
		border: 1px solid rgba(0, 230, 118, 0.25);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--green);
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.live-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--green);
		animation: live-pulse 2s ease-in-out infinite;
	}

	@keyframes live-pulse {
		0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0, 230, 118, 0.4); }
		50% { opacity: 0.6; box-shadow: 0 0 0 6px rgba(0, 230, 118, 0); }
	}

	/* Map section */
	.map-section {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		overflow: hidden;
	}

	.map-chrome {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-dim);
	}

	.section-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.map-legend {
		display: flex;
		gap: var(--space-md);
		font-size: 11px;
		color: var(--text-muted);
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.legend-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.legend-dot-home { background: var(--green); }
	.legend-dot-active { background: var(--cyan); }
	.legend-dot-alert { background: var(--red); }

	.map-wrapper {
		height: 400px;
	}

	/* Charts row */
	.charts-row {
		display: grid;
		grid-template-columns: 30% 1fr;
		gap: var(--space-md);
	}

	.card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		overflow: hidden;
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-md);
		border-bottom: 1px solid var(--border-dim);
	}

	.card-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.card-meta {
		font-size: 11px;
		color: var(--text-muted);
	}

	.card-body {
		padding: var(--space-md);
	}

	/* Filter pills */
	.filter-pills {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.filter-pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		background: var(--accent-muted);
		border: 1px solid rgba(0, 212, 255, 0.2);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--accent);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.filter-pill:hover { background: rgba(0, 212, 255, 0.2); }
	.pill-x { font-size: 14px; opacity: 0.6; }

	.clear-btn {
		color: var(--text-muted);
		font-size: var(--text-xs);
		cursor: pointer;
		border: none;
		background: none;
		font-family: var(--font-sans);
		transition: color var(--transition-fast);
	}

	.clear-btn:hover { color: var(--text-secondary); }

	/* Table section */
	.table-section { padding: 0; }

	.table-chrome {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-md);
		border-bottom: 1px solid var(--border-dim);
	}

	/* Status bar */
	.status-bar {
		text-align: center;
		font-size: var(--text-sm);
		padding: var(--space-sm) 0;
	}

	/* Loading */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }

	/* Drawer actions */
	.drawer-actions-row {
		display: flex;
		gap: var(--space-sm);
	}

	.drawer-actions-row .btn { flex: 1; justify-content: center; }

	/* Responsive */
	@media (max-width: 1024px) {
		.charts-row { grid-template-columns: 1fr; }
		.map-wrapper { height: 350px; }
	}

	@media (max-width: 768px) {
		.page-header { flex-direction: column; }
		.charts-row { grid-template-columns: 1fr; }
		.map-wrapper { height: 250px; }
	}
</style>
