<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		getConnections,
		getConnectionStats,
		getConnectionSankey,
		getConnectionTimeline,
	} from '$api/traffic';
	import type { ConnectionSort } from '$api/traffic';
	import type {
		Connection,
		ConnectionsResponse,
		ConnectionStatsResponse,
		SankeyResponse,
		ConnectionTimelineResponse,
		ConnectionTimelineBucket,
	} from '$api/traffic';
	// OLD CODE START — getLiveConnections({ limit: 1 }).count is the length of a 1-item list
	// import { getLiveConnections } from '$api/live';
	// OLD CODE END
	import { getLiveDashboard } from '$api/live';
	import { loadFailed } from '$lib/utils/load-failed';
	import IPAddress from '$components/IPAddress.svelte';
	// OLD CODE START — replaced by the system's BarList (ui/BarList)
	// import HorizontalBarList from '$components/HorizontalBarList.svelte';
	// import type { BarItem } from '$components/HorizontalBarList.svelte';
	// OLD CODE END
	import BarList, { type BarItem } from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import StatStrip, { type Stat } from '$lib/components/ui/StatStrip.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import ConnResult, { type ConnResultKind } from '$lib/components/ui/ConnResult.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, createLoadGuard, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import type { SortDir } from '$lib/utils/table-sort.svelte';
	import SankeyDiagram from '$components/SankeyDiagram.svelte';
	import SessionTimeline from '$components/SessionTimeline.svelte';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import ConnectionDrawerContent from '$components/drawer/content/ConnectionDrawerContent.svelte';
	import { buildTSharkFilter, getField, asString } from '$lib/utils/tshark-filter';
	import { captureMode } from '$lib/stores/captureMode';
	// OLD CODE START — #145: the client-side sort is gone
	// import { compareValues } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import { connectionDurationMs } from '$lib/utils/connection-duration';

	// ---------------------------------------------------------------------------
	// Types & Constants
	// ---------------------------------------------------------------------------

	type StateFilter = 'all' | 'established' | 'closed' | 'rejected' | 'timeout';

	interface TimeRange {
		label: string;
		value: string;
		ms: number;
		/** The window in words, for card subtitles */
		text: string;
	}

	const TIME_RANGES: TimeRange[] = [
		{ label: '15m', value: '15m', ms: 15 * 60 * 1000, text: 'Last 15 minutes' },
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000, text: 'Last hour' },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000, text: 'Last 4 hours' },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000, text: 'Last 24 hours' },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000, text: 'Last 7 days' },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m', '1h': '5m', '4h': '15m', '24h': '1h', '7d': '6h',
	};

	const STATE_FILTERS: { value: StateFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'established', label: 'Established' },
		{ value: 'closed', label: 'Closed' },
		{ value: 'rejected', label: 'Rejected' },
		{ value: 'timeout', label: 'Timeout' },
	];

	const PROTOCOL_OPTIONS = ['All', 'TCP', 'UDP', 'ICMP', 'TLS'] as const;

	// OLD CODE START — the protocol badges and bars took a colour each; the system's tags and bar
	// lists are one colour (PLAN.md §4.1)
	// const PROTO_COLORS: Record<string, string> = {
	// 	tcp: 'var(--data-1)', udp: 'var(--data-5)', tls: 'var(--data-4)',
	// 	dns: 'var(--data-2)', icmp: 'var(--data-6)', http: 'var(--data-3)',
	// };
	// OLD CODE END

	const RANGE_PILLS = TIME_RANGES.map((r) => ({ value: r.value, label: r.label }));
	const PROTOCOL_PILLS = PROTOCOL_OPTIONS.map((p) => ({ value: p as string, label: p }));
	const AUTO_REFRESH_MS = 15_000;

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// OLD CODE START — the load guard (below) makes a load started before the first one finished
	// safe, so range and filter changes no longer wait for it
	// let initialized = $state(false);
	// OLD CODE END
	let loading = $state(false);

	// Time range
	let selectedTimeRange = $state<TimeRange>(TIME_RANGES[1]); // 1h
	let autoRefresh = $state(false);
	let refreshInterval = $state<ReturnType<typeof setInterval> | null>(null);

	// Stats
	let stats = $state<ConnectionStatsResponse | null>(null);
	// OLD CODE START — #96: 0 before (or without) a successful load read as "0 Active Devices"
	// let activeNow = $state(0);
	// OLD CODE END
	let activeNow = $state<number | null>(null);
	let liveFailed = $state(false);

	// Sankey
	let sankey = $state<SankeyResponse | null>(null);

	// Timeline
	let timeline = $state<ConnectionTimelineBucket[]>([]);

	// #96: a failed request keeps the last good figures and says so, never zeros or "none"
	let statsFailed = $state(false);
	let sankeyFailed = $state(false);
	let timelineFailed = $state(false);
	let connectionsFailed = $state(false);

	// Connections table
	let connections = $state<Connection[]>([]);
	let totalConnections = $state(0);
	let totalPages = $state(0);
	let currentPage = $state(1);
	let pageSize = $state(50);

	// Filters
	let protocolFilter = $state('All');
	let serviceFilter = $state('');
	let ipFilter = $state('');
	let countryFilter = $state('');
	let stateFilter = $state<StateFilter>('all');
	let hasAlertsFilter = $state(false);
	let sankeyFilter = $state<{ type: string; id: string } | null>(null);

	// Drawer
	let drawerConn = $state<Connection | null>(null);
	let drawerTab = $state('summary');
	let isMirrorMode = $state(false);
	const CONN_DRAWER_TABS = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'tshark', label: 'TShark' },
		{ id: 'related', label: 'Related' },
		{ id: 'flow', label: 'Flow' },
	];

	captureMode.subscribe((mode) => { isMirrorMode = mode === 'mirror'; });

	// OLD CODE START — #145: the page sorted only the 50 rows it had
	// // Sort
	// type SortKey = 'timestamp' | 'src' | 'dst' | 'protocol' | 'service' | 'duration' | 'bytesIn' | 'bytesOut' | 'state';
	// let sortKey = $state<SortKey | null>(null);
	// let sortDir = $state<'asc' | 'desc'>('desc');
	// OLD CODE END
	// Sort: on the daemon, so a header orders every page of results, not just the one shown (#145)
	type SortKey = ConnectionSort;
	let sortKey = $state<SortKey>('time');
	let sortDir = $state<'asc' | 'desc'>('desc');

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	// OLD CODE START — #145: sorting moved to the daemon; this ordered one page of 50 rows
	// /** A port as text (asString drops numbers); '' when missing. */
	// function portText(conn: Connection, field: string): string {
	// 	const v = getField(conn, field);
	// 	const first = Array.isArray(v) ? v[0] : v;
	// 	return first === undefined || first === null ? '' : String(first);
	// }

	// function sortValue(conn: Connection, key: SortKey): string | number {
	// 	switch (key) {
	// 		case 'timestamp': return conn['@timestamp'] as string ?? '';
	// 		// OLD CODE START — IP only, so one device's connections kept their ports out of order
	// 		// case 'src': return asString(getField(conn, 'source.ip'));
	// 		// case 'dst': return asString(getField(conn, 'destination.ip'));
	// 		// OLD CODE END
	// 		// IP, then port: compareValues reads both numbers ("192.168.1.9 443" before "192.168.1.10 80")
	// 		case 'src': return `${asString(getField(conn, 'source.ip'))} ${portText(conn, 'source.port')}`.trim();
	// 		case 'dst': return `${asString(getField(conn, 'destination.ip'))} ${portText(conn, 'destination.port')}`.trim();
	// 		case 'protocol': return asString(getField(conn, 'network.transport'));
	// 		case 'service': return asString(getField(conn, 'protocol'));
	// 		// OLD CODE START — #144: NaN for every epoch-ms record, so the sort did nothing
	// 		// case 'duration': {
	// 		// 	const start = getField(conn, 'event.start') as string | undefined;
	// 		// 	const end = getField(conn, 'event.end') as string | undefined;
	// 		// 	if (!start || !end) return 0;
	// 		// 	return new Date(end).getTime() - new Date(start).getTime();
	// 		// }
	// 		// OLD CODE END
	// 		case 'duration': return connectionDurationMs(conn) ?? -1;
	// 		case 'bytesIn': return (getField(conn, 'source.bytes') ?? getField(conn, 'client.bytes') ?? 0) as number;
	// 		case 'bytesOut': return (getField(conn, 'destination.bytes') ?? getField(conn, 'server.bytes') ?? 0) as number;
	// 		case 'state': return connState(conn);
	// 	}
	// }

	// let sortedConnections = $derived.by(() => {
	// 	if (!sortKey) return connections;
	// 	const key = sortKey;
	// 	const dir = sortDir;
	// 	return [...connections].sort((a, b) => {
	// 		const va = sortValue(a, key);
	// 		const vb = sortValue(b, key);
	// 		if (typeof va === 'number' && typeof vb === 'number') return dir === 'asc' ? va - vb : vb - va;
	// 		// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 		// return dir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
	// 		// OLD CODE END
	// 		return dir === 'asc' ? compareValues(va, vb) : compareValues(vb, va);
	// 	});
	// });
	// OLD CODE END

	// OLD CODE START — HorizontalBarList items; the system's BarList takes display/detail, one colour
	// // Bar list items for analytics row
	// let sourceBarItems = $derived<BarItem[]>(
	// 	(stats?.top_sources || []).map((s, i) => ({
	// 		key: s.ip,
	// 		label: s.ip,
	// 		value: s.total_bytes,
	// 		formattedValue: formatBytes(s.total_bytes),
	// 		secondaryValue: `${s.connections} conn`,
	// 		color: 'var(--cyan)',
	// 		isIp: true,
	// 		mono: true,
	// 	}))
	// );
	//
	// let protocolBarItems = $derived<BarItem[]>(
	// 	(stats?.protocols || []).map((p) => ({
	// 		key: p.name,
	// 		label: p.name.toUpperCase(),
	// 		value: p.count,
	// 		formattedValue: formatNumber(p.count),
	// 		color: PROTO_COLORS[p.name.toLowerCase()] || 'var(--accent)',
	// 	}))
	// );
	//
	// let destBarItems = $derived<BarItem[]>(
	// 	(stats?.top_destinations || []).map((d) => ({
	// 		key: d.ip,
	// 		label: d.asn || d.ip,
	// 		value: d.total_bytes,
	// 		formattedValue: formatBytes(d.total_bytes),
	// 		secondaryValue: d.country || '',
	// 		color: 'var(--data-2)',
	// 	}))
	// );
	// OLD CODE END
	// The IP's context menu had "device details"; the bar label now links there
	let sourceBarItems = $derived<BarItem[]>(
		(stats?.top_sources || []).map((s) => ({
			key: s.ip,
			label: s.ip,
			value: s.total_bytes,
			display: formatBytes(s.total_bytes),
			detail: `${s.connections.toLocaleString('en-GB')} conn`,
			href: `/devices/${encodeURIComponent(s.ip)}`,
		}))
	);

	let protocolBarItems = $derived<BarItem[]>(
		(stats?.protocols || []).map((p) => ({
			key: p.name,
			label: p.name.toUpperCase(),
			value: p.count,
			display: formatNumber(p.count),
		}))
	);

	let destBarItems = $derived<BarItem[]>(
		(stats?.top_destinations || []).map((d) => ({
			key: d.ip,
			label: d.asn || d.ip,
			value: d.total_bytes,
			display: formatBytes(d.total_bytes),
			detail: d.country || undefined,
		}))
	);

	let range = $derived(selectedTimeRange.text);

	let summaryStats = $derived<Stat[]>([
		{ key: 'sessions', label: 'Sessions', value: stats ? formatNumber(stats.total_sessions) : '—' },
		{ key: 'data', label: 'Data', value: stats ? formatBytes(stats.bytes_in + stats.bytes_out) : '—' },
		{ key: 'alerts', label: 'With alerts', value: stats ? formatNumber(stats.alert_sessions) : '—' },
		{ key: 'devices', label: 'Active devices', value: activeNow === null ? '—' : String(activeNow) },
	]);

	let summarySub = $derived(
		stats
			? `${range} · ${formatBytes(stats.bytes_in)} in, ${formatBytes(stats.bytes_out)} out · devices active in the last 5 minutes`
			: `${range} · devices active in the last 5 minutes`,
	);

	// Log-scale bars in both byte columns share the page's largest value
	let maxRowBytes = $derived(Math.max(0, ...connections.map((c) => Math.max(bytesIn(c) ?? 0, bytesOut(c) ?? 0))));

	// ---------------------------------------------------------------------------
	// Display helpers
	// ---------------------------------------------------------------------------

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '—';
		try { return new Date(ts).toLocaleString(); } catch { return ts; }
	}

	function formatBytes(bytes: number | undefined): string {
		if (bytes === undefined || bytes === null) return '—';
		if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
		if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
		if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${bytes} B`;
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
		return String(n);
	}

	function formatDuration(conn: Connection): string {
		// OLD CODE START — #144: event.start/end are epoch-ms text on Malcolm 26.x, so every row read "--"
		// const start = getField(conn, 'event.start') as string | undefined;
		// const end = getField(conn, 'event.end') as string | undefined;
		// if (!start || !end) return '--';
		// const ms = new Date(end).getTime() - new Date(start).getTime();
		// if (isNaN(ms) || ms < 0) return '--';
		// OLD CODE END
		const ms = connectionDurationMs(conn);
		if (ms === null) return '—';
		const seconds = ms / 1000;
		if (seconds < 1) return `${ms}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		// OLD CODE START — split before rounding, so 30 min 59.6 s read "30m 60s"
		// const mins = Math.floor(seconds / 60);
		// const secs = (seconds % 60).toFixed(0);
		// return `${mins}m ${secs}s`;
		// OLD CODE END
		const total = Math.round(seconds);
		return `${Math.floor(total / 60)}m ${total % 60}s`;
	}

	function connState(conn: Connection): string {
		const state = asString(getField(conn, 'zeek.conn.conn_state'));
		const lower = state.toLowerCase();
		if (lower.includes('established') || lower === 'sf' || lower === 's1') return 'established';
		if (lower.includes('reject') || lower === 'rej' || lower === 'rstr' || lower === 'rsto') return 'rejected';
		if (lower.includes('timeout') || lower === 's0') return 'timeout';
		if (lower.includes('closed') || lower === 's2' || lower === 's3') return 'closed';
		return lower || 'unknown';
	}

	// OLD CODE START — legacy badge classes; the system shows a connection result as ConnResult
	// function stateBadgeClass(state: string): string {
	// 	switch (state) {
	// 		case 'established': return 'badge badge-success';
	// 		case 'closed': return 'badge badge-muted';
	// 		case 'rejected': return 'badge badge-danger';
	// 		case 'timeout': return 'badge badge-warning';
	// 		default: return 'badge badge-muted';
	// 	}
	// }
	//
	// function stateLabel(conn: Connection): string {
	// 	const raw = asString(getField(conn, 'zeek.conn.conn_state'));
	// 	const mapped = connState(conn);
	// 	if (raw && mapped !== raw.toLowerCase()) return `${mapped.toUpperCase()} (${raw})`;
	// 	return mapped.toUpperCase();
	// }
	// OLD CODE END

	/** Zeek's conn_state as the system's result (README "Connection results"); null when unknown. */
	function connResult(conn: Connection): ConnResultKind | null {
		switch (connState(conn)) {
			// SF ran to a normal close; S1 and the like are still open
			case 'established': return rawState(conn).toUpperCase() === 'SF' ? 'completed' : 'ongoing';
			case 'closed': return 'completed';
			case 'rejected': return 'reset';
			case 'timeout': return 'no-reply';
			default: return null;
		}
	}

	const rawState = (conn: Connection) => asString(getField(conn, 'zeek.conn.conn_state'));
	const bytesIn = (conn: Connection) => (getField(conn, 'source.bytes') ?? getField(conn, 'client.bytes')) as number | undefined;
	const bytesOut = (conn: Connection) => (getField(conn, 'destination.bytes') ?? getField(conn, 'server.bytes')) as number | undefined;

	/** One result for a load from its parts: newer loads own the 'skipped' parts. */
	function outcome(parts: ('ok' | 'failed' | 'skipped')[]): LoadResult {
		const done = parts.filter((p) => p !== 'skipped');
		if (done.length === 0) return 'skipped';
		const failed = done.filter((p) => p === 'failed').length;
		return failed === 0 ? 'ok' : failed === done.length ? 'failed' : 'partial';
	}
	const settled = (r: PromiseSettledResult<unknown>) => (r.status === 'fulfilled' ? 'ok' : 'failed');

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	function getTimeRange() {
		const now = new Date();
		const from = new Date(now.getTime() - selectedTimeRange.ms).toISOString();
		const to = now.toISOString();
		return { from, to };
	}

	function buildSearchQuery(): string {
		const parts: string[] = [];
		if (protocolFilter !== 'All') parts.push(protocolFilter.toLowerCase());
		if (serviceFilter.trim()) parts.push(serviceFilter.trim());
		if (ipFilter.trim()) parts.push(ipFilter.trim());
		// Apply sankey filter
		if (sankeyFilter) {
			if (sankeyFilter.type === 'source') parts.push(`source.ip:${sankeyFilter.id}`);
			else if (sankeyFilter.type === 'protocol') parts.push(sankeyFilter.id.toLowerCase());
			else if (sankeyFilter.type === 'destination') parts.push(`destination.as.full:"${sankeyFilter.id}"`);
		}
		return parts.join(' ');
	}

	// OLD CODE START — PLAN.md §5.5: each load wrote whatever answered last, so a slow 24 h response
	// could overwrite a newer 1 h one; loads now go through the page refresh contract and a load guard
	// // OLD CODE START — always reloaded page 1, so auto-refresh threw the user back to the first page
	// // async function fetchAll() {
	// // OLD CODE END
	// /** Reload everything; the table stays on `pg` (the current page unless told otherwise). */
	// async function fetchAll(pg: number = currentPage) {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	const interval = INTERVAL_MAP[selectedTimeRange.value] || '15m';
	//
	// 	try {
	// 		const [statsRes, sankeyRes, timelineRes, liveRes] = await Promise.allSettled([
	// 			getConnectionStats({ from, to }),
	// 			getConnectionSankey({ from, to, limit: 10 }),
	// 			getConnectionTimeline({ from, to, interval }),
	// 			// OLD CODE START — count of a 1-item list, so "Active Now" was only ever 0 or 1
	// 			// getLiveConnections({ limit: 1 }),
	// 			// OLD CODE END
	// 			getLiveDashboard({ limit: 1 }),
	// 		]);
	//
	// 		if (statsRes.status === 'fulfilled') stats = statsRes.value;
	// 		if (sankeyRes.status === 'fulfilled') sankey = sankeyRes.value;
	// 		if (timelineRes.status === 'fulfilled') timeline = timelineRes.value.buckets;
	// 		statsFailed = statsRes.status === 'rejected';
	// 		sankeyFailed = sankeyRes.status === 'rejected';
	// 		timelineFailed = timelineRes.status === 'rejected';
	// 		// OLD CODE START
	// 		// if (liveRes.status === 'fulfilled') activeNow = liveRes.value.count;
	// 		// OLD CODE END
	// 		// Distinct source devices seen in the live window (last 5 minutes)
	// 		if (liveRes.status === 'fulfilled') activeNow = liveRes.value.stats?.active_devices ?? 0;
	// 		liveFailed = liveRes.status === 'rejected';
	// 	} catch { /* handled per-request */ }
	//
	// 	// OLD CODE START
	// 	// await fetchConnections(1);
	// 	// OLD CODE END
	// 	await fetchConnections(pg);
	// 	loading = false;
	// }
	//
	// async function fetchConnections(pg: number = 1) {
	// 	const { from, to } = getTimeRange();
	// 	const q = buildSearchQuery();
	// 	try {
	// 		// OLD CODE START — #145: filtered one page of 50 rows, while the total and pages counted all
	// 		// const response: ConnectionsResponse = await getConnections({
	// 		// 	from, to, page: pg, size: pageSize, q: q || undefined,
	// 		// });
	// 		// let filtered = response.connections;
	// 		// if (stateFilter !== 'all') {
	// 		// 	filtered = filtered.filter((c) => connState(c) === stateFilter);
	// 		// }
	// 		// connections = filtered;
	// 		// OLD CODE END
	// 		const response: ConnectionsResponse = await getConnections({
	// 			from, to, page: pg, size: pageSize, q: q || undefined,
	// 			sort: sortKey, order: sortDir, state: stateFilter === 'all' ? undefined : stateFilter,
	// 		});
	// 		connections = response.connections;
	// 		currentPage = response.page;
	// 		totalPages = response.total_pages;
	// 		totalConnections = response.total;
	// 		connectionsFailed = false;
	// 	} catch {
	// 		// rows are specific to this page and filter set, so they are not kept as stale
	// 		connections = [];
	// 		totalPages = 0;
	// 		totalConnections = 0;
	// 		connectionsFailed = true;
	// 	}
	// }
	// OLD CODE END

	// The summary (stats, flow, timeline, live) and the table load separately: a page, sort or filter
	// change reloads only the table, so it has its own guard and never drops the summary's figures.
	const tableGuard = createLoadGuard();
	const refresh = registerPageRefresh(loadAll);

	/** The table for page `pg` in `span`; a newer table load makes this one write nothing. */
	async function loadTable(pg: number, span = getTimeRange()): Promise<'ok' | 'failed' | 'skipped'> {
		const t = tableGuard.begin();
		const q = buildSearchQuery();
		const params = {
			...span, page: pg, size: pageSize, q: q || undefined,
			sort: sortKey, order: sortDir, state: stateFilter === 'all' ? undefined : stateFilter,
		};
		try {
			const response: ConnectionsResponse = await getConnections(params);
			if (!tableGuard.current(t)) return 'skipped';
			connections = response.connections;
			currentPage = response.page;
			totalPages = response.total_pages;
			totalConnections = response.total;
			connectionsFailed = false;
			return 'ok';
		} catch {
			if (!tableGuard.current(t)) return 'skipped';
			// rows are specific to this page and filter set, so they are not kept as stale
			connections = [];
			totalPages = 0;
			totalConnections = 0;
			connectionsFailed = true;
			return 'failed';
		}
	}

	/** Reload everything; the table stays on the current page. The top bar's Refresh calls this. */
	async function loadAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const span = getTimeRange();
		const interval = INTERVAL_MAP[selectedTimeRange.value] || '15m';
		loading = true;
		const table = loadTable(currentPage, span);
		const results = await Promise.allSettled([
			getConnectionStats(span),
			getConnectionSankey({ ...span, limit: 10 }),
			getConnectionTimeline({ ...span, interval }),
			getLiveDashboard({ limit: 1 }),
		]);
		const [statsRes, sankeyRes, timelineRes, liveRes] = results;
		if (guard.current(g)) {
			if (statsRes.status === 'fulfilled') stats = statsRes.value;
			if (sankeyRes.status === 'fulfilled') sankey = sankeyRes.value;
			if (timelineRes.status === 'fulfilled') timeline = timelineRes.value.buckets;
			statsFailed = statsRes.status === 'rejected';
			sankeyFailed = sankeyRes.status === 'rejected';
			timelineFailed = timelineRes.status === 'rejected';
			// Distinct source devices seen in the live window (last 5 minutes)
			if (liveRes.status === 'fulfilled') activeNow = liveRes.value.stats?.active_devices ?? 0;
			liveFailed = liveRes.status === 'rejected';
		}
		const tableResult = await table;
		if (!guard.current(g)) return 'skipped';
		loading = false;
		return outcome([...results.map(settled), tableResult]);
	}

	// ---------------------------------------------------------------------------
	// Interaction handlers
	// ---------------------------------------------------------------------------

	// OLD CODE START — the DataTable owns the header buttons and their direction (a new column
	// starts descending, as in every table); the page asks the daemon for that order
	// function toggleSort(key: SortKey) {
	// 	if (sortKey === key) {
	// 		sortDir = sortDir === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		sortKey = key;
	// 		// OLD CODE START — #145: page key names
	// 		// sortDir = key === 'timestamp' ? 'desc' : 'asc';
	// 		// OLD CODE END
	// 		sortDir = key === 'time' ? 'desc' : 'asc';
	// 	}
	// 	fetchConnections(1);
	// }
	// OLD CODE END
	function handleSortChange(key: string, dir: SortDir) {
		sortKey = key as SortKey;
		sortDir = dir;
		void loadTable(1);
	}

	// OLD CODE START — waited for the first load (`initialized`) and took the range object
	// function handleTimeRangeChange(range: TimeRange) {
	// 	selectedTimeRange = range;
	// 	// #96: the last range's figures must not stand in for this range if its load fails
	// 	stats = null;
	// 	sankey = null;
	// 	timeline = [];
	// 	// A new time range is a new result set: start from page 1
	// 	if (initialized) fetchAll(1);
	// }
	// OLD CODE END
	function handleTimeRangeChange(value: string) {
		selectedTimeRange = TIME_RANGES.find((r) => r.value === value) ?? selectedTimeRange;
		// #96: the last range's figures must not stand in for this range if its load fails
		stats = null;
		sankey = null;
		timeline = [];
		// A new time range is a new result set: start from page 1. The new load's guard
		// generation drops whatever the older range's requests return.
		currentPage = 1;
		void refresh.run();
	}

	function handleSankeyNodeClick(type: 'source' | 'protocol' | 'destination', id: string) {
		if (type === 'source') {
			// Source IPs navigate to device intelligence page
			goto(`/devices/${encodeURIComponent(id)}`);
			return;
		}
		// Protocol + Destination: toggle table filter (existing behavior)
		if (sankeyFilter?.type === type && sankeyFilter?.id === id) {
			sankeyFilter = null; // toggle off
		} else {
			sankeyFilter = { type, id };
		}
		// OLD CODE START: if (initialized) fetchConnections(1); OLD CODE END
		void loadTable(1);
	}

	function clearSankeyFilter() {
		sankeyFilter = null;
		// OLD CODE START: if (initialized) fetchConnections(1); OLD CODE END
		void loadTable(1);
	}

	function setProtocolFilter(value: string) {
		protocolFilter = value;
		void loadTable(1);
	}

	function setStateFilter(value: StateFilter) {
		stateFilter = value;
		void loadTable(1);
	}

	function applyOnEnter(e: KeyboardEvent) {
		if (e.key === 'Enter') void loadTable(1);
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			// OLD CODE START
			// refreshInterval = setInterval(fetchAll, 15_000);
			// OLD CODE END
			// OLD CODE START: refreshInterval = setInterval(() => fetchAll(), 15_000); OLD CODE END
			// A tick while a load is still running waits: starting another would make the guard
			// drop the slow one, and on a slow daemon nothing would ever land
			refreshInterval = setInterval(() => { if (!loading) void refresh.run(); }, AUTO_REFRESH_MS);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	function openDrawer(conn: Connection) {
		drawerConn = conn;
		drawerTab = 'summary';
	}

	function closeDrawer() {
		drawerConn = null;
		drawerTab = 'summary';
	}

	function goToPage(pg: number) {
		if (pg < 1 || pg > totalPages) return;
		// OLD CODE START: fetchConnections(pg); OLD CODE END
		void loadTable(pg);
	}

	function handlePageSizeChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		pageSize = parseInt(target.value) || 50;
		// OLD CODE START: fetchConnections(1); OLD CODE END
		void loadTable(1);
	}

	// ---------------------------------------------------------------------------
	// Table
	// ---------------------------------------------------------------------------

	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';

	// Keys are the daemon's sort names: the table is server-sorted (#145)
	const COLUMNS: Column<Connection>[] = [
		{ key: 'time', label: 'Time', cell: timeCell },
		{ key: 'source', label: 'Source', cell: sourceCell },
		{ key: 'destination', label: 'Destination', cell: destinationCell },
		{ key: 'proto', label: 'Protocol', cell: protoCell },
		{ key: 'service', label: 'Service', cell: serviceCell },
		{ key: 'duration', label: 'Duration', numeric: true, cell: durationCell },
		{ key: 'ul', label: 'Bytes in', numeric: true, cell: bytesInCell },
		{ key: 'dl', label: 'Bytes out', numeric: true, cell: bytesOutCell },
		{ key: 'state', label: 'Result', cell: resultCell },
	];

	const rowLabel = (conn: Connection) =>
		`Open connection from ${asString(getField(conn, 'source.ip')) || 'an unknown source'} to ${asString(getField(conn, 'destination.ip')) || 'an unknown destination'}`;

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	onMount(() => {
		const urlIp = $page.url.searchParams.get('ip');
		if (urlIp) ipFilter = urlIp;
		const urlProtocol = $page.url.searchParams.get('protocol');
		if (urlProtocol) protocolFilter = urlProtocol;

		// OLD CODE START: fetchAll().then(() => { initialized = true; }); OLD CODE END
		void refresh.run();
		return () => { if (refreshInterval) clearInterval(refreshInterval); };
	});

	// Navigating away: no pending load may write to this page again
	onDestroy(() => {
		refresh.unregister();
		tableGuard.invalidate();
	});
