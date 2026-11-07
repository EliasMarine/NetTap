<script lang="ts">
	// OLD CODE: import { onDestroy, onMount } from 'svelte'; (slice 2a: the URL hand-off starts the first load, not onMount)
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getAlerts,
		// OLD CODE START — the severity counts come from the shared alert snapshot (PLAN.md §4.1)
		// getAlertCount,
		// OLD CODE END
		// slice 2a: a Custom window's counts are page-local (the shared snapshot holds rolling windows)
		getAlertCount,
		getAlertTimeline,
		getAlertTopSignatures,
		getAlertTopIps,
		getEnhancedCategories,
		getSmartAlertSummary,
		formatNumber,
		// OLD CODE START — severity shows as SeverityPill now
		// severityLabel,
		// severityBadgeClass,
		// OLD CODE END
		suppressAlert,
		markFalsePositive,
	} from '$api/alerts';
	import type {
		Alert,
		AlertsListResponse,
		AlertTimelineBucket,
		AlertSignature,
		AlertIpEntry,
		AlertCategory,
		SmartAlertSummary,
		AlertSort,
	} from '$api/alerts';
	// OLD CODE START — AlertDetailPanel replaced by DetailDrawer
	// import AlertDetailPanel from '$components/AlertDetailPanel.svelte';
	// OLD CODE END
	import IPAddress from '$components/IPAddress.svelte';
	import { ipHref } from '$lib/stores/lan';
	// OLD CODE START — 2026-11-03 redesign: the system's BarList and the docked drawer column
	// import HorizontalBarList from '$components/HorizontalBarList.svelte';
	// import DetailDrawer from '$components/DetailDrawer.svelte';
	// import AlertDrawerContent from '$components/drawer/content/AlertDrawerContent.svelte';
	// OLD CODE END
	// OLD CODE: import { acknowledgeAlert } from '$api/alerts'; (NET-164: the score's method)
	import { acknowledgeAlert, THREAT_SCORE_HOW } from '$api/alerts';
	// OLD CODE START — #146: the alert table sorts on the daemon now
	// import { compareValues, severityRank } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import { severityRank } from '$lib/utils/table-sort.svelte';
	import { severityBuckets, type SeverityLevel } from '$lib/utils/severity';
	import { alertSnapshots, loadAlertSnapshot, refreshAlertSnapshots, type AlertSnapshot } from '$lib/stores/alertSnapshot';
	// OLD CODE: import { alertsHrefForSignature, customRange, type CustomWindow, type DrillWindow } from '$lib/utils/drilldown'; (slice 2b-2)
	// OLD CODE: import { alertsHrefForSignature, customRange, partialListNote, suricataCategoryHref, type CustomWindow, type DrillWindow } from '$lib/utils/drilldown'; (section D)
	import {
		alertsHrefForSignature,
		countDifference,
		customRange,
		DRILL_RANGES,
		fmt,
		linkedCount,
		partialListNote,
		startRange,
		suricataCategoryHref,
		type CustomWindow,
		type DrillWindow,
		type LinkedCount,
	} from '$lib/utils/drilldown';
	import { createLoadGuard, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import AlertRow from '$lib/components/ui/AlertRow.svelte';
	import AlertGroup from '$lib/components/ui/AlertGroup.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import AutoRefreshButton from '$lib/components/ui/AutoRefreshButton.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import SeverityGauge from '$lib/components/ui/charts/SeverityGauge.svelte';
	import Ring from '$lib/components/ui/charts/Ring.svelte';
	import AlertDetail from './AlertDetail.svelte';
	// OLD CODE: import { alertLevel, alertTitle, groupAlerts, shortSeen } from './alert-view'; (slice 2b-2)
	import { alertLevel, alertTitle, groupAlerts, groupCategoryLinked, linkedSuricataCategory, shortSeen } from './alert-view';
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
	// 	// NET-160 slice 2b-1: Home's 6h links here with its window
	// 	{ label: '6h', value: '6h', ms: 6 * 60 * 60 * 1000, words: 'last 6 hours' },
	// 	{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000, words: 'last 24 hours' },
	// 	{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000, words: 'last 7 days' },
	// 	// NET-160: the address and domain pages link here with their 30-day window
	// 	{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000, words: 'last 30 days' },
	// ];
	// OLD CODE END
	// rangeFor sets each range's interval from INTERVAL_MAP below (DRILL_RANGES' interval is Home's wording)
	const TIME_RANGES = DRILL_RANGES.map((r) => ({ ...r, ms: r.hours * 3_600_000 }));

	const INTERVAL_MAP: Record<string, string> = {
		// OLD CODE: '15m': '1m', (NET-192 PR 4)
		'1h': '5m',
		// OLD CODE: '4h': '15m', (NET-192 PR 4)
		'6h': '15m',
		'24h': '1h',
		'7d': '6h',
		'30d': '1d',
	};

	type SeverityFilter = 'all' | 'high' | 'medium' | 'low' | 'info';

	const SEVERITY_FILTERS: { value: SeverityFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'high', label: 'High' },
		{ value: 'medium', label: 'Medium' },
		{ value: 'low', label: 'Low' },
		{ value: 'info', label: 'Info' },
	];

	const THREAT_LEVELS: SeverityLevel[] = ['critical', 'high', 'medium', 'low'];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// OLD CODE START — a filter clicked before the first load finished was ignored; the load guards order every request now
	// let initialized = $state(false);
	// let loading = $state(false);
	// OLD CODE END
	/** The first full load has finished (every card leaves its loading state). */
	let loaded = $state(false);
	/** The alert list has answered at least once. */
	let listLoaded = $state(false);
	// OLD CODE START: let selectedTimeRange = $state('24h'); — a link's ?range= was ignored OLD CODE END
	// OLD CODE START — 2026-11-06 (slice 2a): read once; the URL hand-off below applies ?range= on every change
	// // A link from a page with its own window (?range=, NET-160) opens on that window when it is one of ours
	// const urlRange = $page.url.searchParams.get('range');
	// let selectedTimeRange = $state(TIME_RANGES.some((r) => r.value === urlRange) ? (urlRange as string) : '24h');
	// OLD CODE END
	/** One of TIME_RANGES, or 'custom' while a link's exact window (?from=&to=) is on. */
	let selectedTimeRange = $state('24h');
	/** The URL's standard range (without one, the saved default, else 24h): the words and fallback a Custom window travels with. */
	let baseRange = $state('24h');
	/** The exact window a link brought (?from=&to=, NET-160 slice 2a), shown as "Custom". */
	let custom = $state<CustomWindow | null>(null);
	const AUTO_REFRESH_MS = 15_000;
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Server data
	// OLD CODE START — the counts come from the shared alert snapshot (PLAN.md §4.1)
	// let alertCounts = $state({ total: 0, high: 0, medium: 0, low: 0 });
	// OLD CODE END
	let timeline = $state<AlertTimelineBucket[]>([]);
	let topSignatures = $state<AlertSignature[]>([]);
	let topDestIps = $state<AlertIpEntry[]>([]);
	let topSrcIps = $state<AlertIpEntry[]>([]);
	/** Each top list's note when the daemon couldn't read every key (its rows aren't a true top N); null otherwise */
	let topPartial = $state<{ signatures: string | null; destIps: string | null; srcIps: string | null }>({ signatures: null, destIps: null, srcIps: null });
	let enhancedCategories = $state<AlertCategory[]>([]);
	let alerts = $state<Alert[]>([]);
	let threatScore = $state(0);
	let threatLevel = $state('none');
	let smartSummary = $state<SmartAlertSummary | null>(null);
	// #96: sections whose request failed; they say so instead of showing the last value or "none"
	let failed = $state<Record<string, boolean>>({});

	// Filters
	let activeFilter = $state<SeverityFilter>('all');
	let signatureSearch = $state('');
	// OLD CODE START — 2026-11-06 (slice 2a): signature was read once and ip derived; the URL hand-off applies both now
	// let urlSignature = $page.url.searchParams.get('signature') || '';
	// OLD CODE END
	let urlCategory = $page.url.searchParams.get('category') || '';
	// OLD CODE START — 2026-11-06 (slice 2a)
	// let signatureFilter = $state(urlSignature);
	// let ipFilter = $derived($page.url.searchParams.get('ip') || '');
	// OLD CODE END
	let signatureFilter = $state('');
	let ipFilter = $state('');
	/** A smart alert's source and destination (NET-160 slice 2b-1) */
	let srcFilter = $state('');
	let dstFilter = $state('');
	/** One raw Suricata category, rule.category (NET-160 slice 2b-2) */
	let suricataCategoryFilter = $state('');
	/** The list shows the activity alerts (ET rates them informational or unknown, never counted) instead (NET-191) */
	let activityFilter = $state(false);
	/** The activity alerts over the window loadAll asked about; null while unknown or when the request failed */
	let activityCount = $state<(DrillWindow & { total: number }) | null>(null);

	// Pagination
	/** The current search's window: paging reuses it, so rows arriving between pages don't shift the list. */
	let listWindow = $state<DrillWindow>({ from: '', to: '' });
	/** The window and range words of the rows on screen; set when a list lands, so links never run ahead of the rows. */
	let shownWindow = $state<DrillWindow & { range: string }>({ from: '', to: '', range: '24h' });
	/** The window the Top signatures counts on screen came from; a row opens the list over it (slice 2b-2). */
	let signaturesWindow = $state<DrillWindow & { range: string }>({ from: '', to: '', range: '24h' });
	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalAlerts = $state(0);
	const pageSize = 50;
	/** A counted link's figure against the total of the one list request it started (NET-160 section D). */
	let linked = $state<LinkedCount | null>(null);

	// OLD CODE START — replaced by DetailDrawer
	// let selectedAlert = $state<Alert | null>(null);
	// let expandedAlertId = $state<string | null>(null);
	// OLD CODE END

	// Detail drawer state
	let drawerAlert = $state<Alert | null>(null);
	// OLD CODE START — 2026-11-03: the drawer's tabs became its collapsible sections, and the timeline is the AreaChart
	// let drawerTab = $state('summary');
	// const ALERT_DRAWER_TABS = [
	// 	{ id: 'summary', label: 'Summary' },
	// 	{ id: 'related', label: 'Related events' },
	// 	{ id: 'raw', label: 'Raw JSON' },
	// ];
	// let hoveredBarIndex = $state<number | null>(null);
	// let chartWidth = $state(800);
	// OLD CODE END
	let actionError = $state('');
	/** The list shows grouped AlertRows or the full table; both read the same page of alerts. */
	let view = $state<'category' | 'all'>('category');

	// Sort
	// OLD CODE START — Protocol couldn't be sorted (design system: every column sorts)
	// type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip' | 'category';
	// OLD CODE END
	type SortKey = 'timestamp' | 'severity' | 'signature' | 'src_ip' | 'dest_ip' | 'protocol' | 'category';
	let sortKey = $state<SortKey>('timestamp');
	let sortDir = $state<'asc' | 'desc'>('desc');
	// Each column's name on the daemon, which sorts every page (#146)
	const SERVER_SORT: Record<SortKey, AlertSort> = {
		timestamp: 'time', severity: 'severity', signature: 'signature', src_ip: 'source',
		dest_ip: 'destination', protocol: 'proto', category: 'category',
	};

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03: the hand-drawn timeline and bar lists scaled themselves; AreaChart and BarList do it now
	// let maxBucketTotal = $derived(
	// 	Math.max(1, ...timeline.map((b) => b.high + b.medium + b.low))
	// );
	// OLD CODE END

	let filteredSignatures = $derived.by(() => {
		if (!signatureSearch) return topSignatures;
		const q = signatureSearch.toLowerCase();
		// OLD CODE: return topSignatures.filter((s) => s.signature.toLowerCase().includes(q)); (a row with no rule name is null)
		return topSignatures.filter((s) => (s.signature ?? '').toLowerCase().includes(q));
	});

	// OLD CODE START — 2026-11-03: BarList scales to its largest item
	// let maxSigCount = $derived(topSignatures.length > 0 ? topSignatures[0].count : 1);
	//
	// let maxDestIpCount = $derived(topDestIps.length > 0 ? topDestIps[0].count : 1);
	// let maxSrcIpCount = $derived(topSrcIps.length > 0 ? topSrcIps[0].count : 1);
	// OLD CODE END

	// OLD CODE START — PLAN.md §4.1: "Critical" was the malware-c2 category, which overlaps High; the
	// category's figure now shows with the other smart-alert categories in the threat summary card
	// /** Compute "critical" count as total minus high+medium+low (info-severity alerts). */
	// let criticalCount = $derived(
	// 	smartSummary
	// 		? (smartSummary.categories['malware-c2']?.events ?? 0)
	// 		: 0
	// );
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
	// 			case 'protocol':
	// 				cmp = compareValues(a.proto ?? '', b.proto ?? '');
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
	// 			case 'category':
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// cmp = (a.alert?.category || '').localeCompare(b.alert?.category || '');
	// 				// OLD CODE END
	// 				cmp = compareValues(a.alert?.category || '', b.alert?.category || '');
	// 				break;
	// 		}
	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	});
	// 	return list;
	// });
	// OLD CODE END
	// The daemon returns the rows in the table's order (#146)
	let sortedAlerts = $derived(alerts);

	// OLD CODE START — 2026-11-06 (slice 2a): no Custom window, and the counts were always the shared snapshot's
	// const range = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange) ?? TIME_RANGES[3]);
	// const rangeHours = $derived(range.ms / 3_600_000);
	// // One global count per window, shared with Home and the sidebar (PLAN.md §4.1)
	// const snapshot = $derived($alertSnapshots[rangeHours]);
	// OLD CODE END
	const range = $derived(rangeFor(selectedTimeRange, custom));
	const rangeHours = $derived(range.ms / 3_600_000);
	/** A Custom window's severity counts, loaded by this page: the shared snapshot holds rolling windows only. */
	let customCounts = $state<AlertSnapshot | null>(null);
	// One global count per rolling window, shared with Home and the sidebar (PLAN.md §4.1)
	const snapshot = $derived(range.value === 'custom' ? customCounts : $alertSnapshots[rangeHours]);
	// on 'error' the store keeps the last good counts (#96): show them with a stale note, as Home does
	const counts = $derived(snapshot?.data?.counts);
	const buckets = $derived(counts ? severityBuckets(counts) : []);
	const groups = $derived(groupAlerts(sortedAlerts));
	const fromRow = $derived(totalAlerts > 0 ? (currentPage - 1) * pageSize + 1 : 0);
	const toRow = $derived(Math.min(totalAlerts, fromRow + alerts.length - 1));
	/** "You clicked N. This search now matches M alerts (…)", once the counted link's request answers with another total. */
	const countLine = $derived(
		linked && linked.observed !== null
			? countDifference(linked.expected, linked.observed, { lead: 'This search now matches', one: 'alert', many: 'alerts' })
			: null,
	);

	// OLD CODE START — the counts come from the shared alert snapshot, and info from severityBuckets
	// function filterCountForTab(filter: SeverityFilter): number {
	// 	switch (filter) {
	// 		case 'all':
	// 			return alertCounts.total;
	// 		case 'high':
	// 			return alertCounts.high;
	// 		case 'medium':
	// 			return alertCounts.medium;
	// 		case 'low':
	// 			return alertCounts.low;
	// 		case 'info':
	// 			return Math.max(
	// 				0,
	// 				alertCounts.total - alertCounts.high - alertCounts.medium - alertCounts.low
	// 			);
	// 	}
	// }
	// OLD CODE END
	// OLD CODE START — 2026-11-06 (slice 2a): the pills filter the list over its own window and filters, so
	// the card's counts beside them could be another window's; the tiles above carry the counts
	// function filterCountForTab(filter: SeverityFilter): string {
	// 	if (!counts) return '—';
	// 	const n = filter === 'all' ? counts.total : (buckets.find((b) => b.level === filter)?.count ?? 0);
	// 	return n.toLocaleString('en-GB');
	// }
	//
	// const severityOptions = $derived(
	// 	SEVERITY_FILTERS.map((f) => ({ value: f.value, label: `${f.label} ${filterCountForTab(f.value)}` })),
	// );
	// OLD CODE END
	const severityOptions = SEVERITY_FILTERS;

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	/**
	 * Our range for `value`. Custom takes its window's span and words, and the timeline bucket of the
	 * smallest standard range that covers it.
	 */
	function rangeFor(value: string, win: CustomWindow | null) {
		if (value === 'custom' && win) {
			const ms = win.hours * 3_600_000;
			const fit = TIME_RANGES.find((r) => r.ms >= ms) ?? TIME_RANGES[TIME_RANGES.length - 1];
			return { label: win.label, value: win.value, ms, words: win.words, interval: INTERVAL_MAP[fit.value] };
		}
		// OLD CODE: ?? TIME_RANGES[3]; (slice 2b-1: 6h moved 24h to index 4)
		// OLD CODE: ?? TIME_RANGES[4]; (NET-192 PR 4: 15m and 4h dropped, 24h is index 2)
		// OLD CODE: ?? TIME_RANGES[2] (NET-192 PR 4: the default by value, not by position)
		const r = TIME_RANGES.find((t) => t.value === value) ?? TIME_RANGES.find((r) => r.value === '24h')!;
		return { ...r, interval: INTERVAL_MAP[r.value] };
	}

	function getTimeRange(): { from: string; to: string } {
		// slice 2a: a Custom window is fixed, not a span ending now
		if (selectedTimeRange === 'custom' && custom) return { from: custom.from, to: custom.to };
		const now = Date.now();
		// OLD CODE: || TIME_RANGES[3]; (slice 2b-1: 6h moved 24h to index 4)
		// OLD CODE: || TIME_RANGES[4]; (NET-192 PR 4: 15m and 4h dropped, 24h is index 2)
		// OLD CODE: || TIME_RANGES[2] (NET-192 PR 4: the default by value, not by position)
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange) || TIME_RANGES.find((r) => r.value === '24h')!;
		return {
			from: new Date(now - range.ms).toISOString(),
			to: new Date(now).toISOString(),
		};
	}

	// OLD CODE START — I1: Info sent no severity, so the Info filter listed every alert
	// function severityFilterToNumber(f: SeverityFilter): number | undefined {
	// 	switch (f) {
	// 		case 'high':
	// 			return 1;
	// 		case 'medium':
	// 			return 2;
	// 		case 'low':
	// 			return 3;
	// 		default:
	// 			return undefined;
	// 	}
	// }
	// OLD CODE END
	function severityFilterToNumber(f: SeverityFilter): number | 'info' | undefined {
		switch (f) {
			case 'high':
				return 1;
			case 'medium':
				return 2;
			case 'low':
				return 3;
			case 'info':
				return 'info';
			default:
				return undefined;
		}
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
	// 		return new Date(ts).toLocaleString(undefined, {
	// 			month: 'short',
	// 			day: 'numeric',
	// 			hour: '2-digit',
	// 			minute: '2-digit',
	// 		});
	// 	} catch {
	// 		return ts;
	// 	}
	// }
	// OLD CODE END
	const formatShortTimestamp = (ts: string) => formatTime(ts, 'short');

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
		// OLD CODE: fetchAlerts(1); (slice 2a: page 1 of a new search takes a new window; paging keeps it)
		fetchAlerts(1, getTimeRange());
	}

	function copyToClipboard(text: string, e: Event) {
		e.stopPropagation();
		navigator.clipboard.writeText(text);
	}

	// OLD CODE START — 2026-11-03 redesign: helpers for the hand-drawn category cards, sparklines and
	// threat gauge, replaced by BarList, Ring and SeverityPill (no emoji, no raw colour names)
	// /** Convert sparkline data array to SVG polyline points. */
	// function sparklinePoints(data: number[]): string {
	// 	if (!data.length) return '';
	// 	const max = Math.max(...data, 1);
	// 	return data.map((v, i) => {
	// 		const x = (i / Math.max(data.length - 1, 1)) * 56;
	// 		const y = 20 - (v / max) * 18;
	// 		return `${x},${y}`;
	// 	}).join(' ');
	// }
	//
	// /** Map category color names to CSS variable references. */
	// /** Map icon name from API to emoji for category cards */
	// const ICON_EMOJI: Record<string, string> = {
	// 	'shield-alert': '\u{1F6E1}', 'upload-cloud': '\u{2601}', 'search': '\u{1F50D}', 'bug': '\u{1F41B}',
	// 	'gavel': '\u{2696}', 'alert-triangle': '\u{26A0}', 'key': '\u{1F511}', 'globe': '\u{1F310}',
	// 	'lock': '\u{1F512}', 'cpu': '\u{1F4BB}', 'zap': '\u{26A1}', 'eye': '\u{1F441}', 'info': '\u{2139}',
	// };
	//
	// function catIconEmoji(icon: string): string {
	// 	return ICON_EMOJI[icon] ?? '\u{2139}';
	// }
	//
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
	// /** Compute percentage of a severity count within a category. */
	// function sevPct(cat: AlertCategory, level: 'critical' | 'high' | 'medium' | 'low' | 'info'): number {
	// 	const total = cat.severity_breakdown.critical + cat.severity_breakdown.high + cat.severity_breakdown.medium + cat.severity_breakdown.low + cat.severity_breakdown.info;
	// 	if (total === 0) return 0;
	// 	return (cat.severity_breakdown[level] / total) * 100;
	// }
	//
	// /** Determine trend CSS class for category cards. */
	// function trendClass(dir: string): string {
	// 	if (dir === 'increasing') return 'up-bad';
	// 	if (dir === 'decreasing') return 'down-good';
	// 	return 'stable';
	// }
	//
	// /** Get threat score color based on score value. */
	// function threatScoreColor(score: number): string {
	// 	if (score >= 75) return 'var(--red)';
	// 	if (score >= 50) return 'var(--orange)';
	// 	if (score >= 25) return 'var(--amber)';
	// 	return 'var(--green)';
	// }
	//
	// /** Compute the arc path for the threat gauge based on score (0-100). */
	// function threatArcPath(score: number): string {
	// 	// Semi-circle from (6,28) to (54,28) with radius 24, center (30,28)
	// 	const fraction = Math.min(score, 100) / 100;
	// 	const angle = Math.PI * fraction;
	// 	const endX = 30 - 24 * Math.cos(angle);
	// 	const endY = 28 - 24 * Math.sin(angle);
	// 	const largeArc = fraction > 0.5 ? 1 : 0;
	// 	return `M 6 28 A 24 24 0 ${largeArc} 1 ${endX.toFixed(1)} ${endY.toFixed(1)}`;
	// }
	//
	// /** Get the threat level badge color. */
	// function threatLevelColor(level: string): { bg: string; text: string } {
	// 	switch (level) {
	// 		case 'critical': return { bg: 'var(--sev-critical-muted)', text: 'var(--sev-critical)' };
	// 		case 'high': return { bg: 'var(--sev-high-muted)', text: 'var(--sev-high)' };
	// 		case 'medium': return { bg: 'var(--sev-medium-muted)', text: 'var(--sev-medium)' };
	// 		case 'low': return { bg: 'var(--sev-low-muted)', text: 'var(--sev-low)' };
	// 		default: return { bg: 'var(--green-dim)', text: 'var(--ok)' };
	// 	}
	// }
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN.md §5.5: didn't report what loaded, and a slow older load could overwrite a newer one
	// // OLD CODE START — always reloaded page 1, so auto-refresh threw the user back to the first page
	// // async function fetchAll() {
	// // OLD CODE END
	// /** Reload everything; the alert table stays on `pg` (the current page unless told otherwise). */
	// async function fetchAll(pg: number = currentPage) {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	const interval = INTERVAL_MAP[selectedTimeRange] || '1h';
	//
	// 	const results = await Promise.allSettled([
	// 		getAlertCount({ from, to }),
	// 		getAlertTimeline({ from, to, interval }),
	// 		getAlertTopSignatures({ from, to, limit: 20 }),
	// 		getAlertTopIps({ from, to, limit: 10, direction: 'dest' }),
	// 		getAlertTopIps({ from, to, limit: 10, direction: 'src' }),
	// 		getEnhancedCategories({ from, to }),
	// 		getAlerts({
	// 			from,
	// 			to,
	// 			severity: severityFilterToNumber(activeFilter),
	// 			// OLD CODE START
	// 			// page: 1,
	// 			// OLD CODE END
	// 			page: pg,
	// 			size: pageSize,
	// 			ip: ipFilter || undefined,
	// 			signature: signatureFilter || undefined,
	// 			sort: SERVER_SORT[sortKey],
	// 			order: sortDir,
	// 		}),
	// 		getSmartAlertSummary({ from, to }),
	// 	]);
	//
	// 	if (results[0].status === 'fulfilled') alertCounts = results[0].value.counts;
	// 	if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
	// 	if (results[2].status === 'fulfilled') topSignatures = results[2].value.signatures;
	// 	if (results[3].status === 'fulfilled') topDestIps = results[3].value.ips;
	// 	if (results[4].status === 'fulfilled') topSrcIps = results[4].value.ips;
	// 	if (results[5].status === 'fulfilled') enhancedCategories = results[5].value.categories;
	// 	if (results[6].status === 'fulfilled') {
	// 		const r = results[6].value;
	// 		alerts = r.alerts;
	// 		totalPages = r.total_pages;
	// 		totalAlerts = r.total;
	// 		// OLD CODE START
	// 		// currentPage = 1;
	// 		// OLD CODE END
	// 		currentPage = r.page;
	// 	}
	// 	if (results[7].status === 'fulfilled') {
	// 		smartSummary = results[7].value;
	// 		threatScore = results[7].value.threat_score;
	// 		threatLevel = results[7].value.threat_level;
	// 	}
	// 	const sections = ['counts', 'timeline', 'signatures', 'destIps', 'srcIps', 'categories', 'alerts', 'summary'];
	// 	failed = Object.fromEntries(sections.map((name, i) => [name, results[i].status === 'rejected']));
	// 	loading = false;
	// }
	//
	// async function fetchAlerts(pg: number = 1) {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	try {
	// 		const r = await getAlerts({
	// 			from,
	// 			to,
	// 			severity: severityFilterToNumber(activeFilter),
	// 			page: pg,
	// 			size: pageSize,
	// 			ip: ipFilter || undefined,
	// 			signature: signatureFilter || undefined,
	// 			sort: SERVER_SORT[sortKey],
	// 			order: sortDir,
	// 		});
	// 		alerts = r.alerts;
	// 		totalPages = r.total_pages;
	// 		totalAlerts = r.total;
	// 		currentPage = r.page;
	// 		failed = { ...failed, alerts: false };
	// 	} catch {
	// 		alerts = [];
	// 		totalPages = 0;
	// 		totalAlerts = 0;
	// 		failed = { ...failed, alerts: true };
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// OLD CODE END

	/** The list request for page `pg`, built from the filters as they are now (copied before any await). */
	function listParams(pg: number, window: { from: string; to: string }) {
		return {
			...window,
			severity: severityFilterToNumber(activeFilter),
			page: pg,
			size: pageSize,
			ip: ipFilter || undefined,
			src: srcFilter || undefined,
			dst: dstFilter || undefined,
			signature: signatureFilter || undefined,
			suricata_category: suricataCategoryFilter || undefined,
			activity: activityFilter || undefined,
			sort: SERVER_SORT[sortKey],
			order: sortDir,
		};
	}

	// OLD CODE: function applyList(result: PromiseSettledResult<AlertsListResponse>) { (slice 2a: rows didn't keep their window)
	// OLD CODE: function applyList(result: PromiseSettledResult<AlertsListResponse>, shown: DrillWindow & { range: string }) { (section D: `lg`)
	function applyList(result: PromiseSettledResult<AlertsListResponse>, shown: DrillWindow & { range: string }, lg: number) {
		if (result.status === 'fulfilled') {
			const r = result.value;
			shownWindow = shown;
			alerts = r.alerts;
			totalPages = r.total_pages;
			totalAlerts = r.total;
			currentPage = r.page;
			// Only the counted link's own request records the total it is compared with
			if (linked?.gen === lg) linked = { ...linked, observed: r.total };
		} else {
			// a failure clears the list: the rows on screen may be another filter's or range's
			alerts = [];
			totalPages = 0;
			totalAlerts = 0;
		}
		failed = { ...failed, alerts: result.status === 'rejected' };
		listLoaded = true;
	}

	// The list has its own generation as well, so a filter change mid-refresh drops only the
	// refresh's stale list and keeps the rest of what it loaded
	const listGuard = createLoadGuard();
	/**
	 * Start a list request. The URL hand-off's own request takes the comparison it set up (gen null);
	 * every other list load (sort, page, refresh, retry, an action) ends any comparison (section D).
	 */
	function beginList(): number {
		const lg = listGuard.begin();
		linked = linked && linked.gen === null ? { ...linked, gen: lg } : null;
		return lg;
	}
	/**
	 * A list request is out. Its rows replace the ones on screen, so the pager waits for them: a page
	 * asked for now would mix the new filters with the shown rows' window, and its request would
	 * discard the new search's answer.
	 */
	let listPending = $state(false);
	/** The snapshot window this page already loaded: loading it again is a refresh. */
	let snapshotHoursLoaded: number | null = null;

	/**
	 * The page refresh contract (PLAN.md §5.5): every request, awaited, then the result.
	 * The alert table stays on the current page.
	 */
	async function loadAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// OLD CODE: const lg = listGuard.begin(); (section D: a load also starts or ends the count comparison)
		const lg = beginList();
		listPending = true;
		// OLD CODE START — 2026-11-06 (slice 2a): no Custom window
		// const timeRange = TIME_RANGES.find((r) => r.value === selectedTimeRange) ?? TIME_RANGES[3];
		// OLD CODE END
		const timeRange = rangeFor(selectedTimeRange, custom);
		const hours = timeRange.ms / 3_600_000;
		const { from, to } = getTimeRange();
		// OLD CODE: const interval = INTERVAL_MAP[timeRange.value] || '1h'; (slice 2a: Custom has no entry)
		const interval = timeRange.interval;
		const list = listParams(currentPage, { from, to });
		listWindow = { from, to };
		const shown = { from, to, range: baseRange };
		const customWindow = timeRange.value === 'custom' ? { from, to } : null;

		// OLD CODE START — 2026-11-06 (slice 2a): every window was the shared snapshot's
		// // A refresh moves every reader of the shared count (sidebar, Home) to the new window together
		// if (snapshotHoursLoaded === hours) void refreshAlertSnapshots();
		// snapshotHoursLoaded = hours;
		// OLD CODE END
		if (!customWindow) {
			// A refresh moves every reader of the shared count (sidebar, Home) to the new window together
			if (snapshotHoursLoaded === hours) void refreshAlertSnapshots();
			snapshotHoursLoaded = hours;
		}

		const [snap, results] = await Promise.all([
			// OLD CODE: loadAlertSnapshot(hours), (slice 2a: a Custom window counts on this page)
			customWindow ? loadCustomCounts(customWindow, hours) : loadAlertSnapshot(hours),
			Promise.allSettled([
				getAlertTimeline({ from, to, interval }),
				getAlertTopSignatures({ from, to, limit: 20 }),
				getAlertTopIps({ from, to, limit: 10, direction: 'dest' }),
				getAlertTopIps({ from, to, limit: 10, direction: 'src' }),
				getEnhancedCategories({ from, to }),
				getAlerts(list),
				getSmartAlertSummary({ from, to }),
				// NET-191: last, so it never takes a count reply meant for the snapshot above
				getAlertCount({ from, to, activity: true }),
			] as const),
		]);
		// OLD CODE: const [tl, sigs, dest, src, cats, listResult, summary] = results; (NET-191: the activity count)
		const [tl, sigs, dest, src, cats, listResult, summary, activity] = results;
		const succeeded = [snap.status === 'ok', ...results.map((r) => r.status === 'fulfilled')];
		if (!guard.current(g)) return 'skipped';

		if (customWindow) customCounts = snap;
		if (tl.status === 'fulfilled') timeline = tl.value.buckets;
		// OLD CODE: if (sigs.status === 'fulfilled') topSignatures = sigs.value.signatures; (slice 2b-2: the rows keep their window)
		if (sigs.status === 'fulfilled') {
			topSignatures = sigs.value.signatures;
			signaturesWindow = shown;
			topPartial = { ...topPartial, signatures: partialNote(sigs.value, 'rules') };
		}
		// OLD CODE: if (dest.status === 'fulfilled') topDestIps = dest.value.ips; (NET-160: the list says when it is partial)
		if (dest.status === 'fulfilled') {
			topDestIps = dest.value.ips;
			topPartial = { ...topPartial, destIps: partialNote(dest.value, 'addresses') };
		}
		// OLD CODE: if (src.status === 'fulfilled') topSrcIps = src.value.ips; (NET-160: the list says when it is partial)
		if (src.status === 'fulfilled') {
			topSrcIps = src.value.ips;
			topPartial = { ...topPartial, srcIps: partialNote(src.value, 'addresses') };
		}
		if (cats.status === 'fulfilled') enhancedCategories = cats.value.categories;
		if (summary.status === 'fulfilled') {
			smartSummary = summary.value;
			threatScore = summary.value.threat_score;
			threatLevel = summary.value.threat_level;
		}
		// A failed count keeps the last one, as the cards above keep theirs; a new window cleared it already
		if (activity.status === 'fulfilled') activityCount = { from, to, total: activity.value.counts.total };
		const sections = ['timeline', 'signatures', 'destIps', 'srcIps', 'categories', 'alerts', 'summary'];
		failed = { ...Object.fromEntries(sections.map((name, i) => [name, results[i].status === 'rejected'])), alerts: failed.alerts ?? false };
		// OLD CODE: if (listGuard.current(lg)) applyList(listResult);
		// OLD CODE: if (listGuard.current(lg)) applyList(listResult, shown); (the pager didn't wait)
		if (listGuard.current(lg)) {
			// OLD CODE: applyList(listResult, shown); (section D)
			applyList(listResult, shown, lg);
			listPending = false;
		}
		loaded = true;

		if (succeeded.every(Boolean)) return 'ok';
		return succeeded.some(Boolean) ? 'partial' : 'failed';
	}

	/**
	 * A Custom window's counts, from the same /api/alerts/count the shared snapshot uses. A new window
	 * shows loading; a failed refresh of the same window keeps the last figures with a stale note (#96).
	 */
	function loadCustomCounts(win: DrillWindow, hours: number): Promise<AlertSnapshot> {
		const sameWindow = customCounts?.from === win.from && customCounts?.to === win.to;
		const last = sameWindow ? (customCounts?.data ?? null) : null;
		if (!sameWindow) customCounts = { status: 'loading', hours, ...win, data: null };
		return getAlertCount({ from: win.from, to: win.to }).then(
			(data): AlertSnapshot => ({ status: 'ok', hours, ...win, data }),
			(): AlertSnapshot => ({ status: 'error', hours, ...win, data: last }),
		);
	}

	const refresh = registerPageRefresh(loadAll);

	// OLD CODE START — 2026-11-06 (slice 2a): every page recomputed the window, so rows arriving between pages shifted the list
	// async function fetchAlerts(pg: number = 1) {
	// 	const lg = listGuard.begin();
	// 	const params = listParams(pg, getTimeRange());
	// OLD CODE END
	/** Page `pg` of the list over `win`: the current search's window unless a new search passes its own. */
	async function fetchAlerts(pg: number = 1, win: DrillWindow = listWindow) {
		// OLD CODE: const lg = listGuard.begin(); (section D: a load also starts or ends the count comparison)
		const lg = beginList();
		listPending = true;
		listWindow = win;
		const shown = { ...win, range: baseRange };
		const params = listParams(pg, win);
		const result = await getAlerts(params).then(
			(value): PromiseSettledResult<AlertsListResponse> => ({ status: 'fulfilled', value }),
			(reason): PromiseSettledResult<AlertsListResponse> => ({ status: 'rejected', reason }),
		);
		// OLD CODE: if (listGuard.current(lg)) applyList(result);
		// OLD CODE: if (listGuard.current(lg)) applyList(result, shown); (the pager didn't wait)
		if (listGuard.current(lg)) {
			// OLD CODE: applyList(result, shown); (section D)
			applyList(result, shown, lg);
			listPending = false;
		}
	}

	/** A top list's partial note, or null when the daemon read every key. */
	const partialNote = (reply: { complete: boolean; examined: number }, noun: string) => (reply.complete ? null : partialListNote(noun, reply.examined));

	function scrollToList() {
		document.getElementById('alerts-table')?.scrollIntoView?.({ behavior: 'smooth' });
	}

	// The list's filters and window, in the URL (slice 2a)
	// OLD CODE: const LIST_PARAMS = ['severity', 'signature', 'ip', 'range', 'from', 'to'] as const; (slice 2b-1: src and dst)
	// OLD CODE: const LIST_PARAMS = ['severity', 'signature', 'ip', 'src', 'dst', 'range', 'from', 'to'] as const; (slice 2b-2: suricata_category)
	// OLD CODE: const LIST_PARAMS = ['severity', 'signature', 'ip', 'src', 'dst', 'suricata_category', 'range', 'from', 'to'] as const; (NET-191: activity)
	const LIST_PARAMS = ['severity', 'signature', 'ip', 'src', 'dst', 'suricata_category', 'activity', 'range', 'from', 'to'] as const;
	/** Where the window's parameters start in LIST_PARAMS: range, from, to. */
	const WINDOW_AT = LIST_PARAMS.indexOf('range');

	/** Change only the given list parameters in the URL (null drops one); the URL hand-off below applies them. */
	function setListParams(changes: Partial<Record<(typeof LIST_PARAMS)[number], string | null>>) {
		const url = new URL($page.url);
		for (const [key, value] of Object.entries(changes)) {
			if (value) url.searchParams.set(key, value);
			else url.searchParams.delete(key);
		}
		// A control's own search: the figure a link was clicked at no longer describes it (section D)
		url.searchParams.delete('count');
		return goto(`${url.pathname}${url.search}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// OLD CODE START — 2026-11-06 (slice 2a): the controls set local state and fetched; they write the URL now
	// function handleTimeRangeChange(value: string) {
	// 	selectedTimeRange = value;
	// 	// A new time range is a new result set: start from page 1
	// 	// OLD CODE START — waited for the first load; the guards drop whichever load is older now
	// 	// if (initialized) fetchAll(1);
	// 	// OLD CODE END
	// 	currentPage = 1;
	// 	refresh.run();
	// }
	//
	// function handleSeverityChange(value: SeverityFilter) {
	// 	activeFilter = value;
	// 	// OLD CODE START — waited for the first load; the list guard drops the older list now
	// 	// if (initialized) fetchAlerts(1);
	// 	// OLD CODE END
	// 	fetchAlerts(1);
	// }
	//
	// /** A severity tile: filter the list by that severity and bring it into view (the old stat cards). */
	// function showSeverity(level: SeverityFilter) {
	// 	handleSeverityChange(level);
	// 	scrollToList();
	// }
	//
	// function filterBySignature(sig: string) {
	// 	// Toggle: click same signature again to clear filter
	// 	if (signatureFilter === sig) {
	// 		signatureFilter = '';
	// 	} else {
	// 		signatureFilter = sig;
	// 	}
	// 	// OLD CODE START — waited for the first load; the list guard drops the older list now
	// 	// if (initialized) {
	// 	// 	fetchAlerts(1).then(() => {
	// 	// 		document.getElementById('alerts-table')?.scrollIntoView({ behavior: 'smooth' });
	// 	// 	});
	// 	// }
	// 	// OLD CODE END
	// 	fetchAlerts(1).then(scrollToList);
	// }
	//
	// function clearSignatureFilter() {
	// 	signatureFilter = '';
	// 	// OLD CODE START — waited for the first load; the list guard drops the older list now
	// 	// if (initialized) fetchAlerts(1);
	// 	// OLD CODE END
	// 	fetchAlerts(1);
	// }
	// OLD CODE END

	/** A range pill: a rolling window ending now, so the link's exact window (Custom) goes. */
	function handleTimeRangeChange(value: string) {
		if (value !== 'custom') void setListParams({ range: value, from: null, to: null });
	}

	function handleSeverityChange(value: SeverityFilter) {
		void setListParams({ severity: value === 'all' ? null : value });
	}

	/**
	 * A severity tile opens the alerts it counts: that level, every signature and address, over the
	 * displayed counts' own window (on a failed refresh, the older figures' window), then brings the list into view.
	 */
	function showSeverity(level: SeverityFilter) {
		const data = snapshot?.data;
		if (!data) return;
		const q = new URLSearchParams({ severity: level, from: data.from, to: data.to, range: baseRange });
		void goto(`/alerts?${q.toString()}`, { keepFocus: true, noScroll: true });
		scrollToList();
	}

	/**
	 * The "not counted" line opens exactly the activity it counted, as a severity tile does: the
	 * activity alerts alone over that count's window, every other filter cleared (NET-191).
	 */
	function showActivity() {
		if (!activityCount) return;
		const q = new URLSearchParams({ activity: 'true', from: activityCount.from, to: activityCount.to, range: baseRange });
		void goto(`/alerts?${q.toString()}`, { keepFocus: true, noScroll: true });
		scrollToList();
	}

	// OLD CODE START — slice 2b-2 (Codex r2 #6): the other filters stayed, so the list held fewer alerts than the row's window-wide count
	// /** A top signature filters the list; selecting it again clears the filter. */
	// async function filterBySignature(sig: string) {
	// 	await setListParams({ signature: signatureFilter === sig ? null : sig });
	// 	scrollToList();
	// }
	// OLD CODE END
	/**
	 * A top signature opens exactly its row's count: that signature alone, over the window the
	 * counts came from, every other filter cleared. Selecting it again clears only the signature.
	 */
	async function filterBySignature(sig: string) {
		if (signatureFilter === sig) {
			await setListParams({ signature: null });
		} else {
			const { from, to, range } = signaturesWindow;
			const q = new URLSearchParams({ signature: sig, from, to, range });
			await goto(`/alerts?${q.toString()}`, { keepFocus: true, noScroll: true });
		}
		scrollToList();
	}

	function clearSignatureFilter() {
		void setListParams({ signature: null });
	}

	// Pagination
	function goToPage(pg: number) {
		// OLD CODE: if (pg < 1 || pg > totalPages) return; (a page during a new search mixed two queries)
		if (pg < 1 || pg > totalPages || listPending) return;
		// OLD CODE: fetchAlerts(pg); (listWindow can be a refresh still in flight, so page 2 came from a newer window than page 1)
		// Page through the window of the rows on screen
		fetchAlerts(pg, { from: shownWindow.from, to: shownWindow.to });
	}

	// Auto-refresh
	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			// OLD CODE START
			// refreshInterval = setInterval(fetchAll, 15_000);
			// OLD CODE END
			// OLD CODE START — the auto loop goes through the page refresh contract, so "Updated" stays honest
			// refreshInterval = setInterval(() => fetchAll(), 15_000);
			// OLD CODE END
			refreshInterval = setInterval(() => refresh.runIfIdle(), AUTO_REFRESH_MS);
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
		// OLD CODE START — the drawer has no tabs now
		// drawerTab = 'summary';
		// OLD CODE END
	}

	function closeDrawer() {
		drawerAlert = null;
		// OLD CODE START — the drawer has no tabs now
		// drawerTab = 'summary';
		// OLD CODE END
	}

	// OLD CODE START — a refused acknowledgement did nothing, so it looked like the click was lost
	// async function handleDrawerAcknowledge(alertId: string) {
	// 	const result = await acknowledgeAlert(alertId);
	// 	if (result && drawerAlert) {
	// 		drawerAlert.acknowledged = true;
	// 		drawerAlert.acknowledged_at = result.acknowledged_at;
	// 	}
	// }
	// OLD CODE END
	async function handleDrawerAcknowledge(alertId: string) {
		const result = await acknowledgeAlert(alertId);
		if (!result) throw new Error('the acknowledgement failed. Try again.');
		if (drawerAlert) {
			drawerAlert.acknowledged = true;
			drawerAlert.acknowledged_at = result.acknowledged_at;
		}
	}

	// OLD CODE START — no error handling; the helpers now throw when the daemon refuses
	// async function handleSuppressAlert(alert: Alert) {
	// 	const sigId = alert.alert?.signature_id;
	// 	if (sigId) {
	// 		await suppressAlert(sigId);
	// 		// Refresh alerts to reflect the change
	// 		fetchAlerts(currentPage);
	// 	}
	// }
	//
	// async function handleFalsePositive(alert: Alert) {
	// 	const sigId = alert.alert?.signature_id;
	// 	if (sigId) {
	// 		await markFalsePositive(sigId);
	// 		fetchAlerts(currentPage);
	// 	}
	// }
	// OLD CODE END
	async function runAlertAction(action: () => Promise<void>) {
		actionError = '';
		try {
			await action();
			// Refresh alerts to reflect the change
			fetchAlerts(currentPage);
		} catch (err) {
			actionError = err instanceof Error ? err.message : 'Action failed';
		}
	}

	async function handleSuppressAlert(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) await runAlertAction(() => suppressAlert(sigId));
	}

	async function handleFalsePositive(alert: Alert) {
		const sigId = alert.alert?.signature_id;
		if (sigId) await runAlertAction(() => markFalsePositive(sigId));
	}

	/** The drawer's own Suppress and False positive: the same calls, with the error in the drawer. */
	async function drawerAction(alert: Alert, action: (sigId: number) => Promise<void>) {
		const sigId = alert.alert?.signature_id;
		if (!sigId) return;
		await action(sigId);
		fetchAlerts(currentPage);
	}

	// ---------------------------------------------------------------------------
	// IP filter reactivity
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-06 (slice 2a): only ip followed the URL (signature and range were read once),
	// and it searched on the old window, so a link changing ip and the window together went half-applied
	// let prevIpFilter: string | null = null;
	// $effect(() => {
	// 	if (prevIpFilter !== null && prevIpFilter !== ipFilter) {
	// 		fetchAlerts(1);
	// 	}
	// 	prevIpFilter = ipFilter;
	// });
	// OLD CODE END
	/** The list parameters last applied from the URL; null before the first load. */
	let appliedUrl: string[] | null = null;
	/**
	 * The link's `count` last applied (section D). It is a key of its own, never in LIST_PARAMS, so the
	 * window comparison below is unchanged: a change of `count` alone is one list search.
	 */
	let appliedCount: number | null = null;
	// The URL is the one source of the list's filters and window. A change applies them all together from
	// page 1 with one request: a list search when only severity, signature, ip, src, dst or count changed,
	// otherwise a full reload on the new window. The first run is the page's first load.
	$effect(() => {
		const params = $page.url.searchParams;
		const next = LIST_PARAMS.map((key) => params.get(key) ?? '');
		const count = linkedCount(params.get('count'));
		untrack(() => {
			const prev = appliedUrl;
			// OLD CODE: if (prev && next.every((v, i) => v === prev[i])) return; (section D: a new count is a new hand-off)
			if (prev && next.every((v, i) => v === prev[i]) && count === appliedCount) return;
			appliedUrl = next;
			appliedCount = count;
			// OLD CODE: const [severity, signature, ip, rangeParam, from, to] = next; (slice 2b-1: src and dst)
			// OLD CODE: const [severity, signature, ip, src, dst, rangeParam, from, to] = next; (slice 2b-2: suricata_category)
			// OLD CODE: const [severity, signature, ip, src, dst, suricataCategory, rangeParam, from, to] = next; (NET-191: activity)
			const [severity, signature, ip, src, dst, suricataCategory, activity, rangeParam, from, to] = next;
			activeFilter = SEVERITY_FILTERS.find((f) => f.value === severity)?.value ?? 'all';
			signatureFilter = signature;
			ipFilter = ip;
			srcFilter = src;
			dstFilter = dst;
			suricataCategoryFilter = suricataCategory;
			activityFilter = activity === 'true';
			custom = customRange(from, to);
			// OLD CODE: baseRange = TIME_RANGES.some((r) => r.value === rangeParam) ? rangeParam : '24h'; (NET-195: a link's range, else Settings › Display's default)
			baseRange = TIME_RANGES.some((r) => r.value === rangeParam) ? rangeParam : startRange('24h');
			selectedTimeRange = custom ? 'custom' : baseRange;
			currentPage = 1;
			// OLD CODE: next.slice(3).every((v, i) => v === prev[i + 3]); (slice 2b-1: src and dst moved the window along)
			const sameWindow = prev !== null && next.slice(WINDOW_AT).every((v, i) => v === prev[i + WINDOW_AT]);
			// A counted link: the page-1 request started next takes this comparison (beginList sets its gen)
			linked = count === null ? null : { expected: count, gen: null, observed: null };
			if (sameWindow) void fetchAlerts(1, getTimeRange());
			else {
				// NET-191: the "not counted" line must not show another window's number while this one loads
				activityCount = null;
				void refresh.run();
			}
		});
	});

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	// OLD CODE START — loads go through the page refresh contract now
	// onMount(() => {
	// 	fetchAll().then(() => {
	// 		initialized = true;
	// 	});
	// 	return () => {
	// 		if (refreshInterval) clearInterval(refreshInterval);
	// 	};
	// });
	// OLD CODE END
	// OLD CODE START — 2026-11-06 (slice 2a): the URL hand-off's first run is the first load
	// onMount(() => {
	// 	refresh.run();
	// });
	// OLD CODE END

	onDestroy(() => {
		if (refreshInterval) clearInterval(refreshInterval);
		refresh.unregister();
		listGuard.invalidate();
	});

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

	// OLD CODE START — I1: info alerts were left out, so the slots summed to less than the tiles
	// const timelineTotals = $derived(timeline.map((b) => b.high + b.medium + b.low));
	// OLD CODE END
	const timelineTotals = $derived(timeline.map((b) => b.high + b.medium + b.low + (b.info ?? 0)));
	const busiest = $derived(timelineTotals.reduce((best, v, i) => (v > timelineTotals[best] ? i : best), 0));
	const timelineLabel = $derived(
		timelineTotals.length && timelineTotals[busiest] > 0
			? `Busiest ${formatShortTimestamp(timeline[busiest].timestamp)}, with ${fmt(timelineTotals[busiest])} alerts`
			: `No alerts in the ${range.words}`,
	);
	const gaugeLabel = $derived(
		counts
			? `${fmt(counts.total)} alerts in the ${range.words}: ${buckets.map((b) => `${fmt(b.count)} ${b.level}`).join(', ')}`
			: '',
	);
	const smartCategories = $derived(
		Object.entries(smartSummary?.categories ?? {})
			.map(([key, c]) => ({ key, ...c }))
			.sort((a, b) => b.events - a.events || a.label.localeCompare(b.label)),
	);
	const threatPill = $derived(THREAT_LEVELS.find((l) => l === threatLevel));

	// OLD CODE START — NET-160: the device page for every address, unencoded
	// const ipBars = (entries: AlertIpEntry[]) =>
	// 	entries.map((e) => ({ key: e.ip, label: e.ip, value: e.count, display: fmt(e.count), href: `/devices/${e.ip}` }));
	// OLD CODE END
	const ipBars = (entries: AlertIpEntry[]) =>
		entries.map((e) => ({ key: e.ip, label: e.ip, value: e.count, display: fmt(e.count), href: $ipHref(e.ip) }));

	const columns: Column<Alert>[] = [
		{ key: 'timestamp', label: 'Time', cell: timeCell },
		{ key: 'severity', label: 'Severity', cell: severityCell },
		{ key: 'signature', label: 'Signature', class: 'sig-cell', cell: signatureCell },
		{ key: 'src_ip', label: 'Source', cell: srcCell },
		{ key: 'dest_ip', label: 'Destination', cell: destCell },
		{ key: 'protocol', label: 'Protocol', cell: protoCell },
		// Suppress and False positive sit in the last column: every column sorts, so there is no "Actions" one
		{ key: 'category', label: 'Category', cell: categoryCell },
	];

	/**
	 * A null and an empty rule name are separate rows that read the same; neither filters the list,
	 * which drops signature="", so it would open every alert instead of the row's count.
	 */
	const sigRowKey = (s: AlertSignature) => s.signature ?? '\u0000no rule name';
	const signatureColumns: Column<AlertSignature>[] = [
		// OLD CODE: { key: 'signature', label: 'Signature', cell: sigNameCell }, (a null signature sorts as "")
		{ key: 'signature', label: 'Signature', sortValue: (s) => s.signature ?? '', cell: sigNameCell },
		{ key: 'severity', label: 'Severity', sortValue: (s) => severityRank(s.severity), cell: sigSeverityCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: sigCountCell },
	];
</script>

{#snippet timeCell(a: Alert)}
	<span class="mono">{formatTimestamp(a.timestamp)}</span>{#if a.acknowledged}<span class="chip">Acknowledged</span>{/if}
{/snippet}
{#snippet severityCell(a: Alert)}<SeverityPill level={alertLevel(a.alert?.severity)} />{/snippet}
<!-- OLD CODE START — slice 2a: the signature wasn't a link
{#snippet signatureCell(a: Alert)}<span class="mono" title={a.alert?.signature || 'Unknown'}>{a.alert?.signature || 'Unknown'}</span>{/snippet}
OLD CODE END -->
<!-- OLD CODE START — slice 2b-1: linked by the shown signature, which can be alert.signature, not the rule.name the filter matches
{#snippet signatureCell(a: Alert)}
	{#if a.alert?.signature}<a class="mono" href={alertsHrefForSignature(a.alert.signature, shownWindow)} title={a.alert.signature}>{a.alert.signature}</a>{:else}<span class="mono">Unknown</span>{/if}
{/snippet}
OLD CODE END -->
<!-- Every alert with this rule, over the list's own window; no link without a rule.name, which the filter matches -->
<!-- OLD CODE: {#if a.rule?.name}<a class="mono" href={alertsHrefForSignature(a.rule.name, shownWindow)} … (NET-191: a row of the activity list opened the counted list, which leaves it out) -->
{#snippet signatureCell(a: Alert)}
	{#if a.rule?.name}<a class="mono" href={alertsHrefForSignature(a.rule.name, shownWindow, { activity: activityFilter })} title={a.alert?.signature || a.rule.name}>{a.alert?.signature || a.rule.name}</a>{:else}<span class="mono" title={a.alert?.signature || 'Unknown'}>{a.alert?.signature || 'Unknown'}</span>{/if}
{/snippet}
{#snippet srcCell(a: Alert)}{#if a.src_ip}<IPAddress ip={a.src_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet destCell(a: Alert)}{#if a.dest_ip}<IPAddress ip={a.dest_ip} />{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet protoCell(a: Alert)}{#if a.proto}<span class="tag">{a.proto.toUpperCase()}</span>{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet categoryCell(a: Alert)}
	{@const linkedCategory = linkedSuricataCategory(a)}
	<span class="cat-cell">
		<!-- OLD CODE: <span>{a.alert?.category || '—'}</span> (slice 2b-2: links when rule.category holds it, over the list's window) -->
		<!-- OLD CODE: {#if linkedCategory} (NET-191: a category page counts only counted alerts, so the activity list doesn't link to it) -->
		{#if linkedCategory && !activityFilter}
			<a href={suricataCategoryHref(linkedCategory, shownWindow)} title="Every alert in this Suricata category over the list's window">{linkedCategory}</a>
		{:else}
			<span>{a.alert?.category || '—'}</span>
		{/if}
		<span class="row-actions">
			<button class="btn" type="button" title="Suppress this signature" onclick={(e) => { e.stopPropagation(); handleSuppressAlert(a); }}>Suppress</button>
			<button class="btn" type="button" title="Mark as false positive" onclick={(e) => { e.stopPropagation(); handleFalsePositive(a); }}>False positive</button>
		</span>
	</span>
{/snippet}
<!-- OLD CODE: {#snippet sigNameCell(s: AlertSignature)}<span class="mono">{s.signature}</span>{/snippet} (a null or empty rule name reads as such) -->
{#snippet sigNameCell(s: AlertSignature)}{#if s.signature}<span class="mono">{s.signature}</span>{:else}<span class="dim">No rule name</span>{/if}{/snippet}
{#snippet sigSeverityCell(s: AlertSignature)}<SeverityPill level={alertLevel(s.severity)} />{/snippet}
{#snippet sigCountCell(s: AlertSignature)}{fmt(s.count)}{/snippet}

<svelte:head>
	<title>Alerts | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<h1 class="page-title">Alerts</h1>
		<p class="page-sub">What Suricata flagged on your network · {range.words}</p>
	</div>
	<div class="head-actions">
		<!-- OLD CODE: options={TIME_RANGES.map((r) => ({ value: r.value, label: r.label }))} (slice 2a: no Custom) -->
		<Pills
			options={[...TIME_RANGES, ...(custom ? [custom] : [])].map((r) => ({ value: r.value, label: r.label }))}
			value={selectedTimeRange}
			onchange={handleTimeRangeChange}
			ariaLabel="Time range"
		/>
		<!-- OLD CODE START — NET-192 PR 4: Home's Auto / Paused button on every page
		<div class="pills" role="group" aria-label="Auto-refresh every 15 seconds">
			<button class="pill" type="button" aria-pressed={autoRefresh} onclick={toggleAutoRefresh}>Auto</button>
		</div>
		OLD CODE END -->
		<AutoRefreshButton on={autoRefresh} seconds={AUTO_REFRESH_MS / 1000} ontoggle={toggleAutoRefresh} />
	</div>
</header>

<div class="grid">
	<Card class="c-12" title="Alerts by severity" sub="Alerts · {range.words}, by severity">
		{#if !snapshot || snapshot.status === 'loading'}
			<CardState state="loading" title="Loading alert counts" />
		{:else if !counts}
			<CardState state="error" title="Couldn't load the alert counts: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			{#if snapshot.status === 'error'}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('the alert counts', true)}</span></p>
			{/if}
			<div class="sev-sum">
				<div class="sev-left">
					<div class="sev-counts" style:--sev-chars={Math.max(...buckets.map((b) => fmt(b.count).length))}>
						{#each buckets as b (b.level)}
							<button class="sev-tile" type="button" aria-label="Show {b.level} alerts ({fmt(b.count)})" onclick={() => showSeverity(b.level as SeverityFilter)}>
								<SeverityPill level={b.level} count={b.count} />
							</button>
						{/each}
					</div>
				</div>
				<SeverityGauge {buckets} total={counts.total} ariaLabel={gaugeLabel} />
			</div>
			<!-- NET-191: ET's informational ratings are stored as activity, never counted above -->
			{#if activityCount && activityCount.total > 0}
				<button class="link activity-link" type="button" onclick={showActivity}>
					{fmt(activityCount.total)} informational {activityCount.total === 1 ? 'event' : 'events'} not counted · Show
				</button>
			{/if}
		{/if}
	</Card>
</div>

<div class="grid alert-layout" class:no-drawer={!drawerAlert}>
	<!-- OLD CODE: <Card class="c-8 alert-list-card" title={view === 'category' ? 'Alerts by category' : 'All alerts'} sub={listLoaded && !failed.alerts ? `${fmt(totalAlerts)} matching · ${range.words}${view === 'category' && totalAlerts > 0 ? ` · alerts ${fmt(fromRow)} to ${fmt(toRow)}, grouped` : ''}` : range.words}> (NET-191: the activity note) -->
	<Card class="c-8 alert-list-card" title={view === 'category' ? 'Alerts by category' : 'All alerts'} sub={`${listLoaded && !failed.alerts ? `${fmt(totalAlerts)} matching · ${range.words}${view === 'category' && totalAlerts > 0 ? ` · alerts ${fmt(fromRow)} to ${fmt(toRow)}, grouped` : ''}` : range.words}${activityFilter ? ' · ET rates these informational. They are not counted as alerts.' : ''}`}>
		{#snippet actions()}
			<Pills
				options={[{ value: 'category', label: 'By category' }, { value: 'all', label: 'All alerts' }]}
				bind:value={view}
				ariaLabel="Alert list view"
			/>
		{/snippet}
		<div id="alerts-table">
			<div class="toolbar">
				<Pills options={severityOptions} value={activeFilter} onchange={handleSeverityChange} ariaLabel="Severity" />
				{#if signatureFilter}
					<span class="chip">
						Signature: <span class="mono">{signatureFilter.length > 40 ? signatureFilter.slice(0, 40) + '…' : signatureFilter}</span>
						<button class="chip-x" type="button" onclick={clearSignatureFilter} aria-label="Clear signature filter"><Icon name="close" /></button>
					</span>
				{/if}
				{#if ipFilter}
					<span class="chip">
						IP: <span class="mono">{ipFilter}</span>
						<!-- OLD CODE: onclick={() => goto('/alerts')} (slice 2a: cleared every other filter and the window too) -->
						<button class="chip-x" type="button" onclick={() => setListParams({ ip: null })} aria-label="Clear IP filter"><Icon name="close" /></button>
					</span>
				{/if}
				{#if srcFilter}
					<span class="chip">
						From <span class="mono">{srcFilter}</span>
						<button class="chip-x" type="button" onclick={() => setListParams({ src: null })} aria-label="Clear source filter"><Icon name="close" /></button>
					</span>
				{/if}
				{#if dstFilter}
					<span class="chip">
						To <span class="mono">{dstFilter}</span>
						<button class="chip-x" type="button" onclick={() => setListParams({ dst: null })} aria-label="Clear destination filter"><Icon name="close" /></button>
					</span>
				{/if}
				{#if suricataCategoryFilter}
					<span class="chip">
						Suricata category: {suricataCategoryFilter.length > 40 ? suricataCategoryFilter.slice(0, 40) + '…' : suricataCategoryFilter}
						<button class="chip-x" type="button" onclick={() => setListParams({ suricata_category: null })} aria-label="Clear Suricata category filter"><Icon name="close" /></button>
					</span>
				{/if}
				{#if activityFilter}
					<span class="chip">
						Activity: rated informational by ET
						<button class="chip-x" type="button" onclick={() => setListParams({ activity: null })} aria-label="Clear activity filter"><Icon name="close" /></button>
					</span>
				{/if}
			</div>
			{#if actionError}
				<p class="notice is-error" role="alert"><Icon name="warn" />Not applied: {actionError}</p>
			{/if}
			<!-- NET-160 section D: the link's figure, when this search's own total differs from it -->
			{#if countLine}
				<p class="notice" role="status">{countLine}</p>
			{/if}
			{#if !listLoaded}
				<CardState state="loading" title="Loading alerts" />
			{:else if failed.alerts}
				<CardState state="error" title="Couldn't load alerts: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => fetchAlerts(currentPage)} />
			{:else if alerts.length === 0 && activityFilter}
				<CardState state="empty" icon="alerts" title="No activity" message="Nothing ET rates informational matched in this window." />
			{:else if alerts.length === 0}
				<CardState state="empty" icon="alerts" title="No alerts" message="Alerts will appear here once Suricata is running and generating detections." />
			{:else if view === 'category'}
				{#each groups as group (group.title)}
					<!-- OLD CODE: <AlertGroup title={group.title} count={group.count}> (slice 2b-2: the title opens its category's page) -->
					<!-- OLD CODE: href={groupCategoryLinked(sortedAlerts, group.title) ? … : undefined} (NET-191: not from the activity list; the category page counts only counted alerts) -->
					<AlertGroup title={group.title} count={group.count} href={!activityFilter && groupCategoryLinked(sortedAlerts, group.title) ? suricataCategoryHref(group.title, shownWindow) : undefined}>
						{#each group.lines as line (line.key)}
							<AlertRow
								severity={line.level}
								title={alertTitle(line.alert)}
								signature={line.alert.alert?.signature || 'Unknown'}
								device={line.alert.src_ip ? { name: line.alert.src_ip } : undefined}
								count={line.count}
								lastSeen={shortSeen(line.lastSeen)}
								selected={drawerAlert?._id === line.alert._id}
								onselect={() => openDrawer(line.alert)}
							/>
						{/each}
					</AlertGroup>
				{/each}
			{:else}
				<DataTable
					{columns}
					rows={sortedAlerts}
					ariaLabel="Alerts, newest first unless sorted"
					{rowKey}
					initialSort={{ key: sortKey, dir: sortDir }}
					onsortchange={changeSort}
					onrowactivate={openDrawer}
					rowLabel={(a) => `Open alert ${a.alert?.signature || 'Unknown'}${a.src_ip ? ` from ${a.src_ip}` : ''}`}
					selectedKey={selectedRowKey}
					pager={totalPages > 1 ? { page: currentPage, pageCount: totalPages, total: totalAlerts, from: fromRow, to: toRow, onpage: goToPage, disabled: listPending } : undefined}
				/>
			{/if}
		</div>
	</Card>
	{#if drawerAlert}
		{@const open = drawerAlert}
		{#key open._id}
			<AlertDetail
				alert={open}
				activity={activityFilter}
				onclose={closeDrawer}
				onacknowledge={() => handleDrawerAcknowledge(open._id)}
				onsuppress={() => drawerAction(open, (sigId) => suppressAlert(sigId))}
				onfalsepositive={() => drawerAction(open, (sigId) => markFalsePositive(sigId))}
			/>
		{/key}
	{/if}
</div>

<div class="grid">
	<!-- OLD CODE: sub="Alerts per {INTERVAL_MAP[selectedTimeRange] ?? '1h'} · …" (slice 2a: Custom has no entry) -->
	<Card class="c-8" hero col title="Alert timeline" sub="Alerts per {range.interval} · {range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading the alert timeline" />
		{:else if failed.timeline}
			<CardState state="error" title="Couldn't load the alert timeline: the request failed." onaction={() => refresh.run()} />
		{:else if timeline.length === 0}
			<CardState state="empty" title="No timeline data yet" message="The timeline fills in once Suricata reports alerts in this window." />
		{:else}
			<AreaChart
				series={[{ key: 'alerts', label: 'Alerts', colour: 1, points: timeline.map((b, i) => ({ t: b.timestamp, v: timelineTotals[i] })) }]}
				formatX={(t) => formatShortTimestamp(String(t))}
				formatY={(v) => fmt(v)}
				formatTip={(i) => `${formatShortTimestamp(timeline[i].timestamp)} · ${fmt(timelineTotals[i])} alerts · High ${fmt(timeline[i].high)} · Medium ${fmt(timeline[i].medium)} · Low ${fmt(timeline[i].low)} · Info ${fmt(timeline[i].info ?? 0)}`}
				highlightIndex={busiest}
				ariaLabel={timelineLabel}
			/>
		{/if}
	</Card>

	<Card class="c-4" title="Threat summary" sub="Smart alert analysis · {range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading the threat summary" />
		{:else if failed.summary || !smartSummary}
			<CardState state="error" title="Couldn't load the threat summary: the request failed." onaction={() => refresh.run()} />
		{:else}
			<!-- OLD CODE: <div class="threat-top"> (NET-192: a copy of the system .trust-top) -->
			<div class="trust-top">
				<!-- OLD CODE: <Ring value={threatScore} label="threat score" …> (NET-164: read as a bare number; Ring's default label states the scale) -->
				<Ring value={threatScore} ariaLabel="Threat score {threatScore} of 100, level {threatLevel}" />
				<div class="chips">
					{#if threatPill}<SeverityPill level={threatPill} />{:else}<span class="chip">No threat level</span>{/if}
					<span class="chip">{fmt(smartSummary.total_groups)} alert groups</span>
				</div>
			</div>
			<p class="dim score-how">{THREAT_SCORE_HOW}</p>
			{#if smartCategories.length > 0}
				<ul class="kv">
					{#each smartCategories as c (c.key)}
						<li><span>{c.label}</span><span></span><b>{fmt(c.events)}</b><span class="pct">events</span></li>
					{/each}
				</ul>
			{:else}
				<p class="dim">No actionable alert groups in this window.</p>
			{/if}
		{/if}
	</Card>

	<Card class="c-4" title="Alert categories" sub={failed.categories ? 'Check failed' : `${enhancedCategories.length} categories · alerts per category · ${range.words}`}>
		{#if !loaded}
			<CardState state="loading" title="Loading alert categories" />
		{:else if failed.categories}
			<CardState state="error" title="Couldn't load alert categories: the request failed." onaction={() => refresh.run()} />
		{:else if enhancedCategories.length === 0}
			<CardState state="empty" title="No category data yet" message="Categories appear once Suricata reports alerts in this window." />
		{:else}
			<BarList
				items={enhancedCategories.map((cat) => ({
					key: cat.id,
					label: cat.label,
					value: cat.count,
					display: formatNumber(cat.count),
					detail: cat.trend.direction === 'stable' ? undefined : cat.trend.direction,
					href: `/alerts/${cat.id}`,
				}))}
			/>
		{/if}
	</Card>

	<!-- OLD CODE: sub={failed.signatures ? 'Check failed' : `${topSignatures.length} rules · alerts per rule · select one to filter the list`} (NET-160: a partial list says so) -->
	<Card class="c-8" title="Top signatures" sub={failed.signatures ? 'Check failed' : `${topPartial.signatures ?? `${topSignatures.length} rules`} · alerts per rule · select one to filter the list`}>
		{#snippet actions()}
			<SearchField id="alerts-signature-search" label="Search signatures" placeholder="Search signatures…" size="toolbar" bind:value={signatureSearch} />
		{/snippet}
		{#if !loaded}
			<CardState state="loading" title="Loading top signatures" />
		{:else if failed.signatures}
			<CardState state="error" title="Couldn't load top signatures: the request failed." onaction={() => refresh.run()} />
		{:else if filteredSignatures.length === 0}
			<CardState state="empty" title="No signatures found" message={signatureSearch ? 'No rule matches that search.' : 'Rules appear here once Suricata reports alerts in this window.'} />
		{:else}
			<!-- OLD CODE: rowKey={(s) => s.signature} onrowactivate={(s) => filterBySignature(s.signature)} (a null or empty rule name is a plain row with its own key) -->
			<DataTable
				columns={signatureColumns}
				rows={filteredSignatures}
				ariaLabel="Top signatures"
				rowKey={sigRowKey}
				initialSort={{ key: 'count', dir: 'desc' }}
				onrowactivate={(s) => s.signature && filterBySignature(s.signature)}
				rowActivatable={(s) => !!s.signature}
				rowLabel={(s) => (signatureFilter === s.signature ? `Clear the filter for ${s.signature}` : `Filter alerts by ${s.signature}`)}
				selectedKey={signatureFilter || undefined}
			/>
		{/if}
	</Card>

	<!-- OLD CODE: sub="Alerts per destination · {range.words}" (NET-160: a partial list says so) -->
	<Card class="c-6 ip-bars" title="Top affected devices" sub="Alerts per destination · {topPartial.destIps ? `${topPartial.destIps} · ` : ''}{range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading affected devices" />
		{:else if failed.destIps}
			<CardState state="error" title="Couldn't load affected devices: the request failed." onaction={() => refresh.run()} />
		{:else if topDestIps.length === 0}
			<CardState state="empty" title="No destination IPs found" message="Devices appear here once alerts name them as the destination." />
		{:else}
			<BarList items={ipBars(topDestIps)} />
		{/if}
	</Card>

	<!-- OLD CODE: sub="Alerts per source · {range.words}" (NET-160: a partial list says so) -->
	<Card class="c-6 ip-bars" title="Top source IPs" sub="Alerts per source · {topPartial.srcIps ? `${topPartial.srcIps} · ` : ''}{range.words}">
		{#if !loaded}
			<CardState state="loading" title="Loading source IPs" />
		{:else if failed.srcIps}
			<CardState state="error" title="Couldn't load source IPs: the request failed." onaction={() => refresh.run()} />
		{:else if topSrcIps.length === 0}
			<CardState state="empty" title="No source IPs found" message="Sources appear here once alerts name them." />
		{:else}
			<BarList items={ipBars(topSrcIps)} />
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.alert-layout { align-items: start; }
	.sev-tile {
		all: unset; display: flex; cursor: pointer; color: var(--text-1); border-radius: var(--r-md);
	}
	.sev-tile > :global(.sev-count) { flex: 1; transition: background var(--dur-fast); }
	.sev-tile:hover > :global(.sev-count) { background: var(--surface-3); }
	.sev-tile:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.chip-x {
		all: unset; display: inline-grid; place-items: center; cursor: pointer; color: var(--text-2); border-radius: var(--r-pill);
	}
	.chip-x:hover { color: var(--text-1); }
	.chip-x:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	/* .link sets the text colour; a button needs the browser's own box taken off */
	.activity-link { background: none; border: 0; padding: 0; margin-top: var(--sp-4); cursor: pointer; }
	.activity-link:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.notice { margin-bottom: var(--sp-4); }
	.cat-cell { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); }
	.row-actions { display: inline-flex; gap: var(--sp-1); }
	.row-actions .btn { min-height: 28px; padding: 0 var(--sp-3); font-size: var(--text-xs); }
	/* OLD CODE START — NET-192: the system .trust-top replaces .threat-top; its margin moves to .score-how
	.threat-top { display: flex; align-items: center; gap: var(--sp-5); margin-bottom: var(--sp-4); }
	.score-how { margin: 0 0 var(--sp-4); font-size: var(--text-xs); }
	OLD CODE END */
	.score-how { margin: var(--sp-4) 0; font-size: var(--text-xs); }
	:global(.ip-bars) :global(.bar-label), :global(.ip-bars) :global(.bars li > span:first-child) { font-family: var(--font-mono); }
</style>
