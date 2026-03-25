<!--
  LiveConnectionTable.svelte — Sortable live connections table with clickable rows.
  Displays timestamp, source/dest IPs, protocol, port, bytes, duration.
  Rows with alerts are badged. Clicking a row calls onrowclick for drawer integration.
-->
<script lang="ts">
	import type { LiveConnection } from '$lib/api/live';
	import IPAddress from '$components/IPAddress.svelte';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		connections,
		selectedId = null,
		onrowclick,
	}: {
		connections: LiveConnection[];
		selectedId: string | null;
		onrowclick: (conn: LiveConnection) => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// Sort state
	// ---------------------------------------------------------------------------

	type SortField = 'timestamp' | 'source_ip' | 'direction' | 'dest_ip' | 'protocol' | 'dest_port' | 'bytes' | 'duration';

	let sortField = $state<SortField>('timestamp');
	let sortDir = $state<'asc' | 'desc'>('desc');

	function toggleSort(field: SortField) {
		if (sortField === field) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
		} else {
			sortField = field;
			sortDir = field === 'timestamp' ? 'desc' : 'asc';
		}
	}

	// ---------------------------------------------------------------------------
	// Format helpers
	// ---------------------------------------------------------------------------

	function formatTime(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleTimeString(undefined, {
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
			});
		} catch {
			return ts;
		}
	}

	function formatBytes(bytes: number): string {
		if (bytes >= 1_000_000_000) return (bytes / 1_000_000_000).toFixed(1) + ' GB';
		if (bytes >= 1_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB';
		if (bytes >= 1_000) return (bytes / 1_000).toFixed(1) + ' KB';
		return bytes + ' B';
	}

	function formatDuration(seconds: number): string {
		if (seconds < 0.001) return '<1ms';
		if (seconds < 1) return (seconds * 1000).toFixed(0) + 'ms';
		if (seconds < 60) return seconds.toFixed(1) + 's';
		if (seconds < 3600) {
			const m = Math.floor(seconds / 60);
			const s = Math.round(seconds % 60);
			return `${m}m ${s}s`;
		}
		const h = Math.floor(seconds / 3600);
		const m = Math.round((seconds % 3600) / 60);
		return `${h}h ${m}m`;
	}

	/** Country code to flag emoji (regional indicator symbols). */
	function countryFlag(code: string): string {
		if (!code || code.length !== 2) return '';
		const base = 0x1F1E6; // Regional Indicator Symbol Letter A
		const upper = code.toUpperCase();
		return String.fromCodePoint(
			upper.codePointAt(0)! - 65 + base,
			upper.codePointAt(1)! - 65 + base
		);
	}

	/**
	 * Heuristic for direction: if dest_port is a well-known service port (<1024)
	 * the connection is outbound (our device talking to a server). Otherwise,
	 * inbound (remote initiated or P2P).
	 */
	function getDirection(conn: LiveConnection): 'OUT' | 'IN' {
		return conn.dest_port < 1024 ? 'OUT' : 'IN';
	}

	/** Build a unique row ID for selection matching. */
	function rowId(conn: LiveConnection): string {
		return conn.timestamp + conn.source_ip + conn.dest_ip;
	}

	// ---------------------------------------------------------------------------
	// Sorted connections (derived)
	// ---------------------------------------------------------------------------

	let sorted = $derived.by(() => {
		const list = [...connections];
		const dir = sortDir === 'asc' ? 1 : -1;

		list.sort((a, b) => {
			let cmp = 0;
			switch (sortField) {
				case 'timestamp':
					cmp = a.timestamp.localeCompare(b.timestamp);
					break;
				case 'source_ip':
					cmp = a.source_ip.localeCompare(b.source_ip);
					break;
				case 'direction':
					cmp = getDirection(a).localeCompare(getDirection(b));
					break;
				case 'dest_ip':
					cmp = a.dest_ip.localeCompare(b.dest_ip);
					break;
				case 'protocol':
					cmp = (a.service || a.protocol).localeCompare(b.service || b.protocol);
					break;
				case 'dest_port':
					cmp = a.dest_port - b.dest_port;
					break;
				case 'bytes':
					cmp = a.bytes - b.bytes;
					break;
				case 'duration':
					cmp = a.duration - b.duration;
					break;
			}
			return cmp * dir;
		});

		return list;
	});

	// ---------------------------------------------------------------------------
	// Column definitions
	// ---------------------------------------------------------------------------

	const columns: { field: SortField; label: string }[] = [
		{ field: 'timestamp', label: 'Time' },
		{ field: 'source_ip', label: 'Source' },
		{ field: 'direction', label: 'Dir' },
		{ field: 'dest_ip', label: 'Destination' },
		{ field: 'protocol', label: 'Protocol' },
		{ field: 'dest_port', label: 'Port' },
		{ field: 'bytes', label: 'Bytes' },
		{ field: 'duration', label: 'Duration' },
	];
</script>

<div class="table-wrap">
	<table class="data-table">
		<thead>
			<tr>
				{#each columns as col}
					<th
						class="sortable"
						class:sorted={sortField === col.field}
						onclick={() => toggleSort(col.field)}
					>
						{col.label}
						{#if sortField === col.field}
							<span class="sort-arrow">{sortDir === 'asc' ? '\u25B2' : '\u25BC'}</span>
						{/if}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#if sorted.length === 0}
				<tr>
					<td colspan={columns.length} class="empty-row">No connections</td>
				</tr>
			{:else}
				{#each sorted as conn (rowId(conn))}
					{@const dir = getDirection(conn)}
					{@const isSelected = selectedId === rowId(conn)}
					<tr
						class="conn-row"
						class:selected={isSelected}
						class:has-alert={conn.has_alert}
						onclick={() => onrowclick(conn)}
					>
						<!-- Time -->
						<td class="mono">{formatTime(conn.timestamp)}</td>

						<!-- Source -->
						<td>
							<IPAddress ip={conn.source_ip} />
						</td>

						<!-- Direction -->
						<td>
							<span class="direction-badge" class:dir-out={dir === 'OUT'} class:dir-in={dir === 'IN'}>
								{dir}
							</span>
						</td>

						<!-- Destination -->
						<td>
							<span class="dest-cell">
								<IPAddress ip={conn.dest_ip} />
								{#if conn.country}
									<span class="country-flag" title={conn.country_name || conn.country}>{countryFlag(conn.country)}</span>
								{/if}
							</span>
						</td>

						<!-- Protocol -->
						<td>
							<span class="proto-label">{String(conn.service || conn.protocol || '').toUpperCase()}</span>
						</td>

						<!-- Port -->
						<td class="mono">{conn.dest_port}</td>

						<!-- Bytes -->
						<td class="mono">{formatBytes(conn.bytes)}</td>

						<!-- Duration -->
						<td class="mono">
							{formatDuration(conn.duration)}
							{#if conn.has_alert}
								<span class="alert-badge badge badge-danger">ALERT</span>
							{/if}
						</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
</div>

<style>
	.table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		background: var(--bg-secondary);
	}

	/* Override sticky header bg for this wrapper */
	.data-table th {
		background: var(--bg-secondary);
	}

	/* Sort arrow */
	.sort-arrow {
		font-size: var(--text-xs);
		margin-left: var(--space-xs);
		color: var(--accent);
	}

	th.sorted {
		color: var(--text-primary);
	}

	/* Row states */
	.conn-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.conn-row:hover td {
		background-color: var(--bg-tertiary);
	}

	.conn-row.selected td {
		background-color: var(--accent-muted);
	}

	.conn-row.has-alert td {
		border-left: 2px solid transparent;
	}

	.conn-row.has-alert td:first-child {
		border-left: 2px solid var(--red);
	}

	/* Direction badge */
	.direction-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 1px 6px;
		font-size: var(--text-xs);
		font-weight: 700;
		font-family: var(--font-mono);
		border-radius: var(--radius-sm);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		min-width: 36px;
	}

	.dir-out {
		background-color: var(--cyan-dim);
		color: var(--cyan);
	}

	.dir-in {
		background-color: var(--green-dim);
		color: var(--green);
	}

	/* Destination cell with flag */
	.dest-cell {
		display: inline-flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.country-flag {
		font-size: var(--text-sm);
		line-height: 1;
		cursor: help;
	}

	/* Protocol label */
	.proto-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
	}

	/* Alert badge inline */
	.alert-badge {
		margin-left: var(--space-sm);
		font-size: 9px;
		padding: 1px 5px;
		vertical-align: middle;
	}

	/* Empty state */
	.empty-row {
		text-align: center;
		color: var(--text-muted);
		padding: var(--space-2xl) var(--space-md) !important;
		font-size: var(--text-sm);
	}
</style>
