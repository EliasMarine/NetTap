<script lang="ts">
	import { onDestroy, untrack, type Snippet } from 'svelte';
	import { page } from '$app/stores';
	import IPAddress from '$components/IPAddress.svelte';
	// OLD CODE: import { isIpAddress } from '$lib/stores/lan'; (slice 2a: domain cells and the drawer's source link)
	import { domainHref, ipHref, isIpAddress } from '$lib/stores/lan';
	// OLD CODE: import { canonicalName, customRange, isHostName, type CustomWindow, type DrillWindow } from '$lib/utils/drilldown'; (NET-160 section D: the figure clicked)
	import {
		canonicalName,
		countDifference,
		customRange,
		fmt,
		DRILL_RANGES,
		isHostName,
		linkedCount,
		pickedTotal,
		pickWindow,
		startRange,
		windowQuery,
		withCount,
		type CustomWindow,
		type DrillRangeValue,
		type DrillWindow,
		type LinkedCount,
		type TimeChart,
	} from '$lib/utils/drilldown';
	import { toTimeChart } from '$lib/utils/chart-pick';
	// OLD CODE START — replaced by the design system's BarList
	// import HorizontalBarList from '$components/HorizontalBarList.svelte';
	// OLD CODE END
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import LogDrawerContent from '$components/drawer/content/LogDrawerContent.svelte';
	import { goto } from '$app/navigation';
	import { getWhois } from '$api/lookup';
	import { loadFailed } from '$lib/utils/load-failed';
	import { partOfWhole } from '$lib/utils/part-of-whole';
	import {
		getLogStats,
		getLogTimeline,
		getLogTopTalkers,
		getLogProtocolBreakdown,
		getLogTopDestinations,
		getLogTopDns,
		formatBytes,
		formatCompactNumber,
		// OLD CODE START — the chart and bars use the system's data colours
		// protocolColor,
		// OLD CODE END
		protocolLabel,
	} from '$lib/api/logs';
	import type {
		LogTimelineBucket,
		LogTalkerEntry,
		LogProtocolEntry,
		LogDestinationEntry,
		LogDnsEntry,
	} from '$lib/api/logs';
	import type { SortDir } from '$lib/utils/table-sort.svelte';
	import { createLoadGuard, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import AutoRefreshButton from '$lib/components/ui/AutoRefreshButton.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import { formatTime } from '$lib/utils/time';

	// ---------------------------------------------------------------------------
	// Types
	// ---------------------------------------------------------------------------

	interface LogHit {
		_id: string;
		_source: Record<string, unknown>;
		sort?: unknown[];
	}

	interface SearchResponse {
		hits: LogHit[];
		total: number;
		search_after?: unknown[];
	}

	interface FieldDef {
		name: string;
		type: string;
		description: string;
	}

	type LogType = 'all' | 'zeek.conn' | 'zeek.dns' | 'zeek.http' | 'zeek.tls' | 'zeek.files' | 'zeek.dhcp' | 'zeek.smtp' | 'suricata';
	// OLD CODE: type TimeRange = '15m' | '1h' | '4h' | '24h' | '7d' | '30d'; (slice 2b-1: 6h, as Home has)
	// OLD CODE: type TimeRange = '15m' | '1h' | '4h' | '6h' | '24h' | '7d' | '30d'; (NET-192 PR 4: Home's five)
	// OLD CODE: type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d'; (NET-196: the app's one list's type)
	type TimeRange = DrillRangeValue;

	/** A table row: each column's display text by field, plus the hit the drawer opens. */
	type LogRow = { _id: string; hit: LogHit } & Record<string, unknown>;

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const COLUMNS: Record<LogType, string[]> = {
		all: ['@timestamp', 'source.ip', 'destination.ip', 'network.transport', 'event.dataset', 'event.provider'],
		'zeek.conn': ['@timestamp', 'source.ip', 'source.port', 'destination.ip', 'destination.port', 'network.transport', 'event.duration', 'source.bytes', 'destination.bytes', 'zeek.conn.conn_state'],
		'zeek.dns': ['@timestamp', 'source.ip', 'zeek.dns.query', 'zeek.dns.qtype_name', 'zeek.dns.rcode_name', 'zeek.dns.answers'],
		'zeek.http': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.http.method', 'zeek.http.host', 'zeek.http.uri', 'zeek.http.status_code'],
		// OLD CODE START — I6: Malcolm writes zeek.ssl.*, zeek.dhcp.host_name/assigned_ip and source.mac; these columns read --
		// 'zeek.tls': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.tls.server_name', 'zeek.tls.version', 'zeek.tls.cipher', 'zeek.tls.established'],
		// 'zeek.dhcp': ['@timestamp', 'source.ip', 'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.dhcp.hostname', 'zeek.dhcp.msg_types'],
		// OLD CODE END
		'zeek.tls': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.ssl.server_name', 'zeek.ssl.ssl_version', 'zeek.ssl.cipher', 'zeek.ssl.established'],
		'zeek.files': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.files.filename', 'zeek.files.mime_type', 'zeek.files.total_bytes'],
		'zeek.dhcp': ['@timestamp', 'source.ip', 'zeek.dhcp.assigned_ip', 'source.mac', 'zeek.dhcp.host_name', 'zeek.dhcp.msg_types'],
		'zeek.smtp': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.smtp.mailfrom', 'zeek.smtp.rcptto', 'zeek.smtp.subject'],
		suricata: ['@timestamp', 'source.ip', 'destination.ip', 'suricata.alert.signature', 'suricata.alert.severity', 'suricata.alert.category'],
	};

	// OLD CODE START — sentence case (design system voice)
	// const LOG_TYPE_LABELS: Record<LogType, string> = {
	// 	all: 'All Logs',
	// OLD CODE END
	const LOG_TYPE_LABELS: Record<LogType, string> = {
		all: 'All logs',
		'zeek.conn': 'Connections',
		'zeek.dns': 'DNS',
		'zeek.http': 'HTTP',
		'zeek.tls': 'TLS',
		'zeek.files': 'Files',
		'zeek.dhcp': 'DHCP',
		'zeek.smtp': 'SMTP',
		suricata: 'Suricata',
	};

	// One range set across the app (NET-192 PR 4): 1h 6h 24h 7d 30d, as on Home. Live is the real-time page.
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES), with this page's ms beside it
	// const TIME_RANGES: { value: TimeRange; label: string; ms: number; words: string }[] = [
	// 	// OLD CODE: { value: '15m', label: '15m', ms: 15 * 60_000, words: 'last 15 minutes' }, (NET-192 PR 4)
	// 	{ value: '1h', label: '1h', ms: 60 * 60_000, words: 'last hour' },
	// 	// OLD CODE: { value: '4h', label: '4h', ms: 4 * 60 * 60_000, words: 'last 4 hours' }, (NET-192 PR 4)
	// 	{ value: '6h', label: '6h', ms: 6 * 60 * 60_000, words: 'last 6 hours' },
	// 	{ value: '24h', label: '24h', ms: 24 * 60 * 60_000, words: 'last 24 hours' },
	// 	{ value: '7d', label: '7d', ms: 7 * 24 * 60 * 60_000, words: 'last 7 days' },
	// 	{ value: '30d', label: '30d', ms: 30 * 24 * 60 * 60_000, words: 'last 30 days' },
	// ];
	// OLD CODE END
	const TIME_RANGES = DRILL_RANGES.map((r) => ({ ...r, ms: r.hours * 3_600_000 }));

	// OLD CODE START — NET-249 slice 2: the timeline's bucket and its words come from the owner's table (DRILL_RANGES)
	// const INTERVAL_MAP: Record<string, string> = {
	// 	// OLD CODE: '15m': '1m', (NET-192 PR 4)
	// 	'1h': '5m',
	// 	// OLD CODE: '4h': '15m', (NET-192 PR 4)
	// 	'6h': '15m',
	// 	'24h': '1h',
	// 	'7d': '6h',
	// 	'30d': '1d',
	// };
	//
	// /** How the timeline card names each INTERVAL_MAP bucket. */
	// const INTERVAL_WORDS: Record<string, string> = {
	// 	'1m': 'minute',
	// 	'5m': '5 minutes',
	// 	'15m': '15 minutes',
	// 	'1h': 'hour',
	// 	'6h': '6 hours',
	// 	'1d': 'day',
	// };
	// OLD CODE END

	// OLD CODE START — I6: the DHCP and TLS field names Malcolm doesn't write
	// const IP_FIELDS = new Set(['source.ip', 'destination.ip', 'zeek.dhcp.client_addr']);
	// const MONO_FIELDS = new Set([
	// 	'source.ip', 'destination.ip', 'source.port', 'destination.port',
	// 	'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.http.status_code',
	// 	'zeek.tls.version', 'source.bytes', 'destination.bytes', 'event.duration',
	// 	'suricata.alert.severity', 'zeek.files.total_bytes',
	// ]);
	// OLD CODE END
	const IP_FIELDS = new Set(['source.ip', 'destination.ip', 'zeek.dhcp.assigned_ip']);
	const MONO_FIELDS = new Set([
		'source.ip', 'destination.ip', 'source.port', 'destination.port',
		'zeek.dhcp.assigned_ip', 'source.mac', 'zeek.http.status_code',
		'zeek.ssl.ssl_version', 'source.bytes', 'destination.bytes', 'event.duration',
		'suricata.alert.severity', 'zeek.files.total_bytes',
	]);
	/** Right-aligned, tabular columns (design system: numbers in tables). */
	const NUMERIC_FIELDS = new Set([
		'source.port', 'destination.port', 'source.bytes', 'destination.bytes', 'event.duration',
		'zeek.http.status_code', 'suricata.alert.severity', 'zeek.files.total_bytes',
	]);

	// OLD CODE START — I5: the timeline plots the daemon's per-slot total now, not a sum of these
	// // Protocol types used for timeline stacking (order matters for visual stacking)
	// // Alert data is excluded from log explorer aggregations (has its own Alerts page)
	// const PROTOCOL_KEYS = ['conn', 'dns', 'http', 'ssl', 'files', 'dhcp', 'smtp'] as const;
	// OLD CODE END

	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let initialized = $state(false);
	let loading = $state(false);
	// OLD CODE: let selectedTimeRange = $state<TimeRange>('24h'); (slice 2a: a link's exact window shows as "Custom")
	// OLD CODE: let selectedTimeRange = $state<TimeRange | 'custom'>('24h'); (NET-195: Settings › Display's default, read where the range starts)
	let selectedTimeRange = $state<TimeRange | 'custom'>(startRange('24h'));
	/** The window a drill-down link brought (?from=&to=), offered as "Custom" until another range is picked. */
	let custom = $state<CustomWindow | null>(null);
	const AUTO_REFRESH_MS = 30_000;
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Aggregation data
	let totalEvents = $state(0);
	let uniqueSources = $state(0);
	let protocolCount = $state(0);
	let totalBytesVal = $state(0);
	let timeline = $state<LogTimelineBucket[]>([]);
	/** The timeline reply on screen as a pickable chart (NET-249); null when its echoed bucket or window can't be picked */
	let timelineChart = $state<TimeChart | null>(null);
	let topTalkers = $state<LogTalkerEntry[]>([]);
	let protocols = $state<LogProtocolEntry[]>([]);
	// A busy box logs 20+ protocols; all of them made the card three times the timeline's height
	let showAllProtocols = $state(false);
	const PROTOCOLS_SHOWN = 10;
	/** The daemon's protocol-breakdown terms size: a full list may be cut off, so it has no total (I5). */
	const PROTOCOL_CAP = 20;
	const protocolsCapped = $derived(protocols.length >= PROTOCOL_CAP);
	let topDestinations = $state<LogDestinationEntry[]>([]);
	let topDns = $state<LogDnsEntry[]>([]);
	// #96: a failed section keeps its last good figures and says so; it never reads as 0 or "No data"
	let statsLoaded = $state(false);
	let statsFailed = $state(false);
	let timelineFailed = $state(false);
	let talkersFailed = $state(false);
	let protocolsFailed = $state(false);
	let destinationsFailed = $state(false);
	let dnsFailed = $state(false);

	// Log table state
	let logType = $state<LogType>('all');
	let query = $state('');
	let results = $state<LogHit[]>([]);
	let totalHits = $state(0);
	let tableLoading = $state(false);
	let error = $state('');
	let searchAfter = $state<unknown[] | undefined>(undefined);
	let loadingMore = $state(false);
	let sortField = $state('@timestamp');
	let sortDir = $state<'desc' | 'asc'>('desc');
	/** The window of the rows on screen: "load more" pages within it, and the drawer reads from it. */
	let tableWindow = $state<DrillWindow | null>(null);
	// OLD CODE START — replaced by DetailDrawer
	// let expandedRow = $state<string | null>(null);
	// let fullDoc = $state<Record<string, unknown> | null>(null);
	// let fullDocLoading = $state(false);
	// let copySuccess = $state(false);
	// OLD CODE END

	// Detail drawer state
	let drawerHit = $state<LogHit | null>(null);
	let drawerTab = $state('fields');
	const LOG_DRAWER_TABS = [
		{ id: 'fields', label: 'Fields' },
		{ id: 'raw', label: 'Raw JSON' },
	];
	// field descriptions, shown as the table headers' hover text
	let fieldDefs = $state<Record<string, string>>({});

	// Active filters from chart clicks
	let activeIpFilter = $state('');
	/** The side the IP filter matches: a top source or destination bar's one side, null for either (NET-184) */
	let ipSide = $state<'source.ip' | 'destination.ip' | null>(null);
	/** The windows the Top sources and Top destinations figures on screen came from (NET-184) */
	let talkersWindow = $state<DrillWindow | null>(null);
	let destinationsWindow = $state<DrillWindow | null>(null);
	/** The window of the latest table search (set when it starts): a sort keeps it (NET-184) */
	let searchWindow: DrillWindow | undefined;
	/** The search-box text the latest table search ran: a sort and "load more" keep it, not unsubmitted text (NET-184) */
	let searchText = '';
	let activeDnsFilter = $state('');
	/** Sources a link's count left out (?exclude_src=, Home's Connections, NET-160 slice 2b-1) */
	let excludeSrc = $state<string[]>([]);

	/** A counted link's figure (?count=) against the total of the one search its hand-off started (NET-160 section D). */
	let linked = $state<LinkedCount | null>(null);
	const countLine = $derived(
		linked?.observed != null
			? countDifference(linked.expected, linked.observed, { lead: 'This search now matches', one: 'record', many: 'records' })
			: null,
	);

	// OLD CODE START — the hand-drawn stacked chart's hover and width; AreaChart handles both
	// // Chart interaction
	// let hoveredBarIndex = $state<number | null>(null);
	// let chartWidth = $state(800);
	// let tooltipX = $state(0);
	// let tooltipBucket = $state<LogTimelineBucket | null>(null);
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	// OLD CODE START — the stacked chart's scale; AreaChart fits its own axis to the totals below
	// let maxBucketTotal = $derived(
	// 	Math.max(1, ...timeline.map((b) => {
	// 		let sum = 0;
	// 		for (const k of PROTOCOL_KEYS) sum += (b[k] || 0);
	// 		return sum;
	// 	}))
	// );
	// OLD CODE END
	/** Events per bucket across the protocols the chart used to stack. */
	// OLD CODE START — I5: seven named types only, so any other dataset in the slot was left out
	// const bucketTotals = $derived(timeline.map((b) => PROTOCOL_KEYS.reduce((sum, k) => sum + (b[k] || 0), 0)));
	// OLD CODE END
	const bucketTotals = $derived(timeline.map((b) => b.total));
	const busiest = $derived(bucketTotals.reduce((best, v, i) => (v > (bucketTotals[best] ?? -1) ? i : best), -1));

	// OLD CODE START — max values now computed internally by HorizontalBarList component
	// let maxTalkerCount = $derived(topTalkers.length > 0 ? topTalkers[0].count : 1);
	// let maxProtocolCount = $derived(protocols.length > 0 ? Math.max(1, ...protocols.map((p) => p.count)) : 1);
	// let maxDestCount = $derived(topDestinations.length > 0 ? topDestinations[0].count : 1);
	// let maxDnsCount = $derived(topDns.length > 0 ? topDns[0].count : 1);
	// OLD CODE END

	// OLD CODE: let hasActiveFilters = $derived(activeIpFilter !== '' || activeDnsFilter !== '' || logType !== 'all'); (slice 2b-1: excluded sources)
	let hasActiveFilters = $derived(activeIpFilter !== '' || activeDnsFilter !== '' || logType !== 'all' || excludeSrc.length > 0);

	// OLD CODE: const rangeWords = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange)?.words ?? 'last 24 hours'); (slice 2a: Custom)
	const rangeWords = $derived(
		selectedTimeRange === 'custom' && custom ? custom.words : (TIME_RANGES.find((r) => r.value === selectedTimeRange)?.words ?? 'last 24 hours'),
	);
	/** The range whose timeline bucket the window uses: for Custom, the smallest standard range that covers it. */
	const intervalRange = $derived(
		selectedTimeRange === 'custom' ? (TIME_RANGES.find((r) => custom && r.ms >= custom.hours * 3_600_000) ?? TIME_RANGES[TIME_RANGES.length - 1]).value : selectedTimeRange,
	);
	/** The table's bucket for that range (NET-249): 1h by the minute … 30d by 3 hours. */
	const bucket = $derived(TIME_RANGES.find((r) => r.value === intervalRange) ?? TIME_RANGES.find((r) => r.value === '24h')!);
	const rangeOptions = $derived([...TIME_RANGES, ...(custom ? [{ value: 'custom' as const, label: custom.label }] : [])]);

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE: function getTimeRange(rangeValue: TimeRange = selectedTimeRange): { from: string; to: string } { (slice 2a: Custom)
	/** The window a load covers: the Custom window as the link gave it, otherwise the range ending now. */
	function getTimeRange(rangeValue: TimeRange | 'custom' = selectedTimeRange): DrillWindow {
		if (rangeValue === 'custom' && custom) return { from: custom.from, to: custom.to };
		const now = Date.now();
		// OLD CODE: || TIME_RANGES[3]; (slice 2b-1: 6h moved 24h to index 4)
		// OLD CODE: || TIME_RANGES[4]; (NET-192 PR 4: 15m and 4h dropped, 24h is index 2)
		// OLD CODE: || TIME_RANGES[2] (NET-192 PR 4: the default by value, not by position)
		const range = TIME_RANGES.find((r) => r.value === rangeValue) || TIME_RANGES.find((r) => r.value === '24h')!;
		return {
			from: new Date(now - range.ms).toISOString(),
			to: new Date(now).toISOString(),
		};
	}

	// OLD CODE START — slice 2a: the table and the drawer read the window of the rows on screen (tableWindow)
	// function timeRangeToISO(range: TimeRange): string {
	// 	const now = Date.now();
	// 	const tr = TIME_RANGES.find((r) => r.value === range);
	// 	return new Date(now - (tr?.ms || 24 * 60 * 60_000)).toISOString();
	// }
	// OLD CODE END

	// OLD CODE START — US month-first order, "Nov 6, 22:37:23" (NET-192 PR 4: formatTime)
	// function formatTimestamp(ts: string): string {
	// 	try {
	// 		const d = new Date(ts);
	// 		const mon = d.toLocaleString('en-US', { month: 'short' });
	// 		const day = d.getDate();
	// 		const time = d.toLocaleTimeString('en-US', { hour12: false });
	// 		return `${mon} ${day}, ${time}`;
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

	function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
		const parts = path.split('.');
		let current: unknown = obj;
		for (const part of parts) {
			if (current == null || typeof current !== 'object') return undefined;
			current = (current as Record<string, unknown>)[part];
		}
		return current;
	}

	function formatCellValue(field: string, value: unknown): string {
		if (value == null || value === '') return '--';
		if (field === '@timestamp' && typeof value === 'string') return formatTimestamp(value);
		if (Array.isArray(value)) return value.join(', ');
		if (typeof value === 'object') return JSON.stringify(value);
		return String(value);
	}

	function shortFieldName(field: string): string {
		const parts = field.split('.');
		if (parts.length <= 2) return field;
		return parts.slice(-2).join('.');
	}

	function copyToClipboard(text: string, e: Event) {
		e.stopPropagation();
		navigator.clipboard.writeText(text);
	}

	// Map log type tab keys to event.dataset filter values
	const LOG_TYPE_TO_DATASET: Record<string, string> = {
		'zeek.conn': 'conn',
		'zeek.dns': 'dns',
		'zeek.http': 'http',
		'zeek.tls': 'ssl',
		'zeek.files': 'files',
		'zeek.dhcp': 'dhcp',
		'zeek.smtp': 'smtp',
		suricata: 'alert',
	};

	// Reverse: dataset → log type
	const DATASET_TO_LOG_TYPE: Record<string, LogType> = {
		conn: 'zeek.conn',
		dns: 'zeek.dns',
		http: 'zeek.http',
		ssl: 'zeek.tls',
		files: 'zeek.files',
		dhcp: 'zeek.dhcp',
		smtp: 'zeek.smtp',
		alert: 'suricata',
	};

	// ---------------------------------------------------------------------------
	// Data fetching — aggregations
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN §5.5: the guarded version below drops an older range's answers
	// async function fetchDashboard() {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	const interval = INTERVAL_MAP[selectedTimeRange] || '1h';
	//
	// 	const results = await Promise.allSettled([
	// 		getLogStats({ from, to }),
	// 		getLogTimeline({ from, to, interval }),
	// 		getLogTopTalkers({ from, to, limit: 10 }),
	// 		getLogProtocolBreakdown({ from, to }),
	// 		getLogTopDestinations({ from, to, limit: 10 }),
	// 		getLogTopDns({ from, to, limit: 10 }),
	// 	]);
	//
	// 	if (results[0].status === 'fulfilled') {
	// 		const s = results[0].value;
	// 		totalEvents = s.total_events;
	// 		uniqueSources = s.unique_sources;
	// 		protocolCount = s.protocol_count;
	// 		totalBytesVal = s.total_bytes;
	// 		statsLoaded = true;
	// 	}
	// 	if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
	// 	if (results[2].status === 'fulfilled') topTalkers = results[2].value.talkers;
	// 	if (results[3].status === 'fulfilled') protocols = results[3].value.protocols;
	// 	if (results[4].status === 'fulfilled') topDestinations = results[4].value.destinations;
	// 	if (results[5].status === 'fulfilled') topDns = results[5].value.queries;
	// 	statsFailed = results[0].status === 'rejected';
	// 	timelineFailed = results[1].status === 'rejected';
	// 	talkersFailed = results[2].status === 'rejected';
	// 	protocolsFailed = results[3].status === 'rejected';
	// 	destinationsFailed = results[4].status === 'rejected';
	// 	dnsFailed = results[5].status === 'rejected';
	//
	// 	loading = false;
	// }
	// OLD CODE END
	// OLD CODE START — slice 2a: worked out its own window, a moment apart from the table's
	// /** The six aggregations for the current range; null when a newer load took over. */
	// async function fetchDashboard(guard: LoadGuard, g: number): Promise<boolean[] | null> {
	// 	const range = selectedTimeRange;
	// 	loading = true;
	// 	const { from, to } = getTimeRange(range);
	// 	const interval = INTERVAL_MAP[range] || '1h';
	// OLD CODE END
	/** The six aggregations over `win` (the table's window too); null when a newer load took over. */
	async function fetchDashboard(guard: LoadGuard, g: number, { from, to }: DrillWindow): Promise<boolean[] | null> {
		loading = true;
		// OLD CODE: const interval = INTERVAL_MAP[intervalRange] || '1h'; (NET-249: the owner's table)
		const interval = bucket.bucket;

		const results = await Promise.allSettled([
			getLogStats({ from, to }),
			getLogTimeline({ from, to, interval }),
			getLogTopTalkers({ from, to, limit: 10 }),
			getLogProtocolBreakdown({ from, to }),
			getLogTopDestinations({ from, to, limit: 10 }),
			getLogTopDns({ from, to, limit: 10 }),
		]);
		if (!guard.current(g)) return null;

		if (results[0].status === 'fulfilled') {
			const s = results[0].value;
			totalEvents = s.total_events;
			uniqueSources = s.unique_sources;
			protocolCount = s.protocol_count;
			totalBytesVal = s.total_bytes;
			statsLoaded = true;
		}
		// OLD CODE: if (results[1].status === 'fulfilled') timeline = results[1].value.buckets; (NET-249: a pick needs the reply's window and bucket too)
		if (results[1].status === 'fulfilled') {
			timeline = results[1].value.buckets;
			timelineChart = toTimeChart(results[1].value, timeline.map((b) => b.timestamp), timeline.map((b) => b.total));
		}
		// OLD CODE: if (results[2].status === 'fulfilled') topTalkers = results[2].value.talkers; (NET-184: a bar keeps its window)
		if (results[2].status === 'fulfilled') {
			topTalkers = results[2].value.talkers;
			talkersWindow = { from, to };
		}
		if (results[3].status === 'fulfilled') protocols = results[3].value.protocols;
		// OLD CODE: if (results[4].status === 'fulfilled') topDestinations = results[4].value.destinations; (NET-184)
		if (results[4].status === 'fulfilled') {
			topDestinations = results[4].value.destinations;
			destinationsWindow = { from, to };
		}
		if (results[5].status === 'fulfilled') topDns = results[5].value.queries;
		statsFailed = results[0].status === 'rejected';
		timelineFailed = results[1].status === 'rejected';
		talkersFailed = results[2].status === 'rejected';
		protocolsFailed = results[3].status === 'rejected';
		destinationsFailed = results[4].status === 'rejected';
		dnsFailed = results[5].status === 'rejected';

		loading = false;
		return results.map((r) => r.status === 'fulfilled');
	}

	// ---------------------------------------------------------------------------
	// Data fetching — log table
	// ---------------------------------------------------------------------------

	/** Table loads have their own guard: a search, sort or type change must not cancel the charts. */
	const tableGuard = createLoadGuard();

	// OLD CODE START — PLAN §5.5: an older, slower search could overwrite a newer one
	// async function fetchLogs(append = false) {
	// 	if (append) {
	// 		loadingMore = true;
	// 	} else {
	// 		tableLoading = true;
	// 		searchAfter = undefined;
	// 	}
	// 	error = '';
	//
	// 	try {
	// 		const params = new URLSearchParams();
	// 		if (logType !== 'all') params.set('log_type', logType);
	//
	// 		// Combine search query with active filters
	// 		let fullQuery = query.trim();
	// 		if (activeIpFilter) {
	// 			const ipQ = `(source.ip:"${activeIpFilter}" OR destination.ip:"${activeIpFilter}")`;
	// 			fullQuery = fullQuery ? `${fullQuery} AND ${ipQ}` : ipQ;
	// 		}
	// 		if (activeDnsFilter) {
	// 			const dnsQ = `zeek.dns.query:"${activeDnsFilter}"`;
	// 			fullQuery = fullQuery ? `${fullQuery} AND ${dnsQ}` : dnsQ;
	// 		}
	// 		if (fullQuery) params.set('query', fullQuery);
	//
	// 		params.set('from', timeRangeToISO(selectedTimeRange));
	// 		params.set('to', new Date().toISOString());
	// 		params.set('size', '100');
	// 		params.set('sort', `${sortField}:${sortDir}`);
	// 		if (append && searchAfter) {
	// 			params.set('search_after', JSON.stringify(searchAfter));
	// 		}
	// 		const columns = COLUMNS[logType];
	// 		params.set('fields', columns.join(','));
	//
	// 		const res = await fetch(`/api/logs/search?${params.toString()}`);
	// 		if (!res.ok) {
	// 			const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
	// 			throw new Error(body.error || `HTTP ${res.status}`);
	// 		}
	//
	// 		const data: SearchResponse = await res.json();
	// 		if (append) {
	// 			results = [...results, ...data.hits];
	// 		} else {
	// 			results = data.hits;
	// 		}
	// 		totalHits = data.total;
	// 		searchAfter = data.search_after;
	// 	} catch (e) {
	// 		error = e instanceof Error ? e.message : 'Failed to fetch logs';
	// 		if (!append) results = [];
	// 	} finally {
	// 		tableLoading = false;
	// 		loadingMore = false;
	// 	}
	// }
	// OLD CODE END
	// OLD CODE: async function fetchLogs(append = false): Promise<LoadResult> { (slice 2a: a window per search)
	/** A new search over `win` (a new window when not given), or with `append`, the next page in the rows' window. */
	// OLD CODE: async function fetchLogs(append = false, win?: DrillWindow): Promise<LoadResult> { (NET-184: and the text to search)
	async function fetchLogs(append = false, win?: DrillWindow, text?: string): Promise<LoadResult> {
		const g = tableGuard.begin();
		// The hand-off's own search takes the comparison it set up (gen null); any other search ends it (section D)
		linked = linked?.gen === null ? { ...linked, gen: g } : null;
		// "load more" never moves the window, so no row is listed twice or skipped
		const w = append && tableWindow ? tableWindow : (win ?? getTimeRange());
		if (!append) searchWindow = w;
		const box = append ? searchText : (text ?? query);
		if (!append) searchText = box;
		if (append) {
			loadingMore = true;
		} else {
			tableLoading = true;
			searchAfter = undefined;
		}
		error = '';

		try {
			// Every parameter is read here, before the first await
			const params = new URLSearchParams();
			if (logType !== 'all') params.set('log_type', logType);

			// Combine search query with active filters
			// OLD CODE: let fullQuery = query.trim(); (NET-184: the rows' own text on a sort or "load more")
			let fullQuery = box.trim();
			if (activeIpFilter) {
				// OLD CODE: const ipQ = `(source.ip:"${activeIpFilter}" OR destination.ip:"${activeIpFilter}")`; (NET-184: a bar's one side)
				const ipQ = ipSide ? `${ipSide}:"${activeIpFilter}"` : `(source.ip:"${activeIpFilter}" OR destination.ip:"${activeIpFilter}")`;
				fullQuery = fullQuery ? `${fullQuery} AND ${ipQ}` : ipQ;
			}
			if (activeDnsFilter) {
				const dnsQ = `zeek.dns.query:"${activeDnsFilter}"`;
				fullQuery = fullQuery ? `${fullQuery} AND ${dnsQ}` : dnsQ;
			}
			if (fullQuery) params.set('query', fullQuery);
			// the daemon validates each and leaves them out as the count's must_not did
			if (excludeSrc.length > 0) params.set('exclude_src', excludeSrc.join(','));

			// OLD CODE START — slice 2a: every page worked out a new window
			// params.set('from', timeRangeToISO(selectedTimeRange));
			// params.set('to', new Date().toISOString());
			// OLD CODE END
			params.set('from', w.from);
			params.set('to', w.to);
			params.set('size', '100');
			params.set('sort', `${sortField}:${sortDir}`);
			if (append && searchAfter) {
				params.set('search_after', JSON.stringify(searchAfter));
			}
			const columns = COLUMNS[logType];
			params.set('fields', columns.join(','));

			const res = await fetch(`/api/logs/search?${params.toString()}`);
			if (!res.ok) {
				const body = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
				throw new Error(body.error || `HTTP ${res.status}`);
			}

			const data: SearchResponse = await res.json();
			if (!tableGuard.current(g)) return 'skipped';
			if (append) {
				results = [...results, ...data.hits];
			} else {
				results = data.hits;
			}
			totalHits = data.total;
			if (linked?.gen === g) linked = { ...linked, observed: data.total };
			searchAfter = data.search_after;
			tableWindow = w;
			return 'ok';
		} catch (e) {
			if (!tableGuard.current(g)) return 'skipped';
			error = e instanceof Error ? e.message : 'Failed to fetch logs';
			if (!append) results = [];
			return 'failed';
		} finally {
			if (tableGuard.current(g)) {
				tableLoading = false;
				loadingMore = false;
			}
		}
	}

	async function fetchFieldDefs() {
		const lt = logType === 'all' ? 'zeek.conn' : logType;
		try {
			const res = await fetch(`/api/logs/fields/${lt}`);
			if (!res.ok) return;
			const data: { fields: FieldDef[] } = await res.json();
			// A type picked since this request asked for its own descriptions; an older reply may land after it
			if (lt !== (logType === 'all' ? 'zeek.conn' : logType)) return;
			const map: Record<string, string> = {};
			for (const f of data.fields) {
				// OLD CODE: map[f.field]; the daemon sends `name`, so every description went under "undefined" (NET-146)
				map[f.name] = f.description;
			}
			fieldDefs = map;
		} catch {
			// Optional — tooltips just won't show
		}
	}

	// ---------------------------------------------------------------------------
	// Combined fetch
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN §5.5: the page refresh contract (a result for the top bar)
	// async function fetchAll() {
	// 	await Promise.all([fetchDashboard(), fetchLogs()]);
	// }
	// OLD CODE END
	const refresh = registerPageRefresh(fetchAll);
	onDestroy(() => {
		refresh.unregister();
		tableGuard.invalidate();
		if (refreshInterval) clearInterval(refreshInterval);
	});

	async function fetchAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// OLD CODE: const [dashboard, table] = await Promise.all([fetchDashboard(guard, g), fetchLogs()]); (slice 2a)
		// One window per load, so the figures and the table cover the same span
		const win = getTimeRange();
		const [dashboard, table] = await Promise.all([fetchDashboard(guard, g, win), fetchLogs(false, win)]);
		if (!guard.current(g) || dashboard === null) return 'skipped';
		// A table load that a newer search replaced says nothing about this refresh
		const outcomes = table === 'skipped' ? dashboard : [...dashboard, table === 'ok'];
		const ok = outcomes.filter(Boolean).length;
		return ok === outcomes.length ? 'ok' : ok === 0 ? 'failed' : 'partial';
	}

	// ---------------------------------------------------------------------------
	// Event handlers
	// ---------------------------------------------------------------------------

	/**
	 * A pick on the timeline (NET-249) opens exactly the events it counted: a hand-off with the picked
	 * slots' window and their figure only, so the log type, query, address and excluded sources it
	 * ignores are cleared (the URL hand-off replaces every filter).
	 */
	function pickTimeline(chart: TimeChart, i: number, j: number) {
		void goto(withCount(`/logs?${windowQuery(pickWindow(chart, i, j), intervalRange)}`, pickedTotal(chart, i, j)));
	}

	// OLD CODE: function handleTimeRangeChange(value: TimeRange) { (slice 2a: Custom)
	function handleTimeRangeChange(value: TimeRange | 'custom') {
		selectedTimeRange = value;
		// Picking a standard range leaves the link's window
		if (value !== 'custom') custom = null;
		// #96: the last range's figures must not stand in for this range if its load fails
		statsLoaded = false;
		timeline = [];
		timelineChart = null;
		topTalkers = [];
		protocols = [];
		topDestinations = [];
		topDns = [];
		// OLD CODE START — PLAN §5.5: the guard drops the older range's load, so always reload
		// if (initialized) fetchAll();
		// OLD CODE END
		refresh.run();
	}

	function handleSearch(e: KeyboardEvent) {
		if (e.key === 'Enter') fetchLogs();
	}

	// OLD CODE START — NET-160 section D: the controls below searched only once the first load had finished,
	// dashboard included, so a type picked during it neither replaced the table request nor ended a comparison
	// function setLogType(lt: LogType) {
	// 	logType = lt;
	// 	if (initialized) {
	// 		fetchLogs();
	// 		fetchFieldDefs();
	// 	}
	// }
	// OLD CODE END
	// A search change always searches, and its column descriptions follow (each drops an older reply)
	function setLogType(lt: LogType) {
		logType = lt;
		fetchLogs();
		fetchFieldDefs();
	}

	// OLD CODE START — DataTable owns the header toggle and reports the new sort
	// function toggleSort(field: string) {
	// 	if (sortField === field) {
	// 		sortDir = sortDir === 'desc' ? 'asc' : 'desc';
	// 	} else {
	// 		sortField = field;
	// 		sortDir = 'desc';
	// 	}
	// 	fetchLogs();
	// }
	// OLD CODE END
	/** The table is sorted by the daemon: DataTable reports the new sort and the search runs again. */
	// OLD CODE START — NET-184: a sort searched a new window, so a bar's list drifted from its figure
	// function setSort(field: string, dir: SortDir) {
	// 	sortField = field;
	// 	sortDir = dir;
	// 	fetchLogs();
	// }
	// OLD CODE END
	function setSort(field: string, dir: SortDir) {
		sortField = field;
		sortDir = dir;
		// the same records in another order: same window, and the clicked figure still applies
		if (linked) linked = { ...linked, gen: null, observed: null };
		// OLD CODE: fetchLogs(false, searchWindow); (NET-184: it ran unsubmitted text from the search box)
		fetchLogs(false, searchWindow, searchText);
	}

	// Click-to-drill handlers
	// OLD CODE START — NET-160 section D: searched only after the first load (see setLogType)
	// function drillByProtocol(dataset: string) {
	// 	const lt = DATASET_TO_LOG_TYPE[dataset];
	// 	if (lt) {
	// 		logType = lt;
	// 		if (initialized) {
	// 			fetchLogs();
	// 			fetchFieldDefs();
	// 			document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
	// 		}
	// 	}
	// }
	//
	// function drillByIp(ip: string) {
	// 	if (activeIpFilter === ip) {
	// 		activeIpFilter = '';
	// 	} else {
	// 		activeIpFilter = ip;
	// 	}
	// 	if (initialized) {
	// 		fetchLogs();
	// 		document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
	// 	}
	// }
	//
	// function drillByDns(domain: string) {
	// 	if (activeDnsFilter === domain) {
	// 		activeDnsFilter = '';
	// 	} else {
	// 		activeDnsFilter = domain;
	// 		// Switch to DNS tab for best context
	// 		logType = 'zeek.dns';
	// 	}
	// 	if (initialized) {
	// 		fetchLogs();
	// 		fetchFieldDefs();
	// 		document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
	// 	}
	// }
	//
	// function clearAllFilters() {
	// 	activeIpFilter = '';
	// 	activeDnsFilter = '';
	// 	excludeSrc = [];
	// 	logType = 'all';
	// 	query = '';
	// 	if (initialized) {
	// 		fetchLogs();
	// 		fetchFieldDefs();
	// 	}
	// }
	// OLD CODE END
	function drillByProtocol(dataset: string) {
		const lt = DATASET_TO_LOG_TYPE[dataset];
		if (lt) {
			logType = lt;
			fetchLogs();
			fetchFieldDefs();
			if (initialized) document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
		}
	}

	// OLD CODE START — NET-184: either side, on top of the other filters, over a new window: the list
	// wasn't the bar's figure
	// function drillByIp(ip: string) {
	// 	if (activeIpFilter === ip) {
	// 		activeIpFilter = '';
	// 	} else {
	// 		activeIpFilter = ip;
	// 	}
	// 	fetchLogs();
	// 	if (initialized) document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
	// }
	// OLD CODE END
	/**
	 * A top source or destination bar opens exactly its figure: that address on that side alone, over
	 * the window the bar counted, every other filter cleared, and the line says if the total differs.
	 * Selecting the bar again clears only the address.
	 */
	function drillByEnd(side: 'source.ip' | 'destination.ip', ip: string, count: number, win: DrillWindow | null) {
		if (activeIpFilter === ip && ipSide === side) {
			activeIpFilter = '';
			fetchLogs();
			return;
		}
		activeIpFilter = ip;
		ipSide = side;
		query = '';
		activeDnsFilter = '';
		excludeSrc = [];
		const typeBefore = logType;
		logType = 'all';
		if (typeBefore !== 'all') fetchFieldDefs();
		linked = { expected: count, gen: null, observed: null };
		fetchLogs(false, win ?? undefined);
		if (initialized) document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
	}

	function drillByDns(domain: string) {
		if (activeDnsFilter === domain) {
			activeDnsFilter = '';
		} else {
			activeDnsFilter = domain;
			// Switch to DNS tab for best context
			logType = 'zeek.dns';
		}
		fetchLogs();
		fetchFieldDefs();
		if (initialized) document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
	}

	function clearAllFilters() {
		activeIpFilter = '';
		ipSide = null;
		activeDnsFilter = '';
		excludeSrc = [];
		logType = 'all';
		query = '';
		fetchLogs();
		fetchFieldDefs();
	}

	// OLD CODE START — row expansion replaced by DetailDrawer
	// async function fetchFullDocument(hit: LogHit) { ... }
	// function toggleRow(id: string) { ... }
	// OLD CODE END

	function openDrawer(hit: LogHit) {
		drawerHit = hit;
		drawerTab = 'fields';
	}

	function closeDrawer() {
		drawerHit = null;
		drawerTab = 'fields';
	}

	function drawerViewSourceDevice() {
		if (!drawerHit) return;
		const src = drawerHit._source['source.ip'] || (drawerHit._source['source'] as Record<string, unknown>)?.['ip'];
		// OLD CODE: if (src) goto(`/devices/${encodeURIComponent(String(Array.isArray(src) ? src[0] : src))}`); (slice 2a: an internet address has no device page)
		if (src) goto($ipHref(String(Array.isArray(src) ? src[0] : src)));
	}

	// CSV export
	function exportCSV() {
		if (results.length === 0) return;
		const columns = COLUMNS[logType];
		const header = columns.join(',');
		const rows = results.map((hit) =>
			columns
				.map((col) => {
					const val = formatCellValue(col, getNestedValue(hit._source, col));
					return `"${val.replace(/"/g, '""')}"`;
				})
				.join(',')
		);
		const csv = [header, ...rows].join('\n');
		const blob = new Blob([csv], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `nettap-logs-${logType}-${new Date().toISOString().slice(0, 10)}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}

	// Auto-refresh
	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			// OLD CODE START — PLAN §5.5: auto-refresh goes through the contract, so "Updated" stays honest
			// refreshInterval = setInterval(fetchAll, 30_000);
			// OLD CODE END
			refreshInterval = setInterval(() => refresh.runIfIdle(), AUTO_REFRESH_MS);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	// ---------------------------------------------------------------------------
	// Table
	// ---------------------------------------------------------------------------

	const IP_CELLS: Record<string, Snippet<[LogRow]>> = {
		'source.ip': sourceIpCell,
		'destination.ip': destinationIpCell,
		// OLD CODE START: 'zeek.dhcp.client_addr': dhcpIpCell, (I6) OLD CODE END
		'zeek.dhcp.assigned_ip': dhcpIpCell,
	};

	/** Names that open their domain page (NET-160 slice 2a). */
	const DOMAIN_CELLS: Record<string, Snippet<[LogRow]>> = {
		'zeek.dns.query': dnsQueryCell,
		'zeek.http.host': httpHostCell,
		'zeek.ssl.server_name': sslNameCell,
	};

	const logColumns = $derived<Column<LogRow>[]>(
		COLUMNS[logType].map((col) => ({
			key: col,
			label: shortFieldName(col),
			numeric: NUMERIC_FIELDS.has(col),
			class: MONO_FIELDS.has(col) || IP_FIELDS.has(col) ? 'mono' : undefined,
			// OLD CODE: cell: IP_CELLS[col], (slice 2a: domain columns link too)
			cell: IP_CELLS[col] ?? DOMAIN_CELLS[col],
			title: fieldDefs[col],
		})),
	);

	const logRows = $derived<LogRow[]>(
		results.map((hit) => ({
			...Object.fromEntries(COLUMNS[logType].map((col) => [col, formatCellValue(col, getNestedValue(hit._source, col))])),
			_id: hit._id,
			hit,
		})),
	);

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	// OLD CODE START — the URL was read once on mount, so a second top-bar search while already
	// on /logs (goto('/logs?ip=…') or goto('/logs?query=…')) did nothing
	// onMount(() => {
	// 	// Read URL params for deep-linking from other pages (e.g., /logs?filter=1.2.3.4)
	// 	const urlFilter = $page.url.searchParams.get('filter');
	// 	const urlIp = $page.url.searchParams.get('ip');
	// 	const urlQuery = $page.url.searchParams.get('query');
	// 	if (urlFilter) {
	// 		activeIpFilter = urlFilter;
	// 	} else if (urlIp) {
	// 		activeIpFilter = urlIp;
	// 	} else if (urlQuery) {
	// 		query = urlQuery;
	// 	}
	//
	// 	fetchAll().then(() => {
	// 		initialized = true;
	// 	});
	// 	fetchFieldDefs();
	// 	return () => {
	// 		if (refreshInterval) clearInterval(refreshInterval);
	// 	};
	// });
	// OLD CODE END
	// OLD CODE START — slice 2a: the window was read on the first load only, and only as ?range=, so a
	// link's exact window (?from=&to=) was ignored and a second link with another window kept the old one
	// /** The ?filter= / ?ip= / ?query= last applied; null before the first load. */
	// let appliedSearch: string | null = null;
	// $effect(() => {
	// 	// Deep links from other pages (e.g., /logs?filter=1.2.3.4) and the top-bar search hand-off
	// 	const params = $page.url.searchParams;
	// 	const urlFilter = params.get('filter');
	// 	const urlIp = params.get('ip');
	// 	const urlQuery = params.get('query');
	// 	const search = JSON.stringify([urlFilter, urlIp, urlQuery]);
	// 	untrack(() => {
	// 		// The hash changes too (the KPI links); only a new search runs one
	// 		if (search === appliedSearch) return;
	// 		const first = appliedSearch === null;
	// 		appliedSearch = search;
	// 		// A link from a page with its own window (?range=, NET-160) opens on that window
	// 		const urlRange = params.get('range');
	// 		if (first && TIME_RANGES.some((r) => r.value === urlRange)) selectedTimeRange = urlRange as TimeRange;
	// 		// A hand-off replaces the last one's IP filter and text; the first load starts from neither
	// 		activeIpFilter = urlFilter || urlIp || '';
	// 		query = urlFilter || urlIp ? '' : (urlQuery ?? '');
	// 		if (first) {
	// 			refresh.run().then(() => {
	// 				initialized = true;
	// 			});
	// 			fetchFieldDefs();
	// 		} else {
	// 			fetchLogs();
	// 		}
	// 	});
	// });
	// OLD CODE END
	/** The ?filter= / ?ip= / ?query= / ?range= / ?from= / ?to= / ?type= / ?exclude_src= last applied; null before the first load. */
	let appliedSearch: string | null = null;
	/** The ?count= last applied, kept out of the search key: it changes no window and no filter (NET-160 section D). */
	let appliedCount: number | null = null;

	$effect(() => {
		// Deep links from other pages (e.g., /logs?filter=1.2.3.4) and the top-bar search hand-off
		const params = $page.url.searchParams;
		// OLD CODE START — slice 2b-1: no log type or excluded sources (Home's Connections link)
		// const keys = ['filter', 'ip', 'query', 'range', 'from', 'to'] as const;
		// const [urlFilter, urlIp, urlQuery, urlRange, urlFrom, urlTo] = keys.map((k) => params.get(k));
		// const search = JSON.stringify([urlFilter, urlIp, urlQuery, urlRange, urlFrom, urlTo]);
		// OLD CODE END
		const keys = ['filter', 'ip', 'query', 'range', 'from', 'to', 'type', 'exclude_src'] as const;
		const [urlFilter, urlIp, urlQuery, urlRange, urlFrom, urlTo, urlType, urlExclude] = keys.map((k) => params.get(k));
		const search = JSON.stringify([urlFilter, urlIp, urlQuery, urlRange, urlFrom, urlTo, urlType, urlExclude]);
		const count = linkedCount(params.get('count'));
		untrack(() => {
			// The hash changes too (the KPI links); only a new search runs one
			// OLD CODE: if (search === appliedSearch) return; (NET-160 section D: a new count alone is a new hand-off, rebuilt from the URL)
			if (search === appliedSearch && count === appliedCount) return;
			const first = appliedSearch === null;
			appliedSearch = search;
			appliedCount = count;
			const windowBefore = JSON.stringify([selectedTimeRange, custom?.from, custom?.to]);
			// A link from a page with its own window (NET-160) opens on that window: the exact one
			// (?from=&to=, "Custom") when it gives it, otherwise its ?range=
			custom = customRange(urlFrom, urlTo);
			// OLD CODE: : selectedTimeRange === 'custom' ? '24h' : selectedTimeRange; (NET-195: Custom falls back to Settings › Display's default)
			// A hand-off without a window keeps the range on screen (a pill's or a link's: the page can't tell)
			selectedTimeRange = custom
				? 'custom'
				: TIME_RANGES.some((r) => r.value === urlRange)
					? (urlRange as TimeRange)
					: selectedTimeRange === 'custom'
						? startRange('24h')
						: selectedTimeRange;
			// A hand-off replaces the last one's IP filter and text; the first load starts from neither
			activeIpFilter = urlFilter || urlIp || '';
			ipSide = null; // a hand-off's address is either side (NET-184)
			query = urlFilter || urlIp ? '' : (urlQuery ?? '');
			// It replaces the log type too (one of ours, else all types) and the excluded sources (the daemon checks each)
			const typeBefore = logType;
			logType = Object.keys(LOG_TYPE_LABELS).includes(urlType ?? '') ? (urlType as LogType) : 'all';
			excludeSrc = (urlExclude ?? '').split(',').map((ip) => ip.trim()).filter(Boolean);
			// No URL carries a DNS-bar choice, so none outlives a hand-off (NET-160 section D)
			activeDnsFilter = '';
			if (!first && logType !== typeBefore) fetchFieldDefs();
			// The table search each path below starts takes this comparison (fetchLogs sets its gen)
			linked = count === null ? null : { expected: count, gen: null, observed: null };
			if (first) {
				refresh.run().then(() => {
					initialized = true;
				});
				fetchFieldDefs();
			} else if (JSON.stringify([selectedTimeRange, custom?.from, custom?.to]) !== windowBefore) {
				// a new window reloads every card, as picking a range does, so no old figure sits under its words
				handleTimeRangeChange(selectedTimeRange);
			} else {
				fetchLogs();
			}
		});
	});
</script>

<!-- OLD CODE START — String() of an array-valued field linked /address/a%2Cb
{#snippet ipValue(value: unknown)}
	{#if value != null && value !== ''}<IPAddress ip={String(value)} />{:else}--{/if}
{/snippet}
OLD CODE END -->
{#snippet ipValue(value: unknown)}
	{#if typeof value === 'string' && isIpAddress(value)}<IPAddress ip={value} />
	{:else if value != null && value !== ''}<IPAddress ip={Array.isArray(value) ? value.join(', ') : String(value)} linked={false} />
	{:else}--{/if}
{/snippet}
{#snippet sourceIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'source.ip'))}{/snippet}
{#snippet destinationIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'destination.ip'))}{/snippet}
<!-- OLD CODE START: {#snippet dhcpIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'zeek.dhcp.client_addr'))}{/snippet} (I6) OLD CODE END -->
{#snippet dhcpIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'zeek.dhcp.assigned_ip'))}{/snippet}
<!-- A host name links to its domain page; an address, host:port or anything else stays text. An array is
     joined text, never one link, as the address cells do. -->
{#snippet domainValue(value: unknown)}
	{#if typeof value === 'string' && isHostName(value) && !isIpAddress(canonicalName(value))}<a href={domainHref(value)}>{value}</a>
	{:else if value != null && value !== ''}{Array.isArray(value) ? value.join(', ') : String(value)}
	{:else}--{/if}
{/snippet}
{#snippet dnsQueryCell(r: LogRow)}{@render domainValue(getNestedValue(r.hit._source, 'zeek.dns.query'))}{/snippet}
{#snippet httpHostCell(r: LogRow)}{@render domainValue(getNestedValue(r.hit._source, 'zeek.http.host'))}{/snippet}
{#snippet sslNameCell(r: LogRow)}{@render domainValue(getNestedValue(r.hit._source, 'zeek.ssl.server_name'))}{/snippet}

{#snippet timelineBody()}
	<!-- NET-249: a pick is a hand-off with only the window, so the type, query and excluded sources go, as the timeline counts every type and ignores them -->
	<AreaChart
		series={[{ key: 'events', label: 'Events', colour: 1, points: timeline.map((b, i) => ({ t: b.timestamp, v: bucketTotals[i] })) }]}
		formatX={(t) => formatShortTimestamp(String(t))}
		formatY={formatCompactNumber}
		formatTip={(i) => `${formatShortTimestamp(timeline[i]?.timestamp ?? '')} · ${fmt(bucketTotals[i] ?? 0)} events`}
		highlightIndex={busiest}
		ariaLabel={busiest >= 0
			? `Busiest at ${formatShortTimestamp(timeline[busiest].timestamp)}, with ${fmt(bucketTotals[busiest])} events`
			: 'Log events over time'}
		onpick={timelineChart ? (i, j) => pickTimeline(timelineChart!, i, j) : undefined}
	/>
	{#if timelineChart}<p class="card-sub pick-hint">Click a point or drag across the chart to see that moment.</p>{/if}
{/snippet}
{#snippet protocolsBody()}
	<BarList
		items={(showAllProtocols ? protocols : protocols.slice(0, PROTOCOLS_SHOWN)).map((proto) => ({
			key: proto.protocol,
			label: proto.label || protocolLabel(proto.protocol),
			value: proto.count,
			display: formatCompactNumber(proto.count),
			onclick: () => drillByProtocol(proto.protocol),
		}))}
	/>
	<!-- OLD CODE START — I5: at the daemon's 20 cap, "of 20" and "Show all 20" claimed a total it never sent
	{#if protocols.length > PROTOCOLS_SHOWN}
		<div class="tbl-foot">
			<span>Showing {partOfWhole(showAllProtocols ? protocols.length : PROTOCOLS_SHOWN, protocols.length)}</span>
			<button class="btn" type="button" onclick={() => (showAllProtocols = !showAllProtocols)}>
				{showAllProtocols ? 'Show fewer' : `Show all ${protocols.length}`}
			</button>
		</div>
	{/if}
	OLD CODE END -->
	{#if protocols.length > PROTOCOLS_SHOWN}
		<div class="tbl-foot">
			{#if protocolsCapped}
				<span>{showAllProtocols ? `The ${PROTOCOL_CAP} most common` : `Showing ${PROTOCOLS_SHOWN} of the ${PROTOCOL_CAP} most common`}</span>
			{:else}
				<span>Showing {partOfWhole(showAllProtocols ? protocols.length : PROTOCOLS_SHOWN, protocols.length)}</span>
			{/if}
			<button class="btn" type="button" onclick={() => (showAllProtocols = !showAllProtocols)}>
				{showAllProtocols ? 'Show fewer' : protocolsCapped ? `Show the ${PROTOCOL_CAP} most common` : `Show all ${protocols.length}`}
			</button>
		</div>
	{/if}
{/snippet}
{#snippet talkersBody()}
	<BarList
		items={topTalkers.map((talker) => ({
			key: talker.ip,
			label: talker.ip,
			value: talker.count,
			display: formatCompactNumber(talker.count),
			// OLD CODE: detail: activeIpFilter === talker.ip ? 'filtering the table' : undefined, onclick: () => drillByIp(talker.ip), (NET-184)
			detail: activeIpFilter === talker.ip && ipSide === 'source.ip' ? 'filtering the table' : undefined,
			onclick: () => drillByEnd('source.ip', talker.ip, talker.count, talkersWindow),
		}))}
	/>
{/snippet}
{#snippet destinationsBody()}
	<BarList
		items={topDestinations.map((dest) => ({
			key: dest.ip,
			label: dest.ip,
			value: dest.count,
			display: formatCompactNumber(dest.count),
			// OLD CODE: detail: activeIpFilter === dest.ip ? 'filtering the table' : undefined, onclick: () => drillByIp(dest.ip), (NET-184)
			detail: activeIpFilter === dest.ip && ipSide === 'destination.ip' ? 'filtering the table' : undefined,
			onclick: () => drillByEnd('destination.ip', dest.ip, dest.count, destinationsWindow),
			colour: 2,
		}))}
	/>
{/snippet}
{#snippet dnsBody()}
	<BarList
		items={topDns.map((dnsEntry) => ({
			key: dnsEntry.domain,
			label: dnsEntry.domain,
			value: dnsEntry.count,
			display: formatCompactNumber(dnsEntry.count),
			detail: activeDnsFilter === dnsEntry.domain ? 'filtering the table' : undefined,
			onclick: () => drillByDns(dnsEntry.domain),
			colour: 3,
		}))}
	/>
{/snippet}

<!-- One card body: its data (with a note when a refresh failed), or its loading, error or empty state -->
{#snippet section(what: string, failed: boolean, has: boolean, emptyTitle: string, emptyMessage: string, body: Snippet)}
	{#if has}
		{#if failed && !loading}
			<p class="notice is-warn stale" role="status"><Icon name="warn" />{loadFailed(what, true)}</p>
		{/if}
		{@render body()}
	{:else if loading}
		<CardState state="loading" title="Loading {what}" />
	{:else if failed}
		<CardState state="error" title={loadFailed(what)} message={RETRY_HINT} onaction={() => refresh.run()} />
	{:else}
		<CardState state="empty" icon="logs" title={emptyTitle} message={emptyMessage} />
	{/if}
{/snippet}

<svelte:head>
	<title>Log Explorer | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Log explorer</h1>
		<!-- OLD CODE START — NET-165: didn't say these figures count excluded devices, so "Top DNS queries" could disagree with the DNS page unexplained -->
		<!-- <p class="page-sub">Every Zeek and Suricata log entry in the range, searchable</p> -->
		<!-- OLD CODE END -->
		<p class="page-sub">Every Zeek and Suricata log entry in the range, searchable. Devices excluded in Settings are counted here too, so figures can differ from the DNS and Devices pages.</p>
	</div>
	<div class="head-actions">
		<!-- OLD CODE: <Pills options={TIME_RANGES} value={selectedTimeRange} onchange={handleTimeRangeChange} ariaLabel="Time range" /> (slice 2a: Custom) -->
		<Pills options={rangeOptions} value={selectedTimeRange} onchange={handleTimeRangeChange} ariaLabel="Time range" />
		<!-- OLD CODE START — NET-192 PR 4: Home's Auto / Paused button on every page
		<button class="btn" type="button" aria-pressed={autoRefresh} onclick={toggleAutoRefresh}>
			<Icon name="refresh" />{autoRefresh ? 'Auto-refresh on' : 'Auto-refresh'}
		</button>
		OLD CODE END -->
		<AutoRefreshButton on={autoRefresh} seconds={AUTO_REFRESH_MS / 1000} ontoggle={toggleAutoRefresh} />
		<button class="btn" type="button" onclick={exportCSV} disabled={results.length === 0}>
			<Icon name="download" />Export CSV
		</button>
	</div>
</div>

<div class="grid">
	{#if statsFailed}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" />{loadFailed('log totals', statsLoaded)}</p>
	{/if}
	<!-- OLD CODE START — #96: the totals start at 0, which read as a fact before (or without) a load
	<span class="stat-value text-white">{formatCompactNumber(totalEvents)}</span>
	<span class="stat-value text-cyan">{formatCompactNumber(uniqueSources)}</span>
	<span class="stat-value text-green">{protocolCount}</span>
	<span class="stat-value text-purple">{formatBytes(totalBytesVal)}</span>
	OLD CODE END -->
	<KpiCard class="c-3" label="Total events" icon="logs" value={statsLoaded ? formatCompactNumber(totalEvents) : '—'} note="All log entries in range" href="#log-table" />
	<KpiCard class="c-3" label="Active sources" icon="devices" value={statsLoaded ? formatCompactNumber(uniqueSources) : '—'} note="Unique source IPs" href="#top-talkers-section" />
	<KpiCard class="c-3" label="Protocols" icon="connections" value={statsLoaded ? protocolCount : '—'} note="Distinct log types" href="#protocol-section" />
	<KpiCard class="c-3" label="Data volume" icon="bandwidth" value={statsLoaded ? formatBytes(totalBytesVal) : '—'} note="Total bytes transferred" href="#log-table" />

	<!-- OLD CODE: sub="Log events per {INTERVAL_WORDS[INTERVAL_MAP[selectedTimeRange]] ?? 'hour'} · {rangeWords}" (slice 2a: Custom) -->
	<!-- OLD CODE: sub="Log events per {INTERVAL_WORDS[INTERVAL_MAP[intervalRange]] ?? 'hour'} · {rangeWords}" (NET-249: the table's bucket) -->
	<Card title="Activity timeline" sub="Log events per {bucket.bucketWords} · {rangeWords}" hero col class="c-8">
		{@render section('the activity timeline', timelineFailed, timeline.length > 0, 'No timeline data available', 'Events appear here once Zeek is processing traffic.', timelineBody)}
	</Card>

	<Card title="Protocol breakdown" sub="Log entries per protocol · {rangeWords}" class="c-4">
		<span id="protocol-section" class="anchor"></span>
		{@render section('protocols', protocolsFailed, protocols.length > 0, 'No protocol data', 'Protocols appear once Zeek logs traffic in this range.', protocolsBody)}
	</Card>

	<Card title="Top source IPs" sub="Most active devices · log entries · {rangeWords}" class="c-4">
		<span id="top-talkers-section" class="anchor"></span>
		{@render section('top sources', talkersFailed, topTalkers.length > 0, 'No source IP data', 'Devices appear once Zeek logs their traffic.', talkersBody)}
	</Card>

	<Card title="Most contacted servers" sub="Destination IPs · log entries · {rangeWords}" class="c-4">
		{@render section('top destinations', destinationsFailed, topDestinations.length > 0, 'No destination data', 'Servers appear once Zeek logs traffic to them.', destinationsBody)}
	</Card>

	<Card title="Top DNS queries" sub="Most looked-up domains · {rangeWords}" class="c-4">
		{@render section('top DNS queries', dnsFailed, topDns.length > 0, 'No DNS data', 'Domains appear once Zeek logs DNS lookups.', dnsBody)}
	</Card>

	<Card title="Log entries" sub="{LOG_TYPE_LABELS[logType]} · {rangeWords} · 100 per page" class="c-12">
		<span id="log-table" class="anchor"></span>
		<div class="toolbar">
			<div class="search-wide">
				<SearchField
					id="logs-search"
					label="Search logs"
					placeholder="Search logs… (e.g. google.com, 192.168.1.1, dns)"
					size="toolbar"
					bind:value={query}
					onkeydown={handleSearch}
				/>
			</div>
			<button class="btn primary" type="button" onclick={() => fetchLogs()} disabled={tableLoading}>
				<Icon name="search" />Search
			</button>
		</div>
		<div class="toolbar types">
			<Pills
				options={Object.entries(LOG_TYPE_LABELS).map(([value, label]) => ({ value: value as LogType, label }))}
				value={logType}
				onchange={setLogType}
				ariaLabel="Log type"
			/>
		</div>

		{#if hasActiveFilters}
			<div class="chips filters">
				<span class="dim">Active filters:</span>
				{#if logType !== 'all'}
					<button class="chip" type="button" aria-label="Remove filter Type: {LOG_TYPE_LABELS[logType]}" onclick={() => { logType = 'all'; fetchLogs(); fetchFieldDefs(); }}>
						Type: {LOG_TYPE_LABELS[logType]}<Icon name="close" />
					</button>
				{/if}
				<!-- OLD CODE: aria-label="Remove filter IP: {activeIpFilter}" … IP: <span class="mono">{activeIpFilter}</span> (NET-184: a bar's filter names its side) -->
				{#if activeIpFilter}
					{@const ipWord = ipSide === 'source.ip' ? 'Source' : ipSide === 'destination.ip' ? 'Destination' : 'IP'}
					<button class="chip" type="button" aria-label="Remove filter {ipWord}: {activeIpFilter}" onclick={() => { activeIpFilter = ''; fetchLogs(); }}>
						{ipWord}: <span class="mono">{activeIpFilter}</span><Icon name="close" />
					</button>
				{/if}
				{#if activeDnsFilter}
					<button class="chip" type="button" aria-label="Remove filter DNS: {activeDnsFilter}" onclick={() => { activeDnsFilter = ''; fetchLogs(); fetchFieldDefs(); }}>
						DNS: <span class="mono">{activeDnsFilter}</span><Icon name="close" />
					</button>
				{/if}
				<!-- Clearing it is local, as every control here is: the URL is a one-time hand-off -->
				{#if excludeSrc.length > 0}
					<button class="chip" type="button" aria-label="Remove filter: leaving out sources {excludeSrc.join(', ')}" onclick={() => { excludeSrc = []; fetchLogs(); }}>
						<!-- OLD CODE: … (excluded in Settings, as Home counts) (PR #189 review: the page can't check where a link's list came from) -->
						Leaving out sources <span class="mono">{excludeSrc.join(', ')}</span> (set by the link you followed)<Icon name="close" />
					</button>
				{/if}
				<button class="link" type="button" onclick={clearAllFilters}>Clear all</button>
			</div>
		{/if}

		<!-- The figure a link was clicked at, when this search's total differs (NET-160 section D) -->
		{#if countLine}
			<p class="notice linked" role="status">{countLine}</p>
		{/if}

		{#if error && results.length === 0}
			<CardState state="error" title="Couldn't search the logs: the request failed." message={error} onaction={() => fetchLogs()} />
		{:else if tableLoading && results.length === 0}
			<CardState state="loading" title="Searching logs" />
		{:else if results.length === 0}
			<CardState
				state="empty"
				icon="logs"
				title="No logs found"
				message="Try adjusting your time range or search query. Logs appear once Zeek/Suricata are processing traffic."
			/>
		{:else}
			{#if error}
				<p class="notice is-error stale" role="alert"><Icon name="warn" />{error}</p>
			{/if}
			<DataTable
				columns={logColumns}
				rows={logRows}
				ariaLabel="Log entries"
				rowKey={(r) => r._id}
				initialSort={{ key: sortField, dir: sortDir }}
				onsortchange={setSort}
				onrowactivate={(r) => openDrawer(r.hit)}
				rowLabel={(r) => `Open log entry from ${String(r['@timestamp'] ?? '')}`}
				selectedKey={drawerHit?._id}
			/>
			<div class="tbl-foot">
				<span aria-live="polite">
					Showing <strong class="num">{fmt(results.length)}</strong> of <strong class="num">{fmt(totalHits)}</strong> results{tableLoading ? ' · searching…' : ''}
				</span>
				{#if searchAfter && results.length < totalHits}
					<button class="btn" type="button" onclick={() => fetchLogs(true)} disabled={loadingMore}>
						{loadingMore ? 'Loading…' : 'Load more'}
					</button>
				{/if}
			</div>
		{/if}
	</Card>
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerHit !== null}
	title={drawerHit ? String(drawerHit._source['event.dataset'] ?? drawerHit._source['event.provider'] ?? 'Log Entry') : ''}
	subtitle={drawerHit ? String(drawerHit._source['@timestamp'] ?? '') : ''}
	tabs={LOG_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => drawerTab = t}
>
	{#snippet children()}
		{#if drawerHit}
			<!-- OLD CODE: <LogDrawerContent hit={drawerHit} activeTab={drawerTab} timeRange={timeRangeToISO(selectedTimeRange)} /> (slice 2a: the rows' own window) -->
			<LogDrawerContent hit={drawerHit} activeTab={drawerTab} timeRange={tableWindow?.from ?? ''} />
		{/if}
	{/snippet}
	{#snippet actions()}
		<button class="btn" type="button" onclick={drawerViewSourceDevice}>
			View source device
		</button>
	{/snippet}
</DetailDrawer>

<script lang="ts" module>
	export function flattenObject(obj: Record<string, unknown>, prefix = ''): Record<string, unknown> {
		const result: Record<string, unknown> = {};
		for (const [key, value] of Object.entries(obj)) {
			const fullKey = prefix ? `${prefix}.${key}` : key;
			if (value && typeof value === 'object' && !Array.isArray(value)) {
				Object.assign(result, flattenObject(value as Record<string, unknown>, fullKey));
			} else {
				result[fullKey] = value;
			}
		}
		return result;
	}
</script>

<style>
	/* Layout glue the system lacks */
	.pick-hint { margin-top: var(--sp-2); }
	/* In-card anchors for the KPI links and the drill scrolls; the margin keeps the card head in view */
	.anchor { display: block; scroll-margin-top: calc(var(--sp-8) * 3); }
	/* OLD CODE: .stale { margin-bottom: var(--sp-3); } (NET-160 section D: the count line too) */
	.stale, .linked { margin-bottom: var(--sp-3); }
	/* The log search takes the toolbar's free width (the system caps a toolbar search at 360px) */
	.search-wide { display: flex; flex: 1 1 28rem; min-width: 0; }
	.search-wide :global(.search) { max-width: none; }
	/* Nine log types: the pill group scrolls sideways instead of overflowing a phone */
	.types { overflow-x: auto; }
	.filters { align-items: center; margin-bottom: var(--sp-4); font-size: var(--text-xs); }
	button.chip { border: 0; cursor: pointer; }
	button.link { background: none; border: 0; padding: 0; cursor: pointer; }
</style>
