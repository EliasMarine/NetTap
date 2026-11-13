<script lang="ts">
	/**
	 * Home: the network at a glance (PLAN.md §5.6, the `/` row).
	 *
	 * KPIs (bandwidth, connections, alerts, devices) with deltas against the previous window;
	 * bandwidth over time beside the protocol mix; traffic categories, top devices and the
	 * alert summary; the capture pipeline. The device cards live on /devices (owner, §3).
	 *
	 * One loader feeds every card through the page refresh contract (§5.5): it awaits every
	 * request, writes only while its load is the current one, and reports ok, partial or failed.
	 * The top bar's Refresh and the 30 s Auto toggle both run it.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import Card from '$components/ui/Card.svelte';
	import CardState from '$components/ui/CardState.svelte';
	import KpiCard from '$components/ui/KpiCard.svelte';
	import Pills from '$components/ui/Pills.svelte';
	import AutoRefreshButton from '$lib/components/ui/AutoRefreshButton.svelte';
	import BarList from '$components/ui/BarList.svelte';
	import DeviceList from '$components/ui/DeviceList.svelte';
	import Pipeline from '$components/ui/Pipeline.svelte';
	import SeverityPill from '$components/ui/SeverityPill.svelte';
	import Icon from '$components/ui/Icon.svelte';
	import AreaChart, { type AreaSeries } from '$components/ui/charts/AreaChart.svelte';
	import Donut from '$components/ui/charts/Donut.svelte';
	import SeverityGauge from '$components/ui/charts/SeverityGauge.svelte';
	import { severityBuckets } from '$lib/utils/severity';
	import { loadFailed } from '$lib/utils/load-failed';
	import { upDownLocal } from '$lib/utils/up-down';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { alertSnapshots, loadAlertSnapshot, refreshAlertSnapshots, snapshotWindow } from '$lib/stores/alertSnapshot';
	import { getTrafficSummary, getBandwidthTimeSeries, getProtocolDistribution, getTrafficCategories } from '$api/traffic';
	import type { TrafficSummary, BandwidthPoint, ProtocolEntry, ProtocolsResponse, TrafficCategory } from '$api/traffic';
	// OLD CODE: import { getAlertCount, getSmartAlerts, getSmartAlertSummary } from '$api/alerts'; (NET-228: the trend reads the timeline)
	import { getAlertTimeline, getSmartAlerts, getSmartAlertSummary } from '$api/alerts';
	// OLD CODE: import { chartTime, connLogsHref, DRILL_RANGES, fmt, NO_EXACT_ALERT_LIST, smartAlertHref, startRange, windowQuery, withCount, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown'; (NET-249: the chart drills into a moment)
	import { chartTime, connLogsHref, DRILL_RANGES, fmt, momentHref, NO_EXACT_ALERT_LIST, serviceLabel, smartAlertHref, startRange, windowQuery, withCount, type BandwidthChart, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown';
	// OLD CODE: import type { AlertCountResponse, SmartAlert, SmartAlertSummary } from '$api/alerts'; (NET-228)
	import type { AlertTimelineBucket, SmartAlert, SmartAlertSummary } from '$api/alerts';
	import { compareHalves, trendWindow, withCoverage, type SlotValue, type TrendWindow } from '$lib/utils/window-trend';
	import { getDevices, getDeviceCount } from '$api/devices';
	import type { Device, DeviceCountResponse } from '$api/devices';
	import { getNewDeviceCount } from '$api/devices-registry';
	// OLD CODE: import { getSystemHealth } from '$api/system'; (NET-228: the zero alert count reads the pipeline's state)
	import { getSystemHealth, nothingFound } from '$api/system';
	import type { SystemHealth } from '$api/system';
	// OLD CODE: import { getCaptureHealth, getCaptureStats, LOSS_SCOPE } (NET-167: the subtitle no longer quotes the scope)
	import { BRIDGE_NO_DEVICES, getCaptureHealth, getCaptureStats } from '$api/capture';
	import type { CaptureHealthResponse, CaptureStatsResponse } from '$api/capture';
	import {
		// OLD CODE: formatBytes, …, computePreviousPeriod, localMidnight, trendPercent, NO_TREND, (NET-228: + the settled trend window)
		formatBytes, formatBytesShort, formatNumber, localMidnight, trendPercent, NO_TREND, NOT_ENOUGH, COMPARE_FAILED,
		kpiDelta, kpiWindow, smartLevel, captureStage, packetsStage, systemStage, openSearchStage, dataStage,
	} from './home';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	const AUTO_REFRESH_MS = 30_000;
	const TOP_DEVICES = 5;
	const TOP_ALERT_GROUPS = 5;
	const TOP_SERVICES = 8;

	// DashboardFilters' time ranges, as head pills (its device and protocol filters were never applied)
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES), with Home's comparison words beside it
	// const RANGES = [
	// 	{ value: '1h', label: '1h', hours: 1, window: 'Last hour', previous: 'previous hour' },
	// 	{ value: '6h', label: '6h', hours: 6, window: 'Last 6 hours', previous: 'previous 6 h' },
	// 	{ value: '24h', label: '24h', hours: 24, window: 'Last 24 hours', previous: 'previous 24 h' },
	// 	{ value: '7d', label: '7d', hours: 168, window: 'Last 7 days', previous: 'previous 7 days' },
	// 	{ value: '30d', label: '30d', hours: 720, window: 'Last 30 days', previous: 'previous 30 days' },
	// ] as const;
	// type RangeKey = (typeof RANGES)[number]['value'];
	// OLD CODE END
	type RangeKey = DrillRangeValue;
	// OLD CODE START — one voice with Traffic: "previous 24 hours", not "previous 24 h"
	// const PREVIOUS: Record<RangeKey, string> = {
	// 	'1h': 'previous hour', '6h': 'previous 6 h', '24h': 'previous 24 h', '7d': 'previous 7 days', '30d': 'previous 30 days',
	// };
	// const RANGES = DRILL_RANGES.map((r) => ({ ...r, window: r.words.charAt(0).toUpperCase() + r.words.slice(1), previous: PREVIOUS[r.value] }));
	// OLD CODE END
	const RANGES = DRILL_RANGES.map((r) => ({
		...r,
		window: r.words.charAt(0).toUpperCase() + r.words.slice(1),
		previous: r.words.replace(/^last /, 'previous '),
	}));
	const RANGE_OPTIONS = RANGES.map(({ value, label }) => ({ value, label }));

	// OLD CODE: let range = $state<RangeKey>('24h'); (NET-195: Settings › Display's default, read where the range starts so the first load uses it)
	let range = $state<RangeKey>(startRange('24h'));
	// OLD CODE: ?? RANGES[2] (NET-192 PR 4: the default by value, not by position)
	const span = $derived(RANGES.find((r) => r.value === range) ?? RANGES.find((r) => r.value === '24h')!);
	const windowText = $derived(span.window.toLowerCase());

	let autoRefresh = $state(true);
	let loading = $state(true);
	let error = $state(false);

	let trafficSummary = $state<TrafficSummary | null>(null);
	// OLD CODE: let prevTrafficSummary = $state<TrafficSummary | null>(null); (NET-228, audit TRF-6: the window ending now vs the one before)
	/** NET-228: two equal windows of settled slots (lib/utils/window-trend.ts); null until loaded or when failed */
	let trendWin = $state<TrendWindow | null>(null);
	let trendTraffic = $state<BandwidthPoint[] | null>(null);
	let trendAlerts = $state<AlertTimelineBucket[] | null>(null);
	// OLD CODE: let bandwidthData = $state<BandwidthPoint[]>([]); (NET-249: a pick needs the reply's window and bucket with its points)
	const NO_CHART = { series: [], from: '', to: '', step: 0 };
	/** The bandwidth reply on screen, whole: a pick's indices and the window they open come from one answer */
	let bandwidth = $state<Omit<BandwidthChart, 'series'> & { series: BandwidthPoint[] }>(NO_CHART);
	const bandwidthData = $derived(bandwidth.series);
	let protocols = $state<ProtocolEntry[]>([]);
	let services = $state<ProtocolEntry[]>([]);
	/** The `unknown` service split into conversations, one-way connections and ICMP (NET-219). Null when the reply has none */
	let unidentified = $state<ProtocolsResponse['unidentified'] | null>(null);
	let categories = $state<TrafficCategory[]>([]);
	// OLD CODE START — NET-160 slice 2b-3: the figure alone; the card's link needs the window it was counted over
	// let deviceCount = $state<number | null>(null); // null until a count loads
	// OLD CODE END
	/** The device count on screen, whole: its figure and the window it was counted over. Null until one loads */
	let deviceCountReply = $state<DeviceCountResponse | null>(null);
	const deviceCount = $derived(deviceCountReply?.count ?? null);
	let newDeviceCount = $state<number | null>(null); // null when it failed: no chip, no number
	// OLD CODE: let prevAlertCount = $state<AlertCountResponse | null>(null); (NET-228)
	let systemHealth = $state<SystemHealth | null>(null);
	let smartAlerts = $state<SmartAlert[]>([]);
	/** The window and range the smart alerts on screen were counted over, set when they land (NET-160 slice 2b-1) */
	let smartWindow = $state<(DrillWindow & { range: RangeKey }) | null>(null);
	let smartAlertSummary = $state<SmartAlertSummary | null>(null);
	let topDevices = $state<Device[]>([]);
	let captureHealth = $state<CaptureHealthResponse | null>(null);
	let captureStats = $state<CaptureStatsResponse | null>(null);

	type Source =
		// OLD CODE: | 'summary' | 'prevSummary' | … | 'prevAlerts' | 'health' … (NET-228: the trend's series)
		| 'summary' | 'trendTraffic' | 'bandwidth' | 'protocols' | 'categories' | 'deviceCount' | 'newDevices'
		| 'trendAlerts' | 'health' | 'smart' | 'smartSummary' | 'devices' | 'capture' | 'captureStats';
	// #96: a failed request keeps the last good figures and says so; it never shows 0 B or "no data"
	let failed = $state<Partial<Record<Source, boolean>>>({});

	// The Alerts KPI and the gauge read the shared snapshot, so Home, Alerts and the sidebar agree (§4.1)
	const snapshot = $derived($alertSnapshots[span.hours]);
	// On error the snapshot keeps the last good counts (#96): show them with a stale note
	const alertCount = $derived(snapshot?.data ?? null);
	const alertCountFailed = $derived(snapshot?.status === 'error');

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	/** Await one request; write its result (or mark it failed) only while load `g` is current. */
	function settle<T>(
		guard: LoadGuard,
		g: number,
		source: Source,
		request: Promise<T>,
		write: (value: T) => void,
		clear?: () => void,
	): Promise<boolean> {
		return request.then(
			(value) => {
				if (guard.current(g)) {
					write(value);
					failed = { ...failed, [source]: false };
				}
				return true;
			},
			() => {
				if (guard.current(g)) {
					clear?.();
					failed = { ...failed, [source]: true };
				}
				return false;
			},
		);
	}

	let snapshotHoursLoaded: number | null = null;

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// the query, fixed before the first await
		const hours = span.hours;
		const r = range;
		// A repeat load moves every reader of the shared count (sidebar, Alerts) to a new window, as Alerts does
		if (snapshotHoursLoaded === hours) void refreshAlertSnapshots();
		snapshotHoursLoaded = hours;
		const win = snapshotWindow(hours, Date.now());
		// OLD CODE: const prev = computePreviousPeriod(win.from, win.to); (NET-228, audit TRF-6)
		const tw = trendWindow(hours, Date.now());
		// NET-249: the chart's bucket scales with the range (1h → 1 min … 30d → 3 h)
		const { bucket, bucketMs } = span;
		const trendQuery = { from: tw.from, to: tw.to, interval: tw.interval };
		const since = localMidnight(new Date());
		loading = true;

		const results = await Promise.all([
			settle(guard, g, 'summary', getTrafficSummary(win), (v) => (trafficSummary = v)),
			// OLD CODE: settle(guard, g, 'prevSummary', getTrafficSummary(prev), …), (NET-228: two settled windows from one series)
			settle(guard, g, 'trendTraffic', getBandwidthTimeSeries(trendQuery), (v) => {
				trendTraffic = v.series;
				trendWin = tw;
			}, () => (trendTraffic = null)),
			// OLD CODE: settle(guard, g, 'bandwidth', getBandwidthTimeSeries({ ...win, interval: '1h' }), (v) => (bandwidthData = v.series)), (NET-249)
			settle(guard, g, 'bandwidth', getBandwidthTimeSeries({ ...win, interval: bucket }), (v) => {
				bandwidth = { series: v.series, from: v.from, to: v.to, step: bucketMs };
			}),
			settle(guard, g, 'protocols', getProtocolDistribution(win), (v) => {
				protocols = v.protocols;
				services = v.services;
				unidentified = v.unidentified ?? null;
			}),
			settle(guard, g, 'categories', getTrafficCategories(win), (v) => (categories = v.categories)),
			// OLD CODE: settle(guard, g, 'deviceCount', getDeviceCount(win), (v) => (deviceCount = v.count)), (slice 2b-3: the card links to the reply's window)
			settle(guard, g, 'deviceCount', getDeviceCount(win), (v) => (deviceCountReply = v)),
			settle(guard, g, 'newDevices', getNewDeviceCount(since), (v) => (newDeviceCount = v.count), () => (newDeviceCount = null)),
			// the store keeps one count per window for every screen; it never rejects
			loadAlertSnapshot(hours).then((s) => s.status === 'ok'),
			// OLD CODE: settle(guard, g, 'prevAlerts', getAlertCount(prev), …), (NET-228)
			settle(guard, g, 'trendAlerts', getAlertTimeline(trendQuery), (v) => (trendAlerts = v.buckets), () => (trendAlerts = null)),
			settle(guard, g, 'health', getSystemHealth(), (v) => (systemHealth = v), () => (systemHealth = null)),
			// OLD CODE: settle(guard, g, 'smart', getSmartAlerts({ ...win, limit: 10 }), (v) => (smartAlerts = v.alerts), () => (smartAlerts = [])), (slice 2b-1: the rows keep their window)
			settle(guard, g, 'smart', getSmartAlerts({ ...win, limit: 10 }), (v) => {
				smartAlerts = v.alerts;
				smartWindow = { from: v.from, to: v.to, range: r };
			}, () => (smartAlerts = [])),
			settle(guard, g, 'smartSummary', getSmartAlertSummary(win), (v) => (smartAlertSummary = v), () => (smartAlertSummary = null)),
			// OLD CODE START — the device cards needed every device's traffic; they moved to /devices
			// getDevices({ ...timeParams, sort: 'bytes', order: 'desc', limit: DEVICE_LIST_LIMIT }),
			// OLD CODE END
			settle(guard, g, 'devices', getDevices({ ...win, sort: 'bytes', order: 'desc', limit: TOP_DEVICES }), (v) => (topDevices = v.devices)),
			// the capture pipeline replaces CaptureHealthPanel, which made these two calls itself
			settle(guard, g, 'capture', getCaptureHealth(), (v) => (captureHealth = v), () => (captureHealth = null)),
			settle(guard, g, 'captureStats', getCaptureStats(), (v) => (captureStats = v), () => (captureStats = null)),
		]);
		if (!guard.current(g)) return 'skipped';
		const result: LoadResult = results.every(Boolean) ? 'ok' : results.some(Boolean) ? 'partial' : 'failed';
		loading = false;
		error = result === 'failed'; // nothing answered: the daemon is unreachable
		return result;
	}

	const handle = registerPageRefresh(load);
	onDestroy(handle.unregister);
	const retry = () => void handle.run();

	/** A new range: drop the last range's figures, then load this one. */
	function changeRange() {
		// #96: the last range's figures must not stand in for this range if its load fails
		trafficSummary = null;
		// OLD CODE: prevTrafficSummary = null; (NET-228)
		trendTraffic = null;
		trendAlerts = null;
		trendWin = null;
		// OLD CODE: bandwidthData = []; (NET-249)
		bandwidth = NO_CHART;
		protocols = [];
		services = [];
		unidentified = null;
		categories = [];
		// OLD CODE: deviceCount = null; (slice 2b-3: the reply carries the figure and its window)
		deviceCountReply = null;
		// OLD CODE: prevAlertCount = null; (NET-228)
		topDevices = [];
		failed = {};
		handle.run();
	}

	// The first load, a load on each Auto toggle (as before), then every 30 s while Auto is on.
	// A tick never cancels a load still running, or a slow range would never land.
	$effect(() => {
		const auto = autoRefresh;
		untrack(() => handle.run());
		if (!auto) return;
		const timer = setInterval(() => {
			if (!loading) handle.run();
		}, AUTO_REFRESH_MS);
		return () => clearInterval(timer);
	});

	// OLD CODE START — replaced by load() above (PLAN.md §5.5): Promise.allSettled plus requests it never
	// awaited (smart alerts, devices), so a refresh read as done while cards were still loading, a slow
	// older load could overwrite a newer range, and nothing reported a partial failure. The capture-mode,
	// registry, top-talker and recent-alert requests fed only the device grid, the mirror header and the
	// new-device banner (moved to /devices) or nothing on screen at all, so they are not made here now.
	// // Filter bar state
	// let activeFilters = $state<FilterState>({
	// 	timeRange: '24h',
	// 	from: '',
	// 	to: '',
	// 	device: '',
	// 	protocol: '',
	// });
	// async function fetchAllData() {
	// 	loading = true;
	// 	error = false;
	//
	// 	// Fetch capture mode first (or in parallel)
	// 	try {
	// 		captureMode = await getCaptureMode();
	// 	} catch {
	// 		captureMode = { mode: 'bridge', interface: '' };
	// 	}
	//
	// 	// If mirror mode, also fetch registry devices
	// 	if (captureMode?.mode === 'mirror') {
	// 		try {
	// 			const regResult = await getRegistryDevices({ limit: 200 });
	// 			registryDevices = regResult.devices;
	// 			registryFailed = false;
	// 		} catch {
	// 			// OLD CODE START — #96: a failure read as "No devices detected yet"
	// 			// registryDevices = [];
	// 			// OLD CODE END
	// 			registryFailed = true;
	// 		}
	// 	}
	//
	// 	// Build time range params from active filters
	// 	const timeParams: { from?: string; to?: string } = {};
	// 	if (activeFilters.from && activeFilters.to) {
	// 		timeParams.from = activeFilters.from;
	// 		timeParams.to = activeFilters.to;
	// 	}
	//
	// 	// Compute the previous period for trend comparison
	// 	let prevTimeParams: { from?: string; to?: string } = {};
	// 	if (timeParams.from && timeParams.to) {
	// 		prevTimeParams = computePreviousPeriod(timeParams.from, timeParams.to);
	// 	}
	//
	// 	try {
	// 		const [
	// 			summaryRes, bandwidthRes, protocolsRes, talkersRes,
	// 			alertCountRes, alertsRes, healthRes, categoriesRes,
	// 			deviceCountRes, prevSummaryRes, prevAlertCountRes,
	// 		] = await Promise.allSettled([
	// 			getTrafficSummary(timeParams),
	// 			getBandwidthTimeSeries({ ...timeParams, interval: '1h' }),
	// 			getProtocolDistribution(timeParams),
	// 			getTopTalkers({ ...timeParams, limit: 10 }),
	// 			getAlertCount(timeParams),
	// 			getAlerts({ ...timeParams, size: 10 }),
	// 			getSystemHealth(),
	// 			getTrafficCategories(timeParams),
	// 			getDeviceCount(timeParams),
	// 			// OLD CODE START — with no range chosen (the default) prevTimeParams stayed {}, so this fetched
	// 			// the current 24 h again and each trend compared the period with itself
	// 			// getTrafficSummary(prevTimeParams),
	// 			// getAlertCount(prevTimeParams),
	// 			// OLD CODE END
	// 			// no range, no previous period: no trend rather than a comparison with itself
	// 			prevTimeParams.from ? getTrafficSummary(prevTimeParams) : Promise.resolve(null),
	// 			prevTimeParams.from ? getAlertCount(prevTimeParams) : Promise.resolve(null),
	// 		]);
	//
	// 		// OLD CODE START — #96: a failure blanked each section, which read as "no data"
	// 		// trafficSummary = summaryRes.status === 'fulfilled' ? summaryRes.value : null;
	// 		// bandwidthData = bandwidthRes.status === 'fulfilled' ? bandwidthRes.value.series : [];
	// 		// protocols = protocolsRes.status === 'fulfilled' ? protocolsRes.value.protocols : [];
	// 		// services = protocolsRes.status === 'fulfilled' ? protocolsRes.value.services : [];
	// 		// OLD CODE END
	// 		if (summaryRes.status === 'fulfilled') trafficSummary = summaryRes.value;
	// 		if (bandwidthRes.status === 'fulfilled') bandwidthData = bandwidthRes.value.series;
	// 		if (protocolsRes.status === 'fulfilled') {
	// 			protocols = protocolsRes.value.protocols;
	// 			services = protocolsRes.value.services;
	// 		}
	// 		summaryFailed = summaryRes.status === 'rejected';
	// 		bandwidthFailed = bandwidthRes.status === 'rejected';
	// 		protocolsFailed = protocolsRes.status === 'rejected';
	// 		topTalkers = talkersRes.status === 'fulfilled' ? talkersRes.value.top_talkers : [];
	// 		// OLD CODE START — a failed refresh cleared the last count and the card read '--'
	// 		// alertCount = alertCountRes.status === 'fulfilled' ? alertCountRes.value : null;
	// 		// OLD CODE END
	// 		if (alertCountRes.status === 'fulfilled') alertCount = alertCountRes.value;
	// 		alertCountFailed = alertCountRes.status === 'rejected';
	// 		recentAlerts = alertsRes.status === 'fulfilled' ? alertsRes.value.alerts : [];
	// 		systemHealth = healthRes.status === 'fulfilled' ? healthRes.value : null;
	// 		systemHealthFailed = healthRes.status === 'rejected';
	// 		// OLD CODE START — #96: see above
	// 		// categories = categoriesRes.status === 'fulfilled' ? categoriesRes.value.categories : [];
	// 		// OLD CODE END
	// 		if (categoriesRes.status === 'fulfilled') categories = categoriesRes.value.categories;
	// 		categoriesFailed = categoriesRes.status === 'rejected';
	// 		// OLD CODE START — #96: see above
	// 		// deviceCount = deviceCountRes.status === 'fulfilled' ? deviceCountRes.value.count : 0;
	// 		// OLD CODE END
	// 		if (deviceCountRes.status === 'fulfilled') deviceCount = deviceCountRes.value.count;
	// 		deviceCountFailed = deviceCountRes.status === 'rejected';
	// 		prevTrafficSummary = prevSummaryRes.status === 'fulfilled' ? prevSummaryRes.value : null;
	// 		prevAlertCount = prevAlertCountRes.status === 'fulfilled' ? prevAlertCountRes.value : null;
	//
	// 		// Fetch smart alerts + top devices in parallel (non-blocking)
	// 		Promise.allSettled([
	// 			getSmartAlerts({ ...timeParams, limit: 10 }),
	// 			getSmartAlertSummary(timeParams),
	// 			// OLD CODE START — the top 5 only; the device cards need every device's traffic
	// 			// getDevices({ ...timeParams, sort: 'bytes', order: 'desc', limit: 5 }),
	// 			// OLD CODE END
	// 			getDevices({ ...timeParams, sort: 'bytes', order: 'desc', limit: DEVICE_LIST_LIMIT }),
	// 		]).then(([smartRes, summaryRes, devicesRes]) => {
	// 			smartAlerts = smartRes.status === 'fulfilled' ? smartRes.value.alerts : [];
	// 			smartAlertsFailed = smartRes.status === 'rejected';
	// 			smartAlertSummary = summaryRes.status === 'fulfilled' ? summaryRes.value : null;
	// 			// OLD CODE START — #96: a failure read as "No device data available"
	// 			// topDevices = devicesRes.status === 'fulfilled' ? devicesRes.value.devices : [];
	// 			// OLD CODE END
	// 			if (devicesRes.status === 'fulfilled') {
	// 				topDevices = devicesRes.value.devices;
	// 				deviceListFrom = devicesRes.value.from;
	// 			}
	// 			topDevicesFailed = devicesRes.status === 'rejected';
	// 		});
	//
	// 		lastUpdated = new Date().toLocaleTimeString();
	//
	// 		// Check if all core fetches failed (daemon unreachable)
	// 		const coreFetches = [summaryRes, bandwidthRes, protocolsRes, talkersRes, alertCountRes, alertsRes, healthRes];
	// 		const allFailed = coreFetches.every((r) => r.status === 'rejected');
	// 		if (allFailed) {
	// 			error = true;
	// 		}
	// 	} catch {
	// 		error = true;
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	//
	// /**
	//  * Handle filter bar changes. Updates active filters and re-fetches data.
	//  */
	// function handleFilterChange(filters: FilterState) {
	// 	activeFilters = filters;
	// 	// #96: the last range's figures must not stand in for this range if its load fails
	// 	trafficSummary = null;
	// 	prevTrafficSummary = null;
	// 	bandwidthData = [];
	// 	protocols = [];
	// 	services = [];
	// 	categories = [];
	// 	deviceCount = null;
	// 	alertCount = null;
	// 	topDevices = [];
	// 	deviceListFrom = null;
	// 	fetchAllData();
	// }
	//
	// // Auto-refresh effect
	// $effect(() => {
	// 	fetchAllData();
	//
	// 	if (autoRefresh) {
	// 		const interval = setInterval(fetchAllData, 30_000);
	// 		return () => clearInterval(interval);
	// 	}
	// });
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Formatting helpers
	// ---------------------------------------------------------------------------

	/** Axis label: the hour within a day, the date across days. */
	function axisLabel(t: number | string): string {
		const d = new Date(t);
		return span.hours <= 24
			? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
			: d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
	}

	// OLD CODE: /** One hourly bucket: "21:00", or "3 Nov 21:00" across days. */ (NET-249: buckets scale with the range)
	/** One bucket's start: "21:05", or "3 Nov 21:00" across days. */
	function pointLabel(t: number | string): string {
		const time = new Date(t).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
		return span.hours <= 24 ? time : `${axisLabel(t)} ${time}`;
	}

	// ---------------------------------------------------------------------------
	// KPIs and trend indicators (compare current vs previous period)
	// ---------------------------------------------------------------------------

	// OLD CODE START — NET-228 (audit TRF-6): the window ending now, still filling in, against the complete one before it
	// let bandwidthTrend = $derived(
	// 	trafficSummary && prevTrafficSummary
	// 		? trendPercent(trafficSummary.total_bytes, prevTrafficSummary.total_bytes)
	// 		: NO_TREND
	// );
	//
	// let connectionTrend = $derived(
	// 	trafficSummary && prevTrafficSummary
	// 		? trendPercent(trafficSummary.connection_count, prevTrafficSummary.connection_count)
	// 		: NO_TREND
	// );
	//
	// let alertTrend = $derived(
	// 	alertCount && prevAlertCount ? trendPercent(alertCount.counts.total, prevAlertCount.counts.total) : NO_TREND,
	// );
	// OLD CODE END
	/** The newer window against the older one, or why not: loading (NO_TREND), failed, or not enough data */
	function halvesTrend(points: SlotValue[] | null, failedReq: boolean, zeroIsUnknown = false) {
		if (failedReq) return COMPARE_FAILED;
		if (!points || !trendWin) return NO_TREND;
		const h = compareHalves(points, trendWin, zeroIsUnknown);
		return h === 'not_enough_data' ? NOT_ENOUGH : trendPercent(h.newer, h.older);
	}
	const trafficSlots = (value: (p: BandwidthPoint) => number): SlotValue[] | null =>
		trendTraffic && trendTraffic.map((p) => ({ timestamp: p.timestamp, value: value(p), connections: p.connections }));

	let bandwidthTrend = $derived(halvesTrend(trafficSlots((p) => p.total_bytes), !!failed.trendTraffic));
	let connectionTrend = $derived(halvesTrend(trafficSlots((p) => p.connections), !!failed.trendTraffic));
	// alerts read the connections' coverage by slot; an alert half of 0 can be Suricata stopped, so it isn't "new"
	// OLD CODE START — review D1: the join moved to withCoverage, which the category page shares
	// let alertTrend = $derived.by(() => {
	// 	const conns = new Map((trendTraffic ?? []).map((p) => [Date.parse(p.timestamp), p.connections]));
	// 	const slots = trendAlerts && trendAlerts.map((b) => ({
	// 		timestamp: b.timestamp,
	// 		value: b.high + b.medium + b.low + (b.info ?? 0),
	// 		connections: conns.get(Date.parse(b.timestamp)) ?? 0,
	// 	}));
	// 	return halvesTrend(trendTraffic && slots, !!(failed.trendAlerts || failed.trendTraffic), true);
	// });
	// OLD CODE END
	let alertTrend = $derived(
		halvesTrend(
			trendTraffic && trendAlerts && withCoverage(trendAlerts, (b) => b.high + b.medium + b.low + (b.info ?? 0), trendTraffic),
			!!(failed.trendAlerts || failed.trendTraffic),
			true,
		),
	);
	/** Where the compared data ends (the newest minutes are still arriving) */
	let trendUpTo = $derived(trendWin ? chartTime(Date.parse(trendWin.to), span.hours) : undefined);
	let trafficCompared = $derived(!!trendTraffic || !!failed.trendTraffic);
	let alertsCompared = $derived((!!trendAlerts && !!trendTraffic) || !!failed.trendAlerts || !!failed.trendTraffic);

	/**
	 * Bandwidth and Connections open the conn records behind the summary on screen: its window and the
	 * sources it left out (NET-160 slice 2b-1). Only a card with no number links by range alone.
	 */
	const trafficHref = $derived(trafficSummary ? connLogsHref(trafficSummary, range) : `/logs?range=${range}`);
	const bandwidthValue = $derived(trafficSummary ? formatBytes(trafficSummary.total_bytes).split(' ') : null);
	// OLD CODE START — NET-226: the originator's bytes were "up", so a port forward's answers read as download
	// // orig_bytes is what the side that opened the connection sent (usually a LAN device): up
	// ? `↓ ${formatBytes(trafficSummary.resp_bytes)} down · ↑ ${formatBytes(trafficSummary.orig_bytes)} up`
	// OLD CODE END
	const bandwidthSub = $derived(
		failed.summary
			? loadFailed('traffic totals', trafficSummary !== null)
			: trafficSummary
				? upDownLocal(trafficSummary, formatBytes)
				: 'Loading…',
	);
	const connectionsSub = $derived(
		failed.summary
			? loadFailed('connection totals', trafficSummary !== null)
			: trafficSummary
				? `Top protocol: ${trafficSummary.top_protocol}`
				: 'Loading…',
	);
	/** NET-228 (audit B5): a zero count is "can't tell" unless current data is arriving */
	const zeroAlerts = $derived(nothingFound('No counted rule matches in this period', systemHealth, !!failed.health));
	// OLD CODE START — NET-228: a zero read "0 high, 0 med, 0 low" with every sensor stopped
	// const alertsSub = $derived(
	// 	alertCountFailed
	// 		? loadFailed('the alert count', alertCount !== null)
	// 		: alertCount
	// 			// OLD CODE: ? `${alertCount.counts.high} high, ${alertCount.counts.medium} med, ${alertCount.counts.low} low` (NET-192 PR 4: "9000 high", no separators)
	// 			? `${fmt(alertCount.counts.high)} high, ${fmt(alertCount.counts.medium)} med, ${fmt(alertCount.counts.low)} low`
	// 			: 'Loading…',
	// );
	// OLD CODE END
	const alertsSub = $derived(
		alertCountFailed
			? loadFailed('the alert count', alertCount !== null)
			: !alertCount
				? 'Loading…'
				: alertCount.counts.total === 0
					? `${zeroAlerts.title} · ${zeroAlerts.detail}`
					: `${fmt(alertCount.counts.high)} high, ${fmt(alertCount.counts.medium)} med, ${fmt(alertCount.counts.low)} low`,
	);
	// NET-225: post-NAT, every device's IPv4 traffic carries the router's address; the capture health reply names the mode
	const bridgeMode = $derived(captureHealth?.mode === 'bridge');
	// OLD CODE: ? 'Devices seen on the network' in every mode (NET-225)
	const devicesSub = $derived(
		failed.deviceCount
			? loadFailed('the device count', deviceCount !== null)
			: deviceCount !== null
				? bridgeMode
					? "In bridge mode devices share the router's IPv4 address"
					: 'Devices seen on the network'
				: 'Loading…',
	);

	// ---------------------------------------------------------------------------
	// Cards
	// ---------------------------------------------------------------------------

	/** The busiest bucket, or -1 when the window carried no traffic. */
	const busiest = $derived(
		bandwidthData.reduce((best, p, i) => (p.total_bytes > (bandwidthData[best]?.total_bytes ?? 0) ? i : best), -1),
	);
	// OLD CODE START — NET-226: down/up were the responder's/originator's bytes, local traffic included
	// { key: 'down', label: 'Downloaded', colour: 1, points: bandwidthData.map((p) => ({ t: p.timestamp, v: p.resp_bytes })) },
	// { key: 'up', label: 'Uploaded', colour: 2, points: bandwidthData.map((p) => ({ t: p.timestamp, v: p.orig_bytes })) },
	// return p ? `${pointLabel(p.timestamp)} · ↓ ${formatBytes(p.resp_bytes)} · ↑ ${formatBytes(p.orig_bytes)}` : '';
	// OLD CODE END
	const bandwidthSeries = $derived<AreaSeries[]>([
		{ key: 'down', label: 'Downloaded', colour: 1, points: bandwidthData.map((p) => ({ t: p.timestamp, v: p.download_bytes })) },
		{ key: 'up', label: 'Uploaded', colour: 2, points: bandwidthData.map((p) => ({ t: p.timestamp, v: p.upload_bytes })) },
		{ key: 'local', label: 'On your network', colour: 3, points: bandwidthData.map((p) => ({ t: p.timestamp, v: p.local_bytes })) },
	]);
	const bandwidthTip = (i: number) => {
		const p = bandwidthData[i];
		return p ? `${pointLabel(p.timestamp)} · ${upDownLocal(p, formatBytes, false)}` : '';
	};
	const busiestText = $derived(
		busiest >= 0
			? `busiest at ${pointLabel(bandwidthData[busiest].timestamp)}, with ${formatBytes(bandwidthData[busiest].total_bytes)}`
			: 'no traffic',
	);

	const protocolItems = $derived(
		protocols.map((p) => ({ key: p.name || 'unknown', label: (p.name || 'unknown').toUpperCase(), value: p.count })),
	);
	const protocolTotal = $derived(protocols.reduce((s, p) => s + p.count, 0));
	// #20: "unknown" is connections Zeek couldn't identify, not missing data
	// OLD CODE: const serviceLabel = (name: string) => (!name || name === 'unknown' ? 'Unidentified' : name.toUpperCase()); (NET-249: shared with the moment page, in utils/drilldown.ts)
	// OLD CODE START — NET-219: the Unidentified bar counted one-way connections and ICMP too, so it led the list
	// const serviceItems = $derived(
	// 	services.slice(0, TOP_SERVICES).map((s, i) => ({
	// 		key: `${s.name}-${i}`,
	// 		label: serviceLabel(s.name),
	// 		value: s.count,
	// 		display: formatNumber(s.count),
	// 	})),
	// );
	// OLD CODE END
	// The Unidentified bar holds only two-way conversations; re-sorted, since it is smaller than `unknown`
	const serviceItems = $derived(
		services
			// only the daemon's own `unknown` bucket is split (ts review #3: an empty name is a different bucket)
			.map((s) => ({ name: s.name, count: s.name === 'unknown' && unidentified ? unidentified.conversations : s.count }))
			.filter((s) => s.count > 0)
			.sort((a, b) => b.count - a.count)
			.slice(0, TOP_SERVICES)
			.map((s, i) => ({
				key: `${s.name}-${i}`,
				label: serviceLabel(s.name),
				value: s.count,
				display: formatNumber(s.count),
			})),
	);
	/** What the bars leave out of `unknown` (NET-219); empty when there is nothing to say */
	const notInBars = $derived.by(() => {
		if (!unidentified) return '';
		const { one_way: oneWay, icmp } = unidentified;
		const clauses = [
			// one name for one thing (the bar says Unidentified); Zeek logs ICMP per exchange, not per message (ts review #4)
			oneWay > 0 ? `${formatNumber(oneWay)} unidentified ${oneWay === 1 ? 'connection' : 'connections'} with no data sent in at least one direction` : '',
			icmp > 0 ? `${formatNumber(icmp)} ICMP ${icmp === 1 ? 'exchange' : 'exchanges'} (pings and network notices)` : '',
		].filter(Boolean);
		return clauses.length > 0 ? `Not in the bars: ${clauses.join(', and ')}.` : '';
	});

	// The bars cover only connections to internet services, not all traffic
	const categoryItems = $derived(
		categories.map((cat) => ({
			key: cat.name,
			label: cat.label,
			value: cat.total_bytes,
			display: formatBytes(cat.total_bytes),
			href: '/traffic/' + cat.name,
		})),
	);

	const deviceItems = $derived(
		topDevices.slice(0, TOP_DEVICES).map((d) => ({
			key: d.ip,
			// OLD CODE: name: d.unifi_name || d.hostname || d.ip, (NET-200: the owner's name first, and their picture)
			name: d.custom_name || d.unifi_name || d.hostname || d.ip,
			ip: d.ip,
			category: d.category,
			picture: d.picture,
			icon: d.icon,
			value: d.total_bytes,
			display: formatBytes(d.total_bytes),
			href: `/devices/${encodeURIComponent(d.ip)}`,
		})),
	);

	// The summary hides informational alerts, so "to review" can be below the total; it says so.
	// #96: with both counts failed it would read "0 to review", so it is left out.
	// OLD CODE START — 2026-11-06 (O9): with the summary failed, every alert (informational
	// included) was shown as "to review"
	// const toReview = $derived(
	// 	smartAlertSummary || alertCount
	// 		? ` · ${formatNumber(smartAlertSummary?.total_events ?? alertCount?.counts?.total ?? 0)} to review${
	// 				smartAlertSummary?.informational_events
	// 					? ` · ${formatNumber(smartAlertSummary.informational_events)} informational`
	// 					: ''
	// 			}`
	// 		: '',
	// );
	// OLD CODE END
	// OLD CODE: ` · ${formatNumber(smartAlertSummary.informational_events)} informational` (NET-209: it also holds context categories and blocklist hits devices did not start)
	// Only the summary knows what is left to review, so without it the count is left out
	const toReview = $derived(
		smartAlertSummary
			? ` · ${formatNumber(smartAlertSummary.total_events)} to review${
					smartAlertSummary.informational_events
						? ` · ${formatNumber(smartAlertSummary.informational_events)} not counted`
						: ''
				}`
			: '',
	);
	/** Smart groups hide context and suppressed alerts, so with alerts stored but no group it says "nothing to review" */
	const noGroups = $derived(
		alertCount && alertCount.counts.total > 0
			? nothingFound('No alert groups to review in this period', systemHealth, !!failed.health, "Can't tell if anything needs review")
			: zeroAlerts,
	);
	const gaugeAria = $derived(
		alertCount
			? `${alertCount.counts.total.toLocaleString('en-GB')} alerts in the ${windowText}: ${fmt(alertCount.counts.high)} high, ${fmt(alertCount.counts.medium)} medium, ${fmt(alertCount.counts.low)} low`
			: '',
	);

	// System health moved into the pipeline: the System and OpenSearch stages
	const stages = $derived([
		captureStage(captureHealth, !!failed.capture),
		packetsStage(captureStats, !!failed.captureStats),
		systemStage(systemHealth, !!failed.health),
		openSearchStage(systemHealth, !!failed.health),
		// F2: the newest record's age and the sensors, so stopped ingestion can't read healthy
		dataStage(systemHealth, !!failed.health),
	]);
