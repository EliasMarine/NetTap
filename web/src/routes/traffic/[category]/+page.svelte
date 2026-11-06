<script lang="ts">
	/**
	 * Traffic Category Detail v2 — Full-featured category analytics drill-down.
	 *
	 * Features:
	 *   1. Bandwidth over time chart (dual-series: DL/UL)
	 *   2. Device hostname resolution
	 *   3. Traffic share (%) column
	 *   4. Download/Upload split bars
	 *   5. Search/filter on device table
	 *   6. Auto-refresh toggle (30s interval)
	 *   7. Service click-through filtering
	 *   8. % of Network stat card
	 *   9. Trend indicators vs previous period
	 */

	import { partOfWhole } from '$lib/utils/part-of-whole';
	// OLD CODE START — the category colour tinted the chart and bars; system charts use data-1/2
	// import { CATEGORY_COLORS } from '$lib/utils/category-colors';
	// OLD CODE END
	import { loadFailed } from '$lib/utils/load-failed';
	import { page } from '$app/stores';
	import { onDestroy, untrack } from 'svelte';
	import {
		getCategoryDetail,
		getCategoryBandwidth,
		getTrafficSummary,
	} from '$api/traffic';
	import type {
		CategoryDetailResponse,
		CategoryBandwidthPoint,
		CategoryDevice,
		TrafficCategoryService,
	} from '$api/traffic';
	// OLD CODE START — replaced by the system's AreaChart; the DataTable sorts
	// import TimeSeriesChart from '$components/charts/TimeSeriesChart.svelte';
	// import { compareValues } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList, { type BarItem } from '$lib/components/ui/BarList.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import AreaChart, { type AreaSeries } from '$lib/components/ui/charts/AreaChart.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';

	// ---------------------------------------------------------------------------
	// Category metadata
	// ---------------------------------------------------------------------------

	// OLD CODE START — emoji icons (the system has none, and no category icon set) and colours
	// const CATEGORY_META: Record<string, { icon: string; color: string }> = {
	// 	streaming: { icon: '▶', color: CATEGORY_COLORS.streaming },
	// 	gaming: { icon: '🎮', color: CATEGORY_COLORS.gaming },
	// 	social: { icon: '👥', color: CATEGORY_COLORS.social },
	// 	communication: { icon: '💬', color: CATEGORY_COLORS.communication },
	// 	work: { icon: '💼', color: CATEGORY_COLORS.work },
	// 	iot: { icon: '📡', color: CATEGORY_COLORS.iot },
	// 	cloud: { icon: '☁', color: CATEGORY_COLORS.cloud },
	// 	file_transfer: { icon: '📁', color: CATEGORY_COLORS.file_transfer },
	// 	dns: { icon: '🌐', color: CATEGORY_COLORS.dns },
	// 	email: { icon: '✉', color: CATEGORY_COLORS.email },
	// 	web: { icon: '🔗', color: CATEGORY_COLORS.web },
	// 	security: { icon: '🔒', color: CATEGORY_COLORS.security },
	// 	shopping: { icon: '🛒', color: CATEGORY_COLORS.shopping },
	// 	news: { icon: '📰', color: CATEGORY_COLORS.news },
	// 	ads: { icon: '📊', color: CATEGORY_COLORS.ads },
	// 	updates: { icon: '⬇', color: CATEGORY_COLORS.updates },
	// 	suspicious: { icon: '⚠', color: CATEGORY_COLORS.suspicious },
	// 	other: { icon: '…', color: CATEGORY_COLORS.other },
	// };
	// OLD CODE END

	const TIME_RANGES = [
		{ label: '1h', value: '1h', text: 'hour' },
		{ label: '6h', value: '6h', text: '6 h' },
		{ label: '24h', value: '24h', text: '24 h' },
		{ label: '7d', value: '7d', text: '7 days' },
		{ label: '30d', value: '30d', text: '30 days' },
	];

	/** Map time range to chart interval */
	const INTERVAL_MAP: Record<string, string> = {
		'1h': '1m',
		'6h': '5m',
		'24h': '15m',
		'7d': '1h',
		'30d': '6h',
	};

	const AUTO_REFRESH_MS = 30_000;
	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let category = $derived(($page.params as Record<string, string>).category ?? 'other');
	// OLD CODE START: let meta = $derived(CATEGORY_META[category] ?? CATEGORY_META['other']); OLD CODE END
	let selectedRange = $state('24h');
	let rangeText = $derived(TIME_RANGES.find((r) => r.value === selectedRange)?.text ?? selectedRange);

	// Data
	let data = $state<CategoryDetailResponse | null>(null);
	let loading = $state(true);
	let topServices = $state<TrafficCategoryService[]>([]);
	let bandwidthSeries = $state<CategoryBandwidthPoint[]>([]);
	let networkPercent = $state<number | null>(null);

	// Trend data
	let prevData = $state<CategoryDetailResponse | null>(null);

	// #96: a failed request says so instead of "No traffic data"
	let detailFailed = $state(false);
	let bandwidthFailed = $state(false);
	/** category|range of the figures on screen (not reactive: only fetchData reads it) */
	let loadedView = '';

	// UI state
	let searchQuery = $state('');
	let autoRefresh = $state(false);
	// OLD CODE START — "Updated" lives in the top bar now, from the page refresh contract
	// let lastUpdated = $state<Date>(new Date());
	// OLD CODE END
	let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;

	// OLD CODE START — the DataTable owns the sort; its rule is the same (a new column starts descending)
	// // Sort state
	// let sortField = $state<string>('total_bytes');
	// let sortDir = $state<'asc' | 'desc'>('desc');
	//
	// function toggleSort(field: string) {
	// 	if (sortField === field) {
	// 		sortDir = sortDir === 'desc' ? 'asc' : 'desc';
	// 	} else {
	// 		sortField = field;
	// 		sortDir = 'desc';
	// 	}
	// }
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Derived: filtered + sorted devices
	// ---------------------------------------------------------------------------

	let filteredDevices = $derived.by(() => {
		if (!data?.devices) return [];
		let devices = [...data.devices];

		// Search filter
		if (searchQuery.trim()) {
			const q = searchQuery.trim().toLowerCase();
			devices = devices.filter(
				(d) =>
					d.ip.toLowerCase().includes(q) ||
					(d.hostname && d.hostname.toLowerCase().includes(q)),
			);
		}

		return devices;
	});

	// OLD CODE START — the DataTable sorts the filtered rows
	// let sortedDevices = $derived.by(() => {
	// 	return [...filteredDevices].sort((a, b) => {
	// 		// eslint-disable-next-line @typescript-eslint/no-explicit-any
	// 		const av = (a as any)[sortField] ?? 0;
	// 		// eslint-disable-next-line @typescript-eslint/no-explicit-any
	// 		const bv = (b as any)[sortField] ?? 0;
	// 		// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 		// const cmp = av < bv ? -1 : av > bv ? 1 : 0;
	// 		// OLD CODE END
	// 		const cmp = compareValues(av, bv);
	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	});
	// });
	// OLD CODE END

	// Max bytes for inline bar widths
	let maxDeviceBytes = $derived.by(() => {
		if (!data?.devices?.length) return 1;
		return Math.max(...data.devices.map((d) => d.total_bytes), 1);
	});

	// OLD CODE START — TimeSeriesChart's single total series; the AreaChart shows download and upload
	// // Chart data for TimeSeriesChart (total = DL + UL)
	// let chartData = $derived(
	// 	bandwidthSeries.map((p) => ({
	// 		time: p.timestamp,
	// 		value: p.total_bytes,
	// 	})),
	// );
	// OLD CODE END
	let chartSeries = $derived<AreaSeries[]>([
		{ key: 'download', label: 'Download', colour: 1, points: bandwidthSeries.map((p) => ({ t: p.timestamp, v: p.download_bytes })) },
		{ key: 'upload', label: 'Upload', colour: 2, points: bandwidthSeries.map((p) => ({ t: p.timestamp, v: p.upload_bytes })) },
	]);

	let busiestPoint = $derived(
		bandwidthSeries.reduce((best, p, i) => (p.total_bytes > (bandwidthSeries[best]?.total_bytes ?? -1) ? i : best), -1),
	);

	let serviceItems = $derived<BarItem[]>(
		topServices.map((s, i) => ({
			key: `${s.name}-${i}`,
			label: s.name,
			value: s.bytes,
			display: formatBytes(s.bytes),
			detail: s.connections ? `${formatNumber(s.connections)} conn` : undefined,
		})),
	);

	// Trend calculations
	let trendBytes = $derived.by(() => {
		if (!data || !prevData || !prevData.total_bytes) return null;
		const diff = data.total_bytes - prevData.total_bytes;
		return {
			pct: ((diff / prevData.total_bytes) * 100).toFixed(1),
			direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'neutral',
		};
	});

	let trendDevices = $derived.by(() => {
		if (!data || !prevData) return null;
		const diff = data.device_count - prevData.device_count;
		if (diff > 0) return { label: `+${diff} new`, direction: 'up' };
		if (diff < 0) return { label: `${diff}`, direction: 'down' };
		return { label: 'stable', direction: 'neutral' };
	});

	let trendConns = $derived.by(() => {
		if (!data || !prevData || !prevData.connection_count) return null;
		const diff = data.connection_count - prevData.connection_count;
		const pct = ((diff / prevData.connection_count) * 100).toFixed(1);
		return {
			pct,
			direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'neutral',
		};
	});

	/** A trend as the KPI's delta chip and comparison line; no trend shows the window instead. */
	function kpiTrend(trend: { text: string; direction: string } | null) {
		if (!trend) return { delta: undefined, comparison: undefined, note: `Last ${rangeText}` };
		if (trend.direction === 'neutral') return { delta: undefined, comparison: `No change vs previous ${rangeText}`, note: undefined };
		return {
			delta: { text: trend.text, direction: trend.direction as 'up' | 'down' },
			comparison: `vs previous ${rangeText}`,
			note: undefined,
		};
	}

	const pctText = (t: { pct: string; direction: string }) => `${t.direction === 'up' ? '+' : ''}${t.pct}%`;
	let bytesKpi = $derived(kpiTrend(trendBytes && { text: pctText(trendBytes), direction: trendBytes.direction }));
	let devicesKpi = $derived(kpiTrend(trendDevices && { text: trendDevices.label, direction: trendDevices.direction }));
	let connsKpi = $derived(kpiTrend(trendConns && { text: pctText(trendConns), direction: trendConns.direction }));

	// OLD CODE START — "Updated N s ago" is the top bar's, from the page refresh contract
	// // "Last updated X ago" text
	// let lastUpdatedText = $derived.by(() => {
	// 	const now = Date.now();
	// 	const diff = Math.floor((now - lastUpdated.getTime()) / 1000);
	// 	if (diff < 5) return 'just now';
	// 	if (diff < 60) return `${diff}s ago`;
	// 	return `${Math.floor(diff / 60)}m ago`;
	// });
	// OLD CODE END

	// Display name
	let displayName = $derived(
		data?.label ?? category.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
	);

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	function computeTimeParams(range: string): { from: string; to: string } {
		const now = new Date();
		let from: Date;
		switch (range) {
			case '1h': from = new Date(now.getTime() - 60 * 60 * 1000); break;
			case '6h': from = new Date(now.getTime() - 6 * 60 * 60 * 1000); break;
			case '7d': from = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000); break;
			case '30d': from = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000); break;
			default: from = new Date(now.getTime() - 24 * 60 * 60 * 1000); break;
		}
		return { from: from.toISOString(), to: now.toISOString() };
	}

	function computePrevTimeParams(range: string): { from: string; to: string } {
		const now = new Date();
		let durationMs: number;
		switch (range) {
			case '1h': durationMs = 60 * 60 * 1000; break;
			case '6h': durationMs = 6 * 60 * 60 * 1000; break;
			case '7d': durationMs = 7 * 24 * 60 * 60 * 1000; break;
			case '30d': durationMs = 30 * 24 * 60 * 60 * 1000; break;
			default: durationMs = 24 * 60 * 60 * 1000; break;
		}
		const to = new Date(now.getTime() - durationMs);
		const from = new Date(to.getTime() - durationMs);
		return { from: from.toISOString(), to: to.toISOString() };
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN.md §5.5: took the view as arguments and wrote whatever answered last, so a
	// slow 30 d load could land over a newer 1 h one; it now reads the view itself (the top bar's
	// Refresh calls it too), reports what happened, and a newer load makes it write nothing
	// async function fetchData(cat: string, range: string) {
	// 	loading = true;
	// 	const timeParams = computeTimeParams(range);
	// 	const prevParams = computePrevTimeParams(range);
	// 	const interval = INTERVAL_MAP[range] ?? '15m';
	//
	// 	// OLD CODE START — #96: the getters faked zeros on failure, which read as "No traffic data"
	// 	// try {
	// 	// 	const [detailResult, bandwidthResult, summaryResult, prevResult] = await Promise.all([
	// 	// 		getCategoryDetail(cat, timeParams),
	// 	// 		getCategoryBandwidth(cat, { ...timeParams, interval }),
	// 	// 		getTrafficSummary(timeParams),
	// 	// 		getCategoryDetail(cat, prevParams),
	// 	// 	]);
	// 	//
	// 	// 	data = detailResult;
	// 	// 	topServices = detailResult?.services ?? [];
	// 	// 	bandwidthSeries = bandwidthResult?.series ?? [];
	// 	// 	prevData = prevResult;
	// 	//
	// 	// 	// Calculate % of total network
	// 	// 	if (summaryResult.total_bytes > 0 && detailResult.total_bytes > 0) {
	// 	// 		networkPercent = (detailResult.total_bytes / summaryResult.total_bytes) * 100;
	// 	// 	} else {
	// 	// 		networkPercent = 0;
	// 	// 	}
	// 	//
	// 	// 	lastUpdated = new Date();
	// 	// } catch (err) {
	// 	// 	console.error('[traffic/category] fetchData error:', err);
	// 	// 	data = null;
	// 	// 	topServices = [];
	// 	// 	bandwidthSeries = [];
	// 	// } finally {
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	// A refresh of the same view keeps its last good figures; another view must not show them
	// 	const view = `${cat}|${range}`;
	// 	if (view !== loadedView) {
	// 		data = null;
	// 		prevData = null;
	// 		topServices = [];
	// 		bandwidthSeries = [];
	// 		networkPercent = null;
	// 	}
	//
	// 	const [detailRes, bandwidthRes, summaryRes, prevRes] = await Promise.allSettled([
	// 		getCategoryDetail(cat, timeParams),
	// 		getCategoryBandwidth(cat, { ...timeParams, interval }),
	// 		getTrafficSummary(timeParams),
	// 		getCategoryDetail(cat, prevParams),
	// 	]);
	// 	detailFailed = detailRes.status === 'rejected';
	// 	bandwidthFailed = bandwidthRes.status === 'rejected';
	//
	// 	if (detailRes.status === 'fulfilled') {
	// 		data = detailRes.value;
	// 		topServices = detailRes.value.services ?? [];
	// 		loadedView = view;
	// 		lastUpdated = new Date();
	// 	} else {
	// 		console.error('[traffic/category] detail failed:', detailRes.reason);
	// 	}
	// 	if (bandwidthRes.status === 'fulfilled') bandwidthSeries = bandwidthRes.value.series ?? [];
	// 	// a failed previous period hides the trend instead of comparing against zero
	// 	if (prevRes.status === 'fulfilled') prevData = prevRes.value;
	// 	// % of total network needs both figures; without them the card shows a dash
	// 	if (detailRes.status === 'fulfilled' && summaryRes.status === 'fulfilled') {
	// 		const total = summaryRes.value.total_bytes;
	// 		networkPercent = total > 0 && detailRes.value.total_bytes > 0 ? (detailRes.value.total_bytes / total) * 100 : 0;
	// 	}
	// 	loading = false;
	// }
	//
	// // Refetch when selectedRange or category changes
	// $effect(() => {
	// 	const cat = category;
	// 	const range = selectedRange;
	// 	fetchData(cat, range);
	// });
	//
	// // Auto-refresh
	// $effect(() => {
	// 	if (autoRefreshTimer) clearInterval(autoRefreshTimer);
	// 	if (autoRefresh) {
	// 		autoRefreshTimer = setInterval(
	// 			() => fetchData(category, selectedRange),
	// 			30_000,
	// 		);
	// 	}
	// 	return () => {
	// 		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
	// 	};
	// });
	// OLD CODE END
	async function fetchData(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// The view this load is for, copied before the first await
		const cat = category;
		const range = selectedRange;
		loading = true;
		const timeParams = computeTimeParams(range);
		const prevParams = computePrevTimeParams(range);
		const interval = INTERVAL_MAP[range] ?? '15m';

		// A refresh of the same view keeps its last good figures; another view must not show them
		const view = `${cat}|${range}`;
		if (view !== loadedView) {
			data = null;
			prevData = null;
			topServices = [];
			bandwidthSeries = [];
			networkPercent = null;
		}

		const results = await Promise.allSettled([
			getCategoryDetail(cat, timeParams),
			getCategoryBandwidth(cat, { ...timeParams, interval }),
			getTrafficSummary(timeParams),
			getCategoryDetail(cat, prevParams),
		]);
		if (!guard.current(g)) return 'skipped';
		const [detailRes, bandwidthRes, summaryRes, prevRes] = results;
		detailFailed = detailRes.status === 'rejected';
		bandwidthFailed = bandwidthRes.status === 'rejected';

		if (detailRes.status === 'fulfilled') {
			data = detailRes.value;
			topServices = detailRes.value.services ?? [];
			loadedView = view;
		} else {
			console.error('[traffic/category] detail failed:', detailRes.reason);
		}
		if (bandwidthRes.status === 'fulfilled') bandwidthSeries = bandwidthRes.value.series ?? [];
		// a failed previous period hides the trend instead of comparing against zero
		if (prevRes.status === 'fulfilled') prevData = prevRes.value;
		// % of total network needs both figures; without them the card shows a dash
		if (detailRes.status === 'fulfilled' && summaryRes.status === 'fulfilled') {
			const total = summaryRes.value.total_bytes;
			networkPercent = total > 0 && detailRes.value.total_bytes > 0 ? (detailRes.value.total_bytes / total) * 100 : 0;
		}
		loading = false;

		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const failed = results.filter((r) => r.status === 'rejected').length;
		// return failed === 0 ? 'ok' : failed === results.length ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(results);
	}

	const refresh = registerPageRefresh(fetchData);

	// A new category or range is a new load (the loader reads both itself)
	$effect(() => {
		category;
		selectedRange;
		untrack(() => void refresh.run());
	});

	// Auto-refresh; a tick waits while a load is running, since starting another would make the
	// guard drop the slow one and a slow daemon would never update
	$effect(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		if (autoRefresh) {
			autoRefreshTimer = setInterval(() => {
				if (!loading) void refresh.run();
			}, AUTO_REFRESH_MS);
		}
		return () => {
			if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		};
	});

	onDestroy(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		refresh.unregister();
	});

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes === 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return n.toLocaleString();
	}

	// OLD CODE START — the DataTable's header shows the sort
	// function sortArrow(field: string): string {
	// 	if (sortField !== field) return '';
	// 	return sortDir === 'asc' ? ' ▲' : ' ▼';
	// }
	// OLD CODE END

	/** Chart axis and tooltip time: the hour for a day or less, the date beyond. */
	function formatPointTime(t: number | string): string {
		const d = new Date(t);
		if (Number.isNaN(d.getTime())) return String(t);
		return selectedRange === '7d' || selectedRange === '30d'
			? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
			: d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	}

	const chartTip = (i: number) =>
		`${formatPointTime(bandwidthSeries[i].timestamp)} · ↓ ${formatBytes(bandwidthSeries[i].download_bytes)} · ↑ ${formatBytes(bandwidthSeries[i].upload_bytes)}`;

	const DEVICE_COLUMNS: Column<CategoryDevice>[] = [
		{ key: 'ip', label: 'Device', cell: deviceCell },
		{ key: 'total_bytes', label: 'Total data', numeric: true, cell: totalCell },
		{ key: 'download_bytes', label: 'Download', numeric: true, cell: downloadCell },
		{ key: 'upload_bytes', label: 'Upload', numeric: true, cell: uploadCell },
		{ key: 'connections', label: 'Connections', numeric: true, cell: connectionsCell },
		{ key: 'percent', label: 'Share', numeric: true, cell: shareCell },
	];

	// NOTE: Service click-through filtering removed — filtering devices by
	// service requires backend support (per-device service mapping) that is
	// not yet implemented. The service sidebar remains as display-only.
