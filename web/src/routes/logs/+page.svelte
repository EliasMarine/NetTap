<script lang="ts">
	import { onDestroy, untrack, type Snippet } from 'svelte';
	import { page } from '$app/stores';
	import IPAddress from '$components/IPAddress.svelte';
	// OLD CODE START — replaced by the design system's BarList
	// import HorizontalBarList from '$components/HorizontalBarList.svelte';
	// OLD CODE END
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import LogDrawerContent from '$components/drawer/content/LogDrawerContent.svelte';
	import { goto } from '$app/navigation';
	import { getWhois } from '$api/lookup';
	import { loadFailed } from '$lib/utils/load-failed';
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
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';

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
	type TimeRange = '15m' | '1h' | '4h' | '24h' | '7d' | '30d';

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
		'zeek.tls': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.tls.server_name', 'zeek.tls.version', 'zeek.tls.cipher', 'zeek.tls.established'],
		'zeek.files': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.files.filename', 'zeek.files.mime_type', 'zeek.files.total_bytes'],
		'zeek.dhcp': ['@timestamp', 'source.ip', 'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.dhcp.hostname', 'zeek.dhcp.msg_types'],
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

	const TIME_RANGES: { value: TimeRange; label: string; ms: number; words: string }[] = [
		{ value: '15m', label: '15m', ms: 15 * 60_000, words: 'last 15 minutes' },
		{ value: '1h', label: '1h', ms: 60 * 60_000, words: 'last hour' },
		{ value: '4h', label: '4h', ms: 4 * 60 * 60_000, words: 'last 4 hours' },
		{ value: '24h', label: '24h', ms: 24 * 60 * 60_000, words: 'last 24 hours' },
		{ value: '7d', label: '7d', ms: 7 * 24 * 60 * 60_000, words: 'last 7 days' },
		{ value: '30d', label: '30d', ms: 30 * 24 * 60 * 60_000, words: 'last 30 days' },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m',
		'1h': '5m',
		'4h': '15m',
		'24h': '1h',
		'7d': '6h',
		'30d': '1d',
	};

	/** How the timeline card names each INTERVAL_MAP bucket. */
	const INTERVAL_WORDS: Record<string, string> = {
		'1m': 'minute',
		'5m': '5 minutes',
		'15m': '15 minutes',
		'1h': 'hour',
		'6h': '6 hours',
		'1d': 'day',
	};

	const IP_FIELDS = new Set(['source.ip', 'destination.ip', 'zeek.dhcp.client_addr']);
	const MONO_FIELDS = new Set([
		'source.ip', 'destination.ip', 'source.port', 'destination.port',
		'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.http.status_code',
		'zeek.tls.version', 'source.bytes', 'destination.bytes', 'event.duration',
		'suricata.alert.severity', 'zeek.files.total_bytes',
	]);
	/** Right-aligned, tabular columns (design system: numbers in tables). */
	const NUMERIC_FIELDS = new Set([
		'source.port', 'destination.port', 'source.bytes', 'destination.bytes', 'event.duration',
		'zeek.http.status_code', 'suricata.alert.severity', 'zeek.files.total_bytes',
	]);

	// Protocol types used for timeline stacking (order matters for visual stacking)
	// Alert data is excluded from log explorer aggregations (has its own Alerts page)
	const PROTOCOL_KEYS = ['conn', 'dns', 'http', 'ssl', 'files', 'dhcp', 'smtp'] as const;

	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let initialized = $state(false);
	let loading = $state(false);
	let selectedTimeRange = $state<TimeRange>('24h');
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Aggregation data
	let totalEvents = $state(0);
	let uniqueSources = $state(0);
	let protocolCount = $state(0);
	let totalBytesVal = $state(0);
	let timeline = $state<LogTimelineBucket[]>([]);
	let topTalkers = $state<LogTalkerEntry[]>([]);
	let protocols = $state<LogProtocolEntry[]>([]);
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
	let activeDnsFilter = $state('');

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
	const bucketTotals = $derived(timeline.map((b) => PROTOCOL_KEYS.reduce((sum, k) => sum + (b[k] || 0), 0)));
	const busiest = $derived(bucketTotals.reduce((best, v, i) => (v > (bucketTotals[best] ?? -1) ? i : best), -1));

	// OLD CODE START — max values now computed internally by HorizontalBarList component
	// let maxTalkerCount = $derived(topTalkers.length > 0 ? topTalkers[0].count : 1);
	// let maxProtocolCount = $derived(protocols.length > 0 ? Math.max(1, ...protocols.map((p) => p.count)) : 1);
	// let maxDestCount = $derived(topDestinations.length > 0 ? topDestinations[0].count : 1);
	// let maxDnsCount = $derived(topDns.length > 0 ? topDns[0].count : 1);
	// OLD CODE END

	let hasActiveFilters = $derived(activeIpFilter !== '' || activeDnsFilter !== '' || logType !== 'all');

	const rangeWords = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange)?.words ?? 'last 24 hours');

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(rangeValue: TimeRange = selectedTimeRange): { from: string; to: string } {
		const now = Date.now();
		const range = TIME_RANGES.find((r) => r.value === rangeValue) || TIME_RANGES[3];
		return {
			from: new Date(now - range.ms).toISOString(),
			to: new Date(now).toISOString(),
		};
	}

	function timeRangeToISO(range: TimeRange): string {
		const now = Date.now();
		const tr = TIME_RANGES.find((r) => r.value === range);
		return new Date(now - (tr?.ms || 24 * 60 * 60_000)).toISOString();
	}

	function formatTimestamp(ts: string): string {
		try {
			const d = new Date(ts);
			const mon = d.toLocaleString('en-US', { month: 'short' });
			const day = d.getDate();
			const time = d.toLocaleTimeString('en-US', { hour12: false });
			return `${mon} ${day}, ${time}`;
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
	/** The six aggregations for the current range; null when a newer load took over. */
	async function fetchDashboard(guard: LoadGuard, g: number): Promise<boolean[] | null> {
		const range = selectedTimeRange;
		loading = true;
		const { from, to } = getTimeRange(range);
		const interval = INTERVAL_MAP[range] || '1h';

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
		if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
		if (results[2].status === 'fulfilled') topTalkers = results[2].value.talkers;
		if (results[3].status === 'fulfilled') protocols = results[3].value.protocols;
		if (results[4].status === 'fulfilled') topDestinations = results[4].value.destinations;
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
	async function fetchLogs(append = false): Promise<LoadResult> {
		const g = tableGuard.begin();
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
			let fullQuery = query.trim();
			if (activeIpFilter) {
				const ipQ = `(source.ip:"${activeIpFilter}" OR destination.ip:"${activeIpFilter}")`;
				fullQuery = fullQuery ? `${fullQuery} AND ${ipQ}` : ipQ;
			}
			if (activeDnsFilter) {
				const dnsQ = `zeek.dns.query:"${activeDnsFilter}"`;
				fullQuery = fullQuery ? `${fullQuery} AND ${dnsQ}` : dnsQ;
			}
			if (fullQuery) params.set('query', fullQuery);

			params.set('from', timeRangeToISO(selectedTimeRange));
			params.set('to', new Date().toISOString());
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
			searchAfter = data.search_after;
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
		const [dashboard, table] = await Promise.all([fetchDashboard(guard, g), fetchLogs()]);
		if (!guard.current(g) || dashboard === null) return 'skipped';
		// A table load that a newer search replaced says nothing about this refresh
		const outcomes = table === 'skipped' ? dashboard : [...dashboard, table === 'ok'];
		const ok = outcomes.filter(Boolean).length;
		return ok === outcomes.length ? 'ok' : ok === 0 ? 'failed' : 'partial';
	}

	// ---------------------------------------------------------------------------
	// Event handlers
	// ---------------------------------------------------------------------------

	function handleTimeRangeChange(value: TimeRange) {
		selectedTimeRange = value;
		// #96: the last range's figures must not stand in for this range if its load fails
		statsLoaded = false;
		timeline = [];
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

	function setLogType(lt: LogType) {
		logType = lt;
		if (initialized) {
			fetchLogs();
			fetchFieldDefs();
		}
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
	function setSort(field: string, dir: SortDir) {
		sortField = field;
		sortDir = dir;
		fetchLogs();
	}

	// Click-to-drill handlers
	function drillByProtocol(dataset: string) {
		const lt = DATASET_TO_LOG_TYPE[dataset];
		if (lt) {
			logType = lt;
			if (initialized) {
				fetchLogs();
				fetchFieldDefs();
				document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
			}
		}
	}

	function drillByIp(ip: string) {
		if (activeIpFilter === ip) {
			activeIpFilter = '';
		} else {
			activeIpFilter = ip;
		}
		if (initialized) {
			fetchLogs();
			document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
		}
	}

	function drillByDns(domain: string) {
		if (activeDnsFilter === domain) {
			activeDnsFilter = '';
		} else {
			activeDnsFilter = domain;
			// Switch to DNS tab for best context
			logType = 'zeek.dns';
		}
		if (initialized) {
			fetchLogs();
			fetchFieldDefs();
			document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' });
		}
	}

	function clearAllFilters() {
		activeIpFilter = '';
		activeDnsFilter = '';
		logType = 'all';
		query = '';
		if (initialized) {
			fetchLogs();
			fetchFieldDefs();
		}
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
		if (src) goto(`/devices/${encodeURIComponent(String(Array.isArray(src) ? src[0] : src))}`);
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
			refreshInterval = setInterval(() => refresh.run(), 30_000);
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
		'zeek.dhcp.client_addr': dhcpIpCell,
	};

	const logColumns = $derived<Column<LogRow>[]>(
		COLUMNS[logType].map((col) => ({
			key: col,
			label: shortFieldName(col),
			numeric: NUMERIC_FIELDS.has(col),
			class: MONO_FIELDS.has(col) || IP_FIELDS.has(col) ? 'mono' : undefined,
			cell: IP_CELLS[col],
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
	/** The ?filter= / ?ip= / ?query= last applied; null before the first load. */
	let appliedSearch: string | null = null;

	$effect(() => {
		// Deep links from other pages (e.g., /logs?filter=1.2.3.4) and the top-bar search hand-off
		const params = $page.url.searchParams;
		const urlFilter = params.get('filter');
		const urlIp = params.get('ip');
		const urlQuery = params.get('query');
		const search = JSON.stringify([urlFilter, urlIp, urlQuery]);
		untrack(() => {
			// The hash changes too (the KPI links); only a new search runs one
			if (search === appliedSearch) return;
			const first = appliedSearch === null;
			appliedSearch = search;
			// A hand-off replaces the last one's IP filter and text; the first load starts from neither
			activeIpFilter = urlFilter || urlIp || '';
			query = urlFilter || urlIp ? '' : (urlQuery ?? '');
			if (first) {
				refresh.run().then(() => {
					initialized = true;
				});
				fetchFieldDefs();
			} else {
				fetchLogs();
			}
		});
	});
</script>

{#snippet ipValue(value: unknown)}
	{#if value != null && value !== ''}<IPAddress ip={String(value)} />{:else}--{/if}
{/snippet}
{#snippet sourceIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'source.ip'))}{/snippet}
{#snippet destinationIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'destination.ip'))}{/snippet}
{#snippet dhcpIpCell(r: LogRow)}{@render ipValue(getNestedValue(r.hit._source, 'zeek.dhcp.client_addr'))}{/snippet}

{#snippet timelineBody()}
	<AreaChart
		series={[{ key: 'events', label: 'Events', colour: 1, points: timeline.map((b, i) => ({ t: b.timestamp, v: bucketTotals[i] })) }]}
		formatX={(t) => formatShortTimestamp(String(t))}
		formatY={formatCompactNumber}
		formatTip={(i) => `${formatShortTimestamp(timeline[i]?.timestamp ?? '')} · ${(bucketTotals[i] ?? 0).toLocaleString()} events`}
		highlightIndex={busiest}
		ariaLabel={busiest >= 0
			? `Busiest at ${formatShortTimestamp(timeline[busiest].timestamp)}, with ${bucketTotals[busiest].toLocaleString()} events`
			: 'Log events over time'}
	/>
{/snippet}
{#snippet protocolsBody()}
	<BarList
		items={protocols.map((proto) => ({
			key: proto.protocol,
			label: proto.label || protocolLabel(proto.protocol),
			value: proto.count,
			display: formatCompactNumber(proto.count),
			onclick: () => drillByProtocol(proto.protocol),
		}))}
	/>
{/snippet}
{#snippet talkersBody()}
	<BarList
		items={topTalkers.map((talker) => ({
			key: talker.ip,
			label: talker.ip,
			value: talker.count,
			display: formatCompactNumber(talker.count),
			detail: activeIpFilter === talker.ip ? 'filtering the table' : undefined,
			onclick: () => drillByIp(talker.ip),
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
			detail: activeIpFilter === dest.ip ? 'filtering the table' : undefined,
			onclick: () => drillByIp(dest.ip),
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
		<p class="page-sub">Every Zeek and Suricata log entry in the range, searchable</p>
	</div>
	<div class="head-actions">
		<Pills options={TIME_RANGES} value={selectedTimeRange} onchange={handleTimeRangeChange} ariaLabel="Time range" />
		<button class="btn" type="button" aria-pressed={autoRefresh} onclick={toggleAutoRefresh}>
			<Icon name="refresh" />{autoRefresh ? 'Auto-refresh on' : 'Auto-refresh'}
		</button>
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

	<Card title="Activity timeline" sub="Log events per {INTERVAL_WORDS[INTERVAL_MAP[selectedTimeRange]] ?? 'hour'} · {rangeWords}" hero class="c-8">
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
				{#if activeIpFilter}
					<button class="chip" type="button" aria-label="Remove filter IP: {activeIpFilter}" onclick={() => { activeIpFilter = ''; fetchLogs(); }}>
						IP: <span class="mono">{activeIpFilter}</span><Icon name="close" />
					</button>
				{/if}
				{#if activeDnsFilter}
					<button class="chip" type="button" aria-label="Remove filter DNS: {activeDnsFilter}" onclick={() => { activeDnsFilter = ''; fetchLogs(); fetchFieldDefs(); }}>
						DNS: <span class="mono">{activeDnsFilter}</span><Icon name="close" />
					</button>
				{/if}
				<button class="link" type="button" onclick={clearAllFilters}>Clear all</button>
			</div>
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
					Showing <strong class="num">{results.length.toLocaleString()}</strong> of <strong class="num">{totalHits.toLocaleString()}</strong> results{tableLoading ? ' · searching…' : ''}
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
			<LogDrawerContent hit={drawerHit} activeTab={drawerTab} timeRange={timeRangeToISO(selectedTimeRange)} />
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
	/* In-card anchors for the KPI links and the drill scrolls; the margin keeps the card head in view */
	.anchor { display: block; scroll-margin-top: calc(var(--sp-8) * 3); }
	.stale { margin-bottom: var(--sp-3); }
	/* The log search takes the toolbar's free width (the system caps a toolbar search at 360px) */
	.search-wide { display: flex; flex: 1 1 28rem; min-width: 0; }
	.search-wide :global(.search) { max-width: none; }
	/* Nine log types: the pill group scrolls sideways instead of overflowing a phone */
	.types { overflow-x: auto; }
	.filters { align-items: center; margin-bottom: var(--sp-4); font-size: var(--text-xs); }
	button.chip { border: 0; cursor: pointer; }
	button.link { background: none; border: 0; padding: 0; cursor: pointer; }
</style>
