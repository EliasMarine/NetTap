<script lang="ts">
	import { getConnections } from '$api/traffic';
	import type { Connection, ConnectionsResponse } from '$api/traffic';
	import { getTSharkStatus } from '$api/tshark';
	import type { TSharkStatus } from '$api/tshark';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	type StateFilter = 'all' | 'established' | 'closed' | 'rejected' | 'timeout';

	interface TimeRange {
		label: string;
		value: string;
		ms: number;
	}

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES: TimeRange[] = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000 },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
	];

	const STATE_FILTERS: { value: StateFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'established', label: 'Established' },
		{ value: 'closed', label: 'Closed' },
		{ value: 'rejected', label: 'Rejected' },
		{ value: 'timeout', label: 'Timeout' },
	];

	const PROTOCOL_OPTIONS = ['All', 'TCP', 'UDP', 'ICMP'] as const;

	const PAGE_SIZE = 50;

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let connections = $state<Connection[]>([]);
	let loading = $state(false);
	let error = $state('');
	let totalConnections = $state(0);
	let totalPages = $state(0);
	let currentPage = $state(1);

	// Filters
	let selectedTimeRange = $state<TimeRange>(TIME_RANGES[1]); // default 1h
	let protocolFilter = $state('All');
	let serviceFilter = $state('');
	let ipFilter = $state('');
	let stateFilter = $state<StateFilter>('all');

	// Expanded row + TShark
	let expandedId = $state<string | null>(null);
	let tsharkStatus = $state<TSharkStatus | null>(null);
	let tsharkChecked = $state(false);

	// ---------------------------------------------------------------------------
	// Nested field accessor for ECS dot-notation paths
	// ---------------------------------------------------------------------------

	function getField(obj: Record<string, unknown>, path: string): unknown {
		const parts = path.split('.');
		let current: unknown = obj;
		for (const part of parts) {
			if (current == null || typeof current !== 'object') return undefined;
			current = (current as Record<string, unknown>)[part];
		}
		return current;
	}

	// ---------------------------------------------------------------------------
	// Safe value extractors (OpenSearch may return arrays for ECS fields)
	// ---------------------------------------------------------------------------

	function asString(val: unknown): string {
		if (Array.isArray(val)) return val[0] ?? '';
		if (typeof val === 'string') return val;
		return '';
	}

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '--';
		try {
			return new Date(ts).toLocaleString();
		} catch {
			return ts;
		}
	}

	function formatBytes(bytes: number | undefined): string {
		if (bytes === undefined || bytes === null) return '--';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

	function buildSearchQuery(): string {
		const parts: string[] = [];
		if (protocolFilter !== 'All') parts.push(protocolFilter.toLowerCase());
		if (serviceFilter.trim()) parts.push(serviceFilter.trim());
		if (ipFilter.trim()) parts.push(ipFilter.trim());
		return parts.join(' ');
	}

	async function fetchConnections(page: number = 1) {
		loading = true;
		error = '';
		try {
			const now = new Date();
			const from = new Date(now.getTime() - selectedTimeRange.ms).toISOString();
			const to = now.toISOString();
			const q = buildSearchQuery();

			const response: ConnectionsResponse = await getConnections({
				from,
				to,
				page,
				size: PAGE_SIZE,
				q: q || undefined,
			});

			let filtered = response.connections;
			if (stateFilter !== 'all') {
				filtered = filtered.filter((c) => connState(c) === stateFilter);
			}

			connections = filtered;
			currentPage = response.page;
			totalPages = response.total_pages;
			totalConnections = response.total;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch connections';
			connections = [];
			totalPages = 0;
			totalConnections = 0;
		} finally {
			loading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// TShark
	// ---------------------------------------------------------------------------

	async function checkTShark() {
		if (tsharkChecked) return;
		try {
			tsharkStatus = await getTSharkStatus();
		} catch {
			tsharkStatus = { available: false, version: '', container_running: false, container_name: '' };
		}
		tsharkChecked = true;
	}

	function toggleRow(id: string) {
		if (expandedId === id) {
			expandedId = null;
		} else {
			expandedId = id;
			checkTShark();
		}
	}

	function buildTSharkFilter(conn: Connection): string {
		const srcIp = asString(getField(conn, 'source.ip'));
		const dstIp = asString(getField(conn, 'destination.ip'));
		const srcPort = getField(conn, 'source.port');
		const dstPort = getField(conn, 'destination.port');
		const proto = asString(getField(conn, 'network.transport')).toLowerCase();

		const parts: string[] = [];
		if (srcIp) parts.push(`ip.addr == ${srcIp}`);
		if (dstIp) parts.push(`ip.addr == ${dstIp}`);
		if (proto && srcPort) parts.push(`${proto}.port == ${srcPort}`);
		if (proto && dstPort) parts.push(`${proto}.port == ${dstPort}`);
		return parts.join(' && ');
	}

	function openInTShark(conn: Connection) {
		const filter = buildTSharkFilter(conn);
		const params = new URLSearchParams();
		if (filter) params.set('filter', filter);
		goto(`/tools/tshark?${params.toString()}`);
	}

	// ---------------------------------------------------------------------------
	// Pagination
	// ---------------------------------------------------------------------------

	function goToPage(page: number) {
		if (page < 1 || page > totalPages) return;
		fetchConnections(page);
	}

	// ---------------------------------------------------------------------------
	// Filter change triggers
	// ---------------------------------------------------------------------------

	let initialized = $state(false);

	$effect(() => {
		// Track filter dependencies
		selectedTimeRange;
		protocolFilter;
		stateFilter;

		if (initialized) {
			fetchConnections(1);
		}
	});

	// Initial fetch — also read IP filter from URL query params (e.g. from IPAddress context menu)
	$effect(() => {
		const urlIp = $page.url.searchParams.get('ip');
		if (urlIp) {
			ipFilter = urlIp;
		}
		fetchConnections(1);
		initialized = true;
	});
</script>

<svelte:head>
	<title>Connections | NetTap</title>
</svelte:head>

<div class="connections-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>Connections</h2>
			<p class="text-muted">
				Network connections captured by Zeek
				{#if totalConnections > 0}
					<span class="connection-count mono">{totalConnections.toLocaleString()} total</span>
				{/if}
			</p>
		</div>
		<div class="header-actions">
			<!-- Time range selector -->
			<div class="pills">
				{#each TIME_RANGES as range}
					<button
						class="pill"
						class:active={selectedTimeRange.value === range.value}
						onclick={() => (selectedTimeRange = range)}
					>
						{range.label}
					</button>
				{/each}
			</div>
			<button class="btn btn-primary btn-sm" onclick={() => fetchConnections(currentPage)} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	<!-- Filter bar -->
	<div class="filter-bar card">
		<div class="filter-row">
			<div class="filter-group">
				<label class="label" for="protocol-filter">Protocol</label>
				<select id="protocol-filter" class="input select" bind:value={protocolFilter}>
					{#each PROTOCOL_OPTIONS as proto}
						<option value={proto}>{proto}</option>
					{/each}
				</select>
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
			<div class="filter-group filter-group-apply">
				<button class="btn btn-secondary btn-sm" onclick={() => fetchConnections(1)} disabled={loading}>
					Apply
				</button>
			</div>
		</div>
		<div class="filter-row">
			<div class="filter-group">
				<label class="label">State</label>
				<div class="pills">
					{#each STATE_FILTERS as sf}
						<button
							class="pill"
							class:active={stateFilter === sf.value}
							onclick={() => (stateFilter = sf.value)}
						>
							{sf.label}
						</button>
					{/each}
				</div>
			</div>
		</div>
	</div>

	<!-- Connection table -->
	{#if loading && connections.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading connections...</p>
		</div>
	{:else if error}
		<div class="alert alert-danger">{error}</div>
	{:else if connections.length === 0}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
				</svg>
			</div>
			<h3>No Connections</h3>
			<p class="text-muted">
				No connections found for the selected time range and filters.
				Make sure traffic is flowing through the bridge and Zeek is capturing.
			</p>
		</div>
	{:else}
		<div class="card table-wrapper">
			<div class="table-scroll">
				<table class="data-table">
					<thead>
						<tr>
							<th>Timestamp</th>
							<th>Source</th>
							<th>Destination</th>
							<th>Protocol</th>
							<th>Service</th>
							<th>Duration</th>
							<th>Bytes In</th>
							<th>Bytes Out</th>
							<th>State</th>
						</tr>
					</thead>
					<tbody>
						{#each connections as conn (conn._id)}
							<tr
								class="conn-row"
								class:expanded={expandedId === conn._id}
								onclick={() => toggleRow(conn._id)}
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
									{:else}
										--
									{/if}
								</td>
								<td>{asString(getField(conn, 'network.transport')).toUpperCase() || '--'}</td>
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
							{#if expandedId === conn._id}
								<tr class="detail-row">
									<td colspan="9">
										<div class="detail-panel">
											<h4>Connection Details</h4>
											<div class="detail-grid">
												<div class="detail-item">
													<span class="label">UID</span>
													<span class="mono">{getField(conn, 'zeek.session_id') || conn._id}</span>
												</div>
												<div class="detail-item">
													<span class="label">Index</span>
													<span class="mono">{conn._index}</span>
												</div>
												{#if getField(conn, 'source.packets')}
													<div class="detail-item">
														<span class="label">Orig Packets</span>
														<span class="mono">{getField(conn, 'source.packets')}</span>
													</div>
												{/if}
												{#if getField(conn, 'destination.packets')}
													<div class="detail-item">
														<span class="label">Resp Packets</span>
														<span class="mono">{getField(conn, 'destination.packets')}</span>
													</div>
												{/if}
												{#if getField(conn, 'zeek.conn.conn_state')}
												<div class="detail-item">
													<span class="label">Conn State</span>
													<span class="mono">{asString(getField(conn, 'zeek.conn.conn_state'))}</span>
												</div>
											{/if}
											{#if getField(conn, 'zeek.conn.conn_state_description')}
												<div class="detail-item">
													<span class="label">State Description</span>
													<span>{asString(getField(conn, 'zeek.conn.conn_state_description'))}</span>
												</div>
											{/if}
											{#if getField(conn, 'zeek.conn.history')}
													<div class="detail-item">
														<span class="label">History</span>
														<span class="mono">{getField(conn, 'zeek.conn.history')}</span>
													</div>
												{/if}
												{#if getField(conn, 'network.community_id')}
													<div class="detail-item">
														<span class="label">Community ID</span>
														<span class="mono">{asString(getField(conn, 'network.community_id'))}</span>
													</div>
												{/if}
											</div>

											<!-- TShark section -->
											<div class="tshark-section">
												<h4>Packet Analysis (TShark)</h4>
												{#if !tsharkChecked}
													<p class="text-muted">Checking TShark availability...</p>
												{:else if !tsharkStatus?.available}
													<div class="alert alert-warning">
														TShark is not available. The packet capture container may not be running,
														or TShark is not installed. PCAP drill-down requires a running TShark instance.
													</div>
												{:else}
													<div class="tshark-info">
														<span class="badge badge-success">TShark Available</span>
														<span class="text-muted mono">{tsharkStatus.version}</span>
													</div>
													<div class="tshark-actions">
														<button class="btn btn-primary btn-sm" onclick={() => openInTShark(conn)}>
															<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
																<polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" />
															</svg>
															Analyze in TShark
														</button>
														<span class="tshark-filter-preview mono">
															{buildTSharkFilter(conn) || 'no filter'}
														</span>
													</div>
												{/if}
											</div>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<!-- Pagination -->
		{#if totalPages > 1}
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
			</div>
		{/if}
	{/if}
</div>

<style>
	.connections-page {
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
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.connection-count {
		margin-left: var(--space-sm);
		color: var(--accent);
		font-size: var(--text-sm);
	}

	/* Filter bar */
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

	.filter-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		min-width: 140px;
	}

	.filter-group-apply {
		min-width: auto;
		justify-content: flex-end;
	}

	.filter-group .input {
		width: 180px;
	}

	.filter-group .select {
		width: 120px;
	}

	/* Table */
	.table-wrapper {
		padding: 0;
		overflow: hidden;
	}

	.table-scroll {
		overflow-x: auto;
		max-height: 70vh;
	}

	.conn-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.conn-row.expanded td {
		background-color: var(--bg-tertiary);
		border-bottom-color: transparent;
	}

	.detail-row td {
		padding: 0;
		background-color: var(--bg-tertiary);
	}

	.detail-panel {
		padding: var(--space-md) var(--space-lg);
		border-top: 1px solid var(--border-dim);
	}

	.detail-panel h4 {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-bottom: var(--space-md);
	}

	.detail-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.detail-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.detail-item .label {
		margin-bottom: 0;
	}

	/* TShark section */
	.tshark-section {
		border-top: 1px solid var(--border-dim);
		padding-top: var(--space-md);
	}

	.tshark-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-sm);
	}

	.tshark-actions {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		margin-top: var(--space-sm);
	}

	.tshark-filter-preview {
		font-size: var(--text-xs);
		color: var(--text-muted);
		background: var(--bg-primary);
		padding: 4px 8px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-dim);
	}

	/* Loading state */
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
	}

	/* Pagination */
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

	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
		}

		.header-actions {
			width: 100%;
			flex-wrap: wrap;
		}

		.filter-group .input,
		.filter-group .select {
			width: 100%;
		}

		.filter-group {
			min-width: 100%;
		}
	}
</style>
