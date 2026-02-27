<script lang="ts">
	import { getAlerts, getAlertCount } from '$api/alerts';
	import type { Alert, AlertsListResponse, AlertCountResponse } from '$api/alerts';
	import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	// OLD CODE START — replaced local Alert interface with imported type from $api/alerts
	// interface Alert {
	// 	id: string;
	// 	severity: 'critical' | 'high' | 'medium' | 'low';
	// 	title: string;
	// 	source_ip: string;
	// 	dest_ip: string;
	// 	protocol: string;
	// 	timestamp: string;
	// 	category: string;
	// }
	// OLD CODE END

	type SeverityFilter = 'all' | 'high' | 'medium' | 'low';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let alerts = $state<Alert[]>([]);
	let loading = $state(false);
	let activeFilter = $state<SeverityFilter>('all');
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Alert counts from the /api/alerts/count endpoint
	let alertCounts = $state({ total: 0, high: 0, medium: 0, low: 0 });

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 50;

	// Detail panel
	let selectedAlert = $state<Alert | null>(null);

	// ---------------------------------------------------------------------------
	// Severity filter tabs
	// ---------------------------------------------------------------------------

	const severityFilters: { value: SeverityFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'high', label: 'High' },
		{ value: 'medium', label: 'Medium' },
		{ value: 'low', label: 'Low' },
	];

	// Map filter values to API severity numbers
	function severityFilterToNumber(filter: SeverityFilter): number | undefined {
		switch (filter) {
			case 'high':
				return 1;
			case 'medium':
				return 2;
			case 'low':
				return 3;
			default:
				return undefined;
		}
	}

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function severityBadgeClass(severity: number | undefined): string {
		switch (severity) {
			case 1:
				return 'badge badge-danger';
			case 2:
				return 'badge badge-warning';
			case 3:
				return 'badge badge-accent';
			default:
				return 'badge';
		}
	}

	function severityLabel(severity: number | undefined): string {
		switch (severity) {
			case 1:
				return 'HIGH';
			case 2:
				return 'MEDIUM';
			case 3:
				return 'LOW';
			default:
				return 'INFO';
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

	function filterCountForTab(filter: SeverityFilter): number {
		switch (filter) {
			case 'all':
				return alertCounts.total;
			case 'high':
				return alertCounts.high;
			case 'medium':
				return alertCounts.medium;
			case 'low':
				return alertCounts.low;
		}
	}

	// ---------------------------------------------------------------------------
	// Data fetching — uses real API calls
	// ---------------------------------------------------------------------------

	async function fetchAlerts(page: number = 1) {
		loading = true;
		try {
			const severity = severityFilterToNumber(activeFilter);
			const response: AlertsListResponse = await getAlerts({
				severity,
				page,
				size: pageSize,
			});
			alerts = response.alerts;
			currentPage = response.page;
			totalPages = response.total_pages;
			totalAlerts = response.total;
		} catch {
			alerts = [];
			totalPages = 0;
			totalAlerts = 0;
		} finally {
			loading = false;
		}
	}

	async function fetchCounts() {
		try {
			const response: AlertCountResponse = await getAlertCount();
			alertCounts = response.counts;
		} catch {
			alertCounts = { total: 0, high: 0, medium: 0, low: 0 };
		}
	}

	async function fetchAll() {
		await Promise.all([fetchAlerts(1), fetchCounts()]);
	}

	// ---------------------------------------------------------------------------
	// Pagination
	// ---------------------------------------------------------------------------

	function goToPage(page: number) {
		if (page < 1 || page > totalPages) return;
		fetchAlerts(page);
	}

	// ---------------------------------------------------------------------------
	// Auto-refresh
	// ---------------------------------------------------------------------------

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			refreshInterval = setInterval(fetchAll, 15_000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	// ---------------------------------------------------------------------------
	// Alert selection / detail panel
	// ---------------------------------------------------------------------------

	function openAlertDetail(alert: Alert) {
		selectedAlert = alert;
	}

	function closeAlertDetail() {
		selectedAlert = null;
	}

	// ---------------------------------------------------------------------------
	// Filter change triggers refetch
	// ---------------------------------------------------------------------------

	let prevFilter: SeverityFilter | null = null;

	$effect(() => {
		if (prevFilter !== null && prevFilter !== activeFilter) {
			fetchAlerts(1);
		}
		prevFilter = activeFilter;
	});

	// ---------------------------------------------------------------------------
	// Initial fetch
	// ---------------------------------------------------------------------------

	$effect(() => {
		fetchAll();
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
			<button class="btn btn-primary btn-sm" onclick={() => fetchAll()} disabled={loading}>
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
				<span class="filter-count">
					{filterCountForTab(filter.value)}
				</span>
			</button>
		{/each}
	</div>

	<!-- Alert list -->
	{#if loading && alerts.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading alerts...</p>
		</div>
	{:else if alerts.length === 0}
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
			{#each alerts as alert (alert._id)}
				<button
					class="card alert-card"
					class:alert-acknowledged={alert.acknowledged}
					onclick={() => openAlertDetail(alert)}
				>
					<div class="alert-card-header">
						<span class={severityBadgeClass(alert.alert?.severity)}>
							{severityLabel(alert.alert?.severity)}
						</span>
						<div class="alert-card-header-right">
							{#if alert.acknowledged}
								<span class="badge badge-success ack-badge">ACK</span>
							{/if}
							<span class="alert-timestamp mono">{formatTimestamp(alert.timestamp)}</span>
						</div>
					</div>
					<div class="alert-card-body">
						<h4 class="alert-title">{alert.alert?.signature || 'Unknown Alert'}</h4>
						{#if alert.plain_description}
							<p class="alert-description text-muted">{alert.plain_description}</p>
						{/if}
						<div class="alert-meta">
							<div class="alert-flow">
								{#if alert.src_ip}
									<IPAddress ip={alert.src_ip} />
								{:else}
									<span class="mono text-muted">--</span>
								{/if}
								<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
									<line x1="5" y1="12" x2="19" y2="12" />
									<polyline points="12 5 19 12 12 19" />
								</svg>
								{#if alert.dest_ip}
									<IPAddress ip={alert.dest_ip} />
								{:else}
									<span class="mono text-muted">--</span>
								{/if}
							</div>
							<div class="alert-badges">
								{#if alert.proto}
									<span class="badge">{alert.proto.toUpperCase()}</span>
								{/if}
								{#if alert.alert?.category}
									<span class="badge">{alert.alert.category}</span>
								{/if}
							</div>
						</div>
					</div>
				</button>
			{/each}
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
					<span class="text-muted">({totalAlerts.toLocaleString()} total)</span>
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

<!-- Alert detail slide-out panel -->
<AlertDetailPanel alert={selectedAlert} onclose={closeAlertDetail} />

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
		cursor: pointer;
		text-align: left;
		width: 100%;
		font-family: var(--font-sans);
		transition: border-color var(--transition-fast), background-color var(--transition-fast);
	}

	.alert-card:hover {
		border-color: var(--accent);
		background-color: var(--bg-tertiary);
	}

	.alert-card.alert-acknowledged {
		opacity: 0.7;
	}

	.alert-card.alert-acknowledged:hover {
		opacity: 1;
	}

	.alert-card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.alert-card-header-right {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.ack-badge {
		font-size: 10px;
		padding: 1px 6px;
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

	.alert-description {
		font-size: var(--text-sm);
		line-height: var(--leading-normal);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
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

	.alert-badges {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.badge-muted {
		background-color: var(--bg-tertiary);
		color: var(--text-muted);
		border-color: var(--border-default);
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
