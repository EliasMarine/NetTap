<script lang="ts">
	import { onMount } from 'svelte';

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
	// Column definitions per log type
	// ---------------------------------------------------------------------------

	const COLUMNS: Record<LogType, string[]> = {
		all: ['@timestamp', 'source.ip', 'destination.ip', 'network.transport', 'event.dataset', 'event.provider'],
		'zeek.conn': ['@timestamp', 'source.ip', 'source.port', 'destination.ip', 'destination.port', 'network.transport', 'event.duration', 'source.bytes', 'destination.bytes', 'zeek.conn.state'],
		'zeek.dns': ['@timestamp', 'source.ip', 'zeek.dns.query', 'zeek.dns.qtype_name', 'zeek.dns.rcode_name', 'zeek.dns.answers'],
		'zeek.http': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.http.method', 'zeek.http.host', 'zeek.http.uri', 'zeek.http.status_code'],
		'zeek.tls': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.tls.server_name', 'zeek.tls.version', 'zeek.tls.cipher', 'zeek.tls.established'],
		'zeek.files': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.files.filename', 'zeek.files.mime_type', 'zeek.files.total_bytes'],
		'zeek.dhcp': ['@timestamp', 'source.ip', 'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.dhcp.hostname', 'zeek.dhcp.msg_types'],
		'zeek.smtp': ['@timestamp', 'source.ip', 'destination.ip', 'zeek.smtp.mailfrom', 'zeek.smtp.rcptto', 'zeek.smtp.subject'],
		suricata: ['@timestamp', 'source.ip', 'destination.ip', 'suricata.alert.signature', 'suricata.alert.severity', 'suricata.alert.category'],
	};

	const LOG_TYPE_LABELS: Record<LogType, string> = {
		all: 'All',
		'zeek.conn': 'Conn',
		'zeek.dns': 'DNS',
		'zeek.http': 'HTTP',
		'zeek.tls': 'TLS',
		'zeek.files': 'Files',
		'zeek.dhcp': 'DHCP',
		'zeek.smtp': 'SMTP',
		suricata: 'Suricata',
	};

	const TIME_RANGES: { value: TimeRange; label: string }[] = [
		{ value: '15m', label: '15m' },
		{ value: '1h', label: '1h' },
		{ value: '4h', label: '4h' },
		{ value: '24h', label: '24h' },
		{ value: '7d', label: '7d' },
		{ value: '30d', label: '30d' },
	];

	const IP_FIELDS = new Set(['source.ip', 'destination.ip', 'zeek.dhcp.client_addr']);
	const MONO_FIELDS = new Set([
		'source.ip', 'destination.ip', 'source.port', 'destination.port',
		'zeek.dhcp.client_addr', 'zeek.dhcp.mac', 'zeek.http.status_code',
		'zeek.tls.version', 'source.bytes', 'destination.bytes', 'event.duration',
		'suricata.alert.severity', 'zeek.files.total_bytes',
	]);

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let logType = $state<LogType>('all');
	let query = $state('');
	let timeRange = $state<TimeRange>('24h');
	let results = $state<LogHit[]>([]);
	let totalHits = $state(0);
	let loading = $state(false);
	let error = $state('');
	let searchAfter = $state<unknown[] | undefined>(undefined);
	let loadingMore = $state(false);
	let sortField = $state('@timestamp');
	let sortDir = $state<'desc' | 'asc'>('desc');
	let expandedRow = $state<string | null>(null);
	let fieldDefs = $state<Record<string, string>>({});

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function timeRangeToISO(range: TimeRange): string {
		const now = Date.now();
		const ms: Record<TimeRange, number> = {
			'15m': 15 * 60_000,
			'1h': 60 * 60_000,
			'4h': 4 * 60 * 60_000,
			'24h': 24 * 60 * 60_000,
			'7d': 7 * 24 * 60 * 60_000,
			'30d': 30 * 24 * 60 * 60_000,
		};
		return new Date(now - ms[range]).toISOString();
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

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	async function fetchLogs(append = false) {
		if (append) {
			loadingMore = true;
		} else {
			loading = true;
			searchAfter = undefined;
		}
		error = '';

		try {
			const params = new URLSearchParams();
			if (logType !== 'all') params.set('log_type', logType);
			if (query.trim()) params.set('query', query.trim());
			params.set('from', timeRangeToISO(timeRange));
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
			loading = false;
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
			// Field defs are optional — tooltips just won't show
		}
	}

	// ---------------------------------------------------------------------------
	// Search + filter handlers
	// ---------------------------------------------------------------------------

	function handleSearch(e: KeyboardEvent) {
		if (e.key === 'Enter') fetchLogs();
	}

	function setLogType(lt: LogType) {
		logType = lt;
	}

	function setTimeRange(tr: TimeRange) {
		timeRange = tr;
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

	function toggleRow(id: string) {
		expandedRow = expandedRow === id ? null : id;
	}

	// ---------------------------------------------------------------------------
	// CSV export
	// ---------------------------------------------------------------------------

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

	// ---------------------------------------------------------------------------
	// Reactive: refetch on logType or timeRange change
	// ---------------------------------------------------------------------------

	let prevLogType: LogType | null = null;
	let prevTimeRange: TimeRange | null = null;

	$effect(() => {
		const ltChanged = prevLogType !== null && prevLogType !== logType;
		const trChanged = prevTimeRange !== null && prevTimeRange !== timeRange;
		prevLogType = logType;
		prevTimeRange = timeRange;
		if (ltChanged || trChanged) {
			fetchLogs();
			if (ltChanged) fetchFieldDefs();
		}
	});

	// ---------------------------------------------------------------------------
	// Initial load
	// ---------------------------------------------------------------------------

	onMount(() => {
		fetchLogs();
		fetchFieldDefs();
	});
</script>

<svelte:head>
	<title>Log Explorer | NetTap</title>
</svelte:head>

<div class="logs-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<h2>Log Explorer</h2>
			<p class="text-muted">Browse raw Zeek and Suricata logs</p>
		</div>
		<div class="page-actions">
			<button class="btn btn-secondary btn-sm" onclick={exportCSV} disabled={results.length === 0}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" y1="15" x2="12" y2="3" />
				</svg>
				Export CSV
			</button>
			<button class="btn btn-primary btn-sm" onclick={() => fetchLogs()} disabled={loading}>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="23 4 23 10 17 10" />
					<polyline points="1 20 1 14 7 14" />
					<path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
				</svg>
				{loading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</div>

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

	<!-- Search + time range bar -->
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
		<div class="pills">
			{#each TIME_RANGES as tr}
				<button
					class="pill"
					class:active={timeRange === tr.value}
					onclick={() => setTimeRange(tr.value)}
				>
					{tr.label}
				</button>
			{/each}
		</div>
	</div>

	<!-- Error state -->
	{#if error}
		<div class="alert alert-danger">{error}</div>
	{/if}

	<!-- Loading state -->
	{#if loading && results.length === 0}
		<div class="loading-state">
			<div class="loading-spinner"></div>
			<p class="text-muted">Searching logs...</p>
		</div>
	{:else if !loading && results.length === 0 && !error}
		<!-- Empty state -->
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
		<!-- Results info bar -->
		<div class="results-info">
			<span class="text-muted">
				Showing <strong>{results.length.toLocaleString()}</strong> of <strong>{totalHits.toLocaleString()}</strong> results
			</span>
			{#if loading}
				<div class="loading-spinner" style="width: 14px; height: 14px;"></div>
			{/if}
		</div>

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
									{formatCellValue(col, value)}
								</td>
							{/each}
						</tr>
						{#if expandedRow === hit._id}
							<tr class="expanded-row">
								<td colspan={COLUMNS[logType].length + 1}>
									<div class="expanded-content">
										<div class="expanded-fields">
											<h4>Fields</h4>
											<div class="field-grid">
												{#each Object.entries(flattenObject(hit._source)) as [key, val]}
													<div class="field-key mono">{key}</div>
													<div class="field-val mono">{String(val ?? '--')}</div>
												{/each}
											</div>
										</div>
										<div class="expanded-raw">
											<h4>Raw JSON</h4>
											<pre>{JSON.stringify(hit._source, null, 2)}</pre>
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
	.logs-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	/* Header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
	}

	.header-left h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		margin-bottom: var(--space-xs);
	}

	/* Search bar */
	.search-bar {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex-wrap: wrap;
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

	/* Results info */
	.results-info {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		font-size: var(--text-sm);
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

	@media (max-width: 768px) {
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
	}
</style>