</script>

<svelte:head>
	<title>Connections | NetTap</title>
</svelte:head>

{#snippet timeCell(conn: Connection)}{formatTimestamp(conn['@timestamp'] as string | undefined)}{/snippet}

{#snippet sourceCell(conn: Connection)}
	{@const ip = asString(getField(conn, 'source.ip'))}
	{@const port = getField(conn, 'source.port')}
	{#if ip}
		<!-- No device name in the record, so the IP leads (in mono, keeping its context menu) -->
		<span class="who"><Icon name="devices" /><span class="mono"><IPAddress {ip} />{#if port}:{port}{/if}</span></span>
	{:else}—{/if}
{/snippet}

{#snippet destinationCell(conn: Connection)}
	{@const ip = asString(getField(conn, 'destination.ip'))}
	{@const port = getField(conn, 'destination.port')}
	{@const org = asString(getField(conn, 'destination.as.full'))}
	{#if ip}
		<span class="dest">
			<span class="mono"><IPAddress {ip} />{#if port}:{port}{/if}</span>
			{#if org}<span class="org trunc" title={org}>{org}</span>{/if}
		</span>
	{:else}—{/if}
{/snippet}

{#snippet protoCell(conn: Connection)}
	{@const proto = asString(getField(conn, 'network.transport')).toUpperCase()}
	{#if proto}<span class="tag">{proto}</span>{:else}—{/if}
{/snippet}

<!-- OLD CODE START: <td>{asString(getField(conn, 'protocol')) || '--'}</td> (#145: protocol's first entry is the transport, so Service read udp/tcp) OLD CODE END -->
{#snippet serviceCell(conn: Connection)}<span class="mono">{asString(getField(conn, 'network.protocol')) || '—'}</span>{/snippet}

{#snippet durationCell(conn: Connection)}{formatDuration(conn)}{/snippet}

{#snippet bytesInCell(conn: Connection)}
	<Bytes value={bytesIn(conn) ?? 0} max={maxRowBytes} display={formatBytes(bytesIn(conn))} />
{/snippet}

{#snippet bytesOutCell(conn: Connection)}
	<Bytes value={bytesOut(conn) ?? 0} max={maxRowBytes} display={formatBytes(bytesOut(conn))} />
{/snippet}

{#snippet resultCell(conn: Connection)}
	{@const result = connResult(conn)}
	{@const raw = rawState(conn)}
	<span class="result">
		{#if result}<ConnResult {result} />{/if}
		{#if raw}<span class="mono raw">{raw}</span>{:else if !result}—{/if}
	</span>
{/snippet}

<div class="page-head">
	<div>
		<h1 class="page-title">Connections</h1>
		<p class="page-sub">Every session your devices opened, with where it went and how it ended</p>
	</div>
	<div class="head-actions">
		<Pills options={RANGE_PILLS} value={selectedTimeRange.value} onchange={handleTimeRangeChange} ariaLabel="Time range" />
		<button class="btn" type="button" title="Refresh every 15 seconds" onclick={toggleAutoRefresh}>
			{autoRefresh ? 'Auto on' : 'Auto'}
		</button>
	</div>
</div>

<div class="grid">
	<!-- OLD CODE START — #96: with no stats (failed or not yet loaded) the cards read 0 sessions, 0 B
	<span class="stat-value mono">{formatNumber(stats?.total_sessions ?? 0)}</span>
	<span class="stat-value mono">{formatBytes(stats?.bytes_in ?? 0)}</span>
	<span class="stat-value mono">{formatBytes(stats?.bytes_out ?? 0)}</span>
	<span class="stat-value mono">{formatNumber(stats?.alert_sessions ?? 0)}</span>
	OLD CODE END -->
	<Card class="c-12" hero title="Summary" sub={summarySub}>
		{#if loading && stats === null && activeNow === null && !statsFailed && !liveFailed}
			<CardState state="loading" title="Loading connection stats" />
		{:else}
			<StatStrip stats={summaryStats} />
			{#if statsFailed}
				<p class="load-note">{loadFailed('connection stats', stats !== null)}</p>
			{/if}
			{#if liveFailed}
				<p class="load-note">{loadFailed('active devices', activeNow !== null)}</p>
			{/if}
		{/if}
	</Card>

	<article class="card c-8">
		<SessionTimeline buckets={timeline} {loading} emptyMessage={timelineFailed ? loadFailed('the session timeline') : undefined} />
		{#if timelineFailed && timeline.length > 0}
			<p class="load-note">{loadFailed('the session timeline', true)}</p>
		{/if}
	</article>

	<Card class="c-4" title="Protocols" sub="Sessions per protocol · {range}">
		{#if protocolBarItems.length > 0}
			<BarList items={protocolBarItems} />
		{:else if loading && !stats}
			<CardState state="loading" title="Loading protocols" />
		{:else if statsFailed}
			<CardState state="error" title={loadFailed('the protocol split')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else}
			<CardState state="empty" title="No protocols in this window" message="Protocols appear here once NetTap sees sessions in this time range." />
		{/if}
	</Card>

	<Card class="c-12" title="Network flow" sub="Source devices, then protocols, then destinations · {range}">
		{#if sankey && (sankey.nodes.sources.length || sankey.nodes.protocols.length || sankey.nodes.destinations.length)}
			<SankeyDiagram
				sources={sankey.nodes.sources}
				protocols={sankey.nodes.protocols}
				destinations={sankey.nodes.destinations}
				links={sankey.links}
				onNodeClick={handleSankeyNodeClick}
			/>
			{#if sankeyFailed}
				<p class="load-note">{loadFailed('the flow diagram', true)}</p>
			{/if}
		{:else if loading}
			<CardState state="loading" title="Loading the flow diagram" />
		{:else if sankeyFailed}
			<CardState state="error" title={loadFailed('the flow diagram')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else}
			<CardState state="empty" title="No flows in this window" message="Flows appear here once NetTap sees traffic in this time range." />
		{/if}
	</Card>

	<Card class="c-6" title="Top sources" sub="Data sent and received · {range}">
		{#if sourceBarItems.length > 0}
			<BarList items={sourceBarItems} />
		{:else if loading && !stats}
			<CardState state="loading" title="Loading top sources" />
		{:else if statsFailed}
			<CardState state="error" title={loadFailed('top sources')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else}
			<CardState state="empty" title="No sources in this window" message="Devices appear here once they send traffic in this time range." />
		{/if}
	</Card>

	<Card class="c-6" title="Top destinations" sub="Data sent and received, by network · {range}">
		{#if destBarItems.length > 0}
			<BarList items={destBarItems} />
		{:else if loading && !stats}
			<CardState state="loading" title="Loading top destinations" />
		{:else if statsFailed}
			<CardState state="error" title={loadFailed('top destinations')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else}
			<CardState state="empty" title="No destinations in this window" message="Destinations appear here once devices reach the internet in this time range." />
		{/if}
	</Card>

	<Card class="c-12" title="Sessions" sub="{connectionsFailed ? '—' : totalConnections.toLocaleString('en-GB')} matching · {range}">
		<div class="toolbar">
			<SearchField id="ip-filter" label="Filter by IP address" placeholder="IP address, such as 192.168.1.100" size="toolbar" bind:value={ipFilter} onkeydown={applyOnEnter} />
			<SearchField id="service-filter" label="Filter by service" placeholder="Service: dns, http, tls…" size="toolbar" bind:value={serviceFilter} onkeydown={applyOnEnter} />
			<Pills options={PROTOCOL_PILLS} value={protocolFilter} onchange={setProtocolFilter} ariaLabel="Protocol" />
			<Pills options={STATE_FILTERS} value={stateFilter} onchange={setStateFilter} ariaLabel="Connection state" />
			<label class="check-row">
				<input type="checkbox" bind:checked={hasAlertsFilter} onchange={() => loadTable(1)} />
				Has alerts
			</label>
			{#if sankeyFilter}
				<button class="chip" type="button" aria-label="Remove the {sankeyFilter.type} filter {sankeyFilter.id}" onclick={clearSankeyFilter}
					>{sankeyFilter.type}: {sankeyFilter.id}<Icon name="close" /></button
				>
			{/if}
			<button class="btn" type="button" onclick={() => loadTable(1)} disabled={loading}>Apply</button>
			<select class="select rows" aria-label="Rows per page" value={String(pageSize)} onchange={handlePageSizeChange}>
				<option value="25">25 rows</option>
				<option value="50">50 rows</option>
				<option value="100">100 rows</option>
			</select>
		</div>

		{#if loading && connections.length === 0 && !connectionsFailed}
			<CardState state="loading" title="Loading connections" />
		{:else if connectionsFailed && !loading}
			<CardState state="error" title={loadFailed('connections')} message={RETRY_HINT} onaction={() => loadTable(currentPage)} />
		{:else if connections.length === 0 && !loading}
			<CardState state="empty" title="No connections" message="No connections match this time range and these filters. Try a longer range or clear a filter." />
		{:else}
			<!-- OLD CODE START: {#each sortedConnections as conn (conn._id)} OLD CODE END -->
			<DataTable
				columns={COLUMNS}
				rows={connections}
				ariaLabel="Connections"
				rowKey={(conn) => conn._id}
				initialSort={{ key: sortKey, dir: sortDir }}
				onsortchange={handleSortChange}
				onrowactivate={openDrawer}
				rowLabel={rowLabel}
				selectedKey={drawerConn?._id}
				pager={totalPages > 0
					? {
							page: currentPage,
							pageCount: totalPages,
							total: totalConnections,
							from: (currentPage - 1) * pageSize + 1,
							to: (currentPage - 1) * pageSize + connections.length,
							onpage: goToPage,
						}
					: undefined}
			/>
		{/if}
	</Card>
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerConn !== null}
	title={drawerConn ? `${asString(getField(drawerConn, 'source.ip'))} → ${asString(getField(drawerConn, 'destination.ip'))}` : ''}
	subtitle={drawerConn ? `${asString(getField(drawerConn, 'network.transport')).toUpperCase()} · ${formatTimestamp(drawerConn['@timestamp'] as string | undefined)}` : ''}
	tabs={CONN_DRAWER_TABS}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => drawerTab = t}
>
	{#snippet children()}
		{#if drawerConn}
			<ConnectionDrawerContent connection={drawerConn} activeTab={drawerTab} {isMirrorMode} />
		{/if}
	{/snippet}
	{#snippet actions()}
		{#if drawerConn}
			{@const srcIp = asString(getField(drawerConn, 'source.ip'))}
			{@const dstIp = asString(getField(drawerConn, 'destination.ip'))}
			{@const cid = asString(getField(drawerConn, 'network.community_id'))}
			{#if srcIp}
				<button class="btn" type="button" onclick={() => goto(`/devices/${encodeURIComponent(srcIp)}`)}>
					View source device
				</button>
			{/if}
			{#if dstIp}
				<button class="btn" type="button" onclick={() => goto(`/devices/${encodeURIComponent(dstIp)}`)}>
					View destination device
				</button>
			{/if}
			{#if cid}
				<button class="btn" type="button" onclick={() => { navigator.clipboard.writeText(cid); }}>
					Copy community ID
				</button>
			{/if}
		{/if}
	{/snippet}
</DetailDrawer>

<style>
	/* Layout glue the system lacks */
	.load-note { margin-top: var(--sp-3); font-size: var(--text-xs); color: var(--sev-medium); }
	.dest { display: inline-flex; flex-direction: column; line-height: 1.3; }
	.org { color: var(--text-3); font-size: var(--text-xs); }
	.result { display: inline-flex; align-items: center; gap: var(--sp-2); }
	.raw { color: var(--text-3); font-size: var(--text-xs); }
	.rows { width: auto; }
	button.chip { border: 0; font-family: inherit; cursor: pointer; }
</style>