</script>

<svelte:head>
	<title>Dashboard | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Network overview</h1>
		<p class="page-sub">Traffic, alerts and capture health · {windowText}</p>
	</div>
	<div class="head-actions">
		<Pills options={RANGE_OPTIONS} bind:value={range} onchange={changeRange} ariaLabel="Time range" />
		<!-- OLD CODE START — NET-192 PR 4: this button, now AutoRefreshButton so every page has it
		<button
			class="btn"
			type="button"
			onclick={() => (autoRefresh = !autoRefresh)}
			title={autoRefresh ? 'Refreshes every 30 s' : 'Auto-refresh is paused'}
		>
			<Icon name={autoRefresh ? 'refresh' : 'pause'} />{autoRefresh ? 'Auto' : 'Paused'}
		</button>
		OLD CODE END -->
		<AutoRefreshButton on={autoRefresh} seconds={AUTO_REFRESH_MS / 1000} ontoggle={() => (autoRefresh = !autoRefresh)} />
	</div>
</div>

{#if error}
	<div class="notice is-error" role="alert">
		<Icon name="warn" /><span>Unable to reach the monitoring daemon. Check that the NetTap daemon container is running.</span>
	</div>
{:else if systemHealth && !systemHealth.opensearch_reachable}
	<div class="notice is-warn" role="status">
		<Icon name="warn" /><span>OpenSearch is not reachable. The daemon is running but cannot connect to OpenSearch. Traffic data will be unavailable until the connection is restored.</span>
	</div>
<!-- OLD CODE START — #96: a failed traffic request would read as "No traffic data yet"
{:else if !loading && systemHealth?.opensearch_reachable && !trafficSummary && bandwidthData.length === 0}
OLD CODE END -->
<!-- OLD CODE START — a loaded summary is never null, so this never showed, even with 0 connections
{:else if !loading && systemHealth?.opensearch_reachable && !summaryFailed && !bandwidthFailed && !trafficSummary && bandwidthData.length === 0}
OLD CODE END -->
{:else if !loading && systemHealth?.opensearch_reachable && !failed.summary && trafficSummary?.connection_count === 0}
	<div class="notice" role="status">
		<Icon name="empty" /><span>No traffic data yet for this time range. OpenSearch is connected but no network connections have been logged in it. Traffic will appear once Zeek and Suricata are capturing.</span>
	</div>
{/if}

{#snippet newToday()}
	<div><span class="chip is-ok">{newDeviceCount} new today</span></div>
{/snippet}

{#snippet staleNote(what: string)}
	<p class="notice is-warn stale" role="status"><Icon name="warn" /><span>{loadFailed(what, true)}</span></p>
{/snippet}

<div class="grid">
	<KpiCard
		class="c-3"
		label="Bandwidth"
		icon="bandwidth"
		href={trafficHref}
		title={trafficSummary ? 'Opens the connections this total is summed from' : undefined}
		value={bandwidthValue?.[0] ?? '—'}
		unit={bandwidthValue?.[1]}
		delta={kpiDelta(bandwidthTrend)}
		{...kpiWindow(trafficCompared, bandwidthTrend, span.window, span.previous, trendUpTo)}
		sub={bandwidthSub}
	/>
	<!-- OLD CODE: href={trafficHref} (section D: the link carries the figure clicked; Bandwidth, a byte sum, does not) -->
	<KpiCard
		class="c-3"
		label="Connections"
		icon="connections"
		href={withCount(trafficHref, trafficSummary?.connection_count)}
		value={trafficSummary ? formatNumber(trafficSummary.connection_count) : '—'}
		delta={kpiDelta(connectionTrend)}
		{...kpiWindow(trafficCompared, connectionTrend, span.window, span.previous, trendUpTo)}
		sub={connectionsSub}
	/>
	<!-- OLD CODE: href={alertCount ? `/alerts?${windowQuery(alertCount, range)}` : `/alerts?range=${range}`} (section D: the window's link carries the figure clicked) -->
	<KpiCard
		class="c-3"
		label="Alerts"
		icon="alerts"
		href={alertCount ? withCount(`/alerts?${windowQuery(alertCount, range)}`, alertCount.counts.total) : `/alerts?range=${range}`}
		value={alertCount ? formatNumber(alertCount.counts.total) : '—'}
		delta={kpiDelta(alertTrend, true)}
		{...kpiWindow(alertsCompared, alertTrend, span.window, span.previous, trendUpTo)}
		sub={alertsSub}
	/>
	<!-- OLD CODE START — NET-160 slice 2b-3: the Devices card opened /iot, which counts something else;
	     it opens the All devices list over the card's own window -->
	<!-- href="/iot" -->
	<!-- OLD CODE END -->
	<!-- OLD CODE: href={deviceCountReply ? `/devices?view=all&${windowQuery(deviceCountReply, range)}` : `/devices?view=all&range=${range}`} (section D: the window's link carries the figure clicked) -->
	<KpiCard
		class="c-3"
		label="Devices"
		icon="devices"
		href={deviceCountReply ? withCount(`/devices?view=all&${windowQuery(deviceCountReply, range)}`, deviceCountReply.count) : `/devices?view=all&range=${range}`}
		value={deviceCount !== null ? formatNumber(deviceCount) : '—'}
		note={span.window}
		sub={devicesSub}
		foot={newDeviceCount && newDeviceCount > 0 ? newToday : undefined}
	/>

	<!-- OLD CODE: sub="Bytes per hour · …" (NET-249: the bucket scales with the range) -->
	<Card title="Bandwidth over time" sub="Bytes per {span.bucketWords} · {windowText}{busiest >= 0 ? ` · ${busiestText}` : ''}" hero col class="c-8">
		{#snippet actions()}
			<ul class="legend">
				<li><span class="sw line c-d1"></span>Downloaded</li>
				<li><span class="sw line c-d2"></span>Uploaded</li>
				<li><span class="sw line c-d3"></span>On your network</li>
			</ul>
		{/snippet}
		{#if bandwidthData.length > 0}
			<AreaChart
				series={bandwidthSeries}
				bytes
				formatX={axisLabel}
				formatY={formatBytesShort}
				formatTip={bandwidthTip}
				highlightIndex={busiest >= 0 ? busiest : undefined}
				ariaLabel="Bandwidth over the {windowText}: {busiestText}"
				height={300}
				onpick={(i, j) => goto(momentHref(bandwidth, i, j, range))}
			/>
			<p class="card-sub pick-hint">Click a point or drag across the chart to see that moment.</p>
			{#if failed.bandwidth}{@render staleNote('bandwidth over time')}{/if}
		{:else if failed.bandwidth}
			<CardState state="error" title={loadFailed('bandwidth over time')} message="Check that the daemon is running on the System page, then try again." onaction={retry} />
		{:else if loading}
			<CardState state="loading" title="Loading bandwidth over time" />
		{:else}
			<CardState state="empty" title="No bandwidth data for this window" message="Traffic appears here once Zeek logs connections." />
		{/if}
	</Card>

	<Card title="Network protocols" sub="Connections by protocol · {windowText}" class="c-4">
		{#if protocolTotal > 0 || services.length > 0}
			{#if failed.protocols}{@render staleNote('network protocols')}{/if}
			<Donut
				items={protocolItems}
				centreLabel="connections"
				formatValue={formatNumber}
				ariaLabel="Connections by transport protocol: {protocolItems.slice(0, 3).map((p) => `${p.label} ${formatNumber(p.value)}`).join(', ')}"
			/>
			<!-- OLD CODE START — NET-219: the bars only; the note about what they leave out is new
			{#if serviceItems.length > 0}
				<p class="eyebrow">Application layer</p>
				<BarList items={serviceItems} />
			{/if}
			OLD CODE END -->
			{#if serviceItems.length > 0 || notInBars}
				<p class="eyebrow">Application layer</p>
				{#if serviceItems.length > 0}<BarList items={serviceItems} />{/if}
				{#if notInBars}<p class="card-sub not-in-bars">{notInBars}</p>{/if}
			{/if}
		{:else if failed.protocols}
			<CardState state="error" title={loadFailed('network protocols')} message="Check that the daemon is running on the System page, then try again." onaction={retry} />
		{:else if loading}
			<CardState state="loading" title="Loading network protocols" />
		{:else}
			<CardState state="empty" title="No protocol data for this window" message="Protocols appear here once Zeek logs connections." />
		{/if}
	</Card>

	<Card title="Traffic categories" sub="Bytes to internet services · {windowText} · local traffic isn't counted" class="c-4">
		{#if categories.length > 0}
			{#if failed.categories}{@render staleNote('traffic categories')}{/if}
			<BarList items={categoryItems} />
		{:else if failed.categories}
			<CardState state="error" title={loadFailed('traffic categories')} message="Check that the daemon is running on the System page, then try again." onaction={retry} />
		{:else if loading}
			<CardState state="loading" title="Loading traffic categories" />
		{:else}
			<CardState state="empty" title="No category data yet" message="Traffic will appear once Zeek captures ASN-tagged connections." />
		{/if}
	</Card>

	<Card title="Top devices" sub="By bytes · {windowText}" class="c-4">
		{#snippet actions()}<a class="link" href="/devices">View all devices</a>{/snippet}
		{#if deviceItems.length > 0}
			{#if failed.devices}{@render staleNote('top devices')}{/if}
			<DeviceList items={deviceItems} />
		{:else if failed.devices}
			<CardState state="error" title={loadFailed('top devices')} message="Check that the daemon is running on the System page, then try again." onaction={retry} />
		{:else if loading}
			<CardState state="loading" title="Loading top devices" />
		{:else if bridgeMode}
			<!-- NET-225: the message below promised devices that inline bridge mode never shows -->
			<CardState state="empty" title="No devices to show in inline bridge mode" message={BRIDGE_NO_DEVICES} />
		{:else}
			<CardState state="empty" title="No devices seen in this window" message="Devices appear here once NetTap sees their traffic." />
		{/if}
	</Card>

	<Card title="Alert summary" sub="By severity · {windowText}{toReview}" class="c-4">
		{#if alertCount}
			{#if alertCountFailed}{@render staleNote('the severity summary')}{/if}
			<SeverityGauge buckets={severityBuckets(alertCount.counts)} total={alertCount.counts.total} ariaLabel={gaugeAria} />
		{:else if alertCountFailed}
			<CardState state="error" title="Couldn't load the severity summary: the request failed." message="Check that the daemon is running on the System page, then try again." onaction={retry} />
		{:else}
			<CardState state="loading" title="Loading the severity summary" />
		{/if}
		<div class="groups">
			{#if smartAlerts.length > 0}
				{#if smartAlertSummary && Object.keys(smartAlertSummary.categories ?? {}).length > 0}
					<div class="chips">
						{#each Object.entries(smartAlertSummary.categories ?? {}) as [key, cat] (key)}
							<span class="chip">{cat.groups} {cat.label}</span>
						{/each}
					</div>
				{/if}
				<div class="top-cats">
					{#each smartAlerts.slice(0, TOP_ALERT_GROUPS) as sa, i (`sa-${sa.signature_id}-${i}`)}
						<!-- OLD CODE: {@const exact = smartWindow ? smartAlertHref(sa.key, smartWindow) : null} (NET-191: an activity group opens the activity list) -->
						{@const exact = smartWindow ? smartAlertHref(sa.key, smartWindow, undefined, sa.activity) : null}
						<!-- OLD CODE: <a class="top-cat" href="/threats"> (slice 2b-1: the ×N opens the alerts it counts) -->
						<!-- OLD CODE: href={exact ?? undefined} (section D: the ×N link carries its figure) -->
						<svelte:element this={exact ? 'a' : 'div'} class="top-cat" href={exact ? withCount(exact, sa.count) : undefined} title={exact ? undefined : NO_EXACT_ALERT_LIST}>
							<span class="group-name"><SeverityPill level={smartLevel(sa.severity)} /><span>{sa.category_label}</span></span>
							<b class="num">&times;{formatNumber(sa.count)}</b>
							<p class="sig">{sa.signature}</p>
						</svelte:element>
					{/each}
				</div>
				<a href="/threats" class="link">View threat intelligence</a>
			{:else if failed.smart}
				<p class="dim">Couldn't load the alert summary: the request failed.</p>
				<a href="/alerts" class="link">View raw alerts</a>
			<!-- OLD CODE START — NET-228: "detected" with no sign of whether data was arriving
			{:else if !loading}
				<p class="dim">No actionable alerts detected.</p>
				<a href="/alerts" class="link">View raw alerts</a>
			OLD CODE END -->
			{:else if !loading}
				<p class={noGroups.trusted ? 'dim' : 'notice is-warn'} role="status">
					{#if !noGroups.trusted}<Icon name="warn" />{/if}<span>{noGroups.title} · {noGroups.detail}</span>
				</p>
				<a href="/alerts" class="link">View raw alerts</a>
			{/if}
		</div>
	</Card>

	<!-- OLD CODE: sub="Each stage at the last refresh" (S9: the packet counts' scope wasn't stated) -->
	<!-- OLD CODE: sub="Each stage at the last refresh · packets: {LOSS_SCOPE.toLowerCase()}" (NET-167: packets cover the last hour, not since the counters reset) -->
	<Card
		title="Capture pipeline"
		sub="Each stage at the last refresh · packets: up to the last 60 minutes on {captureStats?.loss_window.interface || 'the capture interface'}"
		class="c-12"
	>
		{#snippet actions()}<a class="link" href="/infrastructure">View infrastructure</a>{/snippet}
		<Pipeline {stages} />
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.stale { margin-top: var(--sp-3); }
	.pick-hint { margin-top: var(--sp-2); }
	.eyebrow { margin: var(--sp-4) 0 var(--sp-2); }
	.not-in-bars { margin-top: var(--sp-3); }
	.groups { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-3); margin-top: var(--sp-4); }
	.groups .top-cats { align-self: stretch; margin-top: 0; }
	/* OLD CODE: a.top-cat { … } (slice 2b-1: a row with no exact list is a div, laid out the same) */
	.top-cat { text-decoration: none; color: inherit; border-radius: var(--r-md); padding: var(--sp-1) var(--sp-2); margin: 0 calc(var(--sp-2) * -1); }
	a.top-cat:hover { background: var(--row-hover); }
	.group-name { display: flex; align-items: center; gap: var(--sp-2); min-width: 0; }
</style>
