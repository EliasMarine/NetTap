<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getPcapFiles,
		searchPcaps,
		previewPcap,
		getDownloadUrl,
		getFileDownloadUrl,
		formatBytes,
		QUICK_FILTERS,
	} from '$lib/api/pcap';
	import type {
		PcapFile,
		PcapSearchResult,
		PcapPacket,
	} from '$lib/api/pcap';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	interface TimeRange {
		label: string;
		value: string;
		ms: number;
	}

	const TIME_RANGES: TimeRange[] = [
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
		{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000 },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let bpfFilter = $state('');
	let selectedTimeRange = $state('24h');
	let loading = $state(false);
	let error = $state('');

	// File listing
	let files = $state<PcapFile[]>([]);
	let filesLoading = $state(true);

	// Search results
	let searchResults = $state<PcapSearchResult[]>([]);
	let searchDone = $state(false);

	// Preview
	let previewPackets = $state<PcapPacket[]>([]);
	let previewFile = $state('');
	let previewLoading = $state(false);

	// Sorting — Available Files table
	type FileSortKey = 'name' | 'size_bytes' | 'modified';
	let fileSortColumn = $state<FileSortKey>('modified');
	let fileSortDirection = $state<'asc' | 'desc'>('desc');

	// Sorting — Search Results table
	type ResultSortKey = 'name' | 'matching_packets' | 'size_bytes' | 'modified';
	let resultSortColumn = $state<ResultSortKey>('matching_packets');
	let resultSortDirection = $state<'asc' | 'desc'>('desc');

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = new Date();
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange);
		const ms = range?.ms ?? 24 * 60 * 60 * 1000;
		const from = new Date(now.getTime() - ms);
		return {
			from: from.toISOString(),
			to: now.toISOString(),
		};
	}

	// ---------------------------------------------------------------------------
	// Sorting
	// ---------------------------------------------------------------------------

	function sortFiles(column: FileSortKey) {
		if (fileSortColumn === column) {
			fileSortDirection = fileSortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			fileSortColumn = column;
			fileSortDirection = column === 'modified' || column === 'size_bytes' ? 'desc' : 'asc';
		}
	}

	function sortResults(column: ResultSortKey) {
		if (resultSortColumn === column) {
			resultSortDirection = resultSortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			resultSortColumn = column;
			resultSortDirection = column === 'modified' || column === 'size_bytes' || column === 'matching_packets' ? 'desc' : 'asc';
		}
	}

	function sortIndicator(active: boolean, direction: 'asc' | 'desc'): string {
		if (!active) return '';
		return direction === 'asc' ? ' \u2191' : ' \u2193';
	}

	function compareValues(a: unknown, b: unknown): number {
		if (typeof a === 'number' && typeof b === 'number') return a - b;
		return String(a).localeCompare(String(b));
	}

	let sortedFiles = $derived(
		[...files].sort((a, b) => {
			const cmp = compareValues(a[fileSortColumn], b[fileSortColumn]);
			return fileSortDirection === 'asc' ? cmp : -cmp;
		})
	);

	let sortedResults = $derived(
		[...searchResults].sort((a, b) => {
			const cmp = compareValues(a[resultSortColumn], b[resultSortColumn]);
			return resultSortDirection === 'asc' ? cmp : -cmp;
		})
	);

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	async function loadFiles() {
		filesLoading = true;
		try {
			const { from, to } = getTimeRange();
			const response = await getPcapFiles({ from, to });
			files = response.files;
		} catch {
			files = [];
		} finally {
			filesLoading = false;
		}
	}

	async function runSearch() {
		if (!bpfFilter.trim()) {
			error = 'Enter a display filter to search';
			return;
		}

		loading = true;
		error = '';
		searchDone = false;
		searchResults = [];
		previewPackets = [];
		previewFile = '';

		try {
			const { from, to } = getTimeRange();
			const response = await searchPcaps(bpfFilter, { from, to });
			searchResults = response.results;
			searchDone = true;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Search failed';
		} finally {
			loading = false;
		}
	}

	async function showPreview(file: string) {
		previewLoading = true;
		previewFile = file;
		previewPackets = [];
		error = '';

		try {
			const response = await previewPcap(file, {
				filter: bpfFilter || undefined,
				limit: 100,
			});
			previewPackets = response.packets;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Preview failed';
		} finally {
			previewLoading = false;
			// Scroll to the preview section so user can see it
			setTimeout(() => {
				const el = document.querySelector('.preview-section');
				if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
			}, 50);
		}
	}

	function downloadFile(file: string) {
		const url = getFileDownloadUrl(file);
		window.open(url, '_blank');
	}

	function applyQuickFilter(filter: string) {
		bpfFilter = filter;
	}

	function downloadFiltered() {
		if (!bpfFilter.trim()) return;
		const { from, to } = getTimeRange();
		const url = getDownloadUrl(bpfFilter, { from, to });
		window.open(url, '_blank');
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		loadFiles();
	});
