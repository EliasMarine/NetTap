<script lang="ts">
	import { getLiveConnections, getConnectionRate } from '$lib/api/live';
	import type { LiveConnection, ConnectionRate } from '$lib/api/live';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const PROTOCOL_OPTIONS = ['All', 'TCP', 'UDP', 'ICMP'] as const;
	const REFRESH_INTERVAL_MS = 3000;
	const PAGE_SIZE = 100;

	// Port ranges considered unusual for color coding
	const UNUSUAL_PORTS = new Set([
		4444, 5555, 6666, 6667, 8080, 8443, 8888, 9090, 31337,
	]);

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let connections = $state<LiveConnection[]>([]);
	let rate = $state<ConnectionRate>({ connections_per_second: 0, total_in_window: 0, window_seconds: 60 });
	let loading = $state(false);
	let error = $state('');
	let paused = $state(false);

	// Filters
	let deviceFilter = $state('');
	let protocolFilter = $state('All');
	let countryFilter = $state('');

	// Auto-refresh
	let refreshTimer = $state<ReturnType<typeof setInterval> | null>(null);

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	function formatDuration(seconds: number): string {
		if (seconds <= 0) return '--';
		if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const mins = Math.floor(seconds / 60);
		const secs = Math.round(seconds % 60);
		return `${mins}m ${secs}s`;
	}

	function formatTime(ts: string): string {
		if (!ts) return '--';
		try {
			return new Date(ts).toLocaleTimeString();
		} catch {
			return ts;
		}
	}

	function connectionDirection(conn: LiveConnection): string {
		// Simple heuristic: if source port is high and dest port is low, it's outbound
		if (conn.source_port > 1024 && conn.dest_port <= 1024) return 'OUT';
		if (conn.source_port <= 1024 && conn.dest_port > 1024) return 'IN';
		return '--';
	}

	function rowColorClass(conn: LiveConnection): string {
		// Red: could add alert match check later
		if (UNUSUAL_PORTS.has(conn.dest_port)) return 'row-warning';
		return '';
	}

	function countryFlag(code: string): string {
		if (!code || code.length !== 2) return '';
		// Convert country code to flag emoji
		const offset = 0x1f1e6;
		const a = code.charCodeAt(0) - 65 + offset;
		const b = code.charCodeAt(1) - 65 + offset;
		return String.fromCodePoint(a) + String.fromCodePoint(b);
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchData() {
		if (paused) return;
		loading = true;
		error = '';
		try {
			const proto = protocolFilter === 'All' ? undefined : protocolFilter.toLowerCase();
			const [connData, rateData] = await Promise.all([
				getLiveConnections({
					device: deviceFilter || undefined,
					proto,
					country: countryFilter || undefined,
					limit: PAGE_SIZE,
				}),
				getConnectionRate(),
			]);
			connections = connData.connections;
			rate = rateData;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch live connections';
		} finally {
			loading = false;
		}
	}

	function togglePause() {
		paused = !paused;
		if (!paused) {
			fetchData();
		}
	}

	// ---------------------------------------------------------------------------
	// Auto-refresh lifecycle
	// ---------------------------------------------------------------------------

	$effect(() => {
		fetchData();
		const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
		refreshTimer = timer;
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
			<h2>Live Connection Monitor</h2>
			<p class="text-muted">
				Real-time network connections
				<span class="rate-badge mono">{rate.connections_per_second} conn/s</span>
			</p>
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
			<button class="btn btn-secondary btn-sm" onclick={fetchData} disabled={loading}>
				Refresh
			</button>
		</div>
	</div>

	<!-- Filter bar -->
	<div class="filter-bar card">
		<div class="filter-row">
			<div class="filter-group">
				<label class="label" for="device-filter">Device IP</label>
				<input
					id="device-filter"
					class="input"
					type="text"
					placeholder="192.168.1.100"
					bind:value={deviceFilter}
					onkeydown={(e) => { if (e.key === 'Enter') fetchData(); }}
				/>
			</div>
			<div class="filter-group">
				<label class="label" for="proto-filter">Protocol</label>
				<select id="proto-filter" class="input select" bind:value={protocolFilter}>
					{#each PROTOCOL_OPTIONS as proto}
						<option value={proto}>{proto}</option>
					{/each}
				</select>
			</div>
			<div class="filter-group">
				<label class="label" for="country-filter">Country</label>
				<input
					id="country-filter"
					class="input"
					type="text"
					placeholder="US, DE, CN..."
					bind:value={countryFilter}
					onkeydown={(e) => { if (e.key === 'Enter') fetchData(); }}
				/>
			</div>
			<div class="filter-group filter-group-apply">
				<button class="btn btn-secondary btn-sm" onclick={fetchData} disabled={loading}>
					Apply
				</button>
			</div>
		</div>
	</div>

	<!-- Connection table -->
	{#if loading && connections.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading live connections...</p>
		</div>
	{:else if error}
		<div class="alert alert-danger">{error}</div>
	{:else if connections.length === 0}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" />
					<polyline points="12 6 12 12 16 14" />
				</svg>
			</div>
			<h3>No Active Connections</h3>
			<p class="text-muted">
				No connections found in the last 5 minutes matching your filters.
			</p>
		</div>
	{:else}
		<div class="card table-wrapper">
			<div class="table-scroll">
				<table class="data-table">
					<thead>
						<tr>
							<th>Time</th>
							<th>Device</th>
							<th>Dir</th>
							<th>Destination</th>
							<th>Protocol</th>
							<th>Port</th>
							<th>Bytes</th>
							<th>Duration</th>
						</tr>
					</thead>
					<tbody>
						{#each connections as conn}
							<tr class={rowColorClass(conn)}>
								<td class="mono">{formatTime(conn.timestamp)}</td>
								<td class="mono">
									{#if conn.source_ip}
										<IPAddress ip={conn.source_ip} />
									{:else}
										--
									{/if}
								</td>
								<td>
									<span class="badge badge-muted">{connectionDirection(conn)}</span>
								</td>
								<td class="mono">
									{#if conn.dest_ip}
										<IPAddress ip={conn.dest_ip} />
										{#if conn.country}
											<span class="country-flag" title={conn.country_name}>
												{countryFlag(conn.country)}
											</span>
										{/if}
									{:else}
										--
									{/if}
								</td>
								<td>{conn.protocol ? conn.protocol.toUpperCase() : '--'}</td>
								<td class="mono">{conn.dest_port || '--'}</td>
								<td class="mono">{formatBytes(conn.bytes)}</td>
								<td class="mono">{formatDuration(conn.duration)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<div class="status-bar">
			<span class="text-muted">
				Showing {connections.length} connections
				{#if !paused}
					 -- auto-refreshing every {REFRESH_INTERVAL_MS / 1000}s
				{:else}
					 -- paused
				{/if}
			</span>
		</div>
	{/if}
</div>

<style>
	.live-page {
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

	.rate-badge {
		margin-left: var(--space-sm);
		color: var(--accent);
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.filter-bar { padding: var(--space-md); }

	.filter-row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-md);
		flex-wrap: wrap;
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

	.filter-group .input { width: 180px; }
	.filter-group .select { width: 120px; }

	.table-wrapper { padding: 0; overflow: hidden; }
	.table-scroll { overflow-x: auto; max-height: 70vh; }

	.country-flag {
		margin-left: var(--space-xs);
		font-size: var(--text-sm);
	}

	tr.row-warning td {
		background-color: rgba(var(--warning-rgb, 255, 193, 7), 0.08);
	}

	.status-bar {
		text-align: center;
		font-size: var(--text-sm);
		padding: var(--space-sm) 0;
	}

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

	.empty-icon { color: var(--text-muted); margin-bottom: var(--space-md); }
	.empty-state h3 { font-size: var(--text-xl); font-weight: 600; margin-bottom: var(--space-sm); }
	.empty-state p { max-width: 480px; line-height: var(--leading-relaxed); }

	@media (max-width: 768px) {
		.page-header { flex-direction: column; }
		.filter-group .input, .filter-group .select { width: 100%; }
		.filter-group { min-width: 100%; }
	}
</style>