</script>

<svelte:head>
	<title>{displayName} Traffic | NetTap</title>
</svelte:head>

{#snippet deviceCell(device: CategoryDevice)}
	<a href="/devices/{encodeURIComponent(device.ip)}" class="device">
		<!-- OLD CODE START: <IPAddress ip={device.ip} /> (NET-160: a link and menu inside this link) OLD CODE END -->
		<IPAddress ip={device.ip} linked={false} />
		{#if device.hostname}<span class="hostname trunc" title={device.hostname}>{device.hostname}</span>{/if}
	</a>
{/snippet}
{#snippet totalCell(device: CategoryDevice)}<Bytes value={device.total_bytes} max={maxDeviceBytes} display={formatBytes(device.total_bytes)} />{/snippet}
{#snippet downloadCell(device: CategoryDevice)}{formatBytes(device.download_bytes)}{/snippet}
{#snippet uploadCell(device: CategoryDevice)}{formatBytes(device.upload_bytes)}{/snippet}
{#snippet connectionsCell(device: CategoryDevice)}{formatNumber(device.connections)}{/snippet}
{#snippet shareCell(device: CategoryDevice)}{device.percent < 0.1 ? '<0.1' : device.percent.toFixed(1)}%{/snippet}

<div class="page-head">
	<div>
		<a href="/" class="back"><Icon name="back" />Home</a>
		<h1 class="page-title">{displayName}</h1>
		<p class="page-sub">Which devices use {displayName.toLowerCase()} traffic, how much, and on which services</p>
	</div>
	<div class="head-actions">
		<Pills options={TIME_RANGES} value={selectedRange} onchange={(v) => (selectedRange = v)} ariaLabel="Time range" />
		<button class="btn" type="button" title="Refresh every 30 seconds" onclick={() => (autoRefresh = !autoRefresh)}>
			{autoRefresh ? 'Auto on' : 'Auto'}
		</button>
	</div>
</div>

{#if detailFailed && data && !loading}
	<p class="notice is-warn" role="status">{loadFailed(`${displayName} traffic`, true)}</p>
{/if}

<div class="grid">
	{#if !data || (data.device_count === 0 && data.total_bytes === 0)}
		<Card class="c-12" title="{displayName} traffic" sub="Per-device bandwidth · last {rangeText}">
			{#if loading && !data}
				<CardState state="loading" title="Loading category data" />
			{:else if detailFailed && !data}
				<CardState state="error" title={loadFailed(`${displayName} traffic`)} message={RETRY_HINT} onaction={() => refresh.run()} />
			{:else}
				<CardState state="empty" title="No traffic data for {displayName}" message="Try a longer time range, or check that devices are sending traffic in this category." />
			{/if}
		</Card>
	{:else}
		<KpiCard class="c-3" label="Total bandwidth" icon="bandwidth" value={formatBytes(data.total_bytes)} {...bytesKpi} />
		<KpiCard class="c-3" label="Active devices" icon="devices" value={formatNumber(data.device_count)} {...devicesKpi} />
		<KpiCard class="c-3" label="Connections" icon="connections" value={formatNumber(data.connection_count)} {...connsKpi} />
		<KpiCard
			class="c-3"
			label="Share of network"
			icon="live"
			value={networkPercent !== null ? networkPercent.toFixed(1) : '—'}
			unit={networkPercent !== null ? '%' : undefined}
			note="Of all traffic in the last {rangeText}"
		/>

		<Card class="c-8" hero col title="Bandwidth over time" sub="Download and upload per {INTERVAL_MAP[selectedRange] ?? '15m'} · last {rangeText}">
			{#snippet actions()}
				<ul class="legend">
					<li><span class="sw c-d1"></span>Download</li>
					<li><span class="sw c-d2"></span>Upload</li>
				</ul>
			{/snippet}
			{#if bandwidthSeries.length > 0}
				<AreaChart
					series={chartSeries}
					bytes
					formatX={formatPointTime}
					formatY={formatBytes}
					formatTip={chartTip}
					highlightIndex={busiestPoint}
					ariaLabel={busiestPoint >= 0
						? `Busiest at ${formatPointTime(bandwidthSeries[busiestPoint].timestamp)}, with ${formatBytes(bandwidthSeries[busiestPoint].total_bytes)}`
						: 'Bandwidth over time'}
				/>
				{#if bandwidthFailed}
					<p class="load-note">{loadFailed('bandwidth over time', true)}</p>
				{/if}
			{:else if bandwidthFailed}
				<CardState state="error" title={loadFailed('bandwidth over time')} message={RETRY_HINT} onaction={() => refresh.run()} />
			{:else}
				<CardState state="empty" title="No bandwidth points yet" message="The chart fills in as this category's traffic is seen in the window." />
			{/if}
		</Card>

		<Card class="c-4" title="Top services" sub="{topServices.length} {topServices.length === 1 ? 'service' : 'services'} · data in the last {rangeText}">
			{#if serviceItems.length > 0}
				<BarList items={serviceItems} />
			{:else}
				<CardState state="empty" title="No service data available" message="Services appear here once NetTap names the destinations in this category." />
			{/if}
		</Card>

		<Card
			class="c-12"
			title="Per-device breakdown"
			sub="{filteredDevices.length}{filteredDevices.length !== data.devices.length ? ` / ${data.devices.length}` : ''} devices{data.device_count > data.devices.length ? ` · top ${partOfWhole(data.devices.length, data.device_count)}` : ''} · last {rangeText}"
		>
			<div class="toolbar">
				<SearchField id="category-device-filter" label="Filter devices" placeholder="Filter by IP or hostname…" size="toolbar" bind:value={searchQuery} />
			</div>
			<DataTable columns={DEVICE_COLUMNS} rows={filteredDevices} ariaLabel="Per-device breakdown" rowKey={(d) => d.ip} initialSort={{ key: 'total_bytes', dir: 'desc' }}>
				{#snippet empty()}
					<CardState state="empty" title={searchQuery ? `No devices matching "${searchQuery}"` : 'No devices in this window'} message={searchQuery ? 'Try part of an IP address or a hostname.' : 'Devices appear here once they send traffic in this category.'} />
				{/snippet}
			</DataTable>
		</Card>
	{/if}
</div>

<style>
	/* Layout glue the system lacks */
	.load-note { margin-top: var(--sp-3); font-size: var(--text-xs); color: var(--sev-medium); }
	.device { display: inline-flex; flex-direction: column; line-height: 1.3; text-decoration: none; color: inherit; }
	.hostname { color: var(--text-3); font-size: var(--text-xs); }
</style>
