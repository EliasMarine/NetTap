<script lang="ts">
	import { onMount } from 'svelte';
	import { getSystemHealth, getStorageStatus, getSmartHealth } from '$api/system.js';
	import { getBridgeHealth } from '$api/bridge.js';
	import type { SystemHealth, StorageStatus, SmartHealth } from '$api/system.js';
	import type { BridgeHealth } from '$api/bridge.js';

	type TabId = 'opensearch' | 'logstash' | 'system';

	let activeTab = $state<TabId>('opensearch');
	let loading = $state(false);

	// OpenSearch tab data
	let clusterHealth = $state<any>(null);
	let indices = $state<any[]>([]);
	let templates = $state<any[]>([]);
	let showTemplates = $state(false);

	// Logstash tab data
	let logstashStats = $state<any>(null);
	let logstashPipelines = $state<any[]>([]);

	// System tab data
	let systemHealth = $state<SystemHealth | null>(null);
	let bridgeHealth = $state<BridgeHealth | null>(null);
	let storageStatus = $state<StorageStatus | null>(null);
	let smartHealth = $state<SmartHealth | null>(null);
	let versions = $state<any>(null);

	function formatBytes(bytes: number | null | undefined): string {
		if (bytes == null || !isFinite(bytes) || bytes <= 0) return '--';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		const val = bytes / Math.pow(1024, i);
		return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	}

	function formatNumber(n: number | null | undefined): string {
		if (n == null || !isFinite(n)) return '--';
		return n.toLocaleString();
	}

	function formatDate(d: string | null | undefined): string {
		if (!d) return '--';
		try {
			return new Date(d).toLocaleDateString();
		} catch {
			return '--';
		}
	}

	function healthDotClass(status: string | null | undefined): string {
		if (!status) return '';
		const s = status.toLowerCase();
		if (s === 'green') return 'green';
		if (s === 'yellow') return 'yellow';
		return 'red';
	}

	function diskUsageColor(percent: number): string {
		if (percent > 85) return 'var(--danger)';
		if (percent > 70) return 'var(--warning)';
		return 'var(--success)';
	}

	async function fetchJson(url: string): Promise<any> {
		try {
			const res = await fetch(url);
			if (!res.ok) return null;
			return res.json();
		} catch {
			return null;
		}
	}

	async function fetchOpenSearch() {
		loading = true;
		try {
			const [cluster, idx, tmpl] = await Promise.all([
				fetchJson('/api/opensearch/cluster'),
				fetchJson('/api/opensearch/indices'),
				fetchJson('/api/opensearch/templates'),
			]);
			clusterHealth = cluster;
			indices = cluster?.indices || idx?.indices || idx || [];
			if (Array.isArray(tmpl)) {
				templates = tmpl;
			} else if (tmpl?.templates) {
				templates = tmpl.templates;
			} else {
				templates = [];
			}
		} finally {
			loading = false;
		}
	}

	async function fetchLogstash() {
		loading = true;
		try {
			const [stats, pipelines] = await Promise.all([
				fetchJson('/api/logstash/stats'),
				fetchJson('/api/logstash/pipelines'),
			]);
			logstashStats = stats;
			if (Array.isArray(pipelines)) {
				logstashPipelines = pipelines;
			} else if (pipelines?.pipelines) {
				logstashPipelines = pipelines.pipelines;
			} else {
				logstashPipelines = [];
			}
		} finally {
			loading = false;
		}
	}

	async function fetchSystem() {
		loading = true;
		try {
			const [health, bridge, storage, smart, vers] = await Promise.all([
				getSystemHealth(),
				getBridgeHealth(),
				getStorageStatus(),
				getSmartHealth(),
				fetchJson('/api/system/versions'),
			]);
			systemHealth = health;
			bridgeHealth = bridge;
			storageStatus = storage;
			smartHealth = smart;
			versions = vers;
		} finally {
			loading = false;
		}
	}

	function fetchCurrentTab() {
		if (activeTab === 'opensearch') fetchOpenSearch();
		else if (activeTab === 'logstash') fetchLogstash();
		else fetchSystem();
	}

	function switchTab(tab: TabId) {
		activeTab = tab;
	}

	$effect(() => {
		// Re-fetch when tab changes
		const _tab = activeTab;
		fetchCurrentTab();
	});
</script>

<svelte:head>
	<title>Infrastructure | NetTap</title>
</svelte:head>

