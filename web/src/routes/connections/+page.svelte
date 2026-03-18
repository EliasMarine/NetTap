<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getConnections,
		getConnectionStats,
		getConnectionSankey,
		getConnectionTimeline,
	} from '$api/traffic';
	import type {
		Connection,
		ConnectionsResponse,
		ConnectionStatsResponse,
		SankeyResponse,
		ConnectionTimelineResponse,
		ConnectionTimelineBucket,
	} from '$api/traffic';
	import { getLiveConnections } from '$api/live';
	import IPAddress from '$components/IPAddress.svelte';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import type { BarItem } from '$components/HorizontalBarList.svelte';
	import SankeyDiagram from '$components/SankeyDiagram.svelte';
	import SessionTimeline from '$components/SessionTimeline.svelte';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import ConnectionDrawerContent from '$components/drawer/content/ConnectionDrawerContent.svelte';
	import { buildTSharkFilter, getField, asString } from '$lib/utils/tshark-filter';
	import { captureMode } from '$lib/stores/captureMode';

	// ---------------------------------------------------------------------------
	// Types & Constants
	// ---------------------------------------------------------------------------

	type StateFilter = 'all' | 'established' | 'closed' | 'rejected' | 'timeout';

	interface TimeRange {
		label: string;
		value: string;
		ms: number;
	}

	const TIME_RANGES: TimeRange[] = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000 },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m', '1h': '5m', '4h': '15m', '24h': '1h', '7d': '6h',
	};

	const STATE_FILTERS: { value: StateFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'established', label: 'Established' },
		{ value: 'closed', label: 'Closed' },
		{ value: 'rejected', label: 'Rejected' },
		{ value: 'timeout', label: 'Timeout' },
	];

	const PROTOCOL_OPTIONS = ['All', 'TCP', 'UDP', 'ICMP', 'TLS'] as const;

	const PROTO_COLORS: Record<string, string> = {
		tcp: 'var(--cyan)', udp: 'var(--green)', tls: 'var(--purple)',
		dns: 'var(--amber)', icmp: 'var(--red)', http: 'var(--blue)',
	};

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let initialized = $state(false);
	let loading = $state(false);

	// Time range
	let selectedTimeRange = $state<TimeRange>(TIME_RANGES[1]); // 1h
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Stats
	let stats = $state<ConnectionStatsResponse | null>(null);
	let activeNow = $state(0);

	// Sankey
	let sankey = $state<SankeyResponse | null>(null);

	// Timeline
	let timeline = $state<ConnectionTimelineBucket[]>([]);

	// Connections table
	let connections = $state<Connection[]>([]);
	let totalConnections = $state(0);
	let totalPages = $state(0);
	let currentPage = $state(1);
	let pageSize = $state(50);

	// Filters
	let protocolFilter = $state('All');
	let serviceFilter = $state('');
	let ipFilter = $state('');
	let countryFilter = $state('');
	let stateFilter = $state<StateFilter>('all');
	let hasAlertsFilter = $state(false);
	let sankeyFilter = $state<{ type: string; id: string } | null>(null);

	// Drawer
	let drawerConn = $state<Connection | null>(null);
	let drawerTab = $state('summary');
	let isMirrorMode = $state(false);
	const CONN_DRAWER_TABS = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'tshark', label: 'TShark' },
		{ id: 'related', label: 'Related' },
		{ id: 'flow', label: 'Flow' },
	];

	captureMode.subscribe((mode) => { isMirrorMode = mode === 'mirror'; });

	// Sort
	type SortKey = 'timestamp' | 'src' | 'dst' | 'protocol' | 'service' | 'duration' | 'bytesIn' | 'bytesOut' | 'state';
	let sortKey = $state<SortKey | null>(null);
	let sortDir = $state<'asc' | 'desc'>('desc');

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	function sortValue(conn: Connection, key: SortKey): string | number {
		switch (key) {
			case 'timestamp': return conn['@timestamp'] as string ?? '';
			case 'src': return asString(getField(conn, 'source.ip'));
			case 'dst': return asString(getField(conn, 'destination.ip'));
			case 'protocol': return asString(getField(conn, 'network.transport'));
			case 'service': return asString(getField(conn, 'protocol'));
			case 'duration': {
				const start = getField(conn, 'event.start') as string | undefined;
				const end = getField(conn, 'event.end') as string | undefined;
				if (!start || !end) return 0;
				return new Date(end).getTime() - new Date(start).getTime();
			}
			case 'bytesIn': return (getField(conn, 'source.bytes') ?? getField(conn, 'client.bytes') ?? 0) as number;
			case 'bytesOut': return (getField(conn, 'destination.bytes') ?? getField(conn, 'server.bytes') ?? 0) as number;
			case 'state': return connState(conn);
		}
	}

	let sortedConnections = $derived.by(() => {
		if (!sortKey) return connections;
		const key = sortKey;
		const dir = sortDir;
		return [...connections].sort((a, b) => {
			const va = sortValue(a, key);
			const vb = sortValue(b, key);
			if (typeof va === 'number' && typeof vb === 'number') return dir === 'asc' ? va - vb : vb - va;
			return dir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
		});
	});

	// Bar list items for analytics row
	let sourceBarItems = $derived<BarItem[]>(
		(stats?.top_sources || []).map((s, i) => ({
			key: s.ip,
			label: s.ip,
			value: s.total_bytes,
			formattedValue: formatBytes(s.total_bytes),
			secondaryValue: `${s.connections} conn`,
			color: 'var(--cyan)',
			isIp: true,
			mono: true,
		}))
	);

	let protocolBarItems = $derived<BarItem[]>(
		(stats?.protocols || []).map((p) => ({
			key: p.name,
			label: p.name.toUpperCase(),
			value: p.count,
			formattedValue: formatNumber(p.count),
			color: PROTO_COLORS[p.name.toLowerCase()] || 'var(--accent)',
		}))
	);

	let destBarItems = $derived<BarItem[]>(
		(stats?.top_destinations || []).map((d) => ({
			key: d.ip,
			label: d.asn || d.ip,
			value: d.total_bytes,
			formattedValue: formatBytes(d.total_bytes),
			secondaryValue: d.country || '',
			color: 'var(--green)',
		}))
	);

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '--';
		try { return new Date(ts).toLocaleString(); } catch { return ts; }
	}

	function formatBytes(bytes: number | undefined): string {
		if (bytes === undefined || bytes === null) return '--';
		if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
		if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
		if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${bytes} B`;
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return String(n);
	}

	function formatDuration(conn: Connection): string {
		const start = getField(conn, 'event.start') as string | undefined;
		const end = getField(conn, 'event.end') as string | undefined;
		if (!start || !end) return '--';
		const ms = new Date(end).getTime() - new Date(start).getTime();
		if (isNaN(ms) || ms < 0) return '--';
		const seconds = ms / 1000;
		if (seconds < 1) return `${ms}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const mins = Math.floor(seconds / 60);
		const secs = (seconds % 60).toFixed(0);
		return `${mins}m ${secs}s`;
	}

	function connState(conn: Connection): string {
		const state = asString(getField(conn, 'zeek.conn.conn_state'));
		const lower = state.toLowerCase();
		if (lower.includes('established') || lower === 'sf' || lower === 's1') return 'established';
		if (lower.includes('reject') || lower === 'rej' || lower === 'rstr' || lower === 'rsto') return 'rejected';
		if (lower.includes('timeout') || lower === 's0') return 'timeout';
		if (lower.includes('closed') || lower === 's2' || lower === 's3') return 'closed';
		return lower || 'unknown';
	}

	function stateBadgeClass(state: string): string {
		switch (state) {
			case 'established': return 'badge badge-success';
			case 'closed': return 'badge badge-muted';
			case 'rejected': return 'badge badge-danger';
			case 'timeout': return 'badge badge-warning';
			default: return 'badge badge-muted';
		}
	}

	function stateLabel(conn: Connection): string {
		const raw = asString(getField(conn, 'zeek.conn.conn_state'));
		const mapped = connState(conn);
		if (raw && mapped !== raw.toLowerCase()) return `${mapped.toUpperCase()} (${raw})`;
		return mapped.toUpperCase();
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	function getTimeRange() {
		const now = new Date();
		const from = new Date(now.getTime() - selectedTimeRange.ms).toISOString();
		const to = now.toISOString();
		return { from, to };
	}

	function buildSearchQuery(): string {
		const parts: string[] = [];
		if (protocolFilter !== 'All') parts.push(protocolFilter.toLowerCase());
		if (serviceFilter.trim()) parts.push(serviceFilter.trim());
		if (ipFilter.trim()) parts.push(ipFilter.trim());
		// Apply sankey filter
		if (sankeyFilter) {
			if (sankeyFilter.type === 'source') parts.push(`source.ip:${sankeyFilter.id}`);
			else if (sankeyFilter.type === 'protocol') parts.push(sankeyFilter.id.toLowerCase());
			else if (sankeyFilter.type === 'destination') parts.push(`destination.as.full:"${sankeyFilter.id}"`);
		}
		return parts.join(' ');
	}

	async function fetchAll() {
		loading = true;
		const { from, to } = getTimeRange();
		const interval = INTERVAL_MAP[selectedTimeRange.value] || '15m';

		try {
			const [statsRes, sankeyRes, timelineRes, liveRes] = await Promise.allSettled([
				getConnectionStats({ from, to }),
				getConnectionSankey({ from, to, limit: 10 }),
				getConnectionTimeline({ from, to, interval }),
				getLiveConnections({ limit: 1 }),
			]);

			if (statsRes.status === 'fulfilled') stats = statsRes.value;
			if (sankeyRes.status === 'fulfilled') sankey = sankeyRes.value;
			if (timelineRes.status === 'fulfilled') timeline = timelineRes.value.buckets;
			if (liveRes.status === 'fulfilled') activeNow = liveRes.value.count;
		} catch { /* handled per-request */ }

		await fetchConnections(1);
		loading = false;
	}

	async function fetchConnections(pg: number = 1) {
		const { from, to } = getTimeRange();
		const q = buildSearchQuery();
		try {
			const response: ConnectionsResponse = await getConnections({
				from, to, page: pg, size: pageSize, q: q || undefined,
			});
			let filtered = response.connections;
			if (stateFilter !== 'all') {
				filtered = filtered.filter((c) => connState(c) === stateFilter);
			}
			connections = filtered;
			currentPage = response.page;
			totalPages = response.total_pages;
			totalConnections = response.total;
		} catch {
			connections = [];
			totalPages = 0;
			totalConnections = 0;
		}
	}

	// ---------------------------------------------------------------------------
	// Interaction handlers
	// ---------------------------------------------------------------------------

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDir = key === 'timestamp' ? 'desc' : 'asc';
		}
	}

	function handleTimeRangeChange(range: TimeRange) {
		selectedTimeRange = range;
		if (initialized) fetchAll();
	}

	function handleSankeyNodeClick(type: 'source' | 'protocol' | 'destination', id: string) {
		if (sankeyFilter?.type === type && sankeyFilter?.id === id) {
			sankeyFilter = null; // toggle off
		} else {
			sankeyFilter = { type, id };
		}
		if (initialized) fetchConnections(1);
	}

	function clearSankeyFilter() {
		sankeyFilter = null;
		if (initialized) fetchConnections(1);
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			refreshInterval = setInterval(fetchAll, 15_000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	function openDrawer(conn: Connection) {
		drawerConn = conn;
		drawerTab = 'summary';
	}

	function closeDrawer() {
		drawerConn = null;
		drawerTab = 'summary';
	}

	function goToPage(pg: number) {
		if (pg < 1 || pg > totalPages) return;
		fetchConnections(pg);
	}

	function handlePageSizeChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		pageSize = parseInt(target.value) || 50;
		fetchConnections(1);
	}

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	onMount(() => {
		const urlIp = $page.url.searchParams.get('ip');
		if (urlIp) ipFilter = urlIp;
		const urlProtocol = $page.url.searchParams.get('protocol');
		if (urlProtocol) protocolFilter = urlProtocol;

		fetchAll().then(() => { initialized = true; });
		return () => { if (refreshInterval) clearInterval(refreshInterval); };
	});
</script>

<svelte:head>
	<title>Connections | NetTap</title>
</svelte:head>

<div class="page-container">
	<!-- ================================================================== -->
	<!-- Header                                                             -->
	<!-- ================================================================== -->
	<header class="page-header">
		<div class="header-left">
			<h1>Connections</h1>
			<p class="subtitle">Network session explorer</p>
		</div>
		<div class="header-right">
			<div class="pills">
				{#each TIME_RANGES as range}
					<button
						class="pill"
						class:active={selectedTimeRange.value === range.value}
						onclick={() => handleTimeRangeChange(range)}
					>
						{range.label}
					</button>
				{/each}
			</div>
			<button
				class="btn btn-secondary btn-sm"
				class:auto-refresh-active={autoRefresh}
				onclick={toggleAutoRefresh}
			>
				{autoRefresh ? 'Auto ON' : 'Auto'}
			</button>
			<button class="btn btn-primary btn-sm" onclick={() => fetchAll()} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</header>

	<!-- ================================================================== -->
	<!-- Stat Cards                                                         -->
	<!-- ================================================================== -->
	<div class="stat-cards">
		<div class="stat-card">
			<span class="stat-value mono">{formatNumber(stats?.total_sessions ?? 0)}</span>
			<span class="stat-label">Total Sessions</span>
		</div>
		<div class="stat-card">
			<span class="stat-value mono">
				{activeNow}
				{#if activeNow > 0}<span class="pulse-dot"></span>{/if}
			</span>
			<span class="stat-label">Active Now</span>
		</div>
		<div class="stat-card">
			<span class="stat-value mono">{formatBytes(stats?.bytes_in ?? 0)}</span>
			<span class="stat-label">Bytes In</span>
		</div>
		<div class="stat-card">
			<span class="stat-value mono">{formatBytes(stats?.bytes_out ?? 0)}</span>
			<span class="stat-label">Bytes Out</span>
		</div>
		<div class="stat-card" class:has-alerts={stats && stats.alert_sessions > 0}>
			<span class="stat-value mono">{formatNumber(stats?.alert_sessions ?? 0)}</span>
			<span class="stat-label">w/ Alerts</span>
		</div>
	</div>

	<!-- ================================================================== -->
	<!-- Sankey Flow Diagram                                                 -->
	<!-- ================================================================== -->
	<section class="card">
		<div class="card-header">
			<h2>Network Flow</h2>
			<span class="card-badge">Source IPs &rarr; Protocols &rarr; Destinations</span>
		</div>
		<div class="card-body">
			{#if sankey}
				<SankeyDiagram
					sources={sankey.nodes.sources}
					protocols={sankey.nodes.protocols}
					destinations={sankey.nodes.destinations}
					links={sankey.links}
					onNodeClick={handleSankeyNodeClick}
				/>
			{:else if loading}
				<div class="chart-placeholder">
					<div class="spinner"></div>
				</div>
			{:else}
				<div class="chart-placeholder">
					<p class="text-muted">No flow data available</p>
				</div>
			{/if}
		</div>
	</section>

	<!-- ================================================================== -->
	<!-- Session Volume Timeline                                            -->
	<!-- ================================================================== -->
	<section class="card">
		<SessionTimeline buckets={timeline} {loading} />
	</section>

	<!-- ================================================================== -->
	<!-- Three-Column Analytics Row                                         -->
	<!-- ================================================================== -->
	<div class="analytics-row">
		<div class="analytics-col card">
			<div class="analytics-header">
				<h3>Top Sources</h3>
				<span class="card-badge">by bytes</span>
			</div>
			<HorizontalBarList items={sourceBarItems} showRank labelWidth={130} />
		</div>
		<div class="analytics-col card">
			<div class="analytics-header">
				<h3>Protocol Distribution</h3>
			</div>
			<HorizontalBarList items={protocolBarItems} showDot labelWidth={80} />
		</div>
		<div class="analytics-col card">
			<div class="analytics-header">
				<h3>Top Destinations</h3>
				<span class="card-badge">by bytes</span>
			</div>
			<HorizontalBarList items={destBarItems} showRank labelWidth={160} />
		</div>
	</div>

	<!-- ================================================================== -->
	<!-- Filter Bar                                                         -->
	<!-- ================================================================== -->
	<div class="filter-bar card">
		<div class="filter-row">
			<div class="filter-group">
				<label class="label" for="protocol-filter">Protocol</label>
				<div class="pills pills-sm">
					{#each PROTOCOL_OPTIONS as proto}
						<button
							class="pill"
							class:active={protocolFilter === proto}
							onclick={() => { protocolFilter = proto; if (initialized) fetchConnections(1); }}
						>
							{proto}
						</button>
					{/each}
				</div>
			</div>
			<div class="filter-group">
				<label class="label" for="service-filter">Service</label>
				<input
					id="service-filter"
					class="input"
					type="text"
					placeholder="dns, http, tls..."
					bind:value={serviceFilter}
					onkeydown={(e) => { if (e.key === 'Enter') fetchConnections(1); }}
				/>
			</div>
			<div class="filter-group">
				<label class="label" for="ip-filter">IP Address</label>
				<input
					id="ip-filter"
					class="input"
					type="text"
					placeholder="192.168.1.100"
					bind:value={ipFilter}
					onkeydown={(e) => { if (e.key === 'Enter') fetchConnections(1); }}
				/>
			</div>
			<div class="filter-group">
				<label class="label">State</label>
				<div class="pills pills-sm">
					{#each STATE_FILTERS as sf}
						<button
							class="pill"
							class:active={stateFilter === sf.value}
							onclick={() => { stateFilter = sf.value; if (initialized) fetchConnections(1); }}
						>
							{sf.label}
						</button>
					{/each}
				</div>
			</div>
		</div>
		<div class="filter-row filter-row-secondary">
			<div class="filter-group">
				<label class="toggle-label">
					<input type="checkbox" bind:checked={hasAlertsFilter} onchange={() => fetchConnections(1)} />
					<span>Has Alerts</span>
				</label>
			</div>
			{#if sankeyFilter}
				<div class="filter-badge">
					<span class="badge badge-accent">
						{sankeyFilter.type}: {sankeyFilter.id}
						<button class="badge-dismiss" onclick={clearSankeyFilter}>&times;</button>
					</span>
				</div>
			{/if}
			<div class="filter-group filter-group-apply">
				<button class="btn btn-secondary btn-sm" onclick={() => fetchConnections(1)} disabled={loading}>
					Apply
				</button>
			</div>
		</div>
	</div>

	<!-- ================================================================== -->
	<!-- Sessions Table                                                     -->
	<!-- ================================================================== -->
	{#if loading && connections.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading connections...</p>
		</div>
	{:else if connections.length === 0 && !loading}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
				</svg>
			</div>
			<h3>No Connections</h3>
			<p class="text-muted">
				No connections found for the selected time range and filters.
			</p>
		</div>
	{:else}
		<div class="card table-wrapper">
			<div class="table-scroll">
				<table class="data-table">
					<thead>
						<tr>
							{#each [
								{ key: 'timestamp', label: 'Timestamp' },
								{ key: 'src', label: 'Source' },
								{ key: 'dst', label: 'Destination' },
								{ key: 'protocol', label: 'Protocol' },
								{ key: 'service', label: 'Service' },
								{ key: 'duration', label: 'Duration' },
								{ key: 'bytesIn', label: 'Bytes In' },
								{ key: 'bytesOut', label: 'Bytes Out' },
								{ key: 'state', label: 'State' },
							] as col}
								<th class="sortable" onclick={() => toggleSort(col.key as SortKey)}>
									{col.label}
									{#if sortKey === col.key}
										<span class="sort-arrow">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>
									{/if}
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each sortedConnections as conn (conn._id)}
							{@const srcAsn = asString(getField(conn, 'destination.as.full'))}
							<tr
								class="conn-row"
								class:expanded={drawerConn?._id === conn._id}
								onclick={() => openDrawer(conn)}
							>
								<td class="mono">{formatTimestamp(conn['@timestamp'] as string | undefined)}</td>
								<td class="mono">
									{#if getField(conn, 'source.ip')}
										<IPAddress ip={String(getField(conn, 'source.ip'))} /><!--
										-->{#if getField(conn, 'source.port')}:{getField(conn, 'source.port')}{/if}
									{:else}
										--
									{/if}
								</td>
								<td class="mono">
									{#if getField(conn, 'destination.ip')}
										<IPAddress ip={String(getField(conn, 'destination.ip'))} /><!--
										-->{#if getField(conn, 'destination.port')}:{getField(conn, 'destination.port')}{/if}
										{#if srcAsn}
											<span class="org-tag">{srcAsn.length > 20 ? srcAsn.slice(0, 19) + '\u2026' : srcAsn}</span>
										{/if}
									{:else}
										--
									{/if}
								</td>
								<td>
									<span class="proto-badge" style="background: {PROTO_COLORS[asString(getField(conn, 'network.transport')).toLowerCase()] || 'var(--text-muted)'};">
										{asString(getField(conn, 'network.transport')).toUpperCase() || '--'}
									</span>
								</td>
								<td>{asString(getField(conn, 'protocol')) || '--'}</td>
								<td class="mono">{formatDuration(conn)}</td>
								<td class="mono">{formatBytes((getField(conn, 'source.bytes') ?? getField(conn, 'client.bytes')) as number | undefined)}</td>
								<td class="mono">{formatBytes((getField(conn, 'destination.bytes') ?? getField(conn, 'server.bytes')) as number | undefined)}</td>
								<td>
									<span class={stateBadgeClass(connState(conn))}>
										{stateLabel(conn)}
									</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<!-- Pagination -->
		{#if totalPages > 0}
			<div class="pagination">
				<button
					class="btn btn-secondary btn-sm"
					disabled={currentPage <= 1 || loading}
					onclick={() => goToPage(currentPage - 1)}
				>
					Previous
				</button>
				<span class="pagination-info">
					Page {currentPage} of {totalPages}
					<span class="text-muted">({totalConnections.toLocaleString()} total)</span>
				</span>
				<button
					class="btn btn-secondary btn-sm"
					disabled={currentPage >= totalPages || loading}
					onclick={() => goToPage(currentPage + 1)}
				>
					Next
				</button>
				<select class="input select page-size-select" value={String(pageSize)} onchange={handlePageSizeChange}>
					<option value="25">25</option>
					<option value="50">50</option>
					<option value="100">100</option>
				</select>
			</div>
		{/if}
	{/if}
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerConn !== null}
	title={drawerConn ? `${asString(getField(drawerConn, 'source.ip'))} \u2192 ${asString(getField(drawerConn, 'destination.ip'))}` : ''}
	subtitle={drawerConn ? `${asString(getField(drawerConn, 'network.transport')).toUpperCase()} \u00B7 ${formatTimestamp(drawerConn['@timestamp'] as string | undefined)}` : ''}
	tabs={CONN_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => drawerTab = t}
>
	{#snippet children()}
		{#if drawerConn}
			<ConnectionDrawerContent connection={drawerConn} activeTab={drawerTab} {isMirrorMode} />
		{/if}
	{/snippet}
	{#snippet actions()}
		{#if drawerConn}
			{@const srcIp = asString(getField(drawerConn, 'source.ip'))}
			{@const dstIp = asString(getField(drawerConn, 'destination.ip'))}
			{@const cid = asString(getField(drawerConn, 'network.community_id'))}
			{#if srcIp}
				<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(srcIp)}`)}>
					View Source Device
				</button>
			{/if}
			{#if dstIp}
				<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(dstIp)}`)}>
					View Dest Device
				</button>
			{/if}
			{#if cid}
				<button class="btn btn-secondary btn-sm" onclick={() => { navigator.clipboard.writeText(cid); }}>
					Copy Community ID
				</button>
			{/if}
		{/if}
	{/snippet}
</DetailDrawer>

<style>
	/* ================================================================== */
	/* Page container                                                      */
	/* ================================================================== */
	.page-container {
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

	.header-left h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: 2px;
	}

	.subtitle {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.auto-refresh-active {
		color: var(--accent) !important;
		border-color: var(--accent) !important;
	}

	/* ================================================================== */
	/* Stat Cards                                                          */
	/* ================================================================== */
	.stat-cards {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--space-md);
	}

	.stat-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		padding: var(--space-md);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		text-align: center;
	}

	.stat-card .stat-value {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.stat-card .stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.stat-card.has-alerts .stat-value {
		color: var(--red);
	}

	.pulse-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--green);
		animation: pulse 2s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.5; transform: scale(1.3); }
	}

	/* ================================================================== */
	/* Cards                                                               */
	/* ================================================================== */
	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md);
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.card-header h2 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.card-badge {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.card-body {
		padding: 0 var(--space-md) var(--space-md);
	}

	.chart-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
	}

	/* ================================================================== */
	/* Analytics Row                                                       */
	/* ================================================================== */
	.analytics-row {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
	}

	.analytics-col {
		padding: var(--space-md);
		overflow: hidden;
	}

	.analytics-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.analytics-header h3 {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	/* ================================================================== */
	/* Filter Bar                                                          */
	/* ================================================================== */
	.filter-bar {
		padding: var(--space-md);
	}

	.filter-row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.filter-row + .filter-row {
		margin-top: var(--space-md);
	}

	.filter-row-secondary {
		align-items: center;
	}

	.filter-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.filter-group-apply {
		margin-left: auto;
	}

	.filter-group .input {
		width: 180px;
	}

	.pills-sm {
		gap: 2px;
	}

	.toggle-label {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-sm);
		color: var(--text-secondary);
		cursor: pointer;
	}

	.filter-badge {
		display: flex;
		align-items: center;
	}

	.badge-accent {
		background: var(--accent-muted);
		color: var(--accent);
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
	}

	.badge-dismiss {
		background: none;
		border: none;
		color: var(--accent);
		cursor: pointer;
		font-size: var(--text-base);
		line-height: 1;
		padding: 0;
	}

	/* ================================================================== */
	/* Table                                                               */
	/* ================================================================== */
	.table-wrapper {
		padding: 0;
		overflow: hidden;
	}

	.table-scroll {
		overflow-x: auto;
		max-height: 70vh;
	}

	th.sortable {
		cursor: pointer;
		user-select: none;
		white-space: nowrap;
		transition: color var(--transition-fast);
	}

	th.sortable:hover {
		color: var(--accent);
	}

	.sort-arrow {
		font-size: 10px;
		margin-left: 2px;
	}

	.conn-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.conn-row:hover td {
		background-color: var(--bg-tertiary);
	}

	.conn-row.expanded td {
		background-color: var(--bg-tertiary);
		border-bottom-color: transparent;
	}

	.org-tag {
		display: inline-block;
		margin-left: var(--space-xs);
		padding: 1px 4px;
		border-radius: var(--radius-sm);
		font-size: 10px;
		color: var(--text-muted);
		background: var(--bg-tertiary);
		font-family: var(--font-body, inherit);
	}

	.proto-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--bg-primary);
	}

	/* ================================================================== */
	/* Loading / Empty / Pagination                                        */
	/* ================================================================== */
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

	@keyframes spin {
		to { transform: rotate(360deg); }
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

	.pagination {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-md) 0;
	}

	.pagination-info {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.page-size-select {
		width: 70px;
		font-size: var(--text-sm);
	}

	/* ================================================================== */
	/* Responsive                                                          */
	/* ================================================================== */
	@media (max-width: 1200px) {
		.analytics-row {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.header-right {
			width: 100%;
			flex-wrap: wrap;
		}

		.stat-cards {
			grid-template-columns: repeat(2, 1fr);
		}

		.stat-cards .stat-card:last-child {
			grid-column: span 2;
		}

		.filter-group .input {
			width: 100%;
		}
	}
</style>
