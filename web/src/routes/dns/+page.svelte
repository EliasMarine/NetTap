<script lang="ts">
	import { getTopDomains, getDnsStats, getNxdomains, getQueryTypes, getDnsTimeline, getSuspiciousDns, getDeviceDns } from '$lib/api/dns';
	import type { TopDomain, DnsStats, NxdomainEntry, QueryTypeEntry, TimelineEntry, SuspiciousEntry, DeviceDnsEntry } from '$lib/api/dns';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let stats = $state<DnsStats | null>(null);
	let topDomains = $state<TopDomain[]>([]);
	let nxdomains = $state<NxdomainEntry[]>([]);
	let queryTypes = $state<QueryTypeEntry[]>([]);
	let timeline = $state<TimelineEntry[]>([]);
	let suspicious = $state<SuspiciousEntry[]>([]);
	let deviceDns = $state<DeviceDnsEntry[]>([]);
	let loading = $state(false);
	let error = $state('');
	let deviceIp = $state('');
	let deviceLoading = $state(false);

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	function severityColor(severity: string): string {
		switch (severity) {
			case 'critical': return 'var(--danger, #ef4444)';
			case 'high': return 'var(--danger, #ef4444)';
			case 'medium': return 'var(--warning, #f59e0b)';
			default: return 'var(--text-muted)';
		}
	}

	// Query type chart helpers
	function totalQueryCount(): number {
		return queryTypes.reduce((sum, t) => sum + t.count, 0) || 1;
	}

	// Timeline chart helpers
	function maxTimelineCount(): number {
		if (timeline.length === 0) return 1;
		return Math.max(...timeline.map(t => t.count), 1);
	}

	function barHeight(count: number): number {
		return Math.max(2, (count / maxTimelineCount()) * 180);
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		loading = true;
		error = '';
		try {
			const now = new Date();
			const from = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
			const to = now.toISOString();

			const [statsData, domainsData, nxData, typesData, timelineData, suspData] = await Promise.all([
				getDnsStats({ from, to }),
				getTopDomains({ from, to, limit: 50 }),
				getNxdomains({ from, to }),
				getQueryTypes({ from, to }),
				getDnsTimeline({ from, to, interval: '5m' }),
				getSuspiciousDns({ from, to }),
			]);

			stats = statsData;
			topDomains = domainsData.domains;
			nxdomains = nxData.nxdomains;
			queryTypes = typesData.types;
			timeline = timelineData.series;
			suspicious = suspData.suspicious;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch DNS data';
		} finally {
			loading = false;
		}
	}

	async function fetchDeviceDns() {
		if (!deviceIp.trim()) return;
		deviceLoading = true;
		try {
			const now = new Date();
			const from = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
			const to = now.toISOString();
			const result = await getDeviceDns(deviceIp.trim(), { from, to });
			deviceDns = result.domains;
		} catch {
			deviceDns = [];
		} finally {
			deviceLoading = false;
		}
	}

	$effect(() => {
		fetchAll();
	});
</script>

<svelte:head>
	<title>DNS Analytics | NetTap</title>
</svelte:head>

