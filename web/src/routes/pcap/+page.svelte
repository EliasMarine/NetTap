<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getPcapFiles,
		searchPcaps,
		previewPcap,
		getDownloadUrl,
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
			error = 'Enter a BPF filter to search';
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
		}
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
				placeholder="Enter BPF filter (e.g., tcp port 80, host 192.168.1.1, udp and port 53)"
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
			<span class="hint">Syntax:</span>
			<code>host 1.2.3.4</code>
			<code>tcp port 443</code>
			<code>net 192.168.1.0/24</code>
			<code>src host 10.0.0.1 and dst port 80</code>
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
								<th>File</th>
								<th>Matching Packets</th>
								<th>Size</th>
								<th>Modified</th>
								<th>Actions</th>
							</tr>
						</thead>
						<tbody>
							{#each searchResults as result}
								<tr>
									<td class="mono">{result.name}</td>
									<td>{result.matching_packets}</td>
									<td>{formatBytes(result.size_bytes)}</td>
									<td>{new Date(result.modified).toLocaleString()}</td>
									<td>
										<button
											class="btn btn-sm"
											onclick={() => showPreview(result.file)}
										>
											Preview
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
							<th>File</th>
							<th>Size</th>
							<th>Modified</th>
							<th>Path</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each files as file}
							<tr>
								<td class="mono">{file.name}</td>
								<td>{formatBytes(file.size_bytes)}</td>
								<td>{new Date(file.modified).toLocaleString()}</td>
								<td class="mono path-cell">{file.relative_path}</td>
								<td>
									<button
										class="btn btn-sm"
										onclick={() => showPreview(file.file)}
									>
										Preview
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

	.empty-state {
		color: var(--text-muted, #52525b);
		font-size: 0.875rem;
		text-align: center;
		padding: 2rem;
	}
</style>
