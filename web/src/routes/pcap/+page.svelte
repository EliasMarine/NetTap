<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getPcapFiles,
		searchPcaps,
		previewPcap,
		getDownloadUrl,
		getFileDownloadUrl,
		formatBytes,
		formatRelativeTime,
		QUICK_FILTERS,
		PROTO_FILTER_MAP,
	} from '$lib/api/pcap';
	import type {
		PcapFile,
		PcapSearchResult,
		PcapPacket,
	} from '$lib/api/pcap';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const TIME_RANGES = [
		{ label: '1h', value: '1h', ms: 60 * 60 * 1000 },
		{ label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000 },
		{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000 },
		{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000 },
		{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000 },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let selectedTimeRange = $state('24h');
	let initialized = $state(false);

	// Filter
	let bpfFilter = $state('');
	let loading = $state(false);
	let error = $state('');

	// Files
	let files = $state<PcapFile[]>([]);
	let filesLoading = $state(true);

	// Search
	let searchResults = $state<PcapSearchResult[]>([]);
	let searchDone = $state(false);

	// Preview
	let previewPackets = $state<PcapPacket[]>([]);
	let previewFile = $state('');
	let previewLoading = $state(false);

	// Sorting — Files
	type FileSortKey = 'name' | 'size_bytes' | 'modified';
	let fileSortKey = $state<FileSortKey>('modified');
	let fileSortDir = $state<'asc' | 'desc'>('desc');

	// Sorting — Search Results
	type ResultSortKey = 'name' | 'matching_packets' | 'size_bytes' | 'modified';
	let resultSortKey = $state<ResultSortKey>('matching_packets');
	let resultSortDir = $state<'asc' | 'desc'>('desc');

	// Timeline
	let hoveredBarIndex = $state<number | null>(null);
	let chartWidth = $state(800);

	// ---------------------------------------------------------------------------
	// Derived — Stats
	// ---------------------------------------------------------------------------

	let totalFileCount = $derived(files.length);
	let totalBytes = $derived(files.reduce((s, f) => s + f.size_bytes, 0));
	let newestCapture = $derived(files.length ? files.reduce((a, b) => a.modified > b.modified ? a : b).modified : '');
	let oldestCapture = $derived(files.length ? files.reduce((a, b) => a.modified < b.modified ? a : b).modified : '');
	let maxFileSize = $derived(Math.max(1, ...files.map((f) => f.size_bytes)));

	// ---------------------------------------------------------------------------
	// Derived — Capture Timeline
	// ---------------------------------------------------------------------------

	interface TimelineBucket {
		label: string;
		count: number;
		bytes: number;
	}

	function buildCaptureTimeline(fileList: PcapFile[], range: string): TimelineBucket[] {
		if (!fileList.length) return [];
		const now = Date.now();
		const rangeMs = TIME_RANGES.find((r) => r.value === range)?.ms ?? 86400000;
		const bucketMs = range === '1h' ? 5 * 60000 : range === '4h' ? 20 * 60000 : range === '24h' ? 3600000 : range === '7d' ? 6 * 3600000 : 86400000;
		const bucketCount = Math.ceil(rangeMs / bucketMs);
		const startMs = now - rangeMs;
		const buckets: TimelineBucket[] = Array.from({ length: bucketCount }, (_, i) => ({
			label: new Date(startMs + i * bucketMs).toISOString(),
			count: 0,
			bytes: 0,
		}));
		for (const file of fileList) {
			const fileMs = new Date(file.modified).getTime();
			const idx = Math.floor((fileMs - startMs) / bucketMs);
			if (idx >= 0 && idx < bucketCount) {
				buckets[idx].count++;
				buckets[idx].bytes += file.size_bytes;
			}
		}
		return buckets;
	}

	let captureTimeline = $derived(buildCaptureTimeline(files, selectedTimeRange));
	let maxTimelineCount = $derived(Math.max(1, ...captureTimeline.map((b) => b.count)));

	// ---------------------------------------------------------------------------
	// Derived — Protocol Breakdown
	// ---------------------------------------------------------------------------

	interface ProtoEntry {
		protocol: string;
		count: number;
	}

	function buildProtocolBreakdown(packets: PcapPacket[]): ProtoEntry[] {
		const counts = new Map<string, number>();
		for (const pkt of packets) {
			const parts = pkt.protocol.split(':');
			const proto = (parts[parts.length - 1] || pkt.protocol).toUpperCase();
			counts.set(proto, (counts.get(proto) ?? 0) + 1);
		}
		return [...counts.entries()]
			.map(([protocol, count]) => ({ protocol, count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
	}

	let protocolBreakdown = $derived(buildProtocolBreakdown(previewPackets));

	// ---------------------------------------------------------------------------
	// Derived — Sorted tables
	// ---------------------------------------------------------------------------

	let sortedFiles = $derived(
		[...files].sort((a, b) => {
			const cmp = fileSortKey === 'name' ? a.name.localeCompare(b.name) : (a[fileSortKey] as number | string) < (b[fileSortKey] as number | string) ? -1 : 1;
			return fileSortDir === 'asc' ? cmp : -cmp;
		})
	);

	let sortedResults = $derived(
		[...searchResults].sort((a, b) => {
			const cmp = resultSortKey === 'name' ? a.name.localeCompare(b.name) : (a[resultSortKey] as number | string) < (b[resultSortKey] as number | string) ? -1 : 1;
			return resultSortDir === 'asc' ? cmp : -cmp;
		})
	);

	let maxMatchingPackets = $derived(Math.max(1, ...searchResults.map((r) => r.matching_packets)));

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = new Date();
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange);
		const ms = range?.ms ?? 24 * 60 * 60 * 1000;
		return { from: new Date(now.getTime() - ms).toISOString(), to: now.toISOString() };
	}

	function formatNumber(n: number): string {
		if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
		return n.toString();
	}

	function formatTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
		} catch { return ts; }
	}

	function sortIndicator(active: boolean, dir: 'asc' | 'desc'): string {
		return active ? (dir === 'asc' ? ' \u2191' : ' \u2193') : '';
	}

	// ---------------------------------------------------------------------------
	// Data fetching
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
			setTimeout(() => {
				document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
			}, 50);
		}
	}

	function closePreview() {
		previewFile = '';
		previewPackets = [];
	}

	// ---------------------------------------------------------------------------
	// Interaction handlers
	// ---------------------------------------------------------------------------

	function toggleFileSort(key: FileSortKey) {
		if (fileSortKey === key) { fileSortDir = fileSortDir === 'asc' ? 'desc' : 'asc'; }
		else { fileSortKey = key; fileSortDir = key === 'name' ? 'asc' : 'desc'; }
	}

	function toggleResultSort(key: ResultSortKey) {
		if (resultSortKey === key) { resultSortDir = resultSortDir === 'asc' ? 'desc' : 'asc'; }
		else { resultSortKey = key; resultSortDir = key === 'name' ? 'asc' : 'desc'; }
	}

	function applyQuickFilter(filter: string) {
		bpfFilter = filter;
	}

	function applyProtocolFilter(proto: string) {
		bpfFilter = PROTO_FILTER_MAP[proto] ?? proto.toLowerCase();
	}

	function downloadFiltered() {
		if (!bpfFilter.trim()) return;
		const { from, to } = getTimeRange();
		window.open(getDownloadUrl(bpfFilter, { from, to }), '_blank');
	}

	function downloadFile(file: string) {
		window.open(getFileDownloadUrl(file), '_blank');
	}

	function copyText(text: string) {
		navigator.clipboard.writeText(text);
	}

	function handleTimeRangeChange(value: string) {
		selectedTimeRange = value;
		if (initialized) loadFiles();
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		loadFiles().then(() => { initialized = true; });
	});
