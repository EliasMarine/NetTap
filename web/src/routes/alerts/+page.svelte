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
		getEnhancedCategories,
		getSmartAlertSummary,
		formatNumber,
		severityLabel,
		severityBadgeClass,
		suppressAlert,
		markFalsePositive,
	} from '$api/alerts';
	import type {
		Alert,
		AlertTimelineBucket,
		AlertSignature,
		AlertIpEntry,
		AlertCategory,
		SmartAlertSummary,
	} from '$api/alerts';
	// OLD CODE START — AlertDetailPanel replaced by DetailDrawer
	// import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	// OLD CODE END
	import IPAddress from '$components/IPAddress.svelte';
	import HorizontalBarList from '$components/HorizontalBarList.svelte';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import AlertDrawerContent from '$components/drawer/content/AlertDrawerContent.svelte';
	import { acknowledgeAlert } from '$api/alerts';

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
	let enhancedCategories = $state<AlertCategory[]>([]);
	let alerts = $state<Alert[]>([]);
	let threatScore = $state(0);
	let threatLevel = $state('none');
	let smartSummary = $state<SmartAlertSummary | null>(null);

	// Filters
	let activeFilter = $state<SeverityFilter>('all');
	let signatureSearch = $state('');
	let urlSignature = $page.url.searchParams.get('signature') || '';
	let urlCategory = $page.url.searchParams.get('category') || '';
	let signatureFilter = $state(urlSignature);
	let ipFilter = $derived($page.url.searchParams.get('ip') || '');

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 50;

	// OLD CODE START — replaced by DetailDrawer
	// let selectedAlert = $state<Alert | null>(null);
	// let expandedAlertId = $state<string | null>(null);
	// OLD CODE END

	// Detail drawer state
	let drawerAlert = $state<Alert | null>(null);
	let drawerTab = $state('summary');
	const ALERT_DRAWER_TABS = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'related', label: 'Related Events' },
		{ id: 'raw', label: 'Raw JSON' },
	];
	let hoveredBarIndex = $state<number | null>(null);
	let chartWidth = $state(800);

	// Sort
	type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip' | 'category';
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

	let maxDestIpCount = $derived(topDestIps.length > 0 ? topDestIps[0].count : 1);
	let maxSrcIpCount = $derived(topSrcIps.length > 0 ? topSrcIps[0].count : 1);

	/** Compute "critical" count as total minus high+medium+low (info-severity alerts). */
	let criticalCount = $derived(
		smartSummary
			? (smartSummary.categories['malware-c2']?.events ?? 0)
			: 0
	);

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
				case 'category':
					cmp = (a.alert?.category || '').localeCompare(b.alert?.category || '');
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

	/** Convert sparkline data array to SVG polyline points. */
	function sparklinePoints(data: number[]): string {
		if (!data.length) return '';
		const max = Math.max(...data, 1);
		return data.map((v, i) => {
			const x = (i / Math.max(data.length - 1, 1)) * 56;
			const y = 20 - (v / max) * 18;
			return `${x},${y}`;
		}).join(' ');
	}

	/** Map category color names to CSS variable references. */
	/** Map icon name from API to emoji for category cards */
	const ICON_EMOJI: Record<string, string> = {
		'shield-alert': '\u{1F6E1}',
		'upload-cloud': '\u{2601}',
		'search': '\u{1F50D}',
		'bug': '\u{1F41B}',
		'gavel': '\u{2696}',
		'alert-triangle': '\u{26A0}',
		'key': '\u{1F511}',
		'globe': '\u{1F310}',
		'lock': '\u{1F512}',
		'cpu': '\u{1F4BB}',
		'zap': '\u{26A1}',
		'eye': '\u{1F441}',
		'info': '\u{2139}',
	};

	function catIconEmoji(icon: string): string {
		return ICON_EMOJI[icon] ?? '\u{2139}';
	}

	function catColorVar(color: string): string {
		if (color === 'muted') return 'var(--text-muted)';
		return `var(--${color})`;
	}

	function catColorDimVar(color: string): string {
		if (color === 'muted') return 'var(--bg-tertiary)';
		return `var(--${color}-dim)`;
	}

	/** Compute percentage of a severity count within a category. */
	function sevPct(cat: AlertCategory, level: 'critical' | 'high' | 'medium' | 'low' | 'info'): number {
		const total = cat.severity_breakdown.critical + cat.severity_breakdown.high + cat.severity_breakdown.medium + cat.severity_breakdown.low + cat.severity_breakdown.info;
		if (total === 0) return 0;
		return (cat.severity_breakdown[level] / total) * 100;
	}

	/** Determine trend CSS class for category cards. */
	function trendClass(dir: string): string {
		if (dir === 'increasing') return 'up-bad';
		if (dir === 'decreasing') return 'down-good';
		return 'stable';
	}

	/** Get threat score color based on score value. */
	function threatScoreColor(score: number): string {
		if (score >= 75) return 'var(--red)';
		if (score >= 50) return 'var(--orange)';
		if (score >= 25) return 'var(--amber)';
		return 'var(--green)';
	}

	/** Compute the arc path for the threat gauge based on score (0-100). */
	function threatArcPath(score: number): string {
		// Semi-circle from (4,24) to (44,24) with radius 20
		// Score 0 = start, Score 100 = full arc
		const fraction = Math.min(score, 100) / 100;
		const angle = Math.PI * fraction; // 0 to PI
		const endX = 24 - 20 * Math.cos(angle);
		const endY = 24 - 20 * Math.sin(angle);
		const largeArc = fraction > 0.5 ? 1 : 0;
		return `M 4 24 A 20 20 0 ${largeArc} 1 ${endX.toFixed(1)} ${endY.toFixed(1)}`;
	}

	/** Get the threat level badge color. */
	function threatLevelColor(level: string): { bg: string; text: string } {
		switch (level) {
			case 'critical': return { bg: 'var(--red-dim)', text: 'var(--red)' };
			case 'high': return { bg: 'var(--orange-dim)', text: 'var(--orange)' };
			case 'medium': return { bg: 'var(--amber-dim)', text: 'var(--amber)' };
			case 'low': return { bg: 'var(--blue-dim)', text: 'var(--blue)' };
			default: return { bg: 'var(--green-dim)', text: 'var(--green)' };
		}
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
			getEnhancedCategories({ from, to }),
			getAlerts({
				from,
				to,
				severity: severityFilterToNumber(activeFilter),
				page: 1,
				size: pageSize,
				ip: ipFilter || undefined,
				signature: signatureFilter || undefined,
			}),
			getSmartAlertSummary({ from, to }),
		]);

		if (results[0].status === 'fulfilled') alertCounts = results[0].value.counts;
		if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
		if (results[2].status === 'fulfilled') topSignatures = results[2].value.signatures;
		if (results[3].status === 'fulfilled') topDestIps = results[3].value.ips;
		if (results[4].status === 'fulfilled') topSrcIps = results[4].value.ips;
		if (results[5].status === 'fulfilled') enhancedCategories = results[5].value.categories;
		if (results[6].status === 'fulfilled') {
			const r = results[6].value;
			alerts = r.alerts;
			totalPages = r.total_pages;
			totalAlerts = r.total;
			currentPage = 1;
		}
		if (results[7].status === 'fulfilled') {
			smartSummary = results[7].value;
			threatScore = results[7].value.threat_score;
			threatLevel = results[7].value.threat_level;
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

	// OLD CODE START — replaced by DetailDrawer
	// function openAlertDetail(alert: Alert) { selectedAlert = alert; }
	// function closeAlertDetail() { selectedAlert = null; }
	// function toggleExpandRow(alertId: string) { ... }
	// OLD CODE END

	function openDrawer(alert: Alert) {
		drawerAlert = alert;
		drawerTab = 'summary';
	}

	function closeDrawer() {
		drawerAlert = null;
		drawerTab = 'summary';
	}

	async function handleDrawerAcknowledge(alertId: string) {
		const result = await acknowledgeAlert(alertId);
		if (result && drawerAlert) {
			drawerAlert.acknowledged = true;
			drawerAlert.acknowledged_at = result.acknowledged_at;
		}
	}

	async function handleSuppressAlert(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) {
			await suppressAlert(sigId);
			// Refresh alerts to reflect the change
			fetchAlerts(currentPage);
		}
	}

	async function handleFalsePositive(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) {
			await markFalsePositive(sigId);
			fetchAlerts(currentPage);
		}
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
			<div class="title-row">
				<h1>Alerts</h1>
				{#if threatScore > 0}
					<div class="threat-score-mini">
						<svg class="threat-gauge-mini" viewBox="0 0 48 28" width="48" height="28">
							<path d="M 4 24 A 20 20 0 0 1 44 24" fill="none" stroke="var(--bg-tertiary)" stroke-width="4" stroke-linecap="round" />
							<path d={threatArcPath(threatScore)} fill="none" stroke={threatScoreColor(threatScore)} stroke-width="4" stroke-linecap="round" />
							<text x="24" y="20" text-anchor="middle" class="tgm-score" fill={threatScoreColor(threatScore)}>{threatScore}</text>
						</svg>
						<span
							class="threat-level-badge"
							style="background: {threatLevelColor(threatLevel).bg}; color: {threatLevelColor(threatLevel).text};"
						>
							{threatLevel.toUpperCase()}
						</span>
					</div>
				{/if}
			</div>
			<p class="subtitle">Mission control for network security events</p>
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
	<!-- Hero stats — 5 cards                                               -->
	<!-- ================================================================== -->
	<div class="stats-strip">
		<button
			class="stat-card stat-total"
			onclick={() => document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' })}
		>
			<span class="stat-label">Total Alerts</span>
			<span class="stat-value text-primary-val">{formatNumber(alertCounts.total)}</span>
		</button>
		<button
			class="stat-card stat-critical"
			onclick={() => { activeFilter = 'high'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">Critical</span>
			<span class="stat-value text-red">{formatNumber(criticalCount)}</span>
		</button>
		<button
			class="stat-card stat-high"
			onclick={() => { activeFilter = 'high'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">High</span>
			<span class="stat-value text-orange">{formatNumber(alertCounts.high)}</span>
		</button>
		<button
			class="stat-card stat-medium"
			onclick={() => { activeFilter = 'medium'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">Medium</span>
			<span class="stat-value text-amber">{formatNumber(alertCounts.medium)}</span>
		</button>
		<button
			class="stat-card stat-low"
			onclick={() => { activeFilter = 'low'; fetchAlerts(1); document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' }); }}
		>
			<span class="stat-label">Low</span>
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
	<!-- Category Grid (THE STAR FEATURE)                                   -->
	<!-- ================================================================== -->
	<section class="card category-section">
		<div class="card-header">
			<h2>Alert Categories</h2>
			<span class="card-badge">{enhancedCategories.length} categories</span>
		</div>
		{#if enhancedCategories.length > 0}
			<div class="category-grid">
				{#each enhancedCategories as cat (cat.id)}
					<a href="/alerts/{cat.id}" class="cat-card" data-color={cat.color}>
						<div class="cat-glow" style="background: {catColorVar(cat.color)};"></div>
						<div class="cat-card-top">
							<div class="cat-card-identity">
								<div class="cat-icon {cat.color}" style="background: {catColorDimVar(cat.color)};">
									{catIconEmoji(cat.icon)}
								</div>
								<span class="cat-name">{cat.label}</span>
							</div>
							<span class="cat-count mono">{formatNumber(cat.count)}</span>
						</div>

						<!-- Severity micro-bar -->
						<div class="sev-bar">
							{#if sevPct(cat, 'critical') > 0}
								<div class="sev-seg crit" style="width: {sevPct(cat, 'critical')}%;"></div>
							{/if}
							{#if sevPct(cat, 'high') > 0}
								<div class="sev-seg high" style="width: {sevPct(cat, 'high')}%;"></div>
							{/if}
							{#if sevPct(cat, 'medium') > 0}
								<div class="sev-seg med" style="width: {sevPct(cat, 'medium')}%;"></div>
							{/if}
							{#if sevPct(cat, 'low') > 0}
								<div class="sev-seg low" style="width: {sevPct(cat, 'low')}%;"></div>
							{/if}
						</div>

						<!-- Sub-category pills -->
						{#if cat.sub_categories.length > 0}
							<div class="subcat-pills">
								{#each cat.sub_categories.slice(0, 3) as sub}
									<span class="subcat-pill">{sub.label}: {formatNumber(sub.count)}</span>
								{/each}
							</div>
						{/if}

						<!-- Trend + Sparkline row -->
						<div class="cat-card-bottom">
							<span class="cat-trend {trendClass(cat.trend.direction)}">
								{cat.trend.direction === 'increasing' ? '\u2191' : cat.trend.direction === 'decreasing' ? '\u2193' : '\u2192'}
								{cat.trend.percentage > 0 ? `${cat.trend.percentage}%` : 'stable'}
							</span>
							{#if cat.sparkline.length > 0}
								<svg class="cat-sparkline" width="56" height="20" viewBox="0 0 56 20">
									<polyline points={sparklinePoints(cat.sparkline)} fill="none" stroke={catColorVar(cat.color)} stroke-width="1.5" opacity="0.6" />
								</svg>
							{/if}
						</div>
					</a>
				{/each}
			</div>
		{:else if !loading}
			<div class="empty-state-inline">
				<p class="text-muted">No category data available</p>
			</div>
		{/if}
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
	<!-- Two-col: Top Signatures + Top Affected Devices                     -->
	<!-- ================================================================== -->
	<div class="two-col">
		<!-- Top Signatures -->
		<section class="card" id="top-signatures">
			<div class="card-header">
				<h2>Top Signatures</h2>
				<span class="text-muted text-sm">{topSignatures.length} rules</span>
			</div>
			{#if filteredSignatures.length > 0}
				<HorizontalBarList
					items={filteredSignatures.map((sig) => ({
						key: sig.signature,
						label: sig.signature,
						value: sig.count,
						formattedValue: sig.count.toLocaleString(),
						color: 'var(--accent)',
						badgeText: severityLabel(sig.severity),
						badgeClass: severityBadgeClass(sig.severity),
					}))}
					showRank={true}
					labelWidth={220}
					barHeight={12}
					activeKey={signatureFilter}
					onclick={(item) => filterBySignature(item.key)}
				/>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No signatures found</p>
			{/if}
		</section>

		<!-- Top Affected Devices (dest IPs) -->
		<section class="card" id="affected-devices">
			<div class="card-header">
				<h2>Top Affected Devices</h2>
				<span class="text-muted text-sm">destination</span>
			</div>
			{#if topDestIps.length > 0}
				<HorizontalBarList
					items={topDestIps.map((entry) => ({
						key: entry.ip,
						label: entry.ip,
						isIp: true,
						mono: true,
						value: entry.count,
						formattedValue: entry.count.toLocaleString(),
						color: 'var(--red)',
						href: '/devices/' + entry.ip,
					}))}
					showRank={true}
					labelWidth={150}
					barHeight={12}
				/>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No destination IPs found</p>
			{/if}
		</section>
	</div>

	<!-- ================================================================== -->
	<!-- Two-col: Top Source IPs (kept for context)                          -->
	<!-- ================================================================== -->
	<div class="two-col">
		<!-- Top Source IPs (src) -->
		<section class="card" id="source-ips">
			<div class="card-header">
				<h2>Top Source IPs</h2>
				<span class="text-muted text-sm">attackers</span>
			</div>
			{#if topSrcIps.length > 0}
				<HorizontalBarList
					items={topSrcIps.map((entry) => ({
						key: entry.ip,
						label: entry.ip,
						isIp: true,
						mono: true,
						value: entry.count,
						formattedValue: entry.count.toLocaleString(),
						color: 'var(--amber)',
						href: '/devices/' + entry.ip,
					}))}
					showRank={true}
					labelWidth={150}
					barHeight={12}
				/>
			{:else if !loading}
				<p class="text-muted" style="padding: 1rem;">No source IPs found</p>
			{/if}
		</section>

		<!-- Placeholder for future card or empty for layout balance -->
		<div></div>
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
							<th><button class="sort-btn" class:active-sort={sortKey === 'category'} onclick={() => toggleSort('category')}>Category{sortIndicator('category')}</button></th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedAlerts as alert, alertIdx (alert._id ? `${alert._id}-${alertIdx}` : `alert-${alertIdx}`)}
							<tr
								class="clickable-row"
								class:row-expanded={drawerAlert?._id === alert._id}
								class:row-acked={alert.acknowledged}
								onclick={() => openDrawer(alert)}
								role="button"
								tabindex="0"
								onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(alert); }}}
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
										<span class="category-badge">{alert.alert.category}</span>
									{:else}
										<span class="text-muted">--</span>
									{/if}
								</td>
								<td class="actions-cell">
									<button
										class="btn-action"
										title="Suppress this signature"
										onclick={(e) => { e.stopPropagation(); handleSuppressAlert(alert); }}
									>
										Suppress
									</button>
									<button
										class="btn-action"
										title="Mark as false positive"
										onclick={(e) => { e.stopPropagation(); handleFalsePositive(alert); }}
									>
										FP
									</button>
								</td>
							</tr>
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

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerAlert !== null}
	title={drawerAlert?.alert?.signature || 'Alert'}
	subtitle={drawerAlert ? `${severityLabel(drawerAlert.alert?.severity)} · ${formatTimestamp(drawerAlert.timestamp)}` : ''}
	tabs={ALERT_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => drawerTab = t}
>
	{#snippet children()}
		{#if drawerAlert}
			<AlertDrawerContent alert={drawerAlert} activeTab={drawerTab} onacknowledge={handleDrawerAcknowledge} />
		{/if}
	{/snippet}
	{#snippet actions()}
		{#if drawerAlert}
			{#if !drawerAlert.acknowledged}
				<button class="btn btn-primary btn-sm" onclick={() => handleDrawerAcknowledge(drawerAlert!._id)}>
					Acknowledge Alert
				</button>
			{/if}
			{#if drawerAlert.src_ip}
				<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(drawerAlert!.src_ip!)}`)}>
					View Source Device
				</button>
			{/if}
			{#if drawerAlert.dest_ip}
				<button class="btn btn-secondary btn-sm" onclick={() => goto(`/devices/${encodeURIComponent(drawerAlert!.dest_ip!)}`)}>
					View Dest Device
				</button>
			{/if}
			<button class="btn btn-secondary btn-sm" onclick={() => {
				const ips = [drawerAlert!.src_ip, drawerAlert!.dest_ip].filter(Boolean);
				const query = ips.map(ip => `(source.ip:"${ip}" OR destination.ip:"${ip}")`).join(' OR ');
				goto(`/logs?query=${encodeURIComponent(query)}`);
			}}>
				View in Log Explorer
			</button>
		{/if}
	{/snippet}
</DetailDrawer>

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

	.title-row {
		display: flex;
		align-items: center;
		gap: var(--space-md);
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
	/* Threat score mini gauge                                            */
	/* ------------------------------------------------------------------ */

	.threat-score-mini {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-md);
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.threat-gauge-mini {
		flex-shrink: 0;
	}

	.tgm-score {
		font-family: var(--font-mono);
		font-size: 16px;
		font-weight: 700;
	}

	.threat-level-badge {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		white-space: nowrap;
	}

	/* ------------------------------------------------------------------ */
	/* Stats strip — 5 columns                                            */
	/* ------------------------------------------------------------------ */

	.stats-strip {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: var(--space-md);
	}

	.stats-strip .stat-card {
		text-align: left;
		width: 100%;
		position: relative;
		overflow: hidden;
	}

	.stats-strip .stat-card::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 2px;
	}

	.stat-total::before { background: var(--cyan); }
	.stat-critical::before { background: var(--red); }
	.stat-high::before { background: var(--orange); }
	.stat-medium::before { background: var(--amber); }
	.stat-low::before { background: var(--blue); }

	.text-primary-val { color: var(--text-primary); }
	.text-red { color: var(--red); }
	.text-orange { color: var(--orange); }
	.text-amber { color: var(--amber); }
	.text-blue { color: var(--blue); }

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
	/* Category Grid (THE STAR FEATURE)                                   */
	/* ------------------------------------------------------------------ */

	.category-section {
		padding: 0;
		overflow: hidden;
	}

	.category-section .card-header {
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.card-badge {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-muted);
		background: var(--bg-tertiary);
		padding: 2px 8px;
		border-radius: var(--radius-sm);
	}

	.category-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
		padding: var(--space-lg);
	}

	.cat-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		cursor: pointer;
		transition: all var(--transition-fast);
		position: relative;
		overflow: hidden;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		text-decoration: none;
		color: inherit;
	}

	.cat-card:hover {
		border-color: var(--border-bright);
		transform: translateY(-1px);
	}

	.cat-card:hover .cat-glow {
		opacity: 1;
	}

	.cat-glow {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 2px;
		opacity: 0;
		transition: opacity var(--transition-fast);
	}

	/* Category color hover variants */
	.cat-card[data-color="red"]:hover { border-color: rgba(255, 71, 87, 0.4); box-shadow: 0 4px 20px rgba(255, 71, 87, 0.08); }
	.cat-card[data-color="blue"]:hover { border-color: rgba(68, 138, 255, 0.4); box-shadow: 0 4px 20px rgba(68, 138, 255, 0.08); }
	.cat-card[data-color="amber"]:hover { border-color: rgba(255, 171, 0, 0.4); box-shadow: 0 4px 20px rgba(255, 171, 0, 0.08); }
	.cat-card[data-color="cyan"]:hover { border-color: rgba(0, 212, 255, 0.4); box-shadow: 0 4px 20px rgba(0, 212, 255, 0.08); }
	.cat-card[data-color="orange"]:hover { border-color: rgba(255, 109, 0, 0.4); box-shadow: 0 4px 20px rgba(255, 109, 0, 0.08); }
	.cat-card[data-color="pink"]:hover { border-color: rgba(255, 64, 129, 0.4); box-shadow: 0 4px 20px rgba(255, 64, 129, 0.08); }
	.cat-card[data-color="purple"]:hover { border-color: rgba(179, 136, 255, 0.4); box-shadow: 0 4px 20px rgba(179, 136, 255, 0.08); }
	.cat-card[data-color="teal"]:hover { border-color: rgba(29, 233, 182, 0.4); box-shadow: 0 4px 20px rgba(29, 233, 182, 0.08); }
	.cat-card[data-color="green"]:hover { border-color: rgba(0, 230, 118, 0.4); box-shadow: 0 4px 20px rgba(0, 230, 118, 0.08); }
	.cat-card[data-color="muted"]:hover { border-color: rgba(85, 95, 115, 0.4); box-shadow: 0 4px 20px rgba(85, 95, 115, 0.08); }

	.cat-card-top {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.cat-card-identity {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		min-width: 0;
	}

	.cat-icon {
		width: 28px;
		height: 28px;
		border-radius: 6px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 14px;
		flex-shrink: 0;
	}

	.cat-name {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.cat-count {
		font-family: var(--font-mono);
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		letter-spacing: -0.03em;
		line-height: 1;
		flex-shrink: 0;
	}

	/* Severity micro-bar */
	.sev-bar {
		display: flex;
		height: 4px;
		border-radius: 2px;
		overflow: hidden;
		gap: 1px;
		width: 100%;
		background: var(--bg-secondary);
	}

	.sev-seg { border-radius: 2px; height: 100%; }
	.sev-seg.crit { background: var(--red); }
	.sev-seg.high { background: var(--orange); }
	.sev-seg.med { background: var(--amber); }
	.sev-seg.low { background: var(--blue); }

	/* Sub-category pills */
	.subcat-pills {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}

	.subcat-pill {
		font-size: 10px;
		font-family: var(--font-mono);
		color: var(--text-secondary);
		background: var(--bg-secondary);
		padding: 2px 7px;
		border-radius: var(--radius-sm);
		white-space: nowrap;
		border: 1px solid var(--border-dim);
	}

	/* Trend and sparkline row */
	.cat-card-bottom {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.cat-trend {
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		font-weight: 500;
	}

	.cat-trend.up-bad { color: var(--red); }
	.cat-trend.up-neutral { color: var(--amber); }
	.cat-trend.down-good { color: var(--green); }
	.cat-trend.stable { color: var(--text-muted); }

	.cat-sparkline { flex-shrink: 0; }

	.empty-state-inline {
		padding: var(--space-xl);
		text-align: center;
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
		margin-left: var(--space-xs);
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
		font-size: var(--text-lg);
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

	/* OLD CODE START — bar-list styles replaced by HorizontalBarList component */
	/*
	.bar-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
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
		background-color: var(--accent-muted) !important;
		border-left: 3px solid var(--accent);
	}

	.badge-accent {
		background-color: var(--accent-muted);
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
		width: 140px;
		min-width: 140px;
		flex-shrink: 0;
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
	.bar-fill-green { background-color: var(--green); }

	.bar-count {
		flex-shrink: 0;
		width: 50px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	.copy-btn {
		opacity: 0;
		transition: opacity var(--transition-fast);
		font-size: var(--text-lg);
		color: var(--accent);
		background: none;
		border: none;
		cursor: pointer;
		padding: var(--space-xs) var(--space-sm);
		line-height: 1;
	}

	.copy-btn:hover {
		color: var(--accent-hover);
	}

	.clickable-row:hover .copy-btn {
		opacity: 1;
	}
	*/
	/* OLD CODE END */

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
		line-height: 1.75;
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

	.category-badge {
		font-size: 10px;
		font-weight: 600;
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--text-secondary);
		white-space: nowrap;
	}

	.actions-cell {
		display: flex;
		gap: 4px;
		white-space: nowrap;
	}

	.btn-action {
		padding: 2px 6px;
		border: 1px solid var(--border-dim);
		background: transparent;
		border-radius: var(--radius-sm);
		font-size: 10px;
		font-weight: 500;
		color: var(--text-muted);
		cursor: pointer;
		font-family: var(--font-sans);
		transition: all var(--transition-fast);
	}

	.btn-action:hover {
		border-color: var(--border-bright);
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
		line-height: 1.75;
		margin-bottom: var(--space-xs);
	}

	.expanded-risk {
		font-size: var(--text-sm);
		color: var(--amber);
		line-height: 1.5;
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
		padding: var(--space-xs) var(--space-sm);
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

	@media (max-width: 1200px) {
		.category-grid {
			grid-template-columns: repeat(3, 1fr);
		}
	}

	@media (max-width: 1024px) {
		.stats-strip {
			grid-template-columns: repeat(3, 1fr);
		}

		.category-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.two-col {
			grid-template-columns: 1fr;
		}

		.bar-label {
			max-width: 160px;
		}
	}

	@media (max-width: 768px) {
		.stats-strip {
			grid-template-columns: repeat(2, 1fr);
		}

		.category-grid {
			grid-template-columns: 1fr;
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

		.stats-strip {
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
