<script lang="ts">
	/**
	 * Alert Category Detail — Drill-down page for a single alert category.
	 *
	 * Features:
	 *   1. Category header with icon, description, MITRE tactic badge
	 *   2. Severity breakdown pills
	 *   3. Stats strip (total, unique sources/targets, affected devices)
	 *   4. Sub-category horizontal bar breakdown (clickable filter)
	 *   5. SVG timeline chart (stacked bars by sub-category)
	 *   6. Two-column: affected devices + top signatures
	 *   7. MITRE ATT&CK technique grid
	 *   8. Paginated alert table (pre-filtered to category)
	 */

	import { page } from '$app/stores';
	import { onDestroy } from 'svelte';
	import {
		getAlertCategoryDetail,
		getAlertCategoryTimeline,
		getAlerts,
		formatNumber,
		severityLabel,
		suppressAlert,
		markFalsePositive,
	} from '$api/alerts';
	import type {
		CategoryDetailResponse,
		CategoryTimelineResponse,
		CategoryTimelinePoint,
		SubCategory,
		Alert,
	} from '$api/alerts';
	import IPAddress from '$components/IPAddress.svelte';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import AlertDrawerContent from '$components/drawer/content/AlertDrawerContent.svelte';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000 },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
		{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000 },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m',
		'1h': '5m',
		'4h': '15m',
		'24h': '1h',
		'7d': '6h',
		'30d': '12h',
	};

	/** Rotating sub-category bar colors. */
	const SUB_CAT_COLORS = [
		'var(--blue)',
		'var(--cyan)',
		'var(--purple)',
		'var(--teal)',
		'var(--amber)',
		'var(--green)',
		'var(--orange)',
		'var(--pink)',
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let category = $derived(($page.params as Record<string, string>).category ?? '');
	let selectedRange = $state('24h');

	// Data
	let categoryData = $state<CategoryDetailResponse | null>(null);
	let timelineData = $state<CategoryTimelineResponse | null>(null);
	let alerts = $state<Alert[]>([]);
	let loading = $state(true);
	let alertsLoading = $state(false);

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 25;

	// Sub-category filter
	let subCatFilter = $state<string | null>(null);

	// Sort state (alert table)
	type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip';
	let sortKey = $state<SortKey>('timestamp');
	let sortDir = $state<'asc' | 'desc'>('desc');

	// Detail drawer
	let drawerAlert = $state<Alert | null>(null);
	let drawerTab = $state('summary');
	const ALERT_DRAWER_TABS = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'related', label: 'Related Events' },
		{ id: 'raw', label: 'Raw JSON' },
	];

	// Auto-refresh
	let autoRefresh = $state(false);
	let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let displayName = $derived(
		categoryData?.category?.label ??
		category.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
	);

	let catColor = $derived(categoryData?.category?.color ?? 'blue');

	/** Resolve a color token to a CSS var. */
	function catColorVar(color: string): string {
		if (color === 'muted') return 'var(--text-muted)';
		return `var(--${color})`;
	}

	function catColorDimVar(color: string): string {
		if (color === 'muted') return 'var(--bg-tertiary)';
		return `var(--${color}-dim)`;
	}

	let maxSubCount = $derived.by(() => {
		if (!categoryData?.sub_categories?.length) return 1;
		return Math.max(...categoryData.sub_categories.map((s) => s.count), 1);
	});

	let sortedAlerts = $derived.by(() => {
		const list = [...alerts];
		list.sort((a, b) => {
			let cmp = 0;
			switch (sortKey) {
				case 'timestamp':
					cmp = (a.timestamp || '').localeCompare(b.timestamp || '');
					break;
				case 'severity':
					cmp = (a.alert?.severity ?? 4) - (b.alert?.severity ?? 4);
					break;
				case 'signature':
					cmp = (a.alert?.signature || '').localeCompare(b.alert?.signature || '');
					break;
				case 'src_ip':
					cmp = (a.src_ip || '').localeCompare(b.src_ip || '');
					break;
				case 'dest_ip':
					cmp = (a.dest_ip || '').localeCompare(b.dest_ip || '');
					break;
			}
			return sortDir === 'asc' ? cmp : -cmp;
		});
		return list;
	});

	// Timeline chart derived data
	let chartHeight = 200;
	let maxBucketTotal = $derived.by(() => {
		if (!timelineData?.series?.length) return 1;
		return Math.max(...timelineData.series.map((p) => p.total), 1);
	});

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = Date.now();
		const range = TIME_RANGES.find((r) => r.value === selectedRange) || TIME_RANGES[3];
		return {
			from: new Date(now - range.ms).toISOString(),
			to: new Date(now).toISOString(),
		};
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchData(cat: string, range: string) {
		if (!cat) return;
		loading = true;
		const { from, to } = getTimeRange();
		const interval = INTERVAL_MAP[range] ?? '1h';

		try {
			const [detail, timeline, alertsResult] = await Promise.all([
				getAlertCategoryDetail(cat, { from, to }),
				getAlertCategoryTimeline(cat, { from, to, interval }),
				getAlerts({ from, to, page: 1, size: pageSize }),
			]);
			categoryData = detail;
			timelineData = timeline;
			alerts = alertsResult.alerts;
			totalPages = alertsResult.total_pages;
			totalAlerts = alertsResult.total;
			currentPage = 1;
		} catch (err) {
			console.error('[alerts/category] fetchData error:', err);
			categoryData = null;
			timelineData = null;
		} finally {
			loading = false;
		}
	}

	async function fetchAlerts(pg: number = 1) {
		alertsLoading = true;
		const { from, to } = getTimeRange();
		try {
			const r = await getAlerts({ from, to, page: pg, size: pageSize });
			alerts = r.alerts;
			totalPages = r.total_pages;
			totalAlerts = r.total;
			currentPage = r.page;
		} catch (err) {
			console.error('[alerts/category] fetchAlerts error:', err);
		} finally {
			alertsLoading = false;
		}
	}

	// Refetch when category or time range changes
	$effect(() => {
		const cat = category;
		const range = selectedRange;
		fetchData(cat, range);
	});

	// Auto-refresh
	$effect(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		if (autoRefresh) {
			autoRefreshTimer = setInterval(
				() => fetchData(category, selectedRange),
				30_000,
			);
		}
		return () => {
			if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		};
	});

	onDestroy(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
	});

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortDir = key === 'timestamp' ? 'desc' : 'asc';
		}
	}

	function sortIndicator(key: SortKey): string {
		if (sortKey !== key) return '';
		return sortDir === 'asc' ? ' \u2191' : ' \u2193';
	}

	function toggleSubFilter(id: string) {
		subCatFilter = subCatFilter === id ? null : id;
	}

	function formatTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleString(undefined, {
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

	function formatRelativeTime(ts: string): string {
		try {
			const diff = Date.now() - new Date(ts).getTime();
			const mins = Math.floor(diff / 60_000);
			if (mins < 1) return 'just now';
			if (mins < 60) return `${mins}m ago`;
			const hrs = Math.floor(mins / 60);
			if (hrs < 24) return `${hrs}h ago`;
			const days = Math.floor(hrs / 24);
			return `${days}d ago`;
		} catch {
			return ts;
		}
	}

	function severityClass(sev: number | undefined): string {
		switch (sev) {
			case 1: return 'sev-high';
			case 2: return 'sev-medium';
			case 3: return 'sev-low';
			default: return 'sev-info';
		}
	}

	function severityLabelLocal(sev: number | undefined): string {
		switch (sev) {
			case 1: return 'HIGH';
			case 2: return 'MEDIUM';
			case 3: return 'LOW';
			default: return 'INFO';
		}
	}

	function subCatColor(index: number): string {
		return SUB_CAT_COLORS[index % SUB_CAT_COLORS.length];
	}

	/** Build sub-cat id-to-color map for timeline chart. */
	let subCatColorMap = $derived.by(() => {
		const map: Record<string, string> = {};
		(categoryData?.sub_categories ?? []).forEach((sc, i) => {
			map[sc.id] = subCatColor(i);
		});
		return map;
	});

	// Alert table action handlers
	async function handleSuppress(alert: Alert) {
		if (!alert.alert?.signature_id) return;
		await suppressAlert(alert.alert.signature_id, alert.src_ip);
		fetchAlerts(currentPage);
	}

	async function handleFalsePositive(alert: Alert) {
		if (!alert.alert?.signature_id) return;
		await markFalsePositive(alert.alert.signature_id);
		fetchAlerts(currentPage);
	}

	function openDrawer(alert: Alert) {
		drawerAlert = alert;
		drawerTab = 'summary';
	}
</script>

<svelte:head>
	<title>{displayName} Alerts | NetTap</title>
</svelte:head>

<div class="category-detail">
	<!-- ================================================================
	     ROW 1: Page Header
	     ================================================================ -->
	<header class="page-header fade-up">
		<div class="header-left">
			<a href="/alerts" class="back-link">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/></svg>
				Back to Alerts
			</a>
			<div class="cat-title-row">
				<div class="cat-icon" style="background: {catColorDimVar(catColor)}; border-color: color-mix(in srgb, {catColorVar(catColor)} 25%, transparent);">
					<span style="color: {catColorVar(catColor)}; font-size: 1.25rem;">
						{#if categoryData?.category?.icon}
							{@html categoryData.category.icon === 'shield' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>' :
								categoryData.category.icon === 'radar' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 1 0 20"/><line x1="12" y1="12" x2="12" y2="2"/><path d="M12 12l7.07 7.07"/></svg>' :
								categoryData.category.icon === 'alert-triangle' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' :
								categoryData.category.icon === 'lock' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>' :
								categoryData.category.icon === 'wifi-off' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.56 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>' :
								categoryData.category.icon === 'zap' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>' :
								categoryData.category.icon === 'globe' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>' :
								categoryData.category.icon === 'info' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>' :
								'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
							}
						{/if}
					</span>
				</div>
				<div>
					<h1>{displayName}</h1>
					{#if categoryData?.category?.description}
						<p class="subtitle">{categoryData.category.description}</p>
					{/if}
					{#if categoryData?.category?.mitre_tactic}
						<span class="mitre-badge">
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
							{categoryData.category.mitre_tactic.id}: {categoryData.category.mitre_tactic.name}
						</span>
					{/if}
				</div>
			</div>
		</div>
		<div class="header-right">
			{#if categoryData?.stats}
				<div class="alert-count mono">{formatNumber(categoryData.stats.total)} alerts</div>
			{/if}
			{#if categoryData?.severity_breakdown}
				<div class="severity-pills">
					{#if categoryData.severity_breakdown.critical > 0}
						<span class="severity-pill critical">
							<span class="severity-dot"></span>
							Critical: {formatNumber(categoryData.severity_breakdown.critical)}
						</span>
					{/if}
					{#if categoryData.severity_breakdown.high > 0}
						<span class="severity-pill high">
							<span class="severity-dot"></span>
							High: {formatNumber(categoryData.severity_breakdown.high)}
						</span>
					{/if}
					{#if categoryData.severity_breakdown.medium > 0}
						<span class="severity-pill medium">
							<span class="severity-dot"></span>
							Medium: {formatNumber(categoryData.severity_breakdown.medium)}
						</span>
					{/if}
					{#if categoryData.severity_breakdown.low > 0}
						<span class="severity-pill low">
							<span class="severity-dot"></span>
							Low: {formatNumber(categoryData.severity_breakdown.low)}
						</span>
					{/if}
					{#if categoryData.severity_breakdown.info > 0}
						<span class="severity-pill info">
							<span class="severity-dot"></span>
							Info: {formatNumber(categoryData.severity_breakdown.info)}
						</span>
					{/if}
				</div>
			{/if}
			<div class="pills">
				{#each TIME_RANGES as range}
					<button
						class="pill"
						class:active={selectedRange === range.value}
						onclick={() => (selectedRange = range.value)}
					>
						{range.label}
					</button>
				{/each}
			</div>
		</div>
	</header>

	<!-- Loading state -->
	{#if loading}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<span class="text-muted">Loading {displayName} data...</span>
		</div>
	{:else if !categoryData || categoryData.stats.total === 0}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
			</div>
			<p class="empty-text">No alerts in {displayName}</p>
			<p class="empty-hint">Try expanding the time range or check that IDS rules are active.</p>
		</div>
	{:else}
		<!-- ================================================================
		     ROW 2: Stats Strip
		     ================================================================ -->
		<div class="stats-grid fade-up">
			<div class="stat-card">
				<div class="stat-label">Total Alerts</div>
				<div class="stat-value" style="color: {catColorVar(catColor)};">{formatNumber(categoryData.stats.total)}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Unique Sources</div>
				<div class="stat-value">{formatNumber(categoryData.stats.unique_sources)}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Unique Targets</div>
				<div class="stat-value">{formatNumber(categoryData.stats.unique_targets)}</div>
			</div>
			<div class="stat-card">
				<div class="stat-label">Affected Devices</div>
				<div class="stat-value">{formatNumber(categoryData.stats.affected_devices)}</div>
			</div>
		</div>

		<!-- ================================================================
		     ROW 3: Sub-Category Breakdown
		     ================================================================ -->
		{#if categoryData.sub_categories.length > 0}
			<section class="card fade-up">
				<div class="card-header">
					<span class="card-title">Sub-Categories</span>
					<span class="card-badge">{categoryData.sub_categories.length} types</span>
				</div>
				<div class="card-body">
					<div class="sub-cat-list">
						{#each categoryData.sub_categories as sub, i (sub.id)}
							<button
								class="sub-cat-row"
								class:active={subCatFilter === sub.id}
								onclick={() => toggleSubFilter(sub.id)}
							>
								<span class="sub-cat-label">{sub.label}</span>
								<div class="sub-cat-bar-track">
									<div
										class="sub-cat-bar-fill"
										style="width: {(sub.count / maxSubCount) * 100}%; background: {subCatColor(i)};"
									></div>
								</div>
								<span class="sub-cat-count mono">{formatNumber(sub.count)}</span>
								<span class="sub-cat-pct mono">{((sub.count / (categoryData?.stats?.total || 1)) * 100).toFixed(1)}%</span>
							</button>
						{/each}
					</div>
				</div>
				{#if subCatFilter}
					<div class="sub-cat-filter-bar">
						<span class="filter-text">Filtered: <strong>{categoryData.sub_categories.find(s => s.id === subCatFilter)?.label ?? subCatFilter}</strong></span>
						<button class="clear-filter-btn" onclick={() => (subCatFilter = null)}>Clear filter</button>
					</div>
				{/if}
			</section>
		{/if}

		<!-- ================================================================
		     ROW 4: Category Timeline
		     ================================================================ -->
		{#if timelineData?.series?.length}
			<section class="card fade-up">
				<div class="card-header">
					<span class="card-title">Alert Volume Over Time</span>
					<span class="card-badge">{selectedRange} &middot; {INTERVAL_MAP[selectedRange] ?? '1h'} intervals</span>
				</div>
				<div class="chart-body">
					<svg
						class="chart-svg"
						viewBox="0 0 {timelineData.series.length * 24} {chartHeight}"
						preserveAspectRatio="none"
					>
						<!-- Grid lines -->
						{#each [0, 0.25, 0.5, 0.75, 1] as frac}
							<line
								x1="0"
								y1={frac * chartHeight}
								x2={timelineData.series.length * 24}
								y2={frac * chartHeight}
								stroke="var(--border-dim)"
								stroke-dasharray="4 4"
							/>
						{/each}

						<!-- Stacked bars -->
						{#each timelineData.series as point, idx (point.timestamp)}
							{@const barX = idx * 24 + 2}
							{@const barW = 20}
							{@const totalH = (point.total / maxBucketTotal) * (chartHeight - 8)}
							<rect
								x={barX}
								y={chartHeight - totalH - 4}
								width={barW}
								height={totalH}
								rx="2"
								fill={catColorVar(catColor)}
								opacity="0.5"
							>
								<title>{new Date(point.timestamp).toLocaleString()} - {point.total} alerts</title>
							</rect>
						{/each}
					</svg>
				</div>
			</section>
		{/if}

		<!-- ================================================================
		     ROW 5: Two-column — Affected Devices + Top Signatures
		     ================================================================ -->
		<div class="two-col fade-up">
			<!-- Left: Affected Devices -->
			<section class="card">
				<div class="card-header">
					<span class="card-title">Affected Devices</span>
					<span class="card-badge">{categoryData.affected_devices.length} devices</span>
				</div>
				{#if categoryData.affected_devices.length > 0}
					<div class="table-wrap">
						<table class="data-table">
							<thead>
								<tr>
									<th>Device</th>
									<th>Alerts</th>
									<th>Severity</th>
									<th></th>
								</tr>
							</thead>
							<tbody>
								{#each categoryData.affected_devices as device (device.ip)}
									<tr>
										<td>
											<div class="device-cell">
												<IPAddress ip={device.ip} />
												{#if device.hostname}
													<span class="device-hostname">{device.hostname}</span>
												{/if}
											</div>
										</td>
										<td class="mono">{formatNumber(device.count)}</td>
										<td>
											{#if device.severity}
												<span class="sev-badge {device.severity}">{device.severity}</span>
											{/if}
										</td>
										<td>
											<a href="/devices/{encodeURIComponent(device.ip)}" class="view-link">View &rarr;</a>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="card-empty">No affected devices found.</div>
				{/if}
			</section>

			<!-- Right: Top Signatures -->
			<section class="card">
				<div class="card-header">
					<span class="card-title">Top Signatures</span>
					<span class="card-badge">{categoryData.top_signatures.length} signatures</span>
				</div>
				{#if categoryData.top_signatures.length > 0}
					{@const maxSigCount = categoryData.top_signatures[0]?.count ?? 1}
					<div class="sig-list">
						{#each categoryData.top_signatures as sig, i (sig.signature)}
							<div class="sig-row">
								<span class="sig-rank">{i + 1}</span>
								<div class="sig-info">
									<span class="sig-name" title={sig.signature}>{sig.signature}</span>
									<div class="sig-bar-track">
										<div
											class="sig-bar-fill"
											style="width: {(sig.count / maxSigCount) * 100}%; background: {catColorVar(catColor)};"
										></div>
									</div>
								</div>
								<span class="sig-count mono">{formatNumber(sig.count)}</span>
								<span class="sig-time mono">{formatRelativeTime(sig.last_seen)}</span>
							</div>
						{/each}
					</div>
				{:else}
					<div class="card-empty">No signatures found.</div>
				{/if}
			</section>
		</div>

		<!-- ================================================================
		     ROW 6: MITRE ATT&CK Mapping
		     ================================================================ -->
		{#if categoryData.mitre_techniques.length > 0}
			<section class="card fade-up">
				<div class="card-header">
					<span class="card-title">MITRE ATT&CK Techniques</span>
					<span class="card-badge">mapped from alerts</span>
				</div>
				<div class="card-body">
					<div class="mitre-grid">
						{#each categoryData.mitre_techniques as tech (tech.id)}
							<div class="mitre-card">
								<div class="mitre-card-top">
									<span class="mitre-id mono">{tech.id}</span>
									<a
										href="https://attack.mitre.org/techniques/{tech.id.replace('.', '/')}/"
										target="_blank"
										rel="noopener noreferrer"
										class="mitre-external"
										title="View on MITRE ATT&CK"
									>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
									</a>
								</div>
								<div class="mitre-technique-name">{tech.name}</div>
								<p class="mitre-desc">{tech.description}</p>
								{#if tech.count}
									<span class="mitre-count mono"><strong>{formatNumber(tech.count)}</strong> matches</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			</section>
		{/if}

		<!-- ================================================================
		     ROW 7: Alert Table
		     ================================================================ -->
		<section class="card fade-up">
			<div class="card-header">
				<span class="card-title">Recent Alerts</span>
				<span class="card-badge">{formatNumber(totalAlerts)} total</span>
			</div>
			<div class="alert-table-wrap">
				<table class="alert-table">
					<thead>
						<tr>
							<th class:sorted={sortKey === 'timestamp'} onclick={() => toggleSort('timestamp')}>
								Timestamp{sortIndicator('timestamp')}
							</th>
							<th class:sorted={sortKey === 'severity'} onclick={() => toggleSort('severity')}>
								Severity{sortIndicator('severity')}
							</th>
							<th class:sorted={sortKey === 'signature'} onclick={() => toggleSort('signature')}>
								Signature{sortIndicator('signature')}
							</th>
							<th class:sorted={sortKey === 'src_ip'} onclick={() => toggleSort('src_ip')}>
								Source{sortIndicator('src_ip')}
							</th>
							<th class:sorted={sortKey === 'dest_ip'} onclick={() => toggleSort('dest_ip')}>
								Destination{sortIndicator('dest_ip')}
							</th>
							<th>Port</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedAlerts as alert (alert._id)}
							<tr onclick={() => openDrawer(alert)} class="clickable-row">
								<td class="timestamp-cell mono">{formatTimestamp(alert.timestamp)}</td>
								<td>
									<span class="sev-badge {severityClass(alert.alert?.severity)}">
										{severityLabelLocal(alert.alert?.severity)}
									</span>
								</td>
								<td class="sig-cell" title={alert.alert?.signature ?? ''}>{alert.alert?.signature ?? 'Unknown'}</td>
								<td>
									{#if alert.src_ip}
										<IPAddress ip={alert.src_ip} />
									{:else}
										<span class="text-muted">-</span>
									{/if}
								</td>
								<td>
									{#if alert.dest_ip}
										<IPAddress ip={alert.dest_ip} />
									{:else}
										<span class="text-muted">-</span>
									{/if}
								</td>
								<td class="port-cell mono">{alert.dest_port ?? '-'}</td>
								<td>
									<div class="actions-cell">
										<button class="action-btn" onclick={(e) => { e.stopPropagation(); handleSuppress(alert); }} title="Suppress this signature">
											Suppress
										</button>
										<button class="action-btn danger" onclick={(e) => { e.stopPropagation(); handleFalsePositive(alert); }} title="Mark as false positive">
											FP
										</button>
									</div>
								</td>
							</tr>
						{:else}
							<tr>
								<td colspan="7" class="table-empty-cell">No alerts found in this time range.</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Pagination -->
			{#if totalPages > 1}
				<div class="pagination">
					<span class="pagination-info mono">Page {currentPage} of {totalPages} ({formatNumber(totalAlerts)} alerts)</span>
					<div class="pagination-buttons">
						<button class="page-btn" disabled={currentPage <= 1} onclick={() => fetchAlerts(currentPage - 1)}>Prev</button>
						{#each Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
							const start = Math.max(1, Math.min(currentPage - 3, totalPages - 6));
							return start + i;
						}) as pg (pg)}
							<button
								class="page-btn"
								class:active={currentPage === pg}
								onclick={() => fetchAlerts(pg)}
							>
								{pg}
							</button>
						{/each}
						<button class="page-btn" disabled={currentPage >= totalPages} onclick={() => fetchAlerts(currentPage + 1)}>Next</button>
					</div>
				</div>
			{/if}
		</section>
	{/if}
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={!!drawerAlert}
	title={drawerAlert?.alert?.signature ?? 'Alert Detail'}
	subtitle={drawerAlert ? formatTimestamp(drawerAlert.timestamp) : ''}
	tabs={ALERT_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={() => (drawerAlert = null)}
	ontabchange={(t) => (drawerTab = t)}
>
	{#if drawerAlert}
		<AlertDrawerContent alert={drawerAlert} activeTab={drawerTab} />
	{/if}
</DetailDrawer>

<style>
	.category-detail {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* ----------------------------------------------------------------
	   Header
	   ---------------------------------------------------------------- */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-md);
	}

	.header-left {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.back-link {
		font-size: var(--text-sm);
		color: var(--text-link);
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		transition: color var(--transition-fast);
		margin-bottom: var(--space-xs);
	}

	.back-link:hover { color: var(--cyan); opacity: 0.8; }

	.cat-title-row {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.cat-icon {
		width: 48px;
		height: 48px;
		border-radius: var(--radius-lg);
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid;
		flex-shrink: 0;
	}

	.cat-icon :global(svg) {
		width: 22px;
		height: 22px;
	}

	.cat-title-row h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		letter-spacing: -0.02em;
		line-height: 1.2;
	}

	.subtitle {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		margin-top: 2px;
	}

	.mitre-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		border-radius: var(--radius-sm);
		background: var(--blue-dim);
		color: var(--blue);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		margin-top: var(--space-sm);
		border: 1px solid rgba(68, 138, 255, 0.15);
	}

	.header-right {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: var(--space-sm);
	}

	.alert-count {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
		letter-spacing: -0.02em;
	}

	/* Severity pills */
	.severity-pills {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}

	.severity-pill {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 10px;
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		border: 1px solid transparent;
	}

	.severity-pill.critical { background: var(--red-dim); color: var(--red); border-color: rgba(255, 71, 87, 0.2); }
	.severity-pill.high { background: var(--orange-dim); color: var(--orange); border-color: rgba(255, 109, 0, 0.2); }
	.severity-pill.medium { background: var(--amber-dim); color: var(--amber); border-color: rgba(255, 171, 0, 0.2); }
	.severity-pill.low { background: var(--blue-dim); color: var(--blue); border-color: rgba(68, 138, 255, 0.2); }
	.severity-pill.info { background: var(--bg-tertiary); color: var(--text-muted); border-color: var(--border-dim); }

	.severity-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
	}

	.severity-pill.critical .severity-dot { background: var(--red); }
	.severity-pill.high .severity-dot { background: var(--orange); }
	.severity-pill.medium .severity-dot { background: var(--amber); }
	.severity-pill.low .severity-dot { background: var(--blue); }
	.severity-pill.info .severity-dot { background: var(--text-muted); }

	/* Time range pills */
	.pills {
		display: flex;
		gap: 2px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
		padding: 2px;
		border: 1px solid var(--border-dim);
	}

	.pill {
		padding: 5px 12px;
		border: none;
		background: transparent;
		color: var(--text-secondary);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		border-radius: 6px;
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.pill:hover { color: var(--text-primary); background: var(--bg-elevated); }

	.pill.active {
		background: var(--cyan);
		color: var(--bg-void);
		font-weight: 600;
		box-shadow: 0 0 12px rgba(0, 212, 255, 0.3);
	}

	/* ----------------------------------------------------------------
	   Loading / Empty
	   ---------------------------------------------------------------- */
	.loading-state {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-md);
		padding: var(--space-3xl);
	}

	.empty-state {
		text-align: center;
		padding: var(--space-3xl);
	}

	.empty-icon {
		margin-bottom: var(--space-md);
		opacity: 0.4;
		color: var(--text-muted);
	}

	.empty-text {
		font-size: var(--text-lg);
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.empty-hint {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}

	/* ----------------------------------------------------------------
	   Stats Grid
	   ---------------------------------------------------------------- */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.stat-card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md) var(--space-lg);
		position: relative;
		overflow: hidden;
		transition: border-color var(--transition-fast);
	}

	.stat-card:hover { border-color: var(--border-default); }

	.stat-card::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 2px;
		background: var(--border-dim);
		transition: background var(--transition-fast);
	}

	.stat-card:nth-child(1)::before { background: var(--blue); box-shadow: 0 0 12px rgba(68, 138, 255, 0.3); }
	.stat-card:nth-child(2)::before { background: var(--cyan); box-shadow: 0 0 12px rgba(0, 212, 255, 0.3); }
	.stat-card:nth-child(3)::before { background: var(--amber); box-shadow: 0 0 12px rgba(255, 171, 0, 0.3); }
	.stat-card:nth-child(4)::before { background: var(--green); box-shadow: 0 0 12px rgba(0, 230, 118, 0.3); }

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-weight: 500;
		margin-bottom: var(--space-sm);
	}

	.stat-value {
		font-family: var(--font-mono);
		font-size: var(--text-3xl);
		font-weight: 600;
		color: var(--text-primary);
		letter-spacing: -0.03em;
		line-height: 1;
	}

	/* ----------------------------------------------------------------
	   Cards (shared)
	   ---------------------------------------------------------------- */
	.card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		overflow: hidden;
		transition: border-color var(--transition-fast);
	}

	.card:hover { border-color: var(--border-default); }

	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.card-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.card-badge {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-muted);
		background: var(--bg-tertiary);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	.card-body {
		padding: var(--space-lg);
	}

	.card-empty {
		padding: var(--space-xl);
		text-align: center;
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	/* ----------------------------------------------------------------
	   Sub-Category Bars
	   ---------------------------------------------------------------- */
	.sub-cat-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.sub-cat-row {
		display: grid;
		grid-template-columns: 200px 1fr 80px 70px;
		align-items: center;
		gap: var(--space-md);
		cursor: pointer;
		padding: var(--space-sm) var(--space-md);
		border-radius: var(--radius-md);
		border: 1px solid transparent;
		background: none;
		width: 100%;
		text-align: left;
		font: inherit;
		color: inherit;
		transition: all var(--transition-fast);
	}

	.sub-cat-row:hover { background: var(--bg-tertiary); }

	.sub-cat-row.active {
		border-color: var(--cyan);
		background: rgba(0, 212, 255, 0.04);
	}

	.sub-cat-label {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sub-cat-bar-track {
		height: 24px;
		background: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.sub-cat-bar-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		transition: width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94);
	}

	.sub-cat-count {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		text-align: right;
	}

	.sub-cat-pct {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		background: var(--bg-tertiary);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		text-align: center;
	}

	.sub-cat-filter-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-sm) var(--space-lg);
		border-top: 1px solid var(--border-dim);
		background: rgba(0, 212, 255, 0.03);
	}

	.filter-text {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.filter-text strong {
		color: var(--cyan);
	}

	.clear-filter-btn {
		border: none;
		background: none;
		font-size: var(--text-xs);
		color: var(--text-muted);
		cursor: pointer;
		font-family: var(--font-sans);
		transition: color var(--transition-fast);
	}

	.clear-filter-btn:hover { color: var(--accent); }

	/* ----------------------------------------------------------------
	   Timeline Chart
	   ---------------------------------------------------------------- */
	.chart-body {
		padding: var(--space-md) var(--space-lg) var(--space-sm);
		height: 240px;
		position: relative;
	}

	.chart-svg {
		width: 100%;
		height: 100%;
	}

	/* ----------------------------------------------------------------
	   Two-Column Layout
	   ---------------------------------------------------------------- */
	.two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-lg);
	}

	/* Data Table */
	.table-wrap { overflow-x: auto; }

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	.data-table th {
		text-align: left;
		padding: var(--space-sm) var(--space-md);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		border-bottom: 1px solid var(--border-dim);
	}

	.data-table td {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-dim);
		vertical-align: middle;
		color: var(--text-secondary);
	}

	.data-table tbody tr { transition: background var(--transition-fast); }
	.data-table tbody tr:hover { background: var(--bg-tertiary); }
	.data-table tbody tr:last-child td { border-bottom: none; }

	.device-cell {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.device-hostname {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.view-link {
		font-size: var(--text-xs);
		color: var(--text-link);
		text-decoration: none;
		transition: opacity var(--transition-fast);
	}

	.view-link:hover { opacity: 0.7; }

	/* Severity badges */
	.sev-badge {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: 500;
		text-transform: uppercase;
	}

	.sev-badge.critical, .sev-badge.sev-high { background: var(--red-dim); color: var(--red); }
	.sev-badge.high { background: var(--orange-dim); color: var(--orange); }
	.sev-badge.sev-medium, .sev-badge.medium { background: var(--amber-dim); color: var(--amber); }
	.sev-badge.sev-low, .sev-badge.low { background: var(--blue-dim); color: var(--blue); }
	.sev-badge.sev-info { background: var(--bg-tertiary); color: var(--text-muted); }

	/* ----------------------------------------------------------------
	   Signatures List
	   ---------------------------------------------------------------- */
	.sig-list {
		padding: var(--space-xs) 0;
	}

	.sig-row {
		display: grid;
		grid-template-columns: 28px 1fr 60px 80px;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
		transition: background var(--transition-fast);
	}

	.sig-row:last-child { border-bottom: none; }
	.sig-row:hover { background: var(--bg-tertiary); }

	.sig-rank {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-align: center;
		width: 24px;
		height: 24px;
		line-height: 24px;
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
	}

	.sig-info {
		min-width: 0;
	}

	.sig-name {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		display: block;
	}

	.sig-bar-track {
		height: 4px;
		background: var(--bg-tertiary);
		border-radius: 2px;
		overflow: hidden;
		margin-top: 4px;
	}

	.sig-bar-fill {
		height: 100%;
		border-radius: 2px;
		opacity: 0.6;
		transition: width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94);
	}

	.sig-row:hover .sig-bar-fill { opacity: 1; }

	.sig-count {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		text-align: right;
	}

	.sig-time {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	/* ----------------------------------------------------------------
	   MITRE Grid
	   ---------------------------------------------------------------- */
	.mitre-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
	}

	.mitre-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-left: 3px solid var(--blue);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		transition: all var(--transition-fast);
	}

	.mitre-card:hover {
		border-color: var(--border-bright);
		background: var(--bg-elevated);
		transform: translateY(-1px);
	}

	.mitre-card-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.mitre-id {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--blue);
		background: var(--blue-dim);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	.mitre-external {
		color: var(--text-dim);
		transition: color var(--transition-fast);
	}

	.mitre-card:hover .mitre-external { color: var(--text-link); }

	.mitre-technique-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: 6px;
		line-height: 1.3;
	}

	.mitre-desc {
		font-size: var(--text-xs);
		color: var(--text-muted);
		line-height: 1.5;
		margin-bottom: var(--space-sm);
	}

	.mitre-count {
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-secondary);
	}

	.mitre-count strong {
		color: var(--text-primary);
		font-weight: 600;
	}

	/* ----------------------------------------------------------------
	   Alert Table
	   ---------------------------------------------------------------- */
	.alert-table-wrap { overflow-x: auto; }

	.alert-table {
		width: 100%;
		border-collapse: collapse;
		min-width: 900px;
	}

	.alert-table th {
		text-align: left;
		padding: var(--space-sm) var(--space-md);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		border-bottom: 1px solid var(--border-dim);
		cursor: pointer;
		user-select: none;
		white-space: nowrap;
		background: var(--bg-secondary);
		position: sticky;
		top: 0;
		z-index: 2;
		transition: color var(--transition-fast);
	}

	.alert-table th:hover { color: var(--text-secondary); }
	.alert-table th.sorted { color: var(--accent); }

	.alert-table td {
		padding: var(--space-sm) var(--space-md);
		font-size: var(--text-sm);
		border-bottom: 1px solid var(--border-dim);
		color: var(--text-secondary);
		white-space: nowrap;
		transition: background var(--transition-fast);
	}

	.alert-table tr:hover td { background: var(--bg-tertiary); }
	.alert-table tr:last-child td { border-bottom: none; }

	.clickable-row { cursor: pointer; }

	.timestamp-cell {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.sig-cell {
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 500;
		color: var(--text-primary);
	}

	.port-cell {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.table-empty-cell {
		text-align: center;
		padding: var(--space-xl) !important;
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	/* Actions */
	.actions-cell {
		display: flex;
		gap: 4px;
	}

	.action-btn {
		padding: 3px 10px;
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--text-secondary);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		cursor: pointer;
		transition: all var(--transition-fast);
		white-space: nowrap;
	}

	.action-btn:hover {
		border-color: var(--border-bright);
		color: var(--text-primary);
		background: var(--bg-elevated);
	}

	.action-btn.danger:hover {
		border-color: rgba(255, 71, 87, 0.3);
		color: var(--red);
		background: var(--red-dim);
	}

	/* Pagination */
	.pagination {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-top: 1px solid var(--border-dim);
	}

	.pagination-info {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.pagination-buttons {
		display: flex;
		gap: 4px;
	}

	.page-btn {
		padding: 4px 10px;
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--text-secondary);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.page-btn:hover { border-color: var(--border-bright); color: var(--text-primary); }

	.page-btn.active {
		background: var(--blue);
		color: var(--bg-void);
		border-color: var(--blue);
		font-weight: 600;
	}

	.page-btn:disabled { opacity: 0.3; cursor: not-allowed; }

	/* ----------------------------------------------------------------
	   Animations
	   ---------------------------------------------------------------- */
	@keyframes fadeUp {
		from { opacity: 0; transform: translateY(16px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.fade-up {
		opacity: 0;
		animation: fadeUp 0.5s ease forwards;
	}

	.fade-up:nth-child(1) { animation-delay: 0.05s; }
	.fade-up:nth-child(2) { animation-delay: 0.10s; }
	.fade-up:nth-child(3) { animation-delay: 0.15s; }
	.fade-up:nth-child(4) { animation-delay: 0.20s; }
	.fade-up:nth-child(5) { animation-delay: 0.25s; }
	.fade-up:nth-child(6) { animation-delay: 0.30s; }
	.fade-up:nth-child(7) { animation-delay: 0.35s; }

	/* ----------------------------------------------------------------
	   Responsive
	   ---------------------------------------------------------------- */
	@media (max-width: 1024px) {
		.stats-grid { grid-template-columns: repeat(2, 1fr); }
		.two-col { grid-template-columns: 1fr; }
		.mitre-grid { grid-template-columns: repeat(2, 1fr); }
		.sub-cat-row { grid-template-columns: 140px 1fr 70px 60px; }
	}

	@media (max-width: 768px) {
		.stats-grid { grid-template-columns: 1fr; }
		.page-header { flex-direction: column; }
		.header-right { align-items: flex-start; }
		.mitre-grid { grid-template-columns: 1fr; }
		.sub-cat-row { grid-template-columns: 120px 1fr 60px 50px; }
	}
</style>
