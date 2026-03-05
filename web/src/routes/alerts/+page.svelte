<script lang="ts">
	import { onMount } from 'svelte';
	import { getAlerts, getAlertCount } from '$api/alerts';
	import type { Alert, AlertsListResponse, AlertCountResponse } from '$api/alerts';
	import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	type SeverityFilter = 'all' | 'high' | 'medium' | 'low' | 'info';
	type TimeRange = '1h' | '4h' | '24h' | '7d';

	interface HourBucket {
		hour: number;
		high: number;
		medium: number;
		low: number;
	}

	interface RuleCount {
		signature: string;
		count: number;
	}

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let alerts = $state<Alert[]>([]);
	let loading = $state(false);
	let activeFilter = $state<SeverityFilter>('all');
	let activeTimeRange = $state<TimeRange>('24h');
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	let alertCounts = $state({ total: 0, high: 0, medium: 0, low: 0 });

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 50;

	// Detail panel
	let selectedAlert = $state<Alert | null>(null);

	// Expanded row
	let expandedAlertId = $state<string | null>(null);

	// ---------------------------------------------------------------------------
	// Time range helpers
	// ---------------------------------------------------------------------------

	function timeRangeToParams(range: TimeRange): { from: string; to: string } {
		const now = new Date();
		const to = now.toISOString();
		const ms: Record<TimeRange, number> = {
			'1h': 3600_000,
			'4h': 14400_000,
			'24h': 86400_000,
			'7d': 604800_000,
		};
		const from = new Date(now.getTime() - ms[range]).toISOString();
		return { from, to };
	}

	// ---------------------------------------------------------------------------
	// Severity helpers
	// ---------------------------------------------------------------------------

	const severityFilters: { value: SeverityFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'high', label: 'High' },
		{ value: 'medium', label: 'Medium' },
		{ value: 'low', label: 'Low' },
		{ value: 'info', label: 'Info' },
	];

	const timeRanges: { value: TimeRange; label: string }[] = [
		{ value: '1h', label: '1h' },
		{ value: '4h', label: '4h' },
		{ value: '24h', label: '24h' },
		{ value: '7d', label: '7d' },
	];

	function severityFilterToNumber(filter: SeverityFilter): number | undefined {
		switch (filter) {
			case 'high': return 1;
			case 'medium': return 2;
			case 'low': return 3;
			default: return undefined;
		}
	}

	function severityBadgeClass(severity: number | undefined): string {
		switch (severity) {
			case 1: return 'badge severity-high';
			case 2: return 'badge severity-medium';
			case 3: return 'badge severity-low';
			default: return 'badge severity-info';
		}
	}

	function severityLabel(severity: number | undefined): string {
		switch (severity) {
			case 1: return 'HIGH';
			case 2: return 'MEDIUM';
			case 3: return 'LOW';
			default: return 'INFO';
		}
	}

	function formatTimestamp(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return ts;
		}
	}

	function filterCountForTab(filter: SeverityFilter): number {
		switch (filter) {
			case 'all': return alertCounts.total;
			case 'high': return alertCounts.high;
			case 'medium': return alertCounts.medium;
			case 'low': return alertCounts.low;
			case 'info': return Math.max(0, alertCounts.total - alertCounts.high - alertCounts.medium - alertCounts.low);
		}
	}

	// ---------------------------------------------------------------------------
	// Derived: Alert trend chart (24 hour buckets)
	// ---------------------------------------------------------------------------

	let hourBuckets = $derived.by((): HourBucket[] => {
		const buckets: HourBucket[] = [];
		for (let i = 0; i < 24; i++) {
			buckets.push({ hour: i, high: 0, medium: 0, low: 0 });
		}
		const now = new Date();
		for (const a of alerts) {
			const ts = new Date(a.timestamp);
			const hoursAgo = Math.floor((now.getTime() - ts.getTime()) / 3600_000);
			const idx = 23 - hoursAgo;
			if (idx >= 0 && idx < 24) {
				const sev = a.alert?.severity;
				if (sev === 1) buckets[idx].high++;
				else if (sev === 2) buckets[idx].medium++;
				else buckets[idx].low++;
			}
		}
		return buckets;
	});

	let maxBucketTotal = $derived(
		Math.max(1, ...hourBuckets.map((b) => b.high + b.medium + b.low))
	);

	// ---------------------------------------------------------------------------
	// Derived: Top triggered rules
	// ---------------------------------------------------------------------------

	let topRules = $derived.by((): RuleCount[] => {
		const counts = new Map<string, number>();
		for (const a of alerts) {
			const sig = a.alert?.signature || 'Unknown';
			counts.set(sig, (counts.get(sig) || 0) + 1);
		}
		return Array.from(counts.entries())
			.map(([signature, count]) => ({ signature, count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 5);
	});

	let maxRuleCount = $derived(
		topRules.length > 0 ? topRules[0].count : 1
	);

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAlerts(page: number = 1) {
		loading = true;
		try {
			const severity = severityFilterToNumber(activeFilter);
			const timeParams = timeRangeToParams(activeTimeRange);
			const response: AlertsListResponse = await getAlerts({
				severity,
				page,
				size: pageSize,
				...timeParams,
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
			const timeParams = timeRangeToParams(activeTimeRange);
			const response: AlertCountResponse = await getAlertCount(timeParams);
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
	// Row expand / detail
	// ---------------------------------------------------------------------------

	function toggleExpandRow(alertId: string) {
		expandedAlertId = expandedAlertId === alertId ? null : alertId;
	}

	function openAlertDetail(alert: Alert) {
		selectedAlert = alert;
	}

	function closeAlertDetail() {
		selectedAlert = null;
	}

	// ---------------------------------------------------------------------------
	// Filter / time range change triggers refetch
	// ---------------------------------------------------------------------------

	let prevFilter: SeverityFilter | null = null;
	let prevTimeRange: TimeRange | null = null;

	$effect(() => {
		if (prevFilter !== null && prevFilter !== activeFilter) {
			fetchAlerts(1);
		}
		prevFilter = activeFilter;
	});

	$effect(() => {
		if (prevTimeRange !== null && prevTimeRange !== activeTimeRange) {
			fetchAll();
		}
		prevTimeRange = activeTimeRange;
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

	<!-- Summary stat cards -->
	<div class="summary-cards">
		<div class="stat-card">
			<div class="stat-label">Total Alerts</div>
			<div class="stat-value">{alertCounts.total.toLocaleString()}</div>
		</div>
		<div class="stat-card stat-card-high">
			<div class="stat-label">High Severity</div>
			<div class="stat-value stat-value-high">{alertCounts.high.toLocaleString()}</div>
		</div>
		<div class="stat-card stat-card-medium">
			<div class="stat-label">Medium Severity</div>
			<div class="stat-value stat-value-medium">{alertCounts.medium.toLocaleString()}</div>
		</div>
		<div class="stat-card stat-card-low">
			<div class="stat-label">Low Severity</div>
			<div class="stat-value stat-value-low">{alertCounts.low.toLocaleString()}</div>
		</div>
	</div>

	<!-- Alert trend chart (stacked bar sparkline) -->
	<div class="card trend-card">
		<div class="card-header">
			<span class="card-title">Alert Trend</span>
			<span class="card-subtitle">Last 24 hours by severity</span>
		</div>
		<div class="trend-chart">
			<svg viewBox="0 0 480 80" width="100%" height="80" preserveAspectRatio="none">
				{#each hourBuckets as bucket, i}
					{@const total = bucket.high + bucket.medium + bucket.low}
					{@const barWidth = 16}
					{@const gap = 4}
					{@const x = i * (barWidth + gap)}
					{@const maxH = 70}
					{@const hHigh = (bucket.high / maxBucketTotal) * maxH}
					{@const hMed = (bucket.medium / maxBucketTotal) * maxH}
					{@const hLow = (bucket.low / maxBucketTotal) * maxH}
					<!-- Low (bottom) -->
					{#if hLow > 0}
						<rect
							x={x}
							y={80 - hLow}
							width={barWidth}
							height={hLow}
							rx="2"
							fill="var(--blue)"
							opacity="0.8"
						>
							<title>Hour -{23 - i}: {bucket.low} low</title>
						</rect>
					{/if}
					<!-- Medium (middle) -->
					{#if hMed > 0}
						<rect
							x={x}
							y={80 - hLow - hMed}
							width={barWidth}
							height={hMed}
							rx="2"
							fill="var(--amber)"
							opacity="0.8"
						>
							<title>Hour -{23 - i}: {bucket.medium} medium</title>
						</rect>
					{/if}
					<!-- High (top) -->
					{#if hHigh > 0}
						<rect
							x={x}
							y={80 - hLow - hMed - hHigh}
							width={barWidth}
							height={hHigh}
							rx="2"
							fill="var(--red)"
							opacity="0.8"
						>
							<title>Hour -{23 - i}: {bucket.high} high</title>
						</rect>
					{/if}
					<!-- Zero state: dim bar -->
					{#if total === 0}
						<rect
							x={x}
							y={76}
							width={barWidth}
							height={4}
							rx="2"
							fill="var(--border-default)"
							opacity="0.4"
						/>
					{/if}
				{/each}
			</svg>
			<div class="trend-legend">
				<span class="legend-item"><span class="legend-dot" style="background: var(--red);"></span> High</span>
				<span class="legend-item"><span class="legend-dot" style="background: var(--amber);"></span> Medium</span>
				<span class="legend-item"><span class="legend-dot" style="background: var(--blue);"></span> Low</span>
			</div>
		</div>
	</div>

	<!-- Filters row: severity pills + time range -->
	<div class="filters-row">
		<div class="pills">
			{#each severityFilters as filter}
				<button
					class="pill"
					class:active={activeFilter === filter.value}
					onclick={() => (activeFilter = filter.value)}
				>
					{filter.label}
					<span class="pill-count">{filterCountForTab(filter.value)}</span>
				</button>
			{/each}
		</div>
		<div class="pills time-pills">
			{#each timeRanges as tr}
				<button
					class="pill"
					class:active={activeTimeRange === tr.value}
					onclick={() => (activeTimeRange = tr.value)}
				>
					{tr.label}
				</button>
			{/each}
		</div>
	</div>

	<!-- Alerts table -->
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
		<div class="card table-card">
			<div class="table-scroll">
				<table class="data-table">
					<thead>
						<tr>
							<th>Timestamp</th>
							<th>Severity</th>
							<th>Signature</th>
							<th>Source IP</th>
							<th>Dest IP</th>
							<th>Protocol</th>
							<th>Category</th>
						</tr>
					</thead>
					<tbody>
						{#each alerts as alert (alert._id)}
							<tr
								class="alert-row"
								class:alert-row-expanded={expandedAlertId === alert._id}
								class:alert-acknowledged={alert.acknowledged}
								onclick={() => toggleExpandRow(alert._id)}
								role="button"
								tabindex="0"
								onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleExpandRow(alert._id); } }}
							>
								<td class="mono">{formatTimestamp(alert.timestamp)}</td>
								<td>
									<span class={severityBadgeClass(alert.alert?.severity)}>
										{severityLabel(alert.alert?.severity)}
									</span>
								</td>
								<td class="signature-cell" title={alert.alert?.signature || 'Unknown'}>
									{alert.alert?.signature || 'Unknown signature'}
								</td>
								<td class="ip-cell">
									{#if alert.src_ip}
										<IPAddress ip={alert.src_ip} />
									{:else}
										<span class="text-muted">--</span>
									{/if}
								</td>
								<td class="ip-cell">
									{#if alert.dest_ip}
										<IPAddress ip={alert.dest_ip} />
									{:else}
										<span class="text-muted">--</span>
									{/if}
								</td>
								<td>
									{#if alert.proto}
										<span class="badge">{alert.proto.toUpperCase()}</span>
									{:else}
										<span class="text-muted">--</span>
									{/if}
								</td>
								<td>
									{#if alert.alert?.category}
										<span class="category-text">{alert.alert.category}</span>
									{:else}
										<span class="text-muted">--</span>
									{/if}
								</td>
							</tr>
							<!-- Expanded detail row -->
							{#if expandedAlertId === alert._id}
								<tr class="expanded-row">
									<td colspan="7">
										<div class="expanded-detail">
											<div class="expanded-top">
												<div class="expanded-section">
													<h4 class="expanded-sig">{alert.alert?.signature || 'Unknown Alert'}</h4>
													{#if alert.plain_description}
														<p class="expanded-desc">{alert.plain_description}</p>
													{/if}
													{#if alert.risk_context}
														<p class="expanded-risk">{alert.risk_context}</p>
													{/if}
												</div>
												<div class="expanded-actions">
													<button
														class="btn btn-sm btn-secondary"
														onclick={(e) => { e.stopPropagation(); openAlertDetail(alert); }}
													>
														Full details
													</button>
													{#if alert.src_ip && alert.dest_ip}
														<a
															class="btn btn-sm btn-secondary"
															href="/logs?log_type=zeek&src_ip={encodeURIComponent(alert.src_ip)}&dest_ip={encodeURIComponent(alert.dest_ip)}"
															onclick={(e) => e.stopPropagation()}
														>
															Related Zeek logs
														</a>
														<a
															class="btn btn-sm btn-secondary"
															href="/connections?filter=ip.src=={encodeURIComponent(alert.src_ip)}%20AND%20ip.dst=={encodeURIComponent(alert.dest_ip)}"
															onclick={(e) => e.stopPropagation()}
														>
															View connection
														</a>
													{/if}
												</div>
											</div>
											<!-- GeoIP / extra metadata -->
											<div class="expanded-meta">
												{#if alert.src_port}
													<span class="meta-tag mono">src:{alert.src_ip}:{alert.src_port}</span>
												{/if}
												{#if alert.dest_port}
													<span class="meta-tag mono">dst:{alert.dest_ip}:{alert.dest_port}</span>
												{/if}
												{#if alert.alert?.signature_id}
													<span class="meta-tag mono">SID:{alert.alert.signature_id}</span>
												{/if}
												{#if (alert as Record<string, any>).geoip_src?.country_name}
													<span class="meta-tag">Src: {(alert as Record<string, any>).geoip_src.country_name}</span>
												{/if}
												{#if (alert as Record<string, any>).geoip_dest?.country_name}
													<span class="meta-tag">Dst: {(alert as Record<string, any>).geoip_dest.country_name}</span>
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

	<!-- Top triggered rules (horizontal bar chart) -->
	{#if topRules.length > 0}
		<div class="card rules-card">
			<div class="card-header">
				<span class="card-title">Top Triggered Rules</span>
				<span class="card-subtitle">Most frequent alert signatures</span>
			</div>
			<div class="rules-chart">
				{#each topRules as rule, i}
					<div class="rule-row">
						<span class="rule-rank">{i + 1}</span>
						<span class="rule-name" title={rule.signature}>{rule.signature}</span>
						<div class="rule-bar-track">
							<div
								class="rule-bar-fill"
								style="width: {(rule.count / maxRuleCount) * 100}%"
							></div>
						</div>
						<span class="rule-count mono">{rule.count}</span>
					</div>
				{/each}
			</div>
		</div>
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

	/* Summary stat cards */
	.summary-cards {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.summary-cards .stat-card {
		padding: var(--space-md) var(--space-lg);
	}

	.summary-cards .stat-value {
		font-size: var(--text-3xl);
		font-weight: 700;
		font-family: var(--font-mono);
		line-height: 1;
		margin-top: var(--space-xs);
	}

	.stat-card-high {
		border-color: rgba(255, 71, 87, 0.3) !important;
	}

	.stat-value-high {
		color: var(--red);
	}

	.stat-card-medium {
		border-color: rgba(255, 171, 0, 0.3) !important;
	}

	.stat-value-medium {
		color: var(--amber);
	}

	.stat-card-low {
		border-color: rgba(68, 138, 255, 0.3) !important;
	}

	.stat-value-low {
		color: var(--blue);
	}

	/* Trend chart */
	.trend-card {
		padding: var(--space-md) var(--space-lg);
	}

	.trend-chart {
		margin-top: var(--space-sm);
	}

	.trend-chart svg {
		display: block;
	}

	.trend-legend {
		display: flex;
		gap: var(--space-md);
		margin-top: var(--space-sm);
		justify-content: flex-end;
	}

	.legend-item {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.legend-dot {
		width: 8px;
		height: 8px;
		border-radius: 2px;
		display: inline-block;
	}

	/* Filters row */
	.filters-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.pill-count {
		font-size: var(--text-xs);
		opacity: 0.7;
		margin-left: 2px;
	}

	.time-pills {
		flex-shrink: 0;
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

	/* Table card */
	.table-card {
		padding: 0;
		overflow: hidden;
	}

	.table-scroll {
		overflow-x: auto;
	}

	.signature-cell {
		max-width: 260px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.ip-cell {
		white-space: nowrap;
	}

	.category-text {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	/* Alert rows */
	.alert-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.alert-row:hover {
		background-color: var(--bg-tertiary);
	}

	.alert-row-expanded {
		background-color: var(--bg-tertiary);
	}

	.alert-row.alert-acknowledged {
		opacity: 0.6;
	}

	.alert-row.alert-acknowledged:hover {
		opacity: 1;
	}

	/* Expanded detail row */
	.expanded-row td {
		padding: 0 !important;
		border-bottom: 1px solid var(--border-default) !important;
		background-color: var(--bg-elevated);
	}

	.expanded-detail {
		padding: var(--space-md) var(--space-lg);
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.expanded-top {
		display: flex;
		justify-content: space-between;
		gap: var(--space-lg);
		flex-wrap: wrap;
	}

	.expanded-section {
		flex: 1;
		min-width: 0;
	}

	.expanded-sig {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.expanded-desc {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: var(--leading-relaxed);
		margin-bottom: var(--space-xs);
	}

	.expanded-risk {
		font-size: var(--text-sm);
		color: var(--amber);
		line-height: var(--leading-normal);
	}

	.expanded-actions {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		flex-shrink: 0;
	}

	.expanded-meta {
		display: flex;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.meta-tag {
		font-size: var(--text-xs);
		color: var(--text-muted);
		background-color: var(--bg-secondary);
		padding: 2px 8px;
		border-radius: var(--radius-full);
		border: 1px solid var(--border-default);
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

	/* Top triggered rules */
	.rules-card {
		padding: var(--space-md) var(--space-lg);
	}

	.rules-chart {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-top: var(--space-sm);
	}

	.rule-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.rule-rank {
		flex-shrink: 0;
		width: 20px;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-align: center;
	}

	.rule-name {
		flex-shrink: 0;
		width: 240px;
		font-size: var(--text-sm);
		color: var(--text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.rule-bar-track {
		flex: 1;
		height: 18px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.rule-bar-fill {
		height: 100%;
		background-color: var(--accent);
		border-radius: var(--radius-sm);
		transition: width 0.4s ease-out;
		min-width: 2px;
		opacity: 0.7;
	}

	.rule-count {
		flex-shrink: 0;
		width: 50px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	/* Responsive */
	@media (max-width: 1024px) {
		.summary-cards {
			grid-template-columns: repeat(2, 1fr);
		}

		.rule-name {
			width: 160px;
		}
	}

	@media (max-width: 640px) {
		.page-header {
			flex-direction: column;
		}

		.header-actions {
			width: 100%;
			justify-content: flex-end;
		}

		.summary-cards {
			grid-template-columns: repeat(2, 1fr);
		}

		.filters-row {
			flex-direction: column;
			align-items: flex-start;
		}

		.rule-name {
			width: 100px;
			font-size: var(--text-xs);
		}

		.expanded-top {
			flex-direction: column;
		}
	}
</style>