</script>

<svelte:head>
	<title>PCAP Search - NetTap</title>
</svelte:head>

<div class="page-container">
	<!-- Header -->
	<header class="page-header">
		<div class="header-left">
			<h1>PCAP Search</h1>
			<p class="subtitle">Search and analyze captured network traffic</p>
		</div>
		<div class="header-right">
			<div class="pills">
				{#each TIME_RANGES as range}
					<button
						class="pill"
						class:active={selectedTimeRange === range.value}
						onclick={() => handleTimeRangeChange(range.value)}
					>
						{range.label}
					</button>
				{/each}
			</div>
			<button class="btn btn-primary" onclick={loadFiles} disabled={filesLoading}>
				{filesLoading ? 'Loading...' : 'Refresh'}
			</button>
		</div>
	</header>

	<!-- Hero Stats -->
	<div class="stats-grid">
		<button class="stat-card clickable" onclick={() => document.getElementById('files-section')?.scrollIntoView({ behavior: 'smooth' })}>
			<div class="stat-value mono">{totalFileCount}</div>
			<div class="stat-label">PCAP FILES</div>
		</button>
		<div class="stat-card">
			<div class="stat-value mono">{formatBytes(totalBytes)}</div>
			<div class="stat-label">TOTAL CAPTURED</div>
		</div>
		<div class="stat-card">
			<div class="stat-value mono">{newestCapture ? formatRelativeTime(newestCapture) : '\u2014'}</div>
			<div class="stat-label">NEWEST CAPTURE</div>
		</div>
		<div class="stat-card">
			<div class="stat-value mono">{protocolBreakdown.length > 0 ? protocolBreakdown[0].protocol : '\u2014'}</div>
			<div class="stat-label">TOP PROTOCOL</div>
		</div>
	</div>

	<!-- Capture Timeline -->
	<section class="card">
		<h2>Capture Timeline</h2>
		{#if captureTimeline.length === 0 && !filesLoading}
			<p class="empty-state">No PCAP files in this time range.</p>
		{:else if captureTimeline.length > 0}
			<div class="chart-wrapper" bind:clientWidth={chartWidth}>
				<svg class="timeline-svg" viewBox="0 0 {chartWidth} 220" preserveAspectRatio="none">
					{#each [0, 0.25, 0.5, 0.75, 1] as frac}
						<line x1="45" y1={200 - frac * 180} x2={chartWidth} y2={200 - frac * 180} stroke="var(--border-dim, #1f1f35)" stroke-width="1" />
						{#if frac === 0 || frac === 0.5 || frac === 1}
							<text x="40" y={204 - frac * 180} text-anchor="end" font-size="10" fill="var(--text-muted, #52525b)">{Math.round(maxTimelineCount * frac)}</text>
						{/if}
					{/each}
					{#each captureTimeline as bucket, i}
						{@const barW = Math.max(2, (chartWidth - 50) / captureTimeline.length - 1)}
						{@const x = 50 + i * ((chartWidth - 50) / captureTimeline.length)}
						{@const h = (bucket.count / maxTimelineCount) * 180}
						<rect
							{x} y={200 - h} width={barW} height={Math.max(1, h)}
							fill={hoveredBarIndex === i ? 'var(--accent-blue, #3b82f6)' : 'var(--chart-7, #06b6d4)'}
							opacity={hoveredBarIndex !== null && hoveredBarIndex !== i ? 0.4 : 1}
							rx="1"
							onmouseenter={() => hoveredBarIndex = i}
							onmouseleave={() => hoveredBarIndex = null}
							style="cursor: pointer; transition: opacity 100ms"
						/>
					{/each}
					{#each Array(Math.min(6, captureTimeline.length)) as _, idx}
						{@const i = Math.round(idx * (captureTimeline.length - 1) / Math.max(1, Math.min(5, captureTimeline.length - 1)))}
						{@const x = 50 + i * ((chartWidth - 50) / captureTimeline.length) + Math.max(2, (chartWidth - 50) / captureTimeline.length - 1) / 2}
						{#if captureTimeline[i]}
							<text {x} y="216" text-anchor="middle" font-size="10" fill="var(--text-muted, #52525b)">{formatTimestamp(captureTimeline[i].label)}</text>
						{/if}
					{/each}
				</svg>
				{#if hoveredBarIndex !== null && captureTimeline[hoveredBarIndex]}
					{@const tooltipX = 50 + hoveredBarIndex * ((chartWidth - 50) / captureTimeline.length)}
					<div class="bar-tooltip" style="left: {Math.min(tooltipX, chartWidth - 160)}px">
						<span class="mono">{formatTimestamp(captureTimeline[hoveredBarIndex].label)}</span>
						<span class="accent">{captureTimeline[hoveredBarIndex].count} file(s), {formatBytes(captureTimeline[hoveredBarIndex].bytes)}</span>
					</div>
				{/if}
			</div>
		{/if}
	</section>

	<!-- Filter Bar -->
	<div class="card filter-bar">
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
			<button class="btn btn-secondary" onclick={downloadFiltered} disabled={!bpfFilter.trim()}>
				Download Filtered
			</button>
		</div>
		<div class="filter-options">
			<div class="quick-filters">
				{#each QUICK_FILTERS as qf}
					<button class="chip" class:active={bpfFilter === qf.filter} onclick={() => applyQuickFilter(qf.filter)}>
						{qf.label}
					</button>
				{/each}
			</div>
		</div>
		<div class="syntax-hints">
			<span class="hint">Display filter syntax:</span>
			<code>ip.addr == 1.2.3.4</code>
			<code>tcp.port == 443</code>
			<code>http.request</code>
			<code>dns</code>
		</div>
	</div>

	{#if error}
		<div class="error-banner">{error}</div>
	{/if}

	<!-- Search Results -->
	{#if searchDone}
		<section class="card">
			<h2>Search Results ({searchResults.length} files match)</h2>
			{#if searchResults.length === 0}
				<p class="empty-state">No matching packets found in any PCAP file.</p>
			{:else}
				<div class="table-container">
					<table class="data-table">
						<thead>
							<tr>
								<th><button class="sort-btn" class:active-sort={resultSortKey === 'name'} onclick={() => toggleResultSort('name')}>File{sortIndicator(resultSortKey === 'name', resultSortDir)}</button></th>
								<th><button class="sort-btn" class:active-sort={resultSortKey === 'matching_packets'} onclick={() => toggleResultSort('matching_packets')}>Matching{sortIndicator(resultSortKey === 'matching_packets', resultSortDir)}</button></th>
								<th><button class="sort-btn" class:active-sort={resultSortKey === 'size_bytes'} onclick={() => toggleResultSort('size_bytes')}>Size{sortIndicator(resultSortKey === 'size_bytes', resultSortDir)}</button></th>
								<th><button class="sort-btn" class:active-sort={resultSortKey === 'modified'} onclick={() => toggleResultSort('modified')}>Modified{sortIndicator(resultSortKey === 'modified', resultSortDir)}</button></th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each sortedResults as result}
								<tr class="clickable-row" class:selected-row={previewFile === result.file} onclick={() => showPreview(result.file)}>
									<td class="mono">{result.name}</td>
									<td>
										<div class="match-bar-row">
											<div class="match-bar-track"><div class="match-bar-fill" style="width: {(result.matching_packets / maxMatchingPackets * 100).toFixed(1)}%"></div></div>
											<span class="mono">{result.matching_packets.toLocaleString()}</span>
										</div>
									</td>
									<td class="mono">{formatBytes(result.size_bytes)}</td>
									<td class="nowrap">{new Date(result.modified).toLocaleString()}</td>
									<td><button class="btn btn-sm" onclick={(e) => { e.stopPropagation(); downloadFile(result.file); }}>Download</button></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{/if}

	<!-- Packet Preview -->
	<section class="card" id="preview-panel" style="scroll-margin-top: 80px">
		<div class="card-header">
			<h2>
				Packet Preview
				{#if previewFile}
					<span class="preview-filename mono">{files.find((f) => f.file === previewFile)?.name ?? previewFile.split('/').at(-1)}</span>
				{/if}
				{#if previewLoading}<span class="loading-indicator">Loading...</span>{/if}
			</h2>
			{#if previewFile}
				<div class="preview-actions">
					<button class="btn btn-sm" onclick={() => downloadFile(previewFile)}>Download</button>
					<button class="btn btn-sm" onclick={closePreview}>&times; Close</button>
				</div>
			{/if}
		</div>
		{#if !previewFile}
			<p class="empty-state">Select a file below or run a search to preview packets.</p>
		{:else if previewPackets.length > 0}
			<div class="table-container packet-table-container">
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
								<td class="mono proto-cell">{pkt.protocol.split(':').at(-1)?.toUpperCase() ?? pkt.protocol}</td>
								<td class="mono">{pkt.length}</td>
								<td class="info-cell">{pkt.info}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="table-footer">Showing {previewPackets.length} packets</p>
		{:else if !previewLoading}
			<p class="empty-state">No packets to display{bpfFilter ? ` matching filter "${bpfFilter}"` : ''}.</p>
		{/if}
	</section>

	<!-- Two-column: Files + Protocol Breakdown -->
	<div class="two-col pcap-split" id="files-section">
		<!-- Available Files -->
		<section class="card">
			<div class="card-header">
				<h2>Available Files{!filesLoading ? ` (${files.length})` : ''}</h2>
				{#if filesLoading}<span class="loading-indicator">Loading...</span>{/if}
			</div>
			{#if files.length === 0 && !filesLoading}
				<p class="empty-state">No PCAP files found in the selected time range.</p>
			{:else}
				<div class="table-container">
					<table class="data-table">
						<thead>
							<tr>
								<th><button class="sort-btn" class:active-sort={fileSortKey === 'name'} onclick={() => toggleFileSort('name')}>File{sortIndicator(fileSortKey === 'name', fileSortDir)}</button></th>
								<th><button class="sort-btn" class:active-sort={fileSortKey === 'size_bytes'} onclick={() => toggleFileSort('size_bytes')}>Size{sortIndicator(fileSortKey === 'size_bytes', fileSortDir)}</button></th>
								<th><button class="sort-btn" class:active-sort={fileSortKey === 'modified'} onclick={() => toggleFileSort('modified')}>Modified{sortIndicator(fileSortKey === 'modified', fileSortDir)}</button></th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each sortedFiles as file}
								<tr class="clickable-row" class:selected-row={previewFile === file.file} onclick={() => showPreview(file.file)}>
									<td>
										<div class="file-name-cell">
											<span class="mono">{file.name}</span>
											<button class="btn-icon copy-btn" title="Copy filename" onclick={(e) => { e.stopPropagation(); copyText(file.name); }}>&#x2398;</button>
										</div>
									</td>
									<td>
										<div class="size-bar-row">
											<div class="size-bar-track"><div class="size-bar-fill" style="width: {(file.size_bytes / maxFileSize * 100).toFixed(1)}%"></div></div>
											<span class="mono size-label">{formatBytes(file.size_bytes)}</span>
										</div>
									</td>
									<td class="mono nowrap">{new Date(file.modified).toLocaleString()}</td>
									<td><button class="btn btn-sm" onclick={(e) => { e.stopPropagation(); downloadFile(file.file); }}>Download</button></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>

		<!-- Right panel: File Detail + Protocol Breakdown -->
		<div class="right-panel">
			{#if previewFile}
				{@const selectedFileObj = files.find((f) => f.file === previewFile)}
				<div class="card detail-card">
					<div class="card-header">
						<h2>Selected File</h2>
						<button class="btn-icon" onclick={closePreview}>&times;</button>
					</div>
					{#if selectedFileObj}
						<div class="detail-rows">
							<div class="detail-row"><span class="detail-label">Name</span><span class="mono">{selectedFileObj.name}</span></div>
							<div class="detail-row"><span class="detail-label">Size</span><span class="mono">{formatBytes(selectedFileObj.size_bytes)}</span></div>
							<div class="detail-row"><span class="detail-label">Modified</span><span class="mono">{new Date(selectedFileObj.modified).toLocaleString()}</span></div>
							<div class="detail-row"><span class="detail-label">Path</span><span class="mono path-cell">{selectedFileObj.relative_path}</span></div>
						</div>
					{/if}
				</div>
			{:else}
				<div class="card detail-card">
					<p class="empty-state">Click a file to inspect it</p>
				</div>
			{/if}

			<div class="card">
				<h2>Protocol Breakdown</h2>
				{#if protocolBreakdown.length === 0}
					<p class="empty-state">Load a file preview to see protocol distribution.</p>
				{:else}
					<div class="type-bars">
						{#each protocolBreakdown as proto}
							{@const pct = previewPackets.length > 0 ? (proto.count / previewPackets.length) * 100 : 0}
							<button class="type-row" onclick={() => applyProtocolFilter(proto.protocol)}>
								<span class="type-label mono">{proto.protocol}</span>
								<div class="type-bar-track"><div class="type-bar-fill" style="width: {pct.toFixed(1)}%"></div></div>
								<span class="type-count mono">{proto.count}</span>
								<span class="type-pct">{pct.toFixed(1)}%</span>
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.page-container { max-width: 1400px; margin: 0 auto; padding: 1.5rem; }

	/* Header */
	.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem; }
	.header-left h1 { font-size: 1.75rem; font-weight: 700; color: var(--text-primary, #e4e4e7); margin: 0; }
	.subtitle { color: var(--text-secondary, #a1a1aa); margin: 0.25rem 0 0; font-size: 0.9rem; }
	.header-right { display: flex; gap: 0.75rem; align-items: center; }

	/* Pills */
	.pills { display: flex; gap: 0.25rem; background: var(--surface-card, #1a1a2e); border: 1px solid var(--border-color, #2d2d44); border-radius: 0.5rem; padding: 0.2rem; }
	.pill { padding: 0.35rem 0.75rem; border: none; border-radius: 0.375rem; background: transparent; color: var(--text-secondary, #a1a1aa); font-size: 0.8rem; cursor: pointer; transition: all 0.15s; }
	.pill:hover { color: var(--text-primary, #e4e4e7); }
	.pill.active { background: var(--accent-blue, #3b82f6); color: #fff; }

	/* Buttons */
	.btn { padding: 0.5rem 1rem; border: 1px solid var(--border-color, #2d2d44); border-radius: 0.5rem; cursor: pointer; font-size: 0.875rem; transition: all 0.15s; background: var(--surface-card, #1a1a2e); color: var(--text-primary, #e4e4e7); }
	.btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.btn-primary { background: var(--accent-blue, #3b82f6); border-color: var(--accent-blue, #3b82f6); color: #fff; }
	.btn-primary:hover:not(:disabled) { background: #2563eb; }
	.btn-secondary { background: var(--surface-elevated, #252540); }
	.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; }
	.btn-icon { background: none; border: none; color: var(--text-muted, #52525b); cursor: pointer; padding: 0.25rem; font-size: 1rem; line-height: 1; }
	.btn-icon:hover { color: var(--text-primary, #e4e4e7); }

	/* Stats Grid */
	.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
	.stat-card { background: var(--surface-card, #1a1a2e); border: 1px solid var(--border-color, #2d2d44); border-radius: 0.75rem; padding: 1.25rem; text-align: left; }
	.stat-card.clickable { cursor: pointer; transition: border-color 0.15s; }
	.stat-card.clickable:hover { border-color: var(--accent-blue, #3b82f6); }
	.stat-value { font-size: 2rem; font-weight: 700; color: var(--text-primary, #e4e4e7); line-height: 1.2; }
	.stat-label { font-size: 0.7rem; color: var(--text-muted, #52525b); letter-spacing: 0.05em; margin-top: 0.25rem; text-transform: uppercase; }

	/* Cards */
	.card { background: var(--surface-card, #1a1a2e); border: 1px solid var(--border-color, #2d2d44); border-radius: 0.75rem; padding: 1.25rem; margin-bottom: 1.5rem; }
	.card h2 { font-size: 1.1rem; font-weight: 600; color: var(--text-primary, #e4e4e7); margin: 0 0 1rem; }
	.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
	.card-header h2 { margin: 0; }

	/* Two-column layout */
	.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
	.two-col .card { margin-bottom: 0; }
	.pcap-split { grid-template-columns: 1.6fr 1fr; }
	.right-panel { display: flex; flex-direction: column; gap: 1.5rem; }
	.right-panel .card { margin-bottom: 0; }

	/* Timeline Chart */
	.chart-wrapper { position: relative; width: 100%; min-height: 220px; }
	.timeline-svg { width: 100%; height: 220px; }
	.bar-tooltip { position: absolute; top: -8px; background: var(--surface-elevated, #252540); border: 1px solid var(--border-color, #2d2d44); border-radius: 0.375rem; padding: 0.375rem 0.625rem; display: flex; flex-direction: column; gap: 0.125rem; font-size: 0.75rem; pointer-events: none; z-index: 10; white-space: nowrap; }
	.bar-tooltip .accent { color: var(--accent-blue, #3b82f6); font-weight: 600; }

	/* Filter Bar */
	.filter-bar { padding: 1.25rem; }
	.filter-input-row { display: flex; gap: 0.75rem; margin-bottom: 0.75rem; }
	.bpf-input { flex: 1; padding: 0.625rem 1rem; background: var(--surface-input, #0f0f1a); border: 1px solid var(--border-color, #2d2d44); border-radius: 0.5rem; color: var(--text-primary, #e4e4e7); font-family: 'JetBrains Mono', monospace; font-size: 0.875rem; }
	.bpf-input::placeholder { color: var(--text-muted, #52525b); }
	.filter-options { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem; }
	.quick-filters { display: flex; gap: 0.375rem; flex-wrap: wrap; }
	.chip { padding: 0.25rem 0.625rem; font-size: 0.75rem; border-radius: 1rem; border: 1px solid var(--border-color, #2d2d44); background: var(--surface-card, #1a1a2e); color: var(--text-primary, #e4e4e7); cursor: pointer; transition: all 0.15s; }
	.chip:hover { border-color: var(--accent-blue, #3b82f6); }
	.chip.active { background: var(--accent-blue, #3b82f6); border-color: var(--accent-blue, #3b82f6); color: #fff; }
	.syntax-hints { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; font-size: 0.75rem; color: var(--text-muted, #52525b); }
	.syntax-hints code { background: var(--surface-input, #0f0f1a); padding: 0.15rem 0.4rem; border-radius: 0.25rem; }
	.hint { font-weight: 600; }

	/* Error */
	.error-banner { background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); color: #ef4444; padding: 0.75rem 1rem; border-radius: 0.5rem; margin-bottom: 1rem; font-size: 0.875rem; }

	/* Tables */
	.table-container { overflow-x: auto; border: 1px solid var(--border-color, #2d2d44); border-radius: 0.5rem; max-height: 450px; overflow-y: auto; }
	.packet-table-container { max-height: 500px; }
	.data-table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }
	.data-table th { background: var(--surface-card, #1a1a2e); padding: 0.5rem 0.75rem; text-align: left; color: var(--text-secondary, #a1a1aa); font-weight: 600; border-bottom: 1px solid var(--border-color, #2d2d44); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
	.data-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border-subtle, #1f1f35); color: var(--text-primary, #e4e4e7); }
	.clickable-row { cursor: pointer; }
	.clickable-row:hover td { background: var(--surface-hover, #1f1f35); }
	.selected-row td { background: rgba(59, 130, 246, 0.1); border-left: 2px solid var(--accent-blue, #3b82f6); }
	.sort-btn { background: none; border: none; color: var(--text-secondary, #a1a1aa); font-weight: 600; font-size: 0.8125rem; cursor: pointer; padding: 0; white-space: nowrap; }
	.sort-btn:hover { color: var(--text-primary, #e4e4e7); }
	.sort-btn.active-sort { color: var(--accent-blue, #3b82f6); }
	.mono { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; }
	.nowrap { white-space: nowrap; }
	.table-footer { text-align: center; font-size: 0.75rem; color: var(--text-muted, #52525b); padding: 0.5rem; }

	/* File name + copy */
	.file-name-cell { display: flex; align-items: center; gap: 0.25rem; }
	.copy-btn { opacity: 0; transition: opacity 0.15s; font-size: 1.25rem; color: var(--accent-blue, #3b82f6); padding: 0.25rem 0.5rem; }
	.copy-btn:hover { color: #60a5fa; }
	.clickable-row:hover .copy-btn { opacity: 1; }

	/* Size bars */
	.size-bar-row { display: flex; align-items: center; gap: 0.5rem; }
	.size-bar-track { flex: 1; height: 16px; background: var(--surface-input, #0f0f1a); border-radius: 0.25rem; overflow: hidden; min-width: 60px; }
	.size-bar-fill { height: 100%; background: var(--chart-7, #06b6d4); border-radius: 0.25rem; transition: width 0.3s; min-width: 2px; }
	.size-label { white-space: nowrap; font-size: 0.75rem; }

	/* Match bars (search results) */
	.match-bar-row { display: flex; align-items: center; gap: 0.5rem; }
	.match-bar-track { flex: 1; height: 16px; background: var(--surface-input, #0f0f1a); border-radius: 0.25rem; overflow: hidden; min-width: 40px; }
	.match-bar-fill { height: 100%; background: var(--accent-blue, #3b82f6); border-radius: 0.25rem; transition: width 0.3s; min-width: 2px; }

	/* Preview */
	.preview-filename { font-size: 0.85rem; color: var(--accent-blue, #3b82f6); margin-left: 0.5rem; }
	.preview-actions { display: flex; gap: 0.5rem; }
	.loading-indicator { font-size: 0.8rem; color: var(--text-muted, #52525b); font-weight: 400; margin-left: 0.5rem; }
	.proto-cell { color: var(--chart-7, #06b6d4); font-weight: 600; }
	.info-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	/* Protocol Breakdown */
	.type-bars { display: flex; flex-direction: column; gap: 0.625rem; }
	.type-row { display: grid; grid-template-columns: 60px 1fr 50px 50px; align-items: center; gap: 0.75rem; background: none; border: none; cursor: pointer; padding: 0.25rem 0; color: inherit; width: 100%; text-align: left; border-radius: 0.25rem; transition: background 0.15s; }
	.type-row:hover { background: var(--surface-hover, #1f1f35); }
	.type-label { font-size: 0.8rem; color: var(--text-secondary, #a1a1aa); text-align: right; }
	.type-bar-track { height: 24px; background: var(--surface-input, #0f0f1a); border-radius: 0.25rem; overflow: hidden; }
	.type-bar-fill { height: 100%; background: var(--chart-7, #06b6d4); border-radius: 0.25rem; transition: width 0.3s; min-width: 2px; }
	.type-count { text-align: right; font-size: 0.8rem; color: var(--text-primary, #e4e4e7); }
	.type-pct { font-size: 0.75rem; color: var(--text-muted, #52525b); text-align: right; }

	/* Detail card */
	.detail-card { min-height: 120px; }
	.detail-rows { display: flex; flex-direction: column; gap: 0.5rem; }
	.detail-row { display: flex; gap: 0.75rem; align-items: baseline; }
	.detail-label { font-size: 0.7rem; color: var(--text-muted, #52525b); text-transform: uppercase; letter-spacing: 0.05em; min-width: 60px; }
	.path-cell { max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

	/* Empty states */
	.empty-state { color: var(--text-muted, #52525b); font-size: 0.875rem; text-align: center; padding: 2rem 1rem; }

	/* Responsive */
	@media (max-width: 900px) {
		.stats-grid { grid-template-columns: repeat(2, 1fr); }
		.two-col, .pcap-split { grid-template-columns: 1fr; }
	}
</style>