<div class="dns-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>DNS Analytics</h2>
			<p class="text-muted">Domain queries, NXDOMAIN errors, and suspicious patterns</p>
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

	{#if loading && !stats}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading DNS analytics...</p>
		</div>
	{:else}
		<!-- Hero stats -->
		{#if stats}
			<div class="stats-grid">
				<div class="stat-card">
					<span class="stat-value">{formatNumber(stats.total_queries)}</span>
					<span class="stat-label">Total Queries (24h)</span>
				</div>
				<div class="stat-card">
					<span class="stat-value">{formatNumber(stats.unique_domains)}</span>
					<span class="stat-label">Unique Domains</span>
				</div>
				<div class="stat-card" class:alert-stat={stats.nxdomain_count > 100}>
					<span class="stat-value">{formatNumber(stats.nxdomain_count)}</span>
					<span class="stat-label">NXDOMAIN Errors</span>
				</div>
				<div class="stat-card">
					<span class="stat-value">{stats.avg_resolution_ms.toFixed(1)}ms</span>
					<span class="stat-label">Avg Resolution</span>
				</div>
			</div>
		{/if}

		<!-- Top domains table -->
		{#if topDomains.length > 0}
			<div class="card">
				<h3 class="card-title">Top Queried Domains</h3>
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th>#</th>
								<th>Domain</th>
								<th>Queries</th>
								<th>Clients</th>
							</tr>
						</thead>
						<tbody>
							{#each topDomains.slice(0, 25) as domain, i}
								<tr>
									<td class="text-muted">{i + 1}</td>
									<td class="mono">{domain.domain}</td>
									<td class="mono">{domain.count.toLocaleString()}</td>
									<td class="mono">{domain.unique_clients}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Per-device DNS lookup -->
		<div class="card">
			<h3 class="card-title">Per-Device DNS</h3>
			<div class="device-search">
				<input
					type="text"
					class="input"
					placeholder="Enter device IP (e.g. 192.168.1.100)"
					bind:value={deviceIp}
					onkeydown={(e) => { if (e.key === 'Enter') fetchDeviceDns(); }}
				/>
				<button class="btn btn-primary btn-sm" onclick={fetchDeviceDns} disabled={deviceLoading}>
					{deviceLoading ? 'Loading...' : 'Lookup'}
				</button>
			</div>
			{#if deviceDns.length > 0}
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th>Domain</th>
								<th>Queries</th>
								<th>Types</th>
							</tr>
						</thead>
						<tbody>
							{#each deviceDns as entry}
								<tr>
									<td class="mono">{entry.domain}</td>
									<td class="mono">{entry.count.toLocaleString()}</td>
									<td class="mono">{entry.query_types.map(t => t.type).join(', ')}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<!-- Query type distribution -->
		{#if queryTypes.length > 0}
			<div class="card">
				<h3 class="card-title">Query Type Distribution</h3>
				<div class="type-bars">
					{#each queryTypes as qt}
						<div class="type-bar-row">
							<span class="type-label mono">{qt.type}</span>
							<div class="type-bar-track">
								<div class="type-bar-fill" style="width: {(qt.count / totalQueryCount()) * 100}%"></div>
							</div>
							<span class="type-count mono">{qt.count.toLocaleString()}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- DNS timeline -->
		{#if timeline.length > 0}
			<div class="card">
				<h3 class="card-title">Query Volume Timeline</h3>
				<div class="timeline-chart">
					<div class="chart-bars">
						{#each timeline as point}
							<div class="bar-column" title="{point.timestamp}: {point.count} queries">
								<div class="bar" style="height: {barHeight(point.count)}px"></div>
							</div>
						{/each}
					</div>
				</div>
			</div>
		{/if}

		<!-- NXDOMAIN errors -->
		{#if nxdomains.length > 0}
			<div class="card">
				<h3 class="card-title">NXDOMAIN Errors</h3>
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th>Domain</th>
								<th>Count</th>
								<th>Clients</th>
							</tr>
						</thead>
						<tbody>
							{#each nxdomains.slice(0, 20) as nx}
								<tr>
									<td class="mono">{nx.domain}</td>
									<td class="mono">{nx.count.toLocaleString()}</td>
									<td class="mono">{nx.clients.join(', ')}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{/if}

		<!-- Suspicious DNS -->
		{#if suspicious.length > 0}
			<div class="card">
				<h3 class="card-title">Suspicious DNS Patterns</h3>
				<div class="suspicious-list">
					{#each suspicious as s}
						<div class="suspicious-item">
							<div class="suspicious-header">
								<span class="severity-badge" style="background: {severityColor(s.severity)}">{s.severity}</span>
								<span class="suspicious-type">{s.type.replace(/_/g, ' ')}</span>
							</div>
							<p class="suspicious-domain mono">{s.domain}</p>
							<p class="text-muted">{s.description}</p>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.dns-page {
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

	/* Stats grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: var(--space-md);
	}

	.stat-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.stat-card.alert-stat {
		border-color: var(--warning, #f59e0b);
	}

	.stat-value {
		font-size: var(--text-2xl, 1.75rem);
		font-weight: 700;
		color: var(--text-primary);
	}

	.stat-label {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}

	/* Card */
	.card-title {
		font-size: var(--text-lg);
		font-weight: 600;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.table-scroll { overflow-x: auto; }

	/* Device search */
	.device-search {
		display: flex;
		gap: var(--space-sm);
		padding: var(--space-md) var(--space-lg);
	}

	.device-search .input {
		flex: 1;
	}

	/* Type bars */
	.type-bars {
		padding: var(--space-md) var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.type-bar-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.type-label {
		min-width: 60px;
		font-size: var(--text-sm);
	}

	.type-bar-track {
		flex: 1;
		height: 20px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.type-bar-fill {
		height: 100%;
		background: var(--accent, #3b82f6);
		border-radius: var(--radius-sm);
		transition: width 0.3s ease;
	}

	.type-count {
		min-width: 80px;
		text-align: right;
		font-size: var(--text-sm);
	}

	/* Timeline */
	.timeline-chart {
		padding: var(--space-md) var(--space-lg);
		overflow-x: auto;
	}

	.chart-bars {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		min-height: 200px;
	}

	.bar-column {
		flex: 1;
		min-width: 2px;
	}

	.bar {
		width: 100%;
		background: var(--accent, #3b82f6);
		border-radius: 1px 1px 0 0;
	}

	/* Suspicious */
	.suspicious-list {
		padding: var(--space-md) var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.suspicious-item {
		padding: var(--space-md);
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
	}

	.suspicious-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.severity-badge {
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: 600;
		color: white;
		text-transform: uppercase;
	}

	.suspicious-type {
		font-weight: 600;
		text-transform: capitalize;
	}

	.suspicious-domain {
		font-size: var(--text-sm);
		word-break: break-all;
		margin-bottom: var(--space-xs);
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
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }

	@media (max-width: 768px) {
		.page-header { flex-direction: column; }
		.stats-grid { grid-template-columns: repeat(2, 1fr); }
	}
</style>
