<script lang="ts">
	interface Alert {
		id: string;
		severity: 'critical' | 'high' | 'medium' | 'low';
		title: string;
		source_ip: string;
		dest_ip: string;
		protocol: string;
		timestamp: string;
		category: string;
	}

	type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';

	let alerts = $state<Alert[]>([]);
	let loading = $state(false);
	let activeFilter = $state<SeverityFilter>('all');
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	const severityFilters: { value: SeverityFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'critical', label: 'Critical' },
		{ value: 'high', label: 'High' },
		{ value: 'medium', label: 'Medium' },
		{ value: 'low', label: 'Low' },
	];

	let filteredAlerts = $derived(
		activeFilter === 'all'
			? alerts
			: alerts.filter((a) => a.severity === activeFilter)
	);

	function severityBadgeClass(severity: string): string {
		switch (severity) {
			case 'critical':
				return 'badge badge-danger';
			case 'high':
				return 'badge badge-warning';
			case 'medium':
				return 'badge badge-accent';
			case 'low':
				return 'badge badge-muted';
			default:
				return 'badge';
		}
	}

	function formatTimestamp(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleString();
		} catch {
			return ts;
		}
	}

	async function fetchAlerts() {
		loading = true;
		try {
			// Alerts will come from OpenSearch/Suricata once the pipeline is running.
			// For now this is a placeholder that returns an empty array.
			// Future implementation: const res = await fetch('/api/alerts');
			alerts = [];
		} catch {
			alerts = [];
		} finally {
			loading = false;
		}
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			refreshInterval = setInterval(fetchAlerts, 15_000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	$effect(() => {
		fetchAlerts();
		return () => {
			if (refreshInterval) {
				clearInterval(refreshInterval);
			}
		};
	});
</script>

<svelte:head>
	<title>Alerts | NetTap</title>
</svelte:head>

<div class="alerts-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>Alerts</h2>
			<p class="text-muted">Suricata IDS alerts and threat detections</p>
		</div>
		<div class="header-actions">
			<button
				class="btn btn-secondary btn-sm"
				class:auto-refresh-active={autoRefresh}
				onclick={toggleAutoRefresh}
			>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="12" cy="12" r="10" />
					<polyline points="12 6 12 12 16 14" />
				</svg>
				{autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh'}
			</button>
			<button class="btn btn-primary btn-sm" onclick={fetchAlerts} disabled={loading}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10" />
					<polyline points="1 20 1 14 7 14" />
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
				</svg>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

	<!-- Severity filter tabs -->
	<div class="filter-tabs">
		{#each severityFilters as filter}
			<button
				class="filter-tab"
				class:active={activeFilter === filter.value}
				onclick={() => (activeFilter = filter.value)}
			>
				{filter.label}
				{#if filter.value !== 'all'}
					<span class="filter-count">
						{alerts.filter((a) => a.severity === filter.value).length}
					</span>
				{:else}
					<span class="filter-count">{alerts.length}</span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- Alert list -->
	{#if loading && alerts.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading alerts...</p>
		</div>
	{:else if filteredAlerts.length === 0}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
					<path d="M13.73 21a2 2 0 01-3.46 0" />
					<line x1="1" y1="1" x2="23" y2="23" />
				</svg>
			</div>
			<h3>No Alerts</h3>
			<p class="text-muted">
				Alerts will appear here once Suricata is running and generating alerts.
				Make sure the network bridge is configured and traffic is flowing through the appliance.
			</p>
		</div>
	{:else}
		<div class="alert-list">
			{#each filteredAlerts as alert (alert.id)}
				<div class="card alert-card">
					<div class="alert-card-header">
						<span class={severityBadgeClass(alert.severity)}>
							{alert.severity}
						</span>
						<span class="alert-timestamp mono">{formatTimestamp(alert.timestamp)}</span>
					</div>
					<div class="alert-card-body">
						<h4 class="alert-title">{alert.title}</h4>
						<div class="alert-meta">
							<div class="alert-flow">
								<span class="mono alert-ip">{alert.source_ip}</span>
								<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<line x1="5" y1="12" x2="19" y2="12" />
									<polyline points="12 5 19 12 12 19" />
								</svg>
								<span class="mono alert-ip">{alert.dest_ip}</span>
							</div>
							<span class="badge">{alert.protocol}</span>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.alerts-page {
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

	.auto-refresh-active {
		background-color: var(--accent-muted) !important;
		border-color: var(--accent) !important;
		color: var(--accent) !important;
	}

	/* Filter tabs */
	.filter-tabs {
		display: flex;
		gap: 2px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-xs);
		overflow-x: auto;
	}

	.filter-tab {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		padding: var(--space-sm) var(--space-md);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-secondary);
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition-fast);
		white-space: nowrap;
	}

	.filter-tab:hover {
		color: var(--text-primary);
		background-color: var(--bg-tertiary);
	}

	.filter-tab.active {
		color: var(--accent);
		background-color: var(--accent-muted);
	}

	.filter-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 20px;
		height: 20px;
		padding: 0 6px;
		font-size: var(--text-xs);
		font-weight: 600;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
	}

	.filter-tab.active .filter-count {
		background-color: var(--accent);
		color: #fff;
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
		to {
			transform: rotate(360deg);
		}
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

	/* Alert list */
	.alert-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.alert-card {
		padding: var(--space-md);
	}

	.alert-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.alert-timestamp {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.alert-card-body {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.alert-title {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.alert-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.alert-flow {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		color: var(--text-secondary);
	}

	.alert-ip {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.badge-muted {
		background-color: var(--bg-tertiary);
		color: var(--text-muted);
		border-color: var(--border-default);
	}

	@media (max-width: 640px) {
		.page-header {
			flex-direction: column;
		}

		.header-actions {
			width: 100%;
			justify-content: flex-end;
		}

		.alert-meta {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