</script>

<svelte:head>
	<title>PCAP Search - NetTap</title>
</svelte:head>

<div class="page-container">
	<header class="page-header">
		<h1>PCAP Search</h1>
		<p class="subtitle">Search and analyze captured network traffic</p>
	</header>

	<!-- Filter Bar -->
	<div class="filter-bar">
		<div class="filter-input-row">
			<input
				type="text"
				class="bpf-input"
				placeholder="Wireshark display filter (e.g., tcp.port == 80, ip.addr == 192.168.1.1, dns)"
				bind:value={bpfFilter}
				onkeydown={(e) => e.key === 'Enter' && runSearch()}
			/>
			<button class="btn btn-primary" onclick={runSearch} disabled={loading}>
				{loading ? 'Searching...' : 'Search'}
			</button>
			<button
				class="btn btn-secondary"
				onclick={downloadFiltered}
				disabled={!bpfFilter.trim()}
			>
				Download
			</button>
		</div>

		<div class="filter-options">
			<div class="quick-filters">
				{#each QUICK_FILTERS as qf}
					<button
						class="btn btn-chip"
						class:active={bpfFilter === qf.filter}
						onclick={() => applyQuickFilter(qf.filter)}
					>
						{qf.label}
					</button>
				{/each}
			</div>

			<div class="time-range-selector">
				{#each TIME_RANGES as range}
					<button
						class="btn btn-chip"
						class:active={selectedTimeRange === range.value}
						onclick={() => {
							selectedTimeRange = range.value;
							loadFiles();
						}}
					>
						{range.label}
					</button>
				{/each}
			</div>
		</div>

		<div class="syntax-hints">
			<span class="hint">Display filter syntax:</span>
			<code>ip.addr == 1.2.3.4</code>
			<code>tcp.port == 443</code>
			<code>ip.src == 10.0.0.1 && tcp.dstport == 80</code>
			<code>http.request</code>
			<code>dns</code>
		</div>
	</div>

	{#if error}
		<div class="error-banner">{error}</div>
	{/if}

	<!-- Search Results -->
	{#if searchDone}
		<section class="results-section">
			<h2>Search Results ({searchResults.length} files match)</h2>
			{#if searchResults.length === 0}
				<p class="empty-state">No matching packets found in any PCAP file.</p>
			{:else}
				<div class="table-container">
					<table class="data-table">
						<thead>
							<tr>
								<th>
									<button class="sort-btn" class:active-sort={resultSortColumn === 'name'} onclick={() => sortResults('name')}>
										File{sortIndicator(resultSortColumn === 'name', resultSortDirection)}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={resultSortColumn === 'matching_packets'} onclick={() => sortResults('matching_packets')}>
										Matching Packets{sortIndicator(resultSortColumn === 'matching_packets', resultSortDirection)}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={resultSortColumn === 'size_bytes'} onclick={() => sortResults('size_bytes')}>
										Size{sortIndicator(resultSortColumn === 'size_bytes', resultSortDirection)}
									</button>
								</th>
								<th>
									<button class="sort-btn" class:active-sort={resultSortColumn === 'modified'} onclick={() => sortResults('modified')}>
										Modified{sortIndicator(resultSortColumn === 'modified', resultSortDirection)}
									</button>
								</th>
								<th>Actions</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedResults as result}
								<tr>
									<td class="mono">{result.name}</td>
									<td>{result.matching_packets}</td>
									<td>{formatBytes(result.size_bytes)}</td>
									<td>{new Date(result.modified).toLocaleString()}</td>
									<td class="actions-cell">
										<button
											class="btn btn-sm"
											onclick={() => showPreview(result.file)}
										>
											Preview
										</button>
										<button
											class="btn btn-sm"
											onclick={() => downloadFile(result.file)}
										>
											Download
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{/if}

	<!-- Packet Preview -->
	{#if previewFile}
		<section class="preview-section">
			<h2>
				Packet Preview
				{#if previewLoading}
					<span class="loading-indicator">Loading...</span>
				{/if}
			</h2>
			{#if previewPackets.length > 0}
				<div class="table-container">
					<table class="data-table packet-table">
						<thead>
							<tr>
								<th>#</th>
								<th>Time</th>
								<th>Source</th>
								<th>Destination</th>
								<th>Protocol</th>
								<th>Length</th>
								<th>Info</th>
							</tr>
						</thead>
						<tbody>
							{#each previewPackets as pkt}
								<tr>
									<td class="mono">{pkt.frame_number}</td>
									<td class="mono nowrap">{pkt.timestamp}</td>
									<td class="mono">{pkt.source}</td>
									<td class="mono">{pkt.destination}</td>
									<td>{pkt.protocol}</td>
									<td>{pkt.length}</td>
									<td class="info-cell">{pkt.info}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else if !previewLoading}
				<p class="empty-state">No packets to display.</p>
			{/if}
		</section>
	{/if}

	<!-- Available Files -->
	<section class="files-section">
		<h2>
			Available PCAP Files
			{#if filesLoading}
				<span class="loading-indicator">Loading...</span>
			{/if}
		</h2>
		{#if files.length === 0 && !filesLoading}
			<p class="empty-state">No PCAP files found in the selected time range.</p>
		{:else}
			<div class="table-container">
				<table class="data-table">
					<thead>
						<tr>
							<th>
								<button class="sort-btn" class:active-sort={fileSortColumn === 'name'} onclick={() => sortFiles('name')}>
									File{sortIndicator(fileSortColumn === 'name', fileSortDirection)}
								</button>
							</th>
							<th>
								<button class="sort-btn" class:active-sort={fileSortColumn === 'size_bytes'} onclick={() => sortFiles('size_bytes')}>
									Size{sortIndicator(fileSortColumn === 'size_bytes', fileSortDirection)}
								</button>
							</th>
							<th>
								<button class="sort-btn" class:active-sort={fileSortColumn === 'modified'} onclick={() => sortFiles('modified')}>
									Modified{sortIndicator(fileSortColumn === 'modified', fileSortDirection)}
								</button>
							</th>
							<th>Path</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedFiles as file}
							<tr>
								<td class="mono">{file.name}</td>
								<td>{formatBytes(file.size_bytes)}</td>
								<td>{new Date(file.modified).toLocaleString()}</td>
								<td class="mono path-cell">{file.relative_path}</td>
								<td class="actions-cell">
									<button
										class="btn btn-sm"
										onclick={() => showPreview(file.file)}
									>
										Preview
									</button>
									<button
										class="btn btn-sm"
										onclick={() => downloadFile(file.file)}
									>
										Download
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>

<style>
	.page-container {
		max-width: 1400px;
		margin: 0 auto;
		padding: 1.5rem;
	}

	.page-header {
		margin-bottom: 1.5rem;
	}

	.page-header h1 {
		font-size: 1.75rem;
		font-weight: 700;
		color: var(--text-primary, #e4e4e7);
		margin: 0;
	}

	.subtitle {
		color: var(--text-secondary, #a1a1aa);
		margin: 0.25rem 0 0;
		font-size: 0.9rem;
	}

	.filter-bar {
		background: var(--surface-card, #1a1a2e);
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.75rem;
		padding: 1.25rem;
		margin-bottom: 1.5rem;
	}

	.filter-input-row {
		display: flex;
		gap: 0.75rem;
		margin-bottom: 0.75rem;
	}

	.bpf-input {
		flex: 1;
		padding: 0.625rem 1rem;
		background: var(--surface-input, #0f0f1a);
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.5rem;
		color: var(--text-primary, #e4e4e7);
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.875rem;
	}

	.bpf-input::placeholder {
		color: var(--text-muted, #52525b);
	}

	.filter-options {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	.quick-filters,
	.time-range-selector {
		display: flex;
		gap: 0.375rem;
		flex-wrap: wrap;
	}

	.syntax-hints {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
		font-size: 0.75rem;
		color: var(--text-muted, #52525b);
	}

	.syntax-hints code {
		background: var(--surface-input, #0f0f1a);
		padding: 0.15rem 0.4rem;
		border-radius: 0.25rem;
		font-size: 0.75rem;
	}

	.hint {
		font-weight: 600;
	}

	.btn {
		padding: 0.5rem 1rem;
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.5rem;
		cursor: pointer;
		font-size: 0.875rem;
		transition: all 0.15s;
		background: var(--surface-card, #1a1a2e);
		color: var(--text-primary, #e4e4e7);
	}

	.btn:hover {
		border-color: var(--accent-blue, #3b82f6);
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-primary {
		background: var(--accent-blue, #3b82f6);
		border-color: var(--accent-blue, #3b82f6);
		color: #fff;
	}

	.btn-primary:hover:not(:disabled) {
		background: #2563eb;
	}

	.btn-secondary {
		background: var(--surface-elevated, #252540);
	}

	.btn-chip {
		padding: 0.25rem 0.625rem;
		font-size: 0.75rem;
		border-radius: 1rem;
	}

	.btn-chip.active {
		background: var(--accent-blue, #3b82f6);
		border-color: var(--accent-blue, #3b82f6);
		color: #fff;
	}

	.btn-sm {
		padding: 0.25rem 0.5rem;
		font-size: 0.75rem;
	}

	.error-banner {
		background: rgba(239, 68, 68, 0.1);
		border: 1px solid rgba(239, 68, 68, 0.3);
		color: #ef4444;
		padding: 0.75rem 1rem;
		border-radius: 0.5rem;
		margin-bottom: 1rem;
		font-size: 0.875rem;
	}

	section {
		margin-bottom: 1.5rem;
	}

	h2 {
		font-size: 1.1rem;
		font-weight: 600;
		color: var(--text-primary, #e4e4e7);
		margin: 0 0 0.75rem;
	}

	.loading-indicator {
		font-size: 0.8rem;
		color: var(--text-muted, #52525b);
		font-weight: 400;
	}

	.table-container {
		overflow-x: auto;
		border: 1px solid var(--border-color, #2d2d44);
		border-radius: 0.5rem;
	}

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8125rem;
	}

	.data-table th {
		background: var(--surface-card, #1a1a2e);
		padding: 0.5rem 0.75rem;
		text-align: left;
		color: var(--text-secondary, #a1a1aa);
		font-weight: 600;
		border-bottom: 1px solid var(--border-color, #2d2d44);
		white-space: nowrap;
	}

	.data-table td {
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--border-subtle, #1f1f35);
		color: var(--text-primary, #e4e4e7);
	}

	.data-table tbody tr:hover {
		background: var(--surface-hover, #1f1f35);
	}

	.mono {
		font-family: 'JetBrains Mono', monospace;
		font-size: 0.75rem;
	}

	.nowrap {
		white-space: nowrap;
	}

	.info-cell {
		max-width: 400px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.path-cell {
		max-width: 300px;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sort-btn {
		background: none;
		border: none;
		color: var(--text-secondary, #a1a1aa);
		font-weight: 600;
		font-size: 0.8125rem;
		cursor: pointer;
		padding: 0;
		white-space: nowrap;
	}

	.sort-btn:hover {
		color: var(--text-primary, #e4e4e7);
	}

	.sort-btn.active-sort {
		color: var(--accent-blue, #3b82f6);
	}

	.actions-cell {
		display: flex;
		gap: 0.375rem;
		white-space: nowrap;
	}

	.empty-state {
		color: var(--text-muted, #52525b);
		font-size: 0.875rem;
		text-align: center;
		padding: 2rem;
	}
</style>