<div class="infra-page">
	<div class="page-header">
		<div class="header-left">
			<h2>Infrastructure</h2>
			<p class="text-muted">OpenSearch cluster, Logstash pipelines, and system health</p>
		</div>
		<div class="header-actions">
			<button class="btn btn-primary btn-sm" onclick={fetchCurrentTab} disabled={loading}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10" />
					<polyline points="1 20 1 14 7 14" />
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
				</svg>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	<div class="tabs">
		<button class="tab" class:active={activeTab === 'opensearch'} onclick={() => switchTab('opensearch')}>OpenSearch</button>
		<button class="tab" class:active={activeTab === 'logstash'} onclick={() => switchTab('logstash')}>Logstash</button>
		<button class="tab" class:active={activeTab === 'system'} onclick={() => switchTab('system')}>System</button>
	</div>

	<!-- External service links -->
	<div class="services-row">
		<a href="/dashboards/" target="_blank" rel="noopener" class="service-card">
			<div class="service-icon">
				<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<rect x="3" y="3" width="18" height="18" rx="2" />
					<path d="M3 9h18M9 21V9" />
				</svg>
			</div>
			<div class="service-info">
				<span class="service-name">OpenSearch Dashboards</span>
				<span class="service-desc text-muted">Kibana-style visualization</span>
			</div>
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
				<polyline points="15 3 21 3 21 9" />
				<line x1="10" y1="14" x2="21" y2="3" />
			</svg>
		</a>
		<a href="/grafana/" target="_blank" rel="noopener" class="service-card">
			<div class="service-icon">
				<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
				</svg>
			</div>
			<div class="service-info">
				<span class="service-name">Grafana</span>
				<span class="service-desc text-muted">Advanced dashboards &amp; graphs</span>
			</div>
			<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
				<polyline points="15 3 21 3 21 9" />
				<line x1="10" y1="14" x2="21" y2="3" />
			</svg>
		</a>
	</div>

	{#if activeTab === 'opensearch'}
		<!-- Cluster Health Card -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Cluster Health</span>
				{#if clusterHealth}
					<span class="cluster-status">
						<span class="health-dot {healthDotClass(clusterHealth.status)}"></span>
						<span class="mono" style="text-transform: capitalize">{clusterHealth.status ?? 'unknown'}</span>
					</span>
				{:else if loading}
					<span class="badge">Loading...</span>
				{:else}
					<span class="badge badge-muted">Unavailable</span>
				{/if}
			</div>
			{#if clusterHealth}
				<div class="stat-row">
					<div class="stat-item">
						<span class="stat-value mono">{clusterHealth.number_of_nodes ?? clusterHealth.nodes ?? '--'}</span>
						<span class="stat-label">Nodes</span>
					</div>
					<div class="stat-item">
						<span class="stat-value mono">{formatBytes(clusterHealth.total_data_size_bytes ?? clusterHealth.store_size_bytes)}</span>
						<span class="stat-label">Data Size</span>
					</div>
					<div class="stat-item">
						<span class="stat-value mono">{clusterHealth.active_shards ?? clusterHealth.active_primary_shards ?? '--'}</span>
						<span class="stat-label">Active Shards</span>
					</div>
					<div class="stat-item">
						<span class="stat-value mono">{clusterHealth.unassigned_shards ?? 0}</span>
						<span class="stat-label">Unassigned</span>
					</div>
					<div class="stat-item">
						<span class="stat-value mono">{clusterHealth.relocating_shards ?? 0}</span>
						<span class="stat-label">Relocating</span>
					</div>
				</div>
			{:else if !loading}
				<p class="text-muted">Could not retrieve cluster health. Is OpenSearch running?</p>
			{/if}
		</div>

		<!-- Index Table -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Indices</span>
				{#if Array.isArray(indices)}
					<span class="badge">{indices.length}</span>
				{/if}
			</div>
			{#if Array.isArray(indices) && indices.length > 0}
				<div class="table-scroll">
					<table class="data-table">
						<thead>
							<tr>
								<th></th>
								<th>Index</th>
								<th>Docs</th>
								<th>Primary Size</th>
								<th>Total Size</th>
								<th>Created</th>
							</tr>
						</thead>
						<tbody>
							{#each indices as idx}
								<tr>
									<td><span class="health-dot {healthDotClass(idx.health)}"></span></td>
									<td class="mono">{idx.index ?? idx.name ?? '--'}</td>
									<td class="mono">{formatNumber(idx.docs_count ?? idx.docs)}</td>
									<td class="mono">{idx.pri_store_size ?? idx.primary_size ?? formatBytes(idx.primary_size_bytes) ?? '--'}</td>
									<td class="mono">{idx.store_size ?? idx.total_size ?? formatBytes(idx.total_size_bytes) ?? '--'}</td>
									<td class="mono">{formatDate(idx.creation_date ?? idx.created)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if !loading}
				<p class="text-muted">No indices found.</p>
			{/if}
		</div>

		<!-- Templates (collapsible) -->
		<div class="card">
			<div class="card-header clickable" onclick={() => showTemplates = !showTemplates}>
				<span class="card-title">
					<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" class="chevron" class:rotated={showTemplates}>
						<polyline points="9 18 15 12 9 6" />
					</svg>
					Templates
				</span>
				<span class="badge">{Array.isArray(templates) ? templates.length : 0}</span>
			</div>
			{#if showTemplates}
				{#if Array.isArray(templates) && templates.length > 0}
					<div class="table-scroll">
						<table class="data-table">
							<thead>
								<tr>
									<th>Name</th>
									<th>Index Patterns</th>
									<th>Order</th>
								</tr>
							</thead>
							<tbody>
								{#each templates as tmpl}
									<tr>
										<td class="mono">{tmpl.name ?? '--'}</td>
										<td class="mono">{Array.isArray(tmpl.index_patterns) ? tmpl.index_patterns.join(', ') : tmpl.index_patterns ?? '--'}</td>
										<td class="mono">{tmpl.order ?? tmpl.priority ?? '--'}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="text-muted">No templates found.</p>
				{/if}
			{/if}
		</div>

	{:else if activeTab === 'logstash'}
		{#if logstashStats && logstashStats.available === false}
			<div class="card">
				<div class="card-header">
					<span class="card-title">Logstash</span>
					<span class="badge badge-muted">Unavailable</span>
				</div>
				<p class="text-muted">Logstash is not reachable. It may still be starting or is not deployed.</p>
			</div>
		{:else}
			<!-- Pipeline Status -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Pipeline Status</span>
					{#if logstashStats}
						<span class="badge badge-success">Running</span>
					{:else if loading}
						<span class="badge">Loading...</span>
					{:else}
						<span class="badge badge-muted">Unknown</span>
					{/if}
				</div>
				{#if logstashStats}
					<div class="stat-row">
						<div class="stat-item">
							<span class="stat-value mono">{formatNumber(logstashStats.events_in ?? logstashStats.events?.in)}</span>
							<span class="stat-label">Events In</span>
						</div>
						<div class="stat-item">
							<span class="stat-value mono">{formatNumber(logstashStats.events_out ?? logstashStats.events?.out)}</span>
							<span class="stat-label">Events Out</span>
						</div>
						<div class="stat-item">
							<span class="stat-value mono">{formatNumber(logstashStats.events_filtered ?? logstashStats.events?.filtered)}</span>
							<span class="stat-label">Events Filtered</span>
						</div>
					</div>
				{/if}
			</div>

			<!-- JVM Heap -->
			{#if logstashStats?.jvm || logstashStats?.heap_used_bytes != null}
				{@const heapUsed = logstashStats.jvm?.mem?.heap_used_in_bytes ?? logstashStats.heap_used_bytes ?? 0}
				{@const heapMax = logstashStats.jvm?.mem?.heap_max_in_bytes ?? logstashStats.heap_max_bytes ?? 1}
				{@const heapPercent = heapMax > 0 ? (heapUsed / heapMax) * 100 : 0}
				<div class="card">
					<div class="card-header">
						<span class="card-title">JVM Heap</span>
						<span class="mono" style="font-size: var(--text-sm); color: {diskUsageColor(heapPercent)}">
							{heapPercent.toFixed(1)}%
						</span>
					</div>
					<div class="progress-bar-container">
						<div
							class="progress-bar"
							style="width: {Math.min(heapPercent, 100)}%; background-color: {diskUsageColor(heapPercent)}"
						></div>
					</div>
					<div class="heap-labels">
						<span class="mono">{formatBytes(heapUsed)} used</span>
						<span class="mono">{formatBytes(heapMax)} max</span>
					</div>
				</div>
			{/if}

			<!-- Per-pipeline breakdown -->
			{#if logstashPipelines.length > 0}
				<div class="card">
					<div class="card-header">
						<span class="card-title">Pipelines</span>
						<span class="badge">{logstashPipelines.length}</span>
					</div>
					<div class="table-scroll">
						<table class="data-table">
							<thead>
								<tr>
									<th>Pipeline</th>
									<th>Events In</th>
									<th>Events Out</th>
									<th>Duration (ms)</th>
								</tr>
							</thead>
							<tbody>
								{#each logstashPipelines as p}
									<tr>
										<td class="mono">{p.name ?? p.id ?? '--'}</td>
										<td class="mono">{formatNumber(p.events_in ?? p.events?.in)}</td>
										<td class="mono">{formatNumber(p.events_out ?? p.events?.out)}</td>
										<td class="mono">{formatNumber(p.duration_in_millis ?? p.events?.duration_in_millis)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		{/if}

	{:else if activeTab === 'system'}
		<!-- System Health Summary -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">System Health</span>
				{#if systemHealth}
					<span class={systemHealth.healthy ? 'badge badge-success' : 'badge badge-danger'}>
						{systemHealth.healthy ? 'Healthy' : 'Degraded'}
					</span>
				{:else if loading}
					<span class="badge">Loading...</span>
				{:else}
					<span class="badge badge-muted">Unknown</span>
				{/if}
			</div>
			{#if systemHealth}
				<div class="info-grid">
					<div class="info-row">
						<span class="info-label">Uptime</span>
						<span class="info-value mono">
							{#if systemHealth.uptime > 0}
								{Math.floor(systemHealth.uptime / 86400)}d {Math.floor((systemHealth.uptime % 86400) / 3600)}h {Math.floor((systemHealth.uptime % 3600) / 60)}m
							{:else}
								--
							{/if}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">OpenSearch</span>
						<span class="info-value">
							{#if systemHealth.opensearch_reachable}
								<span class="text-success">Connected</span>
							{:else}
								<span class="text-danger">Disconnected</span>
							{/if}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">Last Check</span>
						<span class="info-value mono">{systemHealth.timestamp ? new Date(systemHealth.timestamp).toLocaleString() : '--'}</span>
					</div>
				</div>
			{/if}
		</div>

		<!-- Bridge Health -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Bridge</span>
				{#if bridgeHealth}
					{@const bstate = bridgeHealth.health_status}
					<span class="badge {bstate === 'normal' ? 'badge-success' : bstate === 'degraded' ? 'badge-warning' : bstate === 'bypass' ? 'badge-info' : 'badge-danger'}">
						{bstate === 'not_configured' ? 'Not Configured' : bstate}
					</span>
				{:else}
					<span class="badge badge-muted">Unknown</span>
				{/if}
			</div>
			{#if bridgeHealth && bridgeHealth.bridge_state !== 'not_configured'}
				<div class="info-grid">
					<div class="info-row">
						<span class="info-label">br0 State</span>
						<span class="info-value">
							<span class="health-dot {bridgeHealth.bridge_state === 'up' ? 'green' : 'red'}"></span>
							{bridgeHealth.bridge_state}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">WAN Carrier</span>
						<span class="info-value">
							<span class="health-dot {bridgeHealth.wan_link ? 'green' : 'red'}"></span>
							{bridgeHealth.wan_link ? 'Up' : 'Down'}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">LAN Carrier</span>
						<span class="info-value">
							<span class="health-dot {bridgeHealth.lan_link ? 'green' : 'red'}"></span>
							{bridgeHealth.lan_link ? 'Up' : 'Down'}
						</span>
					</div>
					<div class="info-row">
						<span class="info-label">Promiscuous</span>
						<span class="info-value mono">{bridgeHealth.bypass_active ? 'No (Bypass)' : 'Yes'}</span>
					</div>
				</div>
			{:else if bridgeHealth}
				<p class="text-muted">Bridge is not configured. Run the setup wizard to configure it.</p>
			{/if}
		</div>

		<!-- Storage -->
		<div class="card">
			<div class="card-header">
				<span class="card-title">Storage</span>
				{#if storageStatus}
					<span class="mono" style="font-size: var(--text-sm); color: {diskUsageColor(storageStatus.disk_usage_percent)}">
						{storageStatus.disk_usage_percent.toFixed(1)}% used
					</span>
				{/if}
			</div>
			{#if storageStatus}
				<div class="progress-bar-container">
					<div
						class="progress-bar"
						style="width: {Math.min(storageStatus.disk_usage_percent, 100)}%; background-color: {diskUsageColor(storageStatus.disk_usage_percent)}"
					></div>
				</div>
				<div class="stat-row">
					<div class="stat-item">
						<span class="stat-value mono">{formatBytes(storageStatus.disk_total_bytes)}</span>
						<span class="stat-label">Total</span>
					</div>
					<div class="stat-item">
						<span class="stat-value mono">{formatBytes(storageStatus.disk_used_bytes)}</span>
						<span class="stat-label">Used</span>
					</div>
					<div class="stat-item">
						<span class="stat-value mono">{formatBytes(storageStatus.disk_free_bytes)}</span>
						<span class="stat-label">Free</span>
					</div>
				</div>
				{#if storageStatus.retention && typeof storageStatus.retention === 'object'}
					<div class="retention-section">
						<span class="info-label">Retention Policy</span>
						<div class="retention-items">
							{#each Object.entries(storageStatus.retention) as [key, val]}
								<span class="retention-tag mono">{key}: {val}</span>
							{/each}
						</div>
					</div>
				{/if}
			{:else}
				<p class="text-muted">Storage data unavailable</p>
			{/if}
		</div>

		<!-- SMART + Versions row -->
		<div class="grid grid-cols-2">
			<!-- SMART -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Drive Health</span>
					{#if smartHealth}
						<span class={smartHealth.healthy ? 'badge badge-success' : 'badge badge-danger'}>
							{smartHealth.healthy ? 'Healthy' : 'Degraded'}
						</span>
					{:else}
						<span class="badge badge-muted">Unknown</span>
					{/if}
				</div>
				{#if smartHealth?.device}
					<div class="info-grid">
						<div class="info-row">
							<span class="info-label">Model</span>
							<span class="info-value mono">{smartHealth.model || '--'}</span>
						</div>
						<div class="info-row">
							<span class="info-label">Temperature</span>
							<span class="info-value mono">{smartHealth.temperature_c ?? '--'}&deg;C</span>
						</div>
						<div class="info-row">
							<span class="info-label">Wear</span>
							<span class="info-value mono">{smartHealth.percentage_used ?? '--'}%</span>
						</div>
						<div class="info-row">
							<span class="info-label">Power-On Hours</span>
							<span class="info-value mono">{smartHealth.power_on_hours != null ? smartHealth.power_on_hours.toLocaleString() : '--'}</span>
						</div>
					</div>
				{:else}
					<p class="text-muted">SMART data unavailable</p>
				{/if}
			</div>

			<!-- Versions -->
			<div class="card">
				<div class="card-header">
					<span class="card-title">Versions</span>
				</div>
				{#if versions && typeof versions === 'object' && !versions.error}
					<div class="info-grid">
						{#each Object.entries(versions) as [component, ver]}
							{#if component !== 'timestamp' && component !== 'error'}
								<div class="info-row">
									<span class="info-label" style="text-transform: capitalize">{component.replace(/_/g, ' ')}</span>
									<span class="info-value mono">{ver || '--'}</span>
								</div>
							{/if}
						{/each}
					</div>
				{:else}
					<p class="text-muted">Version information unavailable</p>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.infra-page {
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

	/* Cluster status display */
	.cluster-status {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: var(--text-sm);
	}

	/* Stat row for big numbers */
	.stat-row {
		display: flex;
		gap: var(--space-xl);
		flex-wrap: wrap;
		margin-top: var(--space-sm);
	}

	.stat-item {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.stat-value {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	/* Table scroll container */
	.table-scroll {
		overflow-x: auto;
		max-height: 400px;
		overflow-y: auto;
	}

	/* Collapsible chevron */
	.clickable {
		cursor: pointer;
	}

	.chevron {
		transition: transform var(--transition-fast);
		vertical-align: middle;
		margin-right: var(--space-xs);
	}

	.chevron.rotated {
		transform: rotate(90deg);
	}

	/* Info grid (key-value) */
	.info-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.info-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-xs) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.info-row:last-child {
		border-bottom: none;
	}

	.info-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.info-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 500;
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	/* Progress bar (JVM heap, storage) */
	.progress-bar-container {
		width: 100%;
		height: 8px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: hidden;
		margin-bottom: var(--space-md);
	}

	.progress-bar {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal);
	}

	.heap-labels {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	/* Retention tags */
	.retention-section {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-muted);
	}

	.retention-items {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-sm);
		margin-top: var(--space-sm);
	}

	.retention-tag {
		font-size: var(--text-xs);
		padding: 2px 8px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
	}

	/* External service link cards */
	.services-row {
		display: flex;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.service-card {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		text-decoration: none;
		color: var(--text-primary);
		transition: border-color var(--transition-fast), background-color var(--transition-fast);
		flex: 1;
		min-width: 220px;
	}

	.service-card:hover {
		border-color: var(--accent);
		background-color: var(--bg-tertiary);
	}

	.service-icon {
		color: var(--accent);
		flex-shrink: 0;
	}

	.service-info {
		display: flex;
		flex-direction: column;
		flex: 1;
	}

	.service-name {
		font-weight: 600;
		font-size: var(--text-sm);
	}

	.service-desc {
		font-size: var(--text-xs);
	}

	@media (max-width: 640px) {
		.page-header {
			flex-direction: column;
		}

		.stat-row {
			flex-direction: column;
			gap: var(--space-md);
		}
	}
</style>
