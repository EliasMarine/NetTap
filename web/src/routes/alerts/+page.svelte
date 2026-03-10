<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getAlerts,
		getAlertCount,
		getAlertTimeline,
		getAlertTopSignatures,
		getAlertTopIps,
		getAlertCategories,
		formatNumber,
		severityLabel,
		severityBadgeClass,
	} from '$api/alerts';
	import type {
		Alert,
		AlertTimelineBucket,
		AlertSignature,
		AlertIpEntry,
		AlertCategoryEntry,
	} from '$api/alerts';
	import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000 },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m',
		'1h': '5m',
		'4h': '15m',
		'24h': '1h',
		'7d': '6h',
	};

	type SeverityFilter = 'all' | 'high' | 'medium' | 'low' | 'info';

	const SEVERITY_FILTERS: { value: SeverityFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'high', label: 'High' },
		{ value: 'medium', label: 'Medium' },
		{ value: 'low', label: 'Low' },
		{ value: 'info', label: 'Info' },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let initialized = $state(false);
	let loading = $state(false);
	let selectedTimeRange = $state('24h');
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Server data
	let alertCounts = $state({ total: 0, high: 0, medium: 0, low: 0 });
	let timeline = $state<AlertTimelineBucket[]>([]);
	let topSignatures = $state<AlertSignature[]>([]);
	let topDestIps = $state<AlertIpEntry[]>([]);
	let topSrcIps = $state<AlertIpEntry[]>([]);
	let categories = $state<AlertCategoryEntry[]>([]);
	let alerts = $state<Alert[]>([]);

	// Filters
	let activeFilter = $state<SeverityFilter>('all');
	let signatureSearch = $state('');
	let signatureFilter = $state('');
	let ipFilter = $derived($page.url.searchParams.get('ip') || '');

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 50;

	// Interaction
	let selectedAlert = $state<Alert | null>(null);
	let expandedAlertId = $state<string | null>(null);
	let hoveredBarIndex = $state<number | null>(null);
	let chartWidth = $state(800);

	// Sort
	type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip';
	let sortKey = $state<SortKey>('timestamp');
	let sortDir = $state<'asc' | 'desc'>('desc');

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let maxBucketTotal = $derived(
		Math.max(1, ...timeline.map((b) => b.high + b.medium + b.low))
	);

	let filteredSignatures = $derived.by(() => {
		if (!signatureSearch) return topSignatures;
		const q = signatureSearch.toLowerCase();
		return topSignatures.filter((s) => s.signature.toLowerCase().includes(q));
	});

	let maxSigCount = $derived(topSignatures.length > 0 ? topSignatures[0].count : 1);

	let maxCategoryCount = $derived(
		categories.length > 0 ? Math.max(1, ...categories.map((c) => c.count)) : 1
	);

	let maxDestIpCount = $derived(topDestIps.length > 0 ? topDestIps[0].count : 1);
	let maxSrcIpCount = $derived(topSrcIps.length > 0 ? topSrcIps[0].count : 1);

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
			case 'info':
				return Math.max(
					0,
					alertCounts.total - alertCounts.high - alertCounts.medium - alertCounts.low
				);
		}
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = Date.now();
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange) || TIME_RANGES[3];
		return {
			from: new Date(now - range.ms).toISOString(),
			to: new Date(now).toISOString(),
		};
	}

	function severityFilterToNumber(f: SeverityFilter): number | undefined {
		switch (f) {
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

	function formatShortTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
			});
		} catch {
			return ts;
		}
	}

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

	function copyToClipboard(text: string, e: Event) {
		e.stopPropagation();
		navigator.clipboard.writeText(text);
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		loading = true;
		const { from, to } = getTimeRange();
		const interval = INTERVAL_MAP[selectedTimeRange] || '1h';

		const results = await Promise.allSettled([
			getAlertCount({ from, to }),
			getAlertTimeline({ from, to, interval }),
			getAlertTopSignatures({ from, to, limit: 20 }),
			getAlertTopIps({ from, to, limit: 10, direction: 'dest' }),
			getAlertTopIps({ from, to, limit: 10, direction: 'src' }),
			getAlertCategories({ from, to }),
			getAlerts({
				from,
				to,
				severity: severityFilterToNumber(activeFilter),
				page: 1,
				size: pageSize,
				ip: ipFilter || undefined,
				signature: signatureFilter || undefined,
			}),
		]);

		if (results[0].status === 'fulfilled') alertCounts = results[0].value.counts;
		if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
		if (results[2].status === 'fulfilled') topSignatures = results[2].value.signatures;
		if (results[3].status === 'fulfilled') topDestIps = results[3].value.ips;
		if (results[4].status === 'fulfilled') topSrcIps = results[4].value.ips;
		if (results[5].status === 'fulfilled') categories = results[5].value.categories;
		if (results[6].status === 'fulfilled') {
			const r = results[6].value;
			alerts = r.alerts;
			totalPages = r.total_pages;
			totalAlerts = r.total;
			currentPage = 1;
		}
		loading = false;
	}

	async function fetchAlerts(pg: number = 1) {
		loading = true;
		const { from, to } = getTimeRange();
		try {
			const r = await getAlerts({
				from,
				to,
				severity: severityFilterToNumber(activeFilter),
				page: pg,
				size: pageSize,
				ip: ipFilter || undefined,
				signature: signatureFilter || undefined,
			});
			alerts = r.alerts;
			totalPages = r.total_pages;
			totalAlerts = r.total;
			currentPage = r.page;
		} catch {
			alerts = [];
			totalPages = 0;
			totalAlerts = 0;
		} finally {
			loading = false;
		}
	}

	function handleTimeRangeChange(value: string) {
		selectedTimeRange = value;
		if (initialized) fetchAll();
	}

	function handleSeverityChange(value: SeverityFilter) {
		activeFilter = value;
		if (initialized) fetchAlerts(1);
	}

	function filterBySignature(sig: string) {
		// Toggle: click same signature again to clear filter
		if (signatureFilter === sig) {
			signatureFilter = '';
		} else {
			signatureFilter = sig;
		}
		if (initialized) {
			fetchAlerts(1).then(() => {
				document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' });
			});
		}
	}

	function clearSignatureFilter() {
		signatureFilter = '';
		if (initialized) fetchAlerts(1);
	}

	// Pagination
	function goToPage(pg: number) {
		if (pg < 1 || pg > totalPages) return;
		fetchAlerts(pg);
	}

	// Auto-refresh
	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			refreshInterval = setInterval(fetchAll, 15_000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	// Detail panel
	function openAlertDetail(alert: Alert) {
		selectedAlert = alert;
	}
	function closeAlertDetail() {
		selectedAlert = null;
	}
	function toggleExpandRow(alertId: string) {
		expandedAlertId = expandedAlertId === alertId ? null : alertId;
	}

	// ---------------------------------------------------------------------------
	// IP filter reactivity
	// ---------------------------------------------------------------------------

	let prevIpFilter: string | null = null;
	$effect(() => {
		if (prevIpFilter !== null && prevIpFilter !== ipFilter) {
			fetchAlerts(1);
		}
		prevIpFilter = ipFilter;
	});

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	onMount(() => {
		fetchAll().then(() => {
			initialized = true;
		});
		return () => {
			if (refreshInterval) clearInterval(refreshInterval);
		};
	});
</script>

<svelte:head>
	<title>Alerts | NetTap</title>
</svelte:head>

<div class="page-container">
	<!-- ================================================================== -->
	<!-- Header                                                             -->
	<!-- ================================================================== -->
	<header class="page-header">
		<div class="header-left">
			<h1>Alerts</h1>
			<p class="subtitle">Suricata IDS alerts and threat detections</p>
		</div>
		<div class="header-right">
			<div class="pills">
				{#each TIME_RANGES as tr}
					<button
						class="pill"
						class:active={selectedTimeRange === tr.value}
						onclick={() => handleTimeRangeChange(tr.value)}
					>
						{tr.label}
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
	<!-- Hero stats                                                         -->
	<!-- ================================================================== -->
	<div class="stats-grid">
		<button
			class="stat-card clickable"
			onclick={() => document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' })}
		>
			<span class="stat-label">Total Alerts</span>
			<span class="stat-value">{formatNumber(alertCounts.total)}</span>
		</button>
		<button
			class="stat-card stat-card-high clickable"
			onclick={() => { activeFilter = 'high'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">High Severity</span>
			<span class="stat-value text-red">{formatNumber(alertCounts.high)}</span>
		</button>
		<button
			class="stat-card stat-card-medium clickable"
			onclick={() => { activeFilter = 'medium'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">Medium Severity</span>
			<span class="stat-value text-amber">{formatNumber(alertCounts.medium)}</span>
		</button>
		<button
			class="stat-card stat-card-low clickable"
			onclick={() => { activeFilter = 'low'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">Low Severity</span>
			<span class="stat-value text-blue">{formatNumber(alertCounts.low)}</span>
		</button>
	</div>

	<!-- ================================================================== -->
	<!-- Alert Timeline (stacked bar SVG chart)                             -->
	<!-- ================================================================== -->
	<section class="card">
		<div class="card-header">
			<h2>Alert Timeline</h2>
			<div class="legend-row">
				<span class="legend-item"><span class="legend-dot" style="background: var(--red);"></span> High</span>
				<span class="legend-item"><span class="legend-dot" style="background: var(--amber);"></span> Medium</span>
				<span class="legend-item"><span class="legend-dot" style="background: var(--blue);"></span> Low</span>
			</div>
		</div>
		<div class="chart-wrapper" bind:clientWidth={chartWidth}>
			{#if timeline.length > 0}
				<svg viewBox="0 0 {chartWidth} 220" width="100%" height="220">
					<!-- Grid lines -->
					{#each [0, 0.25, 0.5, 0.75, 1] as frac}
						<line
							x1="50" y1={200 - frac * 180}
							x2={chartWidth} y2={200 - frac * 180}
							stroke="var(--border-default)" stroke-width="0.5" opacity="0.4"
						/>
						<text x="45" y={200 - frac * 180 + 4} text-anchor="end"
							fill="var(--text-muted)" font-size="10">
							{Math.round(maxBucketTotal * frac)}
						</text>
					{/each}

					<!-- Bars -->
					{#each timeline as bucket, i}
						{@const barW = Math.max(2, (chartWidth - 60) / timeline.length - 2)}
						{@const total = bucket.high + bucket.medium + bucket.low}
						{@const x = 55 + i * ((chartWidth - 60) / timeline.length)}
						{@const hLow = (bucket.low / maxBucketTotal) * 180}
						{@const hMed = (bucket.medium / maxBucketTotal) * 180}
						{@const hHigh = (bucket.high / maxBucketTotal) * 180}
						{@const isHovered = hoveredBarIndex === i}
						<g
							role="img"
							onmouseenter={() => (hoveredBarIndex = i)}
							onmouseleave={() => (hoveredBarIndex = null)}
							style="cursor: pointer;"
						>
							<!-- Hit area -->
							<rect x={x} y="20" width={barW} height="180" fill="transparent" />
							<!-- Low -->
							{#if hLow > 0}
								<rect x={x} y={200 - hLow} width={barW} height={hLow} rx="2"
									fill="var(--blue)" opacity={hoveredBarIndex !== null && !isHovered ? 0.3 : 0.8} />
							{/if}
							<!-- Medium -->
							{#if hMed > 0}
								<rect x={x} y={200 - hLow - hMed} width={barW} height={hMed} rx="2"
									fill="var(--amber)" opacity={hoveredBarIndex !== null && !isHovered ? 0.3 : 0.8} />
							{/if}
							<!-- High -->
							{#if hHigh > 0}
								<rect x={x} y={200 - hLow - hMed - hHigh} width={barW} height={hHigh} rx="2"
									fill="var(--red)" opacity={hoveredBarIndex !== null && !isHovered ? 0.3 : 0.8} />
							{/if}
							<!-- Zero baseline -->
							{#if total === 0}
								<rect x={x} y={198} width={barW} height={2} rx="1"
									fill="var(--border-default)" opacity="0.3" />
							{/if}
						</g>
					{/each}

					<!-- X-axis labels -->
					{#each Array(Math.min(6, timeline.length)) as _, li}
						{@const idx = Math.round(li * (timeline.length - 1) / Math.max(1, Math.min(5, timeline.length - 1)))}
						{@const stepW = (chartWidth - 60) / timeline.length}
						{@const lx = 55 + idx * stepW + Math.max(2, stepW - 2) / 2}
						<text x={lx} y="215" text-anchor="middle" fill="var(--text-muted)" font-size="10">
							{formatShortTimestamp(timeline[idx]?.timestamp || '')}
						</text>
					{/each}
				</svg>

				<!-- Hover tooltip -->
				{#if hoveredBarIndex !== null && timeline[hoveredBarIndex]}
					{@const hb = timeline[hoveredBarIndex]}
					{@const tooltipX = 55 + hoveredBarIndex * ((chartWidth - 60) / timeline.length)}
					<div class="bar-tooltip" style="left: {Math.min(tooltipX, chartWidth - 200)}px; top: 20px;">
						<div class="tooltip-time">{formatShortTimestamp(hb.timestamp)}</div>
						<div class="tooltip-row"><span class="legend-dot" style="background: var(--red);"></span> High: <strong>{hb.high}</strong></div>
						<div class="tooltip-row"><span class="legend-dot" style="background: var(--amber);"></span> Medium: <strong>{hb.medium}</strong></div>
						<div class="tooltip-row"><span class="legend-dot" style="background: var(--blue);"></span> Low: <strong>{hb.low}</strong></div>
					</div>
				{/if}
			{:else if !loading}
				<p class="text-muted" style="padding: 2rem; text-align: center;">No timeline data available</p>
			{/if}
		</div>
	</section>

	<!-- ================================================================== -->
	<!-- Filter Bar                                                         -->
	<!-- ================================================================== -->
	<div class="filter-bar">
		<div class="pills">
			{#each SEVERITY_FILTERS as sf}
				<button
					class="pill"
					class:active={activeFilter === sf.value}
					onclick={() => handleSeverityChange(sf.value)}
				>
					{sf.label}
					<span class="pill-count">{filterCountForTab(sf.value)}</span>
				</button>
			{/each}
		</div>
		<input
			class="search-input"
			type="text"
			placeholder="Search signatures..."
			bind:value={signatureSearch}
		/>
		{#if signatureFilter}
			<span class="badge badge-accent">
				Sig: {signatureFilter.length > 40 ? signatureFilter.slice(0, 40) + '...' : signatureFilter}
				<button class="filter-clear" onclick={clearSignatureFilter} title="Clear signature filter">&times;</button>
			</span>
		{/if}
		{#if ipFilter}
			<span class="badge badge-info">
				IP: {ipFilter}
				<button class="filter-clear" onclick={() => goto('/alerts')} title="Clear filter">&times;</button>
			</span>
		{/if}
	</div>

	<!-- ================================================================== -->
	<!-- Two-col: Top Signatures + Category Breakdown                       -->
	<!-- ================================================================== -->
	<div class="two-col">
		<!-- Top Signatures -->
		<section class="card" id="top-signatures">
			<div class="card-header">
				<h2>Top Signatures</h2>
				<span class="text-muted text-sm">{topSignatures.length} rules</span>
			</div>
			{#if filteredSignatures.length > 0}
				<div class="bar-list">
					{#each filteredSignatures as sig, i}
						<button class="bar-row clickable-row" class:bar-row-active={signatureFilter === sig.signature} onclick={() => filterBySignature(sig.signature)}>
							<span class="bar-rank">{i + 1}</span>
							<span class={severityBadgeClass(sig.severity)} style="flex-shrink: 0;">
								{severityLabel(sig.severity)}
							</span>
							<span class="bar-label" title={sig.signature}>{sig.signature}</span>
							<div class="bar-track">
								<div class="bar-fill bar-fill-accent" style="width: {(sig.count / maxSigCount) * 100}%"></div>
							</div>
							<span class="bar-count mono">{sig.count}</span>
						</button>
					{/each}
				</div>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No signatures found</p>
			{/if}
		</section>

		<!-- Category Breakdown -->
		<section class="card" id="categories">
			<div class="card-header">
				<h2>Categories</h2>
				<span class="text-muted text-sm">{categories.length} types</span>
			</div>
			{#if categories.length > 0}
				<div class="bar-list">
					{#each categories as cat, i}
						<div class="bar-row">
							<span class="bar-rank">{i + 1}</span>
							<span class="bar-label" title={cat.category}>{cat.category}</span>
							<div class="bar-track">
								<div class="bar-fill bar-fill-green" style="width: {(cat.count / maxCategoryCount) * 100}%"></div>
							</div>
							<span class="bar-count mono">{cat.count}</span>
						</div>
					{/each}
				</div>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No categories found</p>
			{/if}
		</section>
	</div>

	<!-- ================================================================== -->
	<!-- Two-col: Top Attacked IPs + Top Source IPs                         -->
	<!-- ================================================================== -->
	<div class="two-col">
		<!-- Top Attacked IPs (dest) -->
		<section class="card" id="attacked-ips">
			<div class="card-header">
				<h2>Top Attacked IPs</h2>
				<span class="text-muted text-sm">destination</span>
			</div>
			{#if topDestIps.length > 0}
				<div class="bar-list">
					{#each topDestIps as entry, i}
						<div class="bar-row clickable-row">
							<span class="bar-rank">{i + 1}</span>
							<span class="bar-label mono ip-label">
								{entry.ip}
								<button class="copy-btn" onclick={(e) => copyToClipboard(entry.ip, e)} title="Copy IP">&#x2398;</button>
							</span>
							<div class="bar-track">
								<div class="bar-fill bar-fill-red" style="width: {(entry.count / maxDestIpCount) * 100}%"></div>
							</div>
							<span class="bar-count mono">{entry.count}</span>
						</div>
					{/each}
				</div>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No destination IPs found</p>
			{/if}
		</section>

		<!-- Top Source IPs (src) -->
		<section class="card" id="source-ips">
			<div class="card-header">
				<h2>Top Source IPs</h2>
				<span class="text-muted text-sm">attackers</span>
			</div>
			{#if topSrcIps.length > 0}
				<div class="bar-list">
					{#each topSrcIps as entry, i}
						<div class="bar-row clickable-row">
							<span class="bar-rank">{i + 1}</span>
							<span class="bar-label mono ip-label">
								{entry.ip}
								<button class="copy-btn" onclick={(e) => copyToClipboard(entry.ip, e)} title="Copy IP">&#x2398;</button>
							</span>
							<div class="bar-track">
								<div class="bar-fill bar-fill-amber" style="width: {(entry.count / maxSrcIpCount) * 100}%"></div>
							</div>
							<span class="bar-count mono">{entry.count}</span>
						</div>
					{/each}
				</div>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No source IPs found</p>
			{/if}
		</section>
	</div>

	<!-- ================================================================== -->
	<!-- Alerts Table                                                        -->
	<!-- ================================================================== -->
	{#if loading && alerts.length === 0}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Loading alerts...</p>
		</div>
	{:else if alerts.length === 0 && !loading}
		<div class="empty-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
					<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
					<path d="M13.73 21a2 2 0 01-3.46 0" />
					<line x1="1" y1="1" x2="23" y2="23" />
				</svg>
			</div>
			<h3>No Alerts</h3>
			<p class="text-muted">
				Alerts will appear here once Suricata is running and generating detections.
			</p>
		</div>
	{:else}
		<section class="card table-card" id="alerts-table">
			<div class="card-header">
				<h2>Alert Log <span class="text-muted text-sm">({totalAlerts.toLocaleString()} total)</span></h2>
			</div>
			<div class="table-scroll">
				<table class="data-table">
					<thead>
						<tr>
							<th><button class="sort-btn" class:active-sort={sortKey === 'timestamp'} onclick={() => toggleSort('timestamp')}>Timestamp{sortIndicator('timestamp')}</button></th>
							<th><button class="sort-btn" class:active-sort={sortKey === 'severity'} onclick={() => toggleSort('severity')}>Severity{sortIndicator('severity')}</button></th>
							<th><button class="sort-btn" class:active-sort={sortKey === 'signature'} onclick={() => toggleSort('signature')}>Signature{sortIndicator('signature')}</button></th>
							<th><button class="sort-btn" class:active-sort={sortKey === 'src_ip'} onclick={() => toggleSort('src_ip')}>Source IP{sortIndicator('src_ip')}</button></th>
							<th><button class="sort-btn" class:active-sort={sortKey === 'dest_ip'} onclick={() => toggleSort('dest_ip')}>Dest IP{sortIndicator('dest_ip')}</button></th>
							<th>Protocol</th>
							<th>Category</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedAlerts as alert (alert._id)}
							<tr
								class="clickable-row"
								class:row-expanded={expandedAlertId === alert._id}
								class:row-acked={alert.acknowledged}
								onclick={() => toggleExpandRow(alert._id)}
								role="button"
								tabindex="0"
								onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleExpandRow(alert._id); }}}
							>
								<td class="mono">{formatTimestamp(alert.timestamp)}</td>
								<td>
									<span class={severityBadgeClass(alert.alert?.severity)}>
										{severityLabel(alert.alert?.severity)}
									</span>
								</td>
								<td class="sig-cell" title={alert.alert?.signature || 'Unknown'}>
									{alert.alert?.signature || 'Unknown'}
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
		</section>

		<!-- Pagination -->
		{#if totalPages > 1}
			<div class="pagination">
				<button class="btn btn-secondary btn-sm" disabled={currentPage <= 1 || loading} onclick={() => goToPage(currentPage - 1)}>
					Previous
				</button>
				<span class="pagination-info">
					Page {currentPage} of {totalPages}
					<span class="text-muted">({totalAlerts.toLocaleString()} total)</span>
				</span>
				<button class="btn btn-secondary btn-sm" disabled={currentPage >= totalPages || loading} onclick={() => goToPage(currentPage + 1)}>
					Next
				</button>
			</div>
		{/if}
	{/if}
</div>

<!-- Alert detail slide-out panel -->
<AlertDetailPanel alert={selectedAlert} onclose={closeAlertDetail} />

<style>
	/* ------------------------------------------------------------------ */
	/* Page layout                                                        */
	/* ------------------------------------------------------------------ */

	.page-container {
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

	.header-left h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.subtitle {
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.auto-refresh-active {
		background-color: var(--accent-muted) !important;
		border-color: var(--accent) !important;
		color: var(--accent) !important;
	}

	/* ------------------------------------------------------------------ */
	/* Stats grid                                                         */
	/* ------------------------------------------------------------------ */

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.stat-card.clickable {
		cursor: pointer;
		text-align: left;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: var(--space-md) var(--space-lg);
		transition: border-color var(--transition-fast), transform var(--transition-fast);
	}

	.stat-card.clickable:hover {
		border-color: var(--accent);
		transform: translateY(-1px);
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.stat-value {
		font-size: var(--text-3xl);
		font-weight: 700;
		font-family: var(--font-mono);
		line-height: 1;
		margin-top: var(--space-xs);
		color: var(--text-primary);
	}

	.text-red { color: var(--red); }
	.text-amber { color: var(--amber); }
	.text-blue { color: var(--blue); }

	.stat-card-high { border-color: rgba(255, 71, 87, 0.3) !important; }
	.stat-card-medium { border-color: rgba(255, 171, 0, 0.3) !important; }
	.stat-card-low { border-color: rgba(68, 138, 255, 0.3) !important; }

	/* ------------------------------------------------------------------ */
	/* Chart                                                              */
	/* ------------------------------------------------------------------ */

	.chart-wrapper {
		position: relative;
		min-height: 220px;
	}

	.chart-wrapper svg {
		display: block;
	}

	.bar-tooltip {
		position: absolute;
		pointer-events: none;
		background: var(--bg-elevated);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-md);
		box-shadow: var(--shadow-lg);
		z-index: 10;
		font-size: var(--text-xs);
		min-width: 140px;
	}

	.tooltip-time {
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.tooltip-row {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		color: var(--text-secondary);
	}

	.legend-row {
		display: flex;
		gap: var(--space-md);
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

	/* ------------------------------------------------------------------ */
	/* Filter bar                                                         */
	/* ------------------------------------------------------------------ */

	.filter-bar {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.pill-count {
		font-size: var(--text-xs);
		opacity: 0.7;
		margin-left: 2px;
	}

	.search-input {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-xs) var(--space-md);
		font-size: var(--text-sm);
		color: var(--text-primary);
		min-width: 200px;
	}

	.search-input:focus {
		outline: none;
		border-color: var(--accent);
	}

	.filter-clear {
		background: none;
		border: none;
		color: inherit;
		font-size: var(--text-md);
		cursor: pointer;
		padding: 0 0 0 var(--space-xs);
		line-height: 1;
		opacity: 0.7;
	}

	.filter-clear:hover {
		opacity: 1;
	}

	/* ------------------------------------------------------------------ */
	/* Two-column layout                                                  */
	/* ------------------------------------------------------------------ */

	.two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	/* ------------------------------------------------------------------ */
	/* Bar list (shared by signatures, categories, IPs)                   */
	/* ------------------------------------------------------------------ */

	.bar-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.bar-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-md);
		border-radius: var(--radius-sm);
		transition: background-color var(--transition-fast);
		background: none;
		border: none;
		width: 100%;
		text-align: left;
		color: inherit;
		font: inherit;
	}

	.bar-row.clickable-row {
		cursor: pointer;
	}

	.bar-row.clickable-row:hover {
		background-color: var(--bg-tertiary);
	}

	.bar-row-active {
		background-color: var(--accent-muted, rgba(59, 130, 246, 0.15)) !important;
		border-left: 3px solid var(--accent);
	}

	.badge-accent {
		background-color: var(--accent-muted, rgba(59, 130, 246, 0.15));
		color: var(--accent);
		border: 1px solid var(--accent);
	}

	.bar-rank {
		flex-shrink: 0;
		width: 20px;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-align: center;
	}

	.bar-label {
		flex-shrink: 1;
		min-width: 0;
		max-width: 220px;
		font-size: var(--text-sm);
		color: var(--text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.ip-label {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.bar-track {
		flex: 1;
		height: 18px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.bar-fill {
		height: 100%;
		border-radius: var(--radius-sm);
		transition: width 0.4s ease-out;
		min-width: 2px;
		opacity: 0.7;
	}

	.bar-fill-accent { background-color: var(--accent); }
	.bar-fill-red { background-color: var(--red); }
	.bar-fill-amber { background-color: var(--amber); }
	.bar-fill-green { background-color: var(--green, #22c55e); }

	.bar-count {
		flex-shrink: 0;
		width: 50px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	/* Copy button */
	.copy-btn {
		opacity: 0;
		transition: opacity 0.15s;
		font-size: 1.25rem;
		color: var(--accent-blue, #3b82f6);
		background: none;
		border: none;
		cursor: pointer;
		padding: 0.25rem 0.5rem;
		line-height: 1;
	}

	.copy-btn:hover {
		color: #60a5fa;
	}

	.clickable-row:hover .copy-btn {
		opacity: 1;
	}

	/* ------------------------------------------------------------------ */
	/* Loading / empty                                                    */
	/* ------------------------------------------------------------------ */

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
		margin-bottom: var(--space-sm);
	}

	.empty-state p {
		max-width: 480px;
		line-height: var(--leading-relaxed);
	}

	/* ------------------------------------------------------------------ */
	/* Table                                                              */
	/* ------------------------------------------------------------------ */

	.table-card {
		padding: 0;
		overflow: hidden;
	}

	.table-card .card-header {
		padding: var(--space-md) var(--space-lg);
	}

	.table-scroll {
		overflow-x: auto;
	}

	.sort-btn {
		background: none;
		border: none;
		color: var(--text-secondary);
		font-weight: 600;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		cursor: pointer;
		padding: 0;
		white-space: nowrap;
	}

	.sort-btn:hover {
		color: var(--text-primary);
	}

	.sort-btn.active-sort {
		color: var(--accent);
	}

	.sig-cell {
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

	/* Row states */
	.row-expanded {
		background-color: var(--bg-tertiary);
	}

	.row-acked {
		opacity: 0.6;
	}

	.row-acked:hover {
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

	/* ------------------------------------------------------------------ */
	/* Responsive                                                         */
	/* ------------------------------------------------------------------ */

	@media (max-width: 1024px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.two-col {
			grid-template-columns: 1fr;
		}

		.bar-label {
			max-width: 160px;
		}
	}

	@media (max-width: 640px) {
		.page-header {
			flex-direction: column;
		}

		.header-right {
			width: 100%;
			justify-content: flex-end;
			flex-wrap: wrap;
		}

		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.filter-bar {
			flex-direction: column;
			align-items: flex-start;
		}

		.bar-label {
			max-width: 100px;
			font-size: var(--text-xs);
		}

		.expanded-top {
			flex-direction: column;
		}
	}
</style>
