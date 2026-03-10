<script lang="ts">
	import { onMount } from 'svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import {
		getLogStats,
		getLogTimeline,
		getLogTopTalkers,
		getLogProtocolBreakdown,
		getLogTopDestinations,
		getLogTopDns,
		formatBytes,
		formatCompactNumber,
		protocolColor,
		protocolLabel,
	} from '$lib/api/logs';
	import type {
		LogTimelineBucket,
		LogTalkerEntry,
		LogProtocolEntry,
		LogDestinationEntry,
		LogDnsEntry,
	} from '$lib/api/logs';

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
		field: string;
		type: string;
		description: string;
	}

	type LogType = 'all' | 'zeek.conn' | 'zeek.dns' | 'zeek.http' | 'zeek.tls' | 'zeek.files' | 'zeek.dhcp' | 'zeek.smtp' | 'suricata';
	type TimeRange = '15m' | '1h' | '4h' | '24h' | '7d' | '30d';

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

	const LOG_TYPE_LABELS: Record<LogType, string> = {
		all: 'All Logs',
		'zeek.conn': 'Connections',
		'zeek.dns': 'DNS',
		'zeek.http': 'HTTP',
		'zeek.tls': 'TLS',
		'zeek.files': 'Files',
		'zeek.dhcp': 'DHCP',
		'zeek.smtp': 'SMTP',
		suricata: 'Suricata',
	};

	const TIME_RANGES: { value: TimeRange; label: string; ms: number }[] = [
		{ value: '15m', label: '15m', ms: 15 * 60_000 },
		{ value: '1h', label: '1h', ms: 60 * 60_000 },
		{ value: '4h', label: '4h', ms: 4 * 60 * 60_000 },
		{ value: '24h', label: '24h', ms: 24 * 60 * 60_000 },
		{ value: '7d', label: '7d', ms: 7 * 24 * 60 * 60_000 },
		{ value: '30d', label: '30d', ms: 30 * 24 * 60 * 60_000 },
	];

	const INTERVAL_MAP: Record<string, string> = {
		'15m': '1m',
		'1h': '5m',
		'4h': '15m',
		'24h': '1h',
		'7d': '6h',
		'30d': '1d',
	};

	const IP_FIELDS = new Set(['source.ip', 'destination.ip', 'zeek.dhcp.client_addr']);
	const MONO_FIELDS = new Set([
		'source.ip', 'destination.ip', 'source.port', 'destination.port',
		'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.http.status_code',
		'zeek.tls.version', 'source.bytes', 'destination.bytes', 'event.duration',
		'suricata.alert.severity', 'zeek.files.total_bytes',
	]);

	// Protocol types used for timeline stacking (order matters for visual stacking)
	const PROTOCOL_KEYS = ['conn', 'dns', 'http', 'ssl', 'files', 'dhcp', 'smtp', 'alert'] as const;

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
	let expandedRow = $state<string | null>(null);
	let fullDoc = $state<Record<string, unknown> | null>(null);
	let fullDocLoading = $state(false);
	let copySuccess = $state(false);
	let fieldDefs = $state<Record<string, string>>({});

	// Active filters from chart clicks
	let activeIpFilter = $state('');
	let activeDnsFilter = $state('');

	// Chart interaction
	let hoveredBarIndex = $state<number | null>(null);
	let chartWidth = $state(800);

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	let maxBucketTotal = $derived(
		Math.max(1, ...timeline.map((b) => {
			let sum = 0;
			for (const k of PROTOCOL_KEYS) sum += (b[k] || 0);
			return sum;
		}))
	);

	let maxTalkerCount = $derived(topTalkers.length > 0 ? topTalkers[0].count : 1);
	let maxProtocolCount = $derived(protocols.length > 0 ? Math.max(1, ...protocols.map((p) => p.count)) : 1);
	let maxDestCount = $derived(topDestinations.length > 0 ? topDestinations[0].count : 1);
	let maxDnsCount = $derived(topDns.length > 0 ? topDns[0].count : 1);

	let hasActiveFilters = $derived(activeIpFilter !== '' || activeDnsFilter !== '' || logType !== 'all');

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

	async function fetchDashboard() {
		loading = true;
		const { from, to } = getTimeRange();
		const interval = INTERVAL_MAP[selectedTimeRange] || '1h';

		const results = await Promise.allSettled([
			getLogStats({ from, to }),
			getLogTimeline({ from, to, interval }),
			getLogTopTalkers({ from, to, limit: 10 }),
			getLogProtocolBreakdown({ from, to }),
			getLogTopDestinations({ from, to, limit: 10 }),
			getLogTopDns({ from, to, limit: 10 }),
		]);

		if (results[0].status === 'fulfilled') {
			const s = results[0].value;
			totalEvents = s.total_events;
			uniqueSources = s.unique_sources;
			protocolCount = s.protocol_count;
			totalBytesVal = s.total_bytes;
		}
		if (results[1].status === 'fulfilled') timeline = results[1].value.buckets;
		if (results[2].status === 'fulfilled') topTalkers = results[2].value.talkers;
		if (results[3].status === 'fulfilled') protocols = results[3].value.protocols;
		if (results[4].status === 'fulfilled') topDestinations = results[4].value.destinations;
		if (results[5].status === 'fulfilled') topDns = results[5].value.queries;

		loading = false;
	}

	// ---------------------------------------------------------------------------
	// Data fetching — log table
	// ---------------------------------------------------------------------------

	async function fetchLogs(append = false) {
		if (append) {
			loadingMore = true;
		} else {
			tableLoading = true;
			searchAfter = undefined;
		}
		error = '';

		try {
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
			if (append) {
				results = [...results, ...data.hits];
			} else {
				results = data.hits;
			}
			totalHits = data.total;
			searchAfter = data.search_after;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to fetch logs';
			if (!append) results = [];
		} finally {
			tableLoading = false;
			loadingMore = false;
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
				map[f.field] = f.description;
			}
			fieldDefs = map;
		} catch {
			// Optional — tooltips just won't show
		}
	}

	// ---------------------------------------------------------------------------
	// Combined fetch
	// ---------------------------------------------------------------------------

	async function fetchAll() {
		await Promise.all([fetchDashboard(), fetchLogs()]);
	}

	// ---------------------------------------------------------------------------
	// Event handlers
	// ---------------------------------------------------------------------------

	function handleTimeRangeChange(value: TimeRange) {
		selectedTimeRange = value;
		if (initialized) fetchAll();
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

	function toggleSort(field: string) {
		if (sortField === field) {
			sortDir = sortDir === 'desc' ? 'asc' : 'desc';
		} else {
			sortField = field;
			sortDir = 'desc';
		}
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

	// Row expansion
	async function fetchFullDocument(hit: LogHit) {
		fullDocLoading = true;
		try {
			const params = new URLSearchParams();
			params.set('query', `_id:${hit._id}`);
			params.set('size', '1');
			params.set('from', timeRangeToISO(selectedTimeRange));
			params.set('to', new Date().toISOString());
			const res = await fetch(`/api/logs/search?${params.toString()}`);
			if (res.ok) {
				const data = await res.json();
				if (data.hits && data.hits.length > 0) {
					fullDoc = data.hits[0]._source;
				}
			}
		} catch {
			// Fall back to projected data
		} finally {
			fullDocLoading = false;
		}
	}

	function toggleRow(id: string) {
		if (expandedRow === id) {
			expandedRow = null;
			fullDoc = null;
		} else {
			expandedRow = id;
			const hit = results.find((h) => h._id === id);
			if (hit) fetchFullDocument(hit);
		}
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
			refreshInterval = setInterval(fetchAll, 30_000);
		} else if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	// ---------------------------------------------------------------------------
	// Init
	// ---------------------------------------------------------------------------

	onMount(() => {
		fetchAll().then(() => {
			initialized = true;
		});
		fetchFieldDefs();
		return () => {
			if (refreshInterval) clearInterval(refreshInterval);
		};
	});
</script>

<svelte:head>
	<title>Log Explorer | NetTap</title>
</svelte:head>

<div class="page-container">
	<!-- ================================================================== -->
	<!-- Header                                                             -->
	<!-- ================================================================== -->
	<header class="page-header">
		<div class="header-left">
			<h1>Network Activity</h1>
			<p class="subtitle">Real-time visibility into all network traffic and events</p>
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
			<button class="btn btn-secondary btn-sm" onclick={exportCSV} disabled={results.length === 0}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" y1="15" x2="12" y2="3" />
				</svg>
				CSV
			</button>
			<button class="btn btn-primary btn-sm" onclick={() => fetchAll()} disabled={loading}>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</header>

	<!-- ================================================================== -->
	<!-- Hero Stats                                                         -->
	<!-- ================================================================== -->
	<div class="stats-grid">
		<button
			class="stat-card clickable"
			onclick={() => document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' })}
		>
			<span class="stat-label">Total Events</span>
			<span class="stat-value">{formatCompactNumber(totalEvents)}</span>
			<span class="stat-hint">All log entries in range</span>
		</button>
		<button
			class="stat-card clickable"
			onclick={() => document.getElementById('top-talkers-section')?.scrollIntoView({ behavior: 'smooth' })}
		>
			<span class="stat-label">Active Sources</span>
			<span class="stat-value text-cyan">{formatCompactNumber(uniqueSources)}</span>
			<span class="stat-hint">Unique source IPs</span>
		</button>
		<button
			class="stat-card clickable"
			onclick={() => document.getElementById('protocol-section')?.scrollIntoView({ behavior: 'smooth' })}
		>
			<span class="stat-label">Protocols</span>
			<span class="stat-value text-green">{protocolCount}</span>
			<span class="stat-hint">Distinct log types</span>
		</button>
		<button
			class="stat-card clickable"
			onclick={() => document.getElementById('log-table')?.scrollIntoView({ behavior: 'smooth' })}
		>
			<span class="stat-label">Data Volume</span>
			<span class="stat-value text-purple">{formatBytes(totalBytesVal)}</span>
			<span class="stat-hint">Total bytes transferred</span>
		</button>
	</div>

	<!-- ================================================================== -->
	<!-- Activity Timeline                                                  -->
	<!-- ================================================================== -->
	<section class="card">
		<div class="card-header">
			<h2>Activity Timeline</h2>
			<div class="legend-row">
				{#each PROTOCOL_KEYS as pk}
					<button class="legend-item" onclick={() => drillByProtocol(pk)}>
						<span class="legend-dot" style="background: {protocolColor(pk)};"></span>
						{protocolLabel(pk)}
					</button>
				{/each}
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
							{formatCompactNumber(Math.round(maxBucketTotal * frac))}
						</text>
					{/each}

					<!-- Stacked bars -->
					{#each timeline as bucket, i}
						{@const barW = Math.max(2, (chartWidth - 60) / timeline.length - 2)}
						{@const x = 55 + i * ((chartWidth - 60) / timeline.length)}
						{@const isHovered = hoveredBarIndex === i}

						<!-- Compute stacked heights -->
						{@const heights = PROTOCOL_KEYS.map((k) => ((bucket[k] || 0) / maxBucketTotal) * 180)}
						{@const totalH = heights.reduce((a, b) => a + b, 0)}

						<g
							role="img"
							onmouseenter={() => (hoveredBarIndex = i)}
							onmouseleave={() => (hoveredBarIndex = null)}
							style="cursor: pointer;"
						>
							<!-- Background bar for hover -->
							<rect
								x={x} y={200 - totalH} width={barW} height={totalH}
								fill="transparent"
							/>
							<!-- Stacked segments (bottom to top) -->
							{#each PROTOCOL_KEYS as pk, j}
								{@const h = heights[j]}
								{@const yOffset = heights.slice(j + 1).reduce((a, b) => a + b, 0)}
								{#if h > 0}
									<rect
										role="button"
										tabindex="-1"
										x={x} y={200 - yOffset - h} width={barW} height={h}
										fill={protocolColor(pk)}
										opacity={isHovered ? 1 : 0.8}
										rx="1"
										onclick={() => drillByProtocol(pk)}
										onkeydown={(e) => { if (e.key === 'Enter') drillByProtocol(pk); }}
									/>
								{/if}
							{/each}
						</g>

						<!-- Hover tooltip -->
						{#if isHovered}
							<g transform="translate({Math.min(x, chartWidth - 160)}, 5)">
								<rect x="0" y="0" width="150" height={30 + PROTOCOL_KEYS.filter((k) => (bucket[k] || 0) > 0).length * 14}
									fill="var(--bg-elevated)" stroke="var(--border-default)" rx="4" opacity="0.95" />
								<text x="8" y="16" fill="var(--text-primary)" font-size="11" font-weight="600">
									{formatShortTimestamp(bucket.timestamp)}
								</text>
								{#each PROTOCOL_KEYS.filter((k) => (bucket[k] || 0) > 0) as pk, ti}
									<circle cx="12" cy={30 + ti * 14} r="3" fill={protocolColor(pk)} />
									<text x="20" y={34 + ti * 14} fill="var(--text-secondary)" font-size="10">
										{protocolLabel(pk)}: {(bucket[pk] || 0).toLocaleString()}
									</text>
								{/each}
							</g>
						{/if}
					{/each}
				</svg>
			{:else if loading}
				<div class="chart-placeholder">
					<div class="loading-spinner"></div>
				</div>
			{:else}
				<div class="chart-placeholder">
					<p class="text-muted">No timeline data available</p>
				</div>
			{/if}
		</div>
	</section>

	<!-- ================================================================== -->
	<!-- Protocol Breakdown + Top Talkers (two columns)                     -->
	<!-- ================================================================== -->
	<div class="two-col" id="protocol-section">
		<!-- Protocol Breakdown -->
		<section class="card">
			<div class="card-header">
				<h2>Protocol Breakdown</h2>
			</div>
			{#if protocols.length > 0}
				<div class="bar-list">
					{#each protocols as proto}
						<button class="bar-row" onclick={() => drillByProtocol(proto.protocol)}>
							<div class="bar-label">
								<span class="bar-dot" style="background: {protocolColor(proto.protocol)};"></span>
								<span class="bar-name">{proto.label || protocolLabel(proto.protocol)}</span>
							</div>
							<div class="bar-track">
								<div
									class="bar-fill"
									style="width: {(proto.count / maxProtocolCount) * 100}%; background: {protocolColor(proto.protocol)};"
								></div>
							</div>
							<span class="bar-count mono">{formatCompactNumber(proto.count)}</span>
						</button>
					{/each}
				</div>
			{:else}
				<p class="text-muted empty-section">No protocol data</p>
			{/if}
		</section>

		<!-- Top Talkers -->
		<section class="card" id="top-talkers-section">
			<div class="card-header">
				<h2>Top Source IPs</h2>
				<span class="card-badge">Most Active Devices</span>
			</div>
			{#if topTalkers.length > 0}
				<div class="bar-list">
					{#each topTalkers as talker, idx}
						<button class="bar-row" class:active-filter={activeIpFilter === talker.ip} onclick={() => drillByIp(talker.ip)}>
							<div class="bar-label">
								<span class="bar-rank">{idx + 1}</span>
								<span class="bar-name mono"><IPAddress ip={talker.ip} /></span>
							</div>
							<div class="bar-track">
								<div
									class="bar-fill"
									style="width: {(talker.count / maxTalkerCount) * 100}%; background: var(--cyan);"
								></div>
							</div>
							<span class="bar-count mono">{formatCompactNumber(talker.count)}</span>
						</button>
					{/each}
				</div>
			{:else}
				<p class="text-muted empty-section">No source IP data</p>
			{/if}
		</section>
	</div>

	<!-- ================================================================== -->
	<!-- Top Destinations + Top DNS Queries (two columns)                   -->
	<!-- ================================================================== -->
	<div class="two-col">
		<!-- Top Destinations -->
		<section class="card">
			<div class="card-header">
				<h2>Most Contacted Servers</h2>
				<span class="card-badge">Destination IPs</span>
			</div>
			{#if topDestinations.length > 0}
				<div class="bar-list">
					{#each topDestinations as dest, idx}
						<button class="bar-row" class:active-filter={activeIpFilter === dest.ip} onclick={() => drillByIp(dest.ip)}>
							<div class="bar-label">
								<span class="bar-rank">{idx + 1}</span>
								<span class="bar-name mono"><IPAddress ip={dest.ip} /></span>
							</div>
							<div class="bar-track">
								<div
									class="bar-fill"
									style="width: {(dest.count / maxDestCount) * 100}%; background: var(--orange);"
								></div>
							</div>
							<span class="bar-count mono">{formatCompactNumber(dest.count)}</span>
						</button>
					{/each}
				</div>
			{:else}
				<p class="text-muted empty-section">No destination data</p>
			{/if}
		</section>

		<!-- Top DNS Queries -->
		<section class="card">
			<div class="card-header">
				<h2>Top DNS Queries</h2>
				<span class="card-badge">Most Looked Up Domains</span>
			</div>
			{#if topDns.length > 0}
				<div class="bar-list">
					{#each topDns as dnsEntry, idx}
						<button class="bar-row" class:active-filter={activeDnsFilter === dnsEntry.domain} onclick={() => drillByDns(dnsEntry.domain)}>
							<div class="bar-label">
								<span class="bar-rank">{idx + 1}</span>
								<span class="bar-name mono">{dnsEntry.domain}</span>
							</div>
							<div class="bar-track">
								<div
									class="bar-fill"
									style="width: {(dnsEntry.count / maxDnsCount) * 100}%; background: var(--green);"
								></div>
							</div>
							<span class="bar-count mono">{formatCompactNumber(dnsEntry.count)}</span>
						</button>
					{/each}
				</div>
			{:else}
				<p class="text-muted empty-section">No DNS data</p>
			{/if}
		</section>
	</div>

	<!-- ================================================================== -->
	<!-- Log Table Section                                                  -->
	<!-- ================================================================== -->
	<section id="log-table">
		<!-- Log type tabs -->
		<div class="tabs">
			{#each Object.entries(LOG_TYPE_LABELS) as [value, label]}
				<button
					class="tab"
					class:active={logType === value}
					onclick={() => setLogType(value as LogType)}
				>
					{label}
				</button>
			{/each}
		</div>

		<!-- Search + active filters -->
		<div class="search-bar">
			<div class="search-input-wrap">
				<svg class="search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<circle cx="11" cy="11" r="8" />
					<line x1="21" y1="21" x2="16.65" y2="16.65" />
				</svg>
				<input
					class="input search-input"
					type="text"
					placeholder="Search logs... (e.g. google.com, 192.168.1.1, dns)"
					bind:value={query}
					onkeydown={handleSearch}
				/>
			</div>
			<button class="btn btn-primary btn-sm" onclick={() => fetchLogs()} disabled={tableLoading}>
				Search
			</button>
		</div>

		<!-- Active filter badges -->
		{#if hasActiveFilters}
			<div class="active-filters">
				<span class="filter-label">Active filters:</span>
				{#if logType !== 'all'}
					<button class="filter-badge" onclick={() => { logType = 'all'; fetchLogs(); fetchFieldDefs(); }}>
						Type: {LOG_TYPE_LABELS[logType]}
						<span class="filter-x">&times;</span>
					</button>
				{/if}
				{#if activeIpFilter}
					<button class="filter-badge" onclick={() => { activeIpFilter = ''; fetchLogs(); }}>
						IP: {activeIpFilter}
						<span class="filter-x">&times;</span>
					</button>
				{/if}
				{#if activeDnsFilter}
					<button class="filter-badge" onclick={() => { activeDnsFilter = ''; fetchLogs(); fetchFieldDefs(); }}>
						DNS: {activeDnsFilter}
						<span class="filter-x">&times;</span>
					</button>
				{/if}
				<button class="filter-clear" onclick={clearAllFilters}>Clear all</button>
			</div>
		{/if}

		<!-- Error state -->
		{#if error}
			<div class="alert alert-danger">{error}</div>
		{/if}

		<!-- Results info -->
		{#if !tableLoading || results.length > 0}
			<div class="results-info">
				<span class="text-muted">
					Showing <strong>{results.length.toLocaleString()}</strong> of <strong>{totalHits.toLocaleString()}</strong> results
				</span>
				{#if tableLoading}
					<div class="loading-spinner" style="width: 14px; height: 14px;"></div>
				{/if}
			</div>
		{/if}

		<!-- Loading state (initial) -->
		{#if tableLoading && results.length === 0 && !error}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="text-muted">Searching logs...</p>
			</div>
		{:else if !tableLoading && results.length === 0 && !error}
			<div class="empty-state">
				<div class="empty-icon">
					<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
						<polyline points="14 2 14 8 20 8" />
						<line x1="16" y1="13" x2="8" y2="13" />
						<line x1="16" y1="17" x2="8" y2="17" />
						<polyline points="10 9 9 9 8 9" />
					</svg>
				</div>
				<p class="empty-text">No logs found</p>
				<p class="empty-hint">Try adjusting your time range or search query. Logs appear once Zeek/Suricata are processing traffic.</p>
			</div>
		{:else}
			<!-- Results table -->
			<div class="table-wrap">
				<table class="data-table">
					<thead>
						<tr>
							<th style="width: 28px;"></th>
							{#each COLUMNS[logType] as col}
								<th
									class="sortable"
									class:sorted={sortField === col}
									onclick={() => toggleSort(col)}
									data-tooltip={fieldDefs[col] || ''}
									class:tooltip={!!fieldDefs[col]}
								>
									{shortFieldName(col)}
									{#if sortField === col}
										<span class="sort-arrow">{sortDir === 'desc' ? ' \u2193' : ' \u2191'}</span>
									{/if}
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each results as hit (hit._id)}
							<tr
								class="log-row"
								class:expanded={expandedRow === hit._id}
								onclick={() => toggleRow(hit._id)}
							>
								<td class="expand-cell">
									<span class="expand-icon" class:rotated={expandedRow === hit._id}>&#9654;</span>
								</td>
								{#each COLUMNS[logType] as col}
									{@const value = getNestedValue(hit._source, col)}
									<td class:mono={MONO_FIELDS.has(col) || IP_FIELDS.has(col)}>
										{#if IP_FIELDS.has(col) && value != null && value !== ''}
											<IPAddress ip={String(value)} />
										{:else}
											{formatCellValue(col, value)}
										{/if}
									</td>
								{/each}
							</tr>
							{#if expandedRow === hit._id}
								<tr class="expanded-row">
									<td colspan={COLUMNS[logType].length + 1}>
										<div class="expanded-content">
											<div class="expanded-fields">
												<h4>Fields</h4>
												{#if fullDocLoading}
													<div class="loading-spinner" style="width: 14px; height: 14px;"></div>
												{/if}
												<div class="field-grid">
													{#each Object.entries(flattenObject(fullDoc || hit._source)) as [key, val]}
														<div class="field-key mono">{key}</div>
														<div class="field-val mono">{String(val ?? '--')}</div>
													{/each}
												</div>
											</div>
											<div class="expanded-raw">
												<div class="raw-header">
													<h4>Raw JSON</h4>
													<button class="btn btn-secondary btn-xs copy-btn" onclick={(e: MouseEvent) => {
														e.stopPropagation();
														navigator.clipboard.writeText(JSON.stringify(fullDoc || hit._source, null, 2));
														copySuccess = true;
														setTimeout(() => { copySuccess = false; }, 2000);
													}}>
														{copySuccess ? 'Copied!' : 'Copy'}
													</button>
												</div>
												<pre>{JSON.stringify(fullDoc || hit._source, null, 2)}</pre>
											</div>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>

			<!-- Load more -->
			{#if searchAfter && results.length < totalHits}
				<div class="load-more">
					<button
						class="btn btn-secondary"
						onclick={() => fetchLogs(true)}
						disabled={loadingMore}
					>
						{#if loadingMore}
							<div class="loading-spinner" style="width: 14px; height: 14px;"></div>
							Loading...
						{:else}
							Load More
						{/if}
					</button>
				</div>
			{/if}
		{/if}
	</section>
</div>

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
	.page-container {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	/* Header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	.subtitle {
		color: var(--text-secondary);
		font-size: var(--text-sm);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.auto-refresh-active {
		background: var(--accent-muted) !important;
		border-color: var(--accent) !important;
		color: var(--accent) !important;
	}

	/* Stats grid */
	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--space-md);
	}

	.stat-card.clickable {
		text-align: left;
		width: 100%;
	}

	.stat-hint {
		display: block;
		font-size: var(--text-xs);
		color: var(--text-dim);
		margin-top: 2px;
	}

	.text-cyan { color: var(--cyan); }
	.text-green { color: var(--green); }
	.text-purple { color: var(--purple); }

	/* Card */
	.card {
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-lg);
	}

	.card-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-md);
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	.card-header h2 {
		font-size: var(--text-lg);
		font-weight: 600;
	}

	.card-badge {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	/* Legend */
	.legend-row {
		display: flex;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.legend-item {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		color: var(--text-secondary);
		background: none;
		border: none;
		cursor: pointer;
		padding: 2px 4px;
		border-radius: var(--radius-sm);
		transition: background var(--transition-fast);
	}

	.legend-item:hover {
		background: var(--bg-tertiary);
		color: var(--text-primary);
	}

	.legend-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		display: inline-block;
	}

	/* Chart */
	.chart-wrapper {
		width: 100%;
		overflow: hidden;
	}

	.chart-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 220px;
	}

	/* Two-column layout */
	.two-col {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
	}

	/* Bar list (used in protocol breakdown, top talkers, destinations, dns) */
	.bar-list {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.bar-row {
		display: grid;
		grid-template-columns: minmax(120px, 1.2fr) 1fr auto;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
		background: none;
		border: 1px solid transparent;
		cursor: pointer;
		transition: all var(--transition-fast);
		text-align: left;
		width: 100%;
	}

	.bar-row:hover {
		background: var(--bg-tertiary);
		border-color: var(--border-dim);
	}

	.bar-row.active-filter {
		background: var(--accent-muted);
		border-color: var(--accent);
	}

	.bar-label {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		min-width: 0;
		overflow: hidden;
	}

	.bar-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.bar-rank {
		font-size: var(--text-xs);
		color: var(--text-dim);
		font-weight: 500;
		min-width: 16px;
		text-align: right;
		flex-shrink: 0;
	}

	.bar-name {
		font-size: var(--text-sm);
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.bar-track {
		height: 6px;
		background: var(--bg-tertiary);
		border-radius: 3px;
		overflow: hidden;
		min-width: 60px;
	}

	.bar-fill {
		height: 100%;
		border-radius: 3px;
		transition: width var(--transition-normal);
		min-width: 2px;
	}

	.bar-count {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		text-align: right;
		min-width: 40px;
	}

	.empty-section {
		padding: var(--space-xl);
		text-align: center;
		font-size: var(--text-sm);
	}

	/* Search bar */
	.search-bar {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.search-input-wrap {
		position: relative;
		flex: 1;
		min-width: 240px;
	}

	.search-icon {
		position: absolute;
		left: 12px;
		top: 50%;
		transform: translateY(-50%);
		color: var(--text-dim);
		pointer-events: none;
	}

	.search-input {
		padding-left: 36px;
	}

	/* Active filters */
	.active-filters {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
		margin-bottom: var(--space-md);
	}

	.filter-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.filter-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 10px;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--accent);
		background: var(--accent-muted);
		border: 1px solid rgba(0, 212, 255, 0.3);
		border-radius: var(--radius-full);
		cursor: pointer;
		transition: all var(--transition-fast);
		font-family: var(--font-mono);
	}

	.filter-badge:hover {
		background: rgba(0, 212, 255, 0.2);
	}

	.filter-x {
		font-size: 14px;
		line-height: 1;
		margin-left: 2px;
		opacity: 0.7;
	}

	.filter-clear {
		font-size: var(--text-xs);
		color: var(--text-muted);
		background: none;
		border: none;
		cursor: pointer;
		text-decoration: underline;
		padding: 2px 4px;
	}

	.filter-clear:hover {
		color: var(--text-primary);
	}

	/* Results info */
	.results-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: var(--text-sm);
		margin-bottom: var(--space-sm);
	}

	.results-info strong {
		color: var(--text-primary);
	}

	/* Table wrapper */
	.table-wrap {
		overflow-x: auto;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.data-table th.sorted {
		color: var(--accent);
	}

	.sort-arrow {
		color: var(--accent);
	}

	/* Expand/collapse */
	.expand-cell {
		width: 28px;
		text-align: center;
		cursor: pointer;
		color: var(--text-muted);
	}

	.expand-icon {
		display: inline-block;
		font-size: 10px;
		transition: transform var(--transition-fast);
	}

	.expand-icon.rotated {
		transform: rotate(90deg);
	}

	.log-row {
		cursor: pointer;
	}

	.log-row.expanded td {
		background-color: var(--bg-tertiary);
		border-bottom-color: var(--border-bright);
	}

	/* Expanded row */
	.expanded-row td {
		padding: 0 !important;
		background-color: var(--bg-primary);
	}

	.expanded-content {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-md);
		padding: var(--space-md);
		max-height: 400px;
		overflow-y: auto;
	}

	.expanded-content h4 {
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-bottom: var(--space-sm);
	}

	.field-grid {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px var(--space-md);
		font-size: var(--text-xs);
	}

	.field-key {
		color: var(--cyan);
		white-space: nowrap;
	}

	.field-val {
		color: var(--text-secondary);
		word-break: break-all;
	}

	.raw-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-sm);
	}

	.raw-header h4 {
		margin-bottom: 0;
	}

	.copy-btn {
		font-size: var(--text-xs);
		padding: 2px 8px;
	}

	.expanded-raw pre {
		font-size: var(--text-xs);
		max-height: 340px;
		overflow: auto;
		margin: 0;
	}

	/* Loading state */
	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
	}

	/* Load more */
	.load-more {
		display: flex;
		justify-content: center;
		padding: var(--space-md) 0;
	}

	@media (max-width: 1024px) {
		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.two-col {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 768px) {
		.stats-grid {
			grid-template-columns: 1fr;
		}

		.search-bar {
			flex-direction: column;
			align-items: stretch;
		}

		.expanded-content {
			grid-template-columns: 1fr;
		}

		.page-header {
			flex-direction: column;
		}

		.legend-row {
			display: none;
		}
	}
</style>
