<script lang="ts">
	/**
	 * Alert Category Detail — Drill-down page for a single alert category.
	 *
	 * Features:
	 *   1. Back link, category title and description, time range
	 *   2. KPI row (unique sources, unique targets, affected devices)
	 *   3. Severity summary (sev-count tiles + gauge, from the category's own breakdown)
	 *   4. Sub-category bars (clickable filter) beside the alert volume chart
	 *   5. Two-column: affected devices + top signatures
	 *   6. MITRE ATT&CK techniques
	 *   7. Paginated, server-sorted alert table (pre-filtered to category) with the drawer column
	 */

	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	// OLD CODE START: import { ipHref, isLan } from '$lib/stores/lan'; — only the removed "Open device" link used them OLD CODE END
	import { onDestroy, untrack } from 'svelte';
	import {
		getAlertCategoryDetail,
		getAlertCategoryTimeline,
		getAlerts,
		formatNumber,
		// OLD CODE START — severity shows as SeverityPill now
		// severityLabel,
		// OLD CODE END
		suppressAlert,
		markFalsePositive,
		acknowledgeAlert,
	} from '$api/alerts';
	import type {
		CategoryDetailResponse,
		CategoryDetailDevice,
		CategoryTimelineResponse,
		MitreTechnique,
		Alert,
		AlertsListResponse,
		AlertSort,
	} from '$api/alerts';
	import IPAddress from '$components/IPAddress.svelte';
	// OLD CODE START — 2026-11-03 redesign: the drawer is the docked column beside the table
	// import DetailDrawer from '$components/DetailDrawer.svelte';
	// import AlertDrawerContent from '$components/drawer/content/AlertDrawerContent.svelte';
	// OLD CODE END
	// OLD CODE START — #146: the alert table sorts on the daemon now
	// import { TableSort, compareValues, severityRank } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	// OLD CODE START — 2026-11-03: the affected devices table is the shared DataTable, which sorts itself
	// import { TableSort } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import { severityBuckets, type SeverityLevel } from '$lib/utils/severity';
	// OLD CODE: import { alertsHrefForSignature, type DrillWindow } from '$lib/utils/drilldown'; (section D)
	// OLD CODE: import { alertsHrefForSignature, DRILL_RANGES, fmt, rangeWindow, startRange, withCount, type DrillWindow } from '$lib/utils/drilldown'; (NET-185: the URL's window)
	// OLD CODE: import { alertsHrefForSignature, customRange, DRILL_RANGES, fmt, rangeWindow, startRange, withCount, type DrillWindow } from '$lib/utils/drilldown'; (NET-249: picks)
	import {
		alertsHrefForSignature, bucketFor, customRange, DRILL_RANGES, fmt, linkedCount, pickedTotal, pickWindow, rangeWindow, startRange, withCount, type DrillWindow,
	} from '$lib/utils/drilldown';
	import { NARROW_HINT, narrowTo, pickedLine } from '$lib/utils/narrow-page';
	import { toTimeChart } from '$lib/utils/chart-pick';
	import { createLoadGuard, registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import SeverityGauge from '$lib/components/ui/charts/SeverityGauge.svelte';
	import AlertDetail from '../AlertDetail.svelte';
	import { alertLevel } from '../alert-view';
	import { formatTime } from '$lib/utils/time';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	// One range set across the app (NET-192 PR 4): 1h 6h 24h 7d 30d, as on Home. Live is the real-time page.
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES), with this page's ms beside it
	// const TIME_RANGES = [
	// 	// OLD CODE: { label: '15m', value: '15m', ms: 15 * 60 * 1000, words: 'last 15 minutes' }, (NET-192 PR 4)
	// 	{ label: '1h', value: '1h', ms: 60 * 60 * 1000, words: 'last hour' },
	// 	// OLD CODE: { label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000, words: 'last 4 hours' }, (NET-192 PR 4)
	// 	{ label: '6h', value: '6h', ms: 6 * 60 * 60 * 1000, words: 'last 6 hours' },
	// 	{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000, words: 'last 24 hours' },
	// 	{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000, words: 'last 7 days' },
	// 	{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000, words: 'last 30 days' },
	// ];
	// OLD CODE END
	const TIME_RANGES = DRILL_RANGES;

	// OLD CODE START — NET-249: the timeline asks for the owner's bucket table (drill below)
	// const INTERVAL_MAP: Record<string, string> = {
	// 	// OLD CODE: '15m': '1m', (NET-192 PR 4)
	// 	'1h': '5m',
	// 	// OLD CODE: '4h': '15m', (NET-192 PR 4)
	// 	'6h': '15m',
	// 	'24h': '1h',
	// 	'7d': '6h',
	// 	'30d': '12h',
	// };
	// OLD CODE END

	// OLD CODE START — 2026-11-03: bars use the system's data-1 (PLAN.md §4.1, bar lists keep one colour)
	// /** Rotating sub-category bar colors. */
	// const SUB_CAT_COLORS = [
	// 	'var(--blue)',
	// 	'var(--cyan)',
	// 	'var(--purple)',
	// 	'var(--teal)',
	// 	'var(--amber)',
	// 	'var(--green)',
	// 	'var(--orange)',
	// 	'var(--pink)',
	// ];
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let category = $derived(($page.params as Record<string, string>).category ?? '');
	// OLD CODE: let selectedRange = $state('24h'); (NET-195: Settings › Display's default, read where the range starts)
	// OLD CODE: let selectedRange = $state<string>(startRange('24h')); (NET-185: the window comes from the URL, as on the Suricata category page)
	const params = $derived($page.url.searchParams);
	/** The exact window a link brought (?from=&to=), shown as "Custom". */
	const custom = $derived(customRange(params.get('from'), params.get('to')));
	/** The URL's standard range (without one, the saved default, else 24h): a Custom window's links carry it for their words. */
	const baseRange = $derived(TIME_RANGES.find((r) => r.value === params.get('range')) ?? TIME_RANGES.find((r) => r.value === startRange('24h'))!);
	// OLD CODE START — NET-249: the owner's bucket table (DRILL_RANGES' bucket), not this page's own map
	// /** The timeline's bucket: for Custom, the one of the smallest standard range that covers it. */
	// const interval = $derived(
	// 	INTERVAL_MAP[(custom ? (TIME_RANGES.find((r) => r.hours >= custom.hours) ?? TIME_RANGES[TIME_RANGES.length - 1]) : baseRange).value] ?? '1h',
	// );
	// OLD CODE END
	/** The range whose bucket the timeline asks for: for Custom, `bucketFor`'s (NET-249). */
	const drill = $derived(custom ? bucketFor(Date.parse(custom.from), Date.parse(custom.to)) : baseRange);
	const interval = $derived(drill.bucket);
	/** The alerts a pick on the timeline carried (NET-249), compared with the narrowed chart's own total. */
	const picked = $derived(custom ? linkedCount(params.get('count')) : null);
	const view = $derived(`${category}|${baseRange.value}|${custom?.from ?? ''}|${custom?.to ?? ''}`);

	// Data
	let categoryData = $state<CategoryDetailResponse | null>(null);
	let timelineData = $state<CategoryTimelineResponse | null>(null);
	// #96: each request on its own; a failed one says so instead of "No alerts in <category>"
	let detailFailed = $state(false);
	let timelineFailed = $state(false);
	let alertsFailed = $state(false);
	let alerts = $state<Alert[]>([]);
	let loading = $state(true);

	// Pagination
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 25;

	// Sub-category filter
	let subCatFilter = $state<string | null>(null);

	// Sort state (alert table)
	// OLD CODE START — the Port column couldn't be sorted (design system: every column sorts)
	// type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip';
	// OLD CODE END
	type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip' | 'dest_port';
	// Each column's name on the daemon, which sorts every page (#146)
	const SERVER_SORT: Record<SortKey, AlertSort> = {
		timestamp: 'time', severity: 'severity', signature: 'signature', src_ip: 'source',
		dest_ip: 'destination', dest_port: 'dest_port',
	};

	// Affected Devices table: most alerts first
	const SEVERITY_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
	// OLD CODE START — 2026-11-03: the DataTable keeps its own sort (initialSort: count, descending)
	// const deviceSort = new TableSort<'ip' | 'count' | 'severity'>('count');
	// OLD CODE END
	let sortKey = $state<SortKey>('timestamp');
	let sortDir = $state<'asc' | 'desc'>('desc');

	// Detail drawer
	let drawerAlert = $state<Alert | null>(null);
	// OLD CODE START — the drawer's tabs became its collapsible sections
	// let drawerTab = $state('summary');
	// const ALERT_DRAWER_TABS = [
	// 	{ id: 'summary', label: 'Summary' },
	// 	{ id: 'related', label: 'Related events' },
	// 	{ id: 'raw', label: 'Raw JSON' },
	// ];
	// OLD CODE END

	// Auto-refresh
	let autoRefresh = $state(false);
	let actionError = $state('');
	let autoRefreshTimer: ReturnType<typeof setInterval> | null = null;

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let displayName = $derived(
		categoryData?.category?.label ??
		category.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
	);

	// OLD CODE START — 2026-11-03 redesign: category colours, emoji icons and hand-scaled bars are gone
	// (system tokens only, no emoji; BarList and AreaChart scale themselves)
	// let catColor = $derived(categoryData?.category?.color ?? 'blue');
	//
	// /** Resolve a color token to a CSS var, or pass through raw hex/rgb values. */
	// function catColorVar(color: string): string {
	// 	if (color === 'muted') return 'var(--text-muted)';
	// 	if (color.startsWith('#') || color.startsWith('rgb')) return color;
	// 	return `var(--${color})`;
	// }
	//
	// function catColorDimVar(color: string): string {
	// 	if (color === 'muted') return 'var(--bg-tertiary)';
	// 	if (color.startsWith('#') || color.startsWith('rgb')) return `${color}33`;
	// 	return `var(--${color}-dim)`;
	// }
	//
	// /** Map icon name from API to emoji — mirrors the hub page mapping. */
	// const ICON_EMOJI: Record<string, string> = {
	// 	'shield-alert': '\u{1F6E1}', 'shield': '\u{1F6E1}', 'upload-cloud': '\u{2601}', 'upload': '\u{2B06}',
	// 	'search': '\u{1F50D}', 'bug': '\u{1F41B}', 'gavel': '\u{2696}', 'alert-triangle': '\u{26A0}',
	// 	'alert': '\u{1F6A8}', 'warning': '\u{26A0}', 'key': '\u{1F511}', 'globe': '\u{1F310}',
	// 	'lock': '\u{1F512}', 'cpu': '\u{1F4BB}', 'zap': '\u{26A1}', 'eye': '\u{1F441}',
	// 	'eye-off': '\u{1F648}', 'info': '\u{2139}',
	// };
	//
	// function catIconEmoji(icon: string): string {
	// 	return ICON_EMOJI[icon] ?? '\u{2139}';
	// }
	//
	// let maxSubCount = $derived.by(() => {
	// 	if (!categoryData?.sub_categories?.length) return 1;
	// 	return Math.max(...categoryData.sub_categories.map((s) => s.count), 1);
	// });
	// OLD CODE END

	// OLD CODE START — #146: ordered only the page of rows it had; the daemon sorts every page now
	// let sortedAlerts = $derived.by(() => {
	// 	const list = [...alerts];
	// 	list.sort((a, b) => {
	// 		let cmp = 0;
	// 		switch (sortKey) {
	// 			case 'timestamp':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.timestamp || '').localeCompare(b.timestamp || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.timestamp || '', b.timestamp || '');
	// 				break;
	// 			case 'severity':
	// 				// OLD CODE START — Suricata's 1 is the most severe, so the first (descending) click put LOW on top
	// 				// cmp = (a.alert?.severity ?? 4) - (b.alert?.severity ?? 4);
	// 				// OLD CODE END
	// 				cmp = severityRank(a.alert?.severity) - severityRank(b.alert?.severity);
	// 				break;
	// 			case 'signature':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.alert?.signature || '').localeCompare(b.alert?.signature || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.alert?.signature || '', b.alert?.signature || '');
	// 				break;
	// 			case 'src_ip':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.src_ip || '').localeCompare(b.src_ip || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.src_ip || '', b.src_ip || '');
	// 				break;
	// 			case 'dest_ip':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.dest_ip || '').localeCompare(b.dest_ip || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.dest_ip || '', b.dest_ip || '');
	// 				break;
	// 			case 'dest_port':
	// 				cmp = compareValues(a.dest_port ?? -1, b.dest_port ?? -1);
	// 				break;
	// 		}
	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	// OLD CODE END
	// The daemon returns the rows in the table's order (#146)
	let sortedAlerts = $derived(alerts);

	// OLD CODE START — 2026-11-03: the AreaChart scales itself
	// // Timeline chart derived data
	// let chartHeight = 200;
	// let maxBucketTotal = $derived.by(() => {
	// 	if (!timelineData?.series?.length) return 1;
	// 	return Math.max(...timelineData.series.map((p) => p.total), 1);
	// });
	// OLD CODE END

	// OLD CODE: ?? TIME_RANGES[3]); (NET-192 PR 4: 15m and 4h dropped, 6h added: 24h is index 2)
	// OLD CODE: ?? TIME_RANGES[2] (NET-192 PR 4: the default by value, not by position)
	// OLD CODE: const range = $derived(TIME_RANGES.find((r) => r.value === selectedRange) ?? TIME_RANGES.find((r) => r.value === '24h')!); (NET-185)
	const range = $derived(custom ?? baseRange);
	const buckets = $derived(
		categoryData
			? severityBuckets({ total: categoryData.stats.total, ...categoryData.severity_breakdown })
			: [],
	);
	const series = $derived(timelineData?.series ?? []);
	const busiest = $derived(series.reduce((best, p, i) => (p.total > series[best].total ? i : best), 0));
	/** The timeline reply on screen, whole, when its bucket can be picked on; a failed request leaves none (NET-249) */
	const chart = $derived(
		timelineData
			? toTimeChart(
					timelineData,
					timelineData.series.map((p) => p.timestamp),
					timelineData.series.map((p) => p.total),
				)
			: null,
	);
	const countLine = $derived(pickedLine(picked, chart, { lead: 'This window now shows', one: 'alert', many: 'alerts' }));
	const fromRow = $derived(totalAlerts > 0 ? (currentPage - 1) * pageSize + 1 : 0);
	const toRow = $derived(Math.min(totalAlerts, fromRow + alerts.length - 1));

	// ---------------------------------------------------------------------------
	// Time helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = Date.now();
		// OLD CODE: || TIME_RANGES[3]; (NET-192 PR 4: 24h is index 2)
		// OLD CODE: || TIME_RANGES[2] (NET-192 PR 4: the default by value, not by position)
		// OLD CODE: const range = TIME_RANGES.find((r) => r.value === selectedRange) || TIME_RANGES.find((r) => r.value === '24h')!; (NET-185)
		if (custom) return { from: custom.from, to: custom.to };
		// OLD CODE START — NET-196: the shared list's hours and rangeWindow, not milliseconds
		// return {
		// 	from: new Date(now - range.ms).toISOString(),
		// 	to: new Date(now).toISOString(),
		// };
		// OLD CODE END
		// OLD CODE: return rangeWindow(range.hours, new Date(now)); (NET-185: the derived range)
		return rangeWindow(baseRange.hours, new Date(now));
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN.md §5.5: didn't report what loaded, and a slow older load could overwrite a newer one
	// async function fetchData(cat: string, range: string) {
	// 	if (!cat) return;
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	const interval = INTERVAL_MAP[range] ?? '1h';
	//
	// 	// OLD CODE START — #96: one failure blanked the page as "No alerts in <category>"
	// 	// try {
	// 	// 	const [detail, timeline, alertsResult] = await Promise.all([
	// 	// 		getAlertCategoryDetail(cat, { from, to }),
	// 	// 		getAlertCategoryTimeline(cat, { from, to, interval }),
	// 	// 		getAlerts({ from, to, page: 1, size: pageSize, category: cat }),
	// 	// 	]);
	// 	// 	categoryData = detail;
	// 	// 	timelineData = timeline;
	// 	// 	alerts = alertsResult.alerts;
	// 	// 	totalPages = alertsResult.total_pages;
	// 	// 	totalAlerts = alertsResult.total;
	// 	// 	currentPage = 1;
	// 	// } catch (err) {
	// 	// 	console.error('[alerts/category] fetchData error:', err);
	// 	// 	categoryData = null;
	// 	// 	timelineData = null;
	// 	// } finally {
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	const [detail, timeline, alertsResult] = await Promise.allSettled([
	// 		getAlertCategoryDetail(cat, { from, to }),
	// 		getAlertCategoryTimeline(cat, { from, to, interval }),
	// 		getAlerts({ from, to, page: 1, size: pageSize, category: cat, sub: subCatFilter ?? undefined, sort: SERVER_SORT[sortKey], order: sortDir }),
	// 	]);
	// 	categoryData = detail.status === 'fulfilled' ? detail.value : null;
	// 	detailFailed = detail.status === 'rejected';
	// 	timelineData = timeline.status === 'fulfilled' ? timeline.value : null;
	// 	timelineFailed = timeline.status === 'rejected';
	// 	alertsFailed = alertsResult.status === 'rejected';
	// 	// a failure clears the table: the rows on screen may be another category's or range's
	// 	alerts = alertsResult.status === 'fulfilled' ? alertsResult.value.alerts : [];
	// 	totalPages = alertsResult.status === 'fulfilled' ? alertsResult.value.total_pages : 0;
	// 	totalAlerts = alertsResult.status === 'fulfilled' ? alertsResult.value.total : 0;
	// 	currentPage = 1;
	// 	loading = false;
	// }
	//
	// async function fetchAlerts(pg: number = 1) {
	// 	alertsLoading = true;
	// 	const { from, to } = getTimeRange();
	// 	try {
	// 		const r = await getAlerts({ from, to, page: pg, size: pageSize, category, sub: subCatFilter ?? undefined, sort: SERVER_SORT[sortKey], order: sortDir });
	// 		alerts = r.alerts;
	// 		totalPages = r.total_pages;
	// 		totalAlerts = r.total;
	// 		currentPage = r.page;
	// 		alertsFailed = false;
	// 	} catch (err) {
	// 		console.error('[alerts/category] fetchAlerts error:', err);
	// 		alerts = [];
	// 		totalPages = 0;
	// 		alertsFailed = true;
	// 	} finally {
	// 		alertsLoading = false;
	// 	}
	// }
	// OLD CODE END

	function applyList(result: PromiseSettledResult<AlertsListResponse>, failedTotal: number) {
		alertsFailed = result.status === 'rejected';
		// a failure clears the table: the rows on screen may be another category's or range's
		alerts = result.status === 'fulfilled' ? result.value.alerts : [];
		totalPages = result.status === 'fulfilled' ? result.value.total_pages : 0;
		totalAlerts = result.status === 'fulfilled' ? result.value.total : failedTotal;
		if (result.status === 'fulfilled') currentPage = result.value.page;
	}

	// The list has its own generation too, so paging or sorting mid-refresh drops only the stale list
	const listGuard = createLoadGuard();
	/** The category and range on screen; a load for another one starts from page 1 and shows loading. */
	let shownKey = '';
	/** The window of the figures on screen (set when a load is applied, not while one is in flight). */
	// OLD CODE: let shownWindow = $state<DrillWindow>({ from: '', to: '' }); (NET-185: with the range words its links carry)
	let shownWindow = $state<DrillWindow & { range: string }>({ from: '', to: '', range: '24h' });

	async function loadAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const lg = listGuard.begin();
		const cat = category;
		if (!cat) return 'skipped';
		// OLD CODE: const key = `${cat}|${selectedRange}`; (NET-185)
		const key = view;
		const fresh = key !== shownKey;
		if (fresh) loading = true;
		const { from, to } = getTimeRange();
		// OLD CODE: const interval = INTERVAL_MAP[selectedRange] ?? '1h'; (NET-185: derived above)
		const base = baseRange.value;
		const pg = fresh ? 1 : currentPage;
		const listQuery = { from, to, page: pg, size: pageSize, category: cat, sub: subCatFilter ?? undefined, sort: SERVER_SORT[sortKey], order: sortDir };

		const [detail, timeline, alertsResult] = await Promise.allSettled([
			getAlertCategoryDetail(cat, { from, to }),
			getAlertCategoryTimeline(cat, { from, to, interval }),
			getAlerts(listQuery),
		]);
		if (!guard.current(g)) return 'skipped';
		categoryData = detail.status === 'fulfilled' ? detail.value : null;
		detailFailed = detail.status === 'rejected';
		timelineData = timeline.status === 'fulfilled' ? timeline.value : null;
		timelineFailed = timeline.status === 'rejected';
		if (listGuard.current(lg)) applyList(alertsResult, 0);
		shownKey = key;
		// OLD CODE: shownWindow = { from, to }; (NET-185)
		shownWindow = { from, to, range: base };
		loading = false;

		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const ok = [detail, timeline, alertsResult].filter((r) => r.status === 'fulfilled').length;
		// return ok === 3 ? 'ok' : ok === 0 ? 'failed' : 'partial';
		// OLD CODE END
		return outcome([detail, timeline, alertsResult]);
	}

	const refresh = registerPageRefresh(loadAll);

	async function fetchAlerts(pg: number = 1) {
		const lg = listGuard.begin();
		// OLD CODE: const { from, to } = getTimeRange(); (NET-185: a page, sort or sub-category moved the list to a new window, away from the figures above it)
		// the figures' own window until the next refresh; a view still loading has none yet
		const { from, to } = shownKey === view ? shownWindow : getTimeRange();
		const params = { from, to, page: pg, size: pageSize, category, sub: subCatFilter ?? undefined, sort: SERVER_SORT[sortKey], order: sortDir };
		const result = await getAlerts(params).then(
			(value): PromiseSettledResult<AlertsListResponse> => ({ status: 'fulfilled', value }),
			(reason): PromiseSettledResult<AlertsListResponse> => ({ status: 'rejected', reason }),
		);
		if (!listGuard.current(lg)) return;
		// the old fetchAlerts kept the total on failure
		applyList(result, totalAlerts);
	}

	// OLD CODE START — #146/#147: fetchData now reads the sort and sub-category, which would make
	// every header click reload the whole page from here as well
	// // Refetch when category or time range changes
	// $effect(() => {
	// 	const cat = category;
	// 	const range = selectedRange;
	// 	fetchData(cat, range);
	// });
	// OLD CODE END
	// Refetch when category or time range changes; a new category drops the old one's sub-category
	let loadedCategory = '';
	$effect(() => {
		const cat = category;
		// OLD CODE: const range = selectedRange; (NET-185: another window in the URL)
		const v = view;
		untrack(() => {
			if (cat !== loadedCategory) subCatFilter = null;
			loadedCategory = cat;
			// OLD CODE START — loads go through the page refresh contract now
			// fetchData(cat, range);
			// OLD CODE END
			// OLD CODE: void range; (NET-185)
			void v;
			refresh.run();
		});
	});

	/** A range pill: a rolling window ending now, so the link's exact window (Custom) goes (NET-185). */
	function pickRange(value: string) {
		if (value !== 'custom') void goto(`${$page.url.pathname}?range=${value}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	/**
	 * A pick on the timeline (NET-249): this page over the picked slots, with their alerts. The chart
	 * counts every sub-category, so the sub-category filter goes; the same window reloads only the list.
	 */
	function pick(i: number, j: number) {
		if (!chart) return;
		const win = pickWindow(chart, i, j);
		subCatFilter = null;
		if (custom && custom.from === win.from && custom.to === win.to) void fetchAlerts(1);
		void narrowTo($page.url, custom, win, baseRange.value, 'count', pickedTotal(chart, i, j));
	}

	// Auto-refresh
	$effect(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		if (autoRefresh) {
			// OLD CODE START — loads go through the page refresh contract now
			// autoRefreshTimer = setInterval(
			// 	() => fetchData(category, selectedRange),
			// 	30_000,
			// );
			// OLD CODE END
			autoRefreshTimer = setInterval(() => refresh.runIfIdle(), 30_000);
		}
		return () => {
			if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		};
	});

	onDestroy(() => {
		if (autoRefreshTimer) clearInterval(autoRefreshTimer);
		refresh.unregister();
		listGuard.invalidate();
	});

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — the DataTable owns the header buttons and reports the new sort (onsortchange)
	// function toggleSort(key: SortKey) {
	// 	if (sortKey === key) {
	// 		sortDir = sortDir === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		sortKey = key;
	// 		// OLD CODE START — severity is now a rank (higher = worse), so it starts descending like time
	// 		// sortDir = key === 'timestamp' ? 'desc' : 'asc';
	// 		// OLD CODE END
	// 		sortDir = key === 'timestamp' || key === 'severity' ? 'desc' : 'asc';
	// 	}
	// 	fetchAlerts(1);
	// }
	//
	// function sortIndicator(key: SortKey): string {
	// 	if (sortKey !== key) return '';
	// 	return sortDir === 'asc' ? ' ↑' : ' ↓';
	// }
	// OLD CODE END
	function changeSort(key: string, dir: 'asc' | 'desc') {
		sortKey = key as SortKey;
		sortDir = dir;
		fetchAlerts(1);
	}

	function toggleSubFilter(id: string) {
		subCatFilter = subCatFilter === id ? null : id;
		// #147: the bar said "Filtered" while the table still listed the whole category
		fetchAlerts(1);
	}

	function clearSubFilter() {
		subCatFilter = null;
		fetchAlerts(1);
	}

	// OLD CODE START — the browser's locale printed "Nov 6, 10:37:23 PM" (NET-192 PR 4: formatTime)
	// function formatTimestamp(ts: string): string {
	// 	try {
	// 		return new Date(ts).toLocaleString(undefined, {
	// 			month: 'short',
	// 			day: 'numeric',
	// 			hour: '2-digit',
	// 			minute: '2-digit',
	// 			second: '2-digit',
	// 		});
	// 	} catch {
	// 		return ts;
	// 	}
	// }
	// OLD CODE END
	const formatTimestamp = (ts: string) => formatTime(ts);

	// OLD CODE START — the browser's locale printed "Nov 6, 10:37 PM" (NET-192 PR 4: formatTime)
	// function formatShortTimestamp(ts: string): string {
	// 	try {
	// 		return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
	// 	} catch {
	// 		return ts;
	// 	}
	// }
	// OLD CODE END
	const formatShortTimestamp = (ts: string) => formatTime(ts, 'short');

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

	// OLD CODE START — 2026-11-03: severity shows as SeverityPill (colour, shape and word)
	// function severityClass(sev: number | undefined): string {
	// 	switch (sev) {
	// 		case 1: return 'sev-high';
	// 		case 2: return 'sev-medium';
	// 		case 3: return 'sev-low';
	// 		default: return 'sev-info';
	// 	}
	// }
	//
	// function severityLabelLocal(sev: number | undefined): string {
	// 	switch (sev) {
	// 		case 1: return 'HIGH';
	// 		case 2: return 'MEDIUM';
	// 		case 3: return 'LOW';
	// 		default: return 'INFO';
	// 	}
	// }
	//
	// function subCatColor(index: number): string {
	// 	return SUB_CAT_COLORS[index % SUB_CAT_COLORS.length];
	// }
	//
	// /** Build sub-cat id-to-color map for timeline chart. */
	// let subCatColorMap = $derived.by(() => {
	// 	const map: Record<string, string> = {};
	// 	(categoryData?.sub_categories ?? []).forEach((sc, i) => {
	// 		map[sc.id] = subCatColor(i);
	// 	});
	// 	return map;
	// });
	// OLD CODE END

	// Alert table action handlers
	// OLD CODE START — no error handling; the helpers now throw when the daemon refuses
	// async function handleSuppress(alert: Alert) {
	// 	if (!alert.alert?.signature_id) return;
	// 	await suppressAlert(alert.alert.signature_id, alert.src_ip);
	// 	fetchAlerts(currentPage);
	// }
	//
	// async function handleFalsePositive(alert: Alert) {
	// 	if (!alert.alert?.signature_id) return;
	// 	await markFalsePositive(alert.alert.signature_id);
	// 	fetchAlerts(currentPage);
	// }
	// OLD CODE END
	async function runAlertAction(action: () => Promise<void>) {
		actionError = '';
		try {
			await action();
			fetchAlerts(currentPage);
		} catch (err) {
			actionError = err instanceof Error ? err.message : 'Action failed';
		}
	}

	async function handleSuppress(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) await runAlertAction(() => suppressAlert(sigId, alert.src_ip));
	}

	async function handleFalsePositive(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) await runAlertAction(() => markFalsePositive(sigId));
	}

	/** The drawer's actions: the same calls, with the error shown in the drawer. */
	async function drawerAction(alert: Alert, action: (sigId: number) => Promise<void>) {
		const sigId = alert.alert?.signature_id;
		if (!sigId) return;
		await action(sigId);
		fetchAlerts(currentPage);
	}

	/** Acknowledge from the drawer (the category drawer had no actions before the redesign). */
	async function acknowledge(alert: Alert) {
		const result = await acknowledgeAlert(alert._id);
		if (!result) throw new Error('the acknowledgement failed. Try again.');
		alert.acknowledged = true;
		alert.acknowledged_at = result.acknowledged_at;
	}

	function openDrawer(alert: Alert) {
		drawerAlert = alert;
		// OLD CODE START — the drawer has no tabs now
		// drawerTab = 'summary';
		// OLD CODE END
	}

	// ---------------------------------------------------------------------------
	// View data
	// ---------------------------------------------------------------------------

	// OLD CODE: const fmt = (n: number) => n.toLocaleString('en-GB'); (NET-192 PR 4: one fmt, from utils/drilldown)
	const rowKey = (a: Alert) => `${a._id}-${alerts.indexOf(a)}`;
	// After a reload the open alert is a new object: find its row by id
	const selectedRowKey = $derived.by(() => {
		const open = drawerAlert && alerts.find((a) => a._id === drawerAlert?._id);
		return open ? rowKey(open) : undefined;
	});
	const deviceLevel = (s: string | undefined): SeverityLevel | undefined =>
		s && s in SEVERITY_RANK ? (s as SeverityLevel) : undefined;

	const alertColumns: Column<Alert>[] = [
		{ key: 'timestamp', label: 'Time', cell: timeCell },
		{ key: 'severity', label: 'Severity', cell: severityCell },
		{ key: 'signature', label: 'Signature', class: 'sig-cell', cell: signatureCell },
		{ key: 'src_ip', label: 'Source', cell: srcCell },
		{ key: 'dest_ip', label: 'Destination', cell: destCell },
		// Suppress and False positive sit in the last column: every column sorts, so there is no "Actions" one
		{ key: 'dest_port', label: 'Port', numeric: true, cell: portCell },
	];

	/** Every alert with this signature over the window of the figures on screen (NET-160 slice 2a). */
	// OLD CODE: const sigHref = (sig: string) => alertsHrefForSignature(sig, { ...shownWindow, range: selectedRange }); (NET-185: null is no rule name)
	const sigHref = (sig: string | null) => alertsHrefForSignature(sig, shownWindow);
	/**
	 * A Top signatures bar's link, carrying its figure (NET-160 section D). None for "Unknown", the
	 * daemon's bucket for alerts with no rule name (the list matches the literal name only), or for
	 * an empty name (the list drops an empty filter and lists every alert), since neither lists its count.
	 */
	// OLD CODE START — NET-185: the daemon keeps "Unknown" (a rule's name) and no rule name (null) apart now
	// const sigBarHref = (sig: { signature: string; count: number }) =>
	// 	sig.signature && sig.signature !== 'Unknown' ? withCount(sigHref(sig.signature), sig.count) : undefined;
	// OLD CODE END
	const sigBarHref = (sig: { signature: string | null; count: number }) =>
		sig.signature !== '' ? withCount(sigHref(sig.signature), sig.count) : undefined;

	/** The daemon lists at most this many addresses and signatures. */
	const LIST_CAP = 20;
	/** "Top 20 of 412 addresses" when capped: the daemon's address total is exact, the list is not (I10). */
	const addressesShown = (d: CategoryDetailResponse) => {
		const n = d.affected_devices.length;
		const total = d.stats.affected_devices;
		return n < total ? `Top ${fmt(n)} of ${fmt(total)} addresses` : `${fmt(n)} ${n === 1 ? 'address' : 'addresses'}`;
	};

	const deviceColumns: Column<CategoryDetailDevice>[] = [
		// OLD CODE START: { key: 'ip', label: 'Device', cell: deviceCell }, (I10: internet addresses too) OLD CODE END
		{ key: 'ip', label: 'Address', cell: deviceCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: deviceCountCell },
		{ key: 'severity', label: 'Severity', sortValue: (d) => SEVERITY_RANK[d.severity ?? ''], cell: deviceSeverityCell },
	];

	const mitreColumns: Column<MitreTechnique>[] = [
		{ key: 'id', label: 'Technique', cell: mitreIdCell },
		{ key: 'name', label: 'Name', cell: mitreNameCell },
		{ key: 'count', label: 'Matches', numeric: true, sortValue: (t) => t.count ?? 0, cell: mitreCountCell },
	];
</script>

{#snippet timeCell(a: Alert)}
	<span class="mono">{formatTimestamp(a.timestamp)}</span>{#if a.acknowledged}<span class="chip">Acknowledged</span>{/if}
{/snippet}
{#snippet severityCell(a: Alert)}<SeverityPill level={alertLevel(a.alert?.severity)} />{/snippet}
<!-- OLD CODE START — slice 2a: the signature wasn't a link
{#snippet signatureCell(a: Alert)}<span class="mono" title={a.alert?.signature || 'Unknown'}>{a.alert?.signature || 'Unknown'}</span>{/snippet}
OLD CODE END -->
{#snippet signatureCell(a: Alert)}
	<!-- OLD CODE: …{:else}<span class="mono">Unknown</span>{/if} (NET-185: the bars call these alerts "No rule name"; "Unknown" can be a real rule's name) -->
	<!-- OLD CODE: {#if a.alert?.signature}<a class="mono" href={sigHref(a.alert.signature)} … (NET-185: linked by the shown signature, which can be Suricata's own, not the rule.name the list matches, so it opened an empty list) -->
	<!-- Every alert with this rule over the figures' window; no link without a rule.name, which the list matches (as on Alerts) -->
	{#if a.rule?.name}<a class="mono" href={sigHref(a.rule.name)} title={a.alert?.signature || a.rule.name}>{a.alert?.signature || a.rule.name}</a>{:else if a.alert?.signature}<span class="mono" title={a.alert.signature}>{a.alert.signature}</span>{:else}<span class="dim">No rule name</span>{/if}
{/snippet}
{#snippet srcCell(a: Alert)}{#if a.src_ip}<IPAddress ip={a.src_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet destCell(a: Alert)}{#if a.dest_ip}<IPAddress ip={a.dest_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet portCell(a: Alert)}
	<span class="port-cell">
		<span class="mono">{a.dest_port ?? '—'}</span>
		<span class="row-actions">
			<button class="btn" type="button" title="Suppress this signature" onclick={(e) => { e.stopPropagation(); handleSuppress(a); }}>Suppress</button>
			<button class="btn" type="button" title="Mark as false positive" onclick={(e) => { e.stopPropagation(); handleFalsePositive(a); }}>False positive</button>
		</span>
	</span>
{/snippet}
{#snippet deviceCell(d: CategoryDetailDevice)}
	<span class="device-cell">
		<IPAddress ip={d.ip} />
		{#if d.hostname}<span class="dim">{d.hostname}</span>{/if}
		<!-- OLD CODE START — NET-160: the device page for internet addresses too
		<a class="link" href="/devices/{encodeURIComponent(d.ip)}">View device</a>
		OLD CODE END -->
		<!-- OLD CODE START — NET-160 review: the address beside it already links to the same page
		<a class="link" href={$ipHref(d.ip)}>{$isLan(d.ip) === true ? 'Open device' : 'Open address'}</a>
		OLD CODE END -->
	</span>
{/snippet}
{#snippet deviceCountCell(d: CategoryDetailDevice)}{formatNumber(d.count)}{/snippet}
{#snippet deviceSeverityCell(d: CategoryDetailDevice)}
	{@const level = deviceLevel(d.severity)}
	{#if level}<SeverityPill {level} />{:else}<span class="dim">—</span>{/if}
{/snippet}
{#snippet mitreIdCell(t: MitreTechnique)}
	<a class="link mono" href="https://attack.mitre.org/techniques/{t.id.replace('.', '/')}/" target="_blank" rel="noopener noreferrer" title="View on MITRE ATT&CK">{t.id}</a>
{/snippet}
{#snippet mitreNameCell(t: MitreTechnique)}
	<span class="mitre-name"><b>{t.name}</b>{#if t.description}<span class="dim">{t.description}</span>{/if}</span>
{/snippet}
{#snippet mitreCountCell(t: MitreTechnique)}{t.count ? formatNumber(t.count) : '—'}{/snippet}

<svelte:head>
	<title>{displayName} Alerts | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<a href="/alerts" class="back"><Icon name="back" />Alerts</a>
		<h1 class="page-title">{displayName}</h1>
		<p class="page-sub">{categoryData?.category?.description || 'Alerts in this category'} · {range.words}</p>
	</div>
	<div class="head-actions">
		{#if categoryData?.stats}
			<span class="chip num">{formatNumber(categoryData.stats.total)} alerts</span>
		{/if}
		<!-- OLD CODE: <Pills options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))} bind:value={selectedRange} ariaLabel="Time range" /> (NET-185: the URL holds the window) -->
		<Pills
			options={[...TIME_RANGES, ...(custom ? [custom] : [])].map((r) => ({ value: r.value, label: r.label }))}
			value={range.value}
			onchange={pickRange}
			ariaLabel="Time range"
		/>
	</div>
</header>

{#if loading}
	<Card title={displayName} sub={range.words}>
		<CardState state="loading" title="Loading {displayName}" />
	</Card>
{:else if detailFailed || !categoryData}
	<Card title={displayName} sub={range.words}>
		<CardState state="error" title="Couldn't load {displayName}: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
	</Card>
{:else if categoryData.stats.total === 0}
	<Card title={displayName} sub={range.words}>
		<CardState state="empty" icon="alerts" title="No alerts in {displayName}" message="Try expanding the time range or check that IDS rules are active." />
		<!-- NET-249: a pick whose alerts have since gone still says what it carried -->
		{#if countLine}<p class="notice pick-hint" role="status">{countLine}</p>{/if}
	</Card>
{:else}
	{@const data = categoryData}
	<div class="grid">
		<KpiCard class="c-4" label="Unique sources" icon="connections" value={formatNumber(data.stats.unique_sources)} note="Addresses that raised these alerts" />
		<KpiCard class="c-4" label="Unique targets" icon="alerts" value={formatNumber(data.stats.unique_targets)} note="Addresses they were aimed at" />
		<!-- OLD CODE START: <KpiCard class="c-4" label="Affected devices" icon="devices" value={formatNumber(data.stats.affected_devices)} note="Devices on your network" /> (I10: it counts every source and target, internet addresses too) OLD CODE END -->
		<KpiCard class="c-4" label="Addresses involved" icon="devices" value={formatNumber(data.stats.affected_devices)} note="Sources and targets, inside and outside your network" />

		<Card class="c-12" title="Alerts by severity" sub="{fmt(data.stats.total)} alerts · {range.words}, by severity">
			<div class="sev-sum">
				<div class="sev-left">
					<div class="sev-counts" style:--sev-chars={Math.max(...buckets.map((b) => fmt(b.count).length))}>
						{#each buckets as b (b.level)}<SeverityPill level={b.level} count={b.count} />{/each}
					</div>
				</div>
				<SeverityGauge
					{buckets}
					total={data.stats.total}
					ariaLabel="{fmt(data.stats.total)} {displayName} alerts in the {range.words}: {buckets.map((b) => `${fmt(b.count)} ${b.level}`).join(', ')}"
				/>
			</div>
		</Card>

		<!-- OLD CODE: sub="Alerts per {interval} · {range.words}" (NET-249: the bucket in words) -->
		<Card class="c-8" hero col title="Alert volume over time" sub="Alerts per {drill.bucketWords} · {range.words}">
			{#if timelineFailed}
				<CardState state="error" title="Couldn't load the alert volume over time: the request failed." onaction={() => refresh.run()} />
			{:else if series.length === 0}
				<CardState state="empty" title="No alert volume yet" message="The chart fills in once this category has alerts in the window." />
			{:else}
				<AreaChart
					series={[{ key: 'alerts', label: 'Alerts', colour: 1, points: series.map((p) => ({ t: p.timestamp, v: p.total })) }]}
					formatX={(t) => formatShortTimestamp(String(t))}
					formatY={(v) => fmt(v)}
					formatTip={(i) => `${formatShortTimestamp(series[i].timestamp)} · ${fmt(series[i].total)} alerts`}
					highlightIndex={busiest}
					ariaLabel={series[busiest].total > 0 ? `Busiest ${formatShortTimestamp(series[busiest].timestamp)}, with ${fmt(series[busiest].total)} alerts` : `No ${displayName} alerts in the ${range.words}`}
					onpick={chart ? pick : undefined}
				/>
				{#if chart}<p class="card-sub pick-hint">{NARROW_HINT}</p>{/if}
				{#if countLine}<p class="notice pick-hint" role="status">{countLine}</p>{/if}
			{/if}
		</Card>

		<Card class="c-4" title="Sub-categories" sub="{data.sub_categories.length} types · select one to filter the alerts">
			{#snippet actions()}
				{#if subCatFilter}<button class="btn" type="button" onclick={clearSubFilter}>Clear filter</button>{/if}
			{/snippet}
			{#if data.sub_categories.length === 0}
				<CardState state="empty" title="No sub-categories" message="This category's alerts aren't split into types." />
			{:else}
				<BarList
					items={data.sub_categories.map((sub) => ({
						key: sub.id,
						label: sub.label,
						value: sub.count,
						display: formatNumber(sub.count),
						detail: `${((sub.count / (data.stats.total || 1)) * 100).toFixed(1)}%${subCatFilter === sub.id ? ' · filtered' : ''}`,
						onclick: () => toggleSubFilter(sub.id),
					}))}
				/>
			{/if}
		</Card>

		<!-- OLD CODE START — I10: internet addresses counted as devices, and the daemon's 20-row cap read as the total
		<Card class="c-6" title="Affected devices" sub="{data.affected_devices.length} devices · alerts per device · {range.words}">
			{#if data.affected_devices.length === 0}
				<CardState state="empty" title="No affected devices found" message="Devices appear here once alerts in this category name them." />
			{:else}
				<DataTable columns={deviceColumns} rows={data.affected_devices} ariaLabel="Affected devices" rowKey={(d) => d.ip} initialSort={{ key: 'count', dir: 'desc' }} />
			{/if}
		</Card>

		<Card class="c-6 sig-bars" title="Top signatures" sub="{data.top_signatures.length} signatures · alerts per rule · last seen">
		OLD CODE END -->
		<Card class="c-6" title="Addresses involved" sub="{addressesShown(data)} · alerts per address · {range.words}">
			{#if data.affected_devices.length === 0}
				<CardState state="empty" title="No addresses found" message="Addresses appear here once alerts in this category name them." />
			{:else}
				<DataTable columns={deviceColumns} rows={data.affected_devices} ariaLabel="Addresses involved" rowKey={(d) => d.ip} initialSort={{ key: 'count', dir: 'desc' }} />
			{/if}
		</Card>

		<Card
			class="c-6 sig-bars"
			title="Top signatures"
			sub="{data.top_signatures.length >= LIST_CAP ? `The ${LIST_CAP} most common` : `${data.top_signatures.length} signatures`} · alerts per rule · last seen"
		>
			{#if data.top_signatures.length === 0}
				<CardState state="empty" title="No signatures found" message="Rules appear here once this category has alerts." />
			{:else}
				<!-- OLD CODE: key: sig.signature, label: sig.signature, (NET-185: a null rule name is its own row) -->
				<BarList
					items={data.top_signatures.map((sig) => ({
						key: sig.signature ?? '\u0000no rule name',
						// OLD CODE: label: sig.signature ?? 'No rule name', (NET-185: an empty name showed a blank label)
						label: sig.signature || 'No rule name',
						value: sig.count,
						display: formatNumber(sig.count),
						detail: formatRelativeTime(sig.last_seen),
						// OLD CODE: href: sigHref(sig.signature), (section D)
						href: sigBarHref(sig),
					}))}
				/>
			{/if}
		</Card>

		{#if data.mitre_techniques.length > 0}
			<Card class="c-12" title="MITRE ATT&CK techniques" sub="Mapped from this category's alerts">
				<DataTable columns={mitreColumns} rows={data.mitre_techniques} ariaLabel="MITRE ATT&CK techniques" rowKey={(t) => t.id} />
			</Card>
		{/if}
	</div>

	<div class="grid alert-layout" class:no-drawer={!drawerAlert}>
		<Card class="c-8 alert-list-card" title="Recent alerts" sub={alertsFailed ? 'Check failed' : `${fmt(totalAlerts)} matching · ${range.words}`}>
			{#if subCatFilter}
				<div class="toolbar">
					<span class="chip">
						Sub-category: {data.sub_categories.find((s) => s.id === subCatFilter)?.label ?? subCatFilter}
						<button class="chip-x" type="button" onclick={clearSubFilter} aria-label="Clear sub-category filter"><Icon name="close" /></button>
					</span>
				</div>
			{/if}
			{#if actionError}
				<p class="notice is-error" role="alert"><Icon name="warn" />Not applied: {actionError}</p>
			{/if}
			{#if alertsFailed}
				<CardState state="error" title="Couldn't load alerts: the request failed." onaction={() => fetchAlerts(currentPage)} />
			{:else if alerts.length === 0}
				<CardState state="empty" icon="alerts" title="No alerts found in this time range." />
			{:else}
				<!-- OLD CODE: rowLabel={(a) => `Open alert ${a.alert?.signature || 'Unknown'}…`} (NET-185: the bars call these alerts "No rule name"; "Unknown" can be a real rule's name) -->
				<DataTable
					columns={alertColumns}
					rows={sortedAlerts}
					ariaLabel="{displayName} alerts, newest first unless sorted"
					{rowKey}
					initialSort={{ key: sortKey, dir: sortDir }}
					onsortchange={changeSort}
					onrowactivate={openDrawer}
					rowLabel={(a) => `Open alert ${a.alert?.signature || 'with no rule name'}${a.src_ip ? ` from ${a.src_ip}` : ''}`}
					selectedKey={selectedRowKey}
					pager={totalPages > 1 ? { page: currentPage, pageCount: totalPages, total: totalAlerts, from: fromRow, to: toRow, onpage: (p) => fetchAlerts(p) } : undefined}
				/>
			{/if}
		</Card>
		{#if drawerAlert}
			{@const open = drawerAlert}
			{#key open._id}
				<AlertDetail
					alert={open}
					onclose={() => (drawerAlert = null)}
					onacknowledge={() => acknowledge(open)}
					onsuppress={() => drawerAction(open, (sigId) => suppressAlert(sigId, open.src_ip))}
					onfalsepositive={() => drawerAction(open, (sigId) => markFalsePositive(sigId))}
				/>
			{/key}
		{/if}
	</div>
{/if}

<style>
	/* Layout glue the system lacks */
	.alert-layout { align-items: start; }
	.chip-x {
		all: unset; display: inline-grid; place-items: center; cursor: pointer; color: var(--text-2); border-radius: var(--r-pill);
	}
	.chip-x:hover { color: var(--text-1); }
	.chip-x:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.notice { margin-bottom: var(--sp-4); }
	.pick-hint { margin-top: var(--sp-2); }
	.port-cell { display: flex; align-items: center; justify-content: flex-end; gap: var(--sp-3); }
	.row-actions { display: inline-flex; gap: var(--sp-1); }
	.row-actions .btn { min-height: 28px; padding: 0 var(--sp-3); font-size: var(--text-xs); }
	.device-cell { display: flex; align-items: baseline; gap: var(--sp-2); flex-wrap: wrap; }
	.mitre-name { display: flex; flex-direction: column; gap: 2px; }
	.mitre-name .dim { font-size: var(--text-xs); }
	:global(.sig-bars) :global(.bars li > :first-child) { font-family: var(--font-mono); }
</style>
