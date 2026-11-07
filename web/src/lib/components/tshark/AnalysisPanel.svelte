<script lang="ts">
	/**
	 * AnalysisPanel — top-level orchestrator for TShark packet analysis.
	 *
	 * Provides:
	 *   - PCAP file path input
	 *   - Display filter (via FilterInput)
	 *   - Output format selector
	 *   - Max packets control
	 *   - Analyze button
	 *   - Status badge for TShark availability
	 *   - PacketTable + ProtocolTree in a split layout
	 */

	import FilterInput from './FilterInput.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	// OLD CODE START — replaced PacketTable + ProtocolTree with PanelManager (3-pane layout)
	// import PacketTable from './PacketTable.svelte';
	// import ProtocolTree from './ProtocolTree.svelte';
	// OLD CODE END
	import PanelManager from './PanelManager.svelte';
	import { getRawHex } from '$lib/utils/tshark-helpers';
	import {
		analyzePcap,
		getTSharkStatus,
		getPcapFiles,
		type TSharkAnalyzeResponse,
		type TSharkStatus,
		type PcapFile,
	} from '$api/tshark';
	import { page } from '$app/stores';
	import { formatTime } from '$lib/utils/time';

	// ---- State ----
	let pcapPath = $state('');
	let displayFilter = $state('');
	let maxPackets = $state(100);
	let outputFormat = $state<'json' | 'text'>('json');
	let pcapFiles = $state<PcapFile[]>([]);
	let pcapFilesLoading = $state(false);
	let pcapFilesFailed = $state(false); // #96: a failed listing is not "no PCAP files"
	let showPcapPicker = $state(false);

	let loading = $state(false);
	let result = $state<TSharkAnalyzeResponse | null>(null);
	let errorMessage = $state('');

	let selectedPacketIndex = $state(-1);
	let selectedPacket = $derived(
		result && selectedPacketIndex >= 0 ? result.packets[selectedPacketIndex] ?? null : null
	);

	let status = $state<TSharkStatus | null>(null);
	let statusLoading = $state(true);
	let statusFailed = $state(false); // #96: a failed check is not "TShark Unavailable"
	// the daemon passes on `tshark --version`'s first line, which already names TShark
	const versionLabel = $derived(
		status && /^tshark\b/i.test(status.version) ? status.version : `TShark ${status?.version ?? ''}`,
	);

	// ---- Read URL query params + auto-analyze on mount ----
	let autoAnalyzeDone = false;

	$effect(() => {
		const urlFilter = $page.url.searchParams.get('filter');
		const urlPcap = $page.url.searchParams.get('pcap');
		const autoRun = $page.url.searchParams.get('auto') === '1';
		const connTs = $page.url.searchParams.get('ts');

		if (urlFilter && !displayFilter) displayFilter = urlFilter;
		if (urlPcap && !pcapPath) pcapPath = urlPcap;

		if (autoRun && !autoAnalyzeDone) {
			autoAnalyzeDone = true;
			autoAnalyze(connTs);
		}
	});

	async function autoAnalyze(connTimestamp: string | null) {
		// Load PCAP files, pick best match, run analysis
		pcapFilesLoading = true;
		pcapFilesFailed = false;
		try {
			const res = await getPcapFiles();
			pcapFiles = res.pcaps;
		} catch {
			pcapFiles = [];
			pcapFilesFailed = true;
		} finally {
			pcapFilesLoading = false;
		}

		if (pcapFilesFailed) {
			errorMessage = "Couldn't load the PCAP file list: the request failed.";
			return;
		}

		if (pcapFiles.length === 0) {
			// OLD CODE START — 2026-11-02: netsniff (pcap-capture) writes the PCAP; Arkime is off (#44)
			// errorMessage = 'No PCAP files found. Arkime may not be capturing packets, or the PCAP volume is empty.';
			// OLD CODE END
			errorMessage = 'No PCAP files found. PCAP capture may be turned off, or the PCAP volume is empty.';
			return;
		}

		// Sort PCAPs by closeness to the connection timestamp
		let sortedPcaps = [...pcapFiles];
		if (connTimestamp && pcapFiles.length > 1) {
			const connTime = new Date(connTimestamp).getTime() / 1000;
			sortedPcaps.sort(
				(a, b) => Math.abs(a.modified - connTime) - Math.abs(b.modified - connTime)
			);
		}

		// Try up to 5 PCAP files (closest first) until we find matching packets
		const maxAttempts = Math.min(5, sortedPcaps.length);
		let cutShort = 0; // searches TShark stopped before the end of the file
		for (let i = 0; i < maxAttempts; i++) {
			pcapPath = sortedPcaps[i].path;
			await runAnalysis();
			if (result?.truncated) cutShort++;

			if (result && result.packet_count > 0) {
				return; // Found matching packets
			}
		}

		// If no packets matched with the filter, show helpful message
		// OLD CODE START — 2026-11-03: said "none found" when the searches had stopped early
		// if (result && result.packet_count === 0 && displayFilter) {
		// 	errorMessage = `No packets matching filter "${displayFilter}" found across ${maxAttempts} PCAP file(s). The connection may have been captured in a different file, or try a broader filter.`;
		// }
		// OLD CODE END
		if (result && result.packet_count === 0 && displayFilter) {
			errorMessage = cutShort
				? `No packets matching filter "${displayFilter}" in the parts of ${maxAttempts} PCAP file(s) TShark searched: it stopped before the end of ${cutShort} of them, so matches may be further in. Try a narrower filter.`
				: `No packets matching filter "${displayFilter}" found across ${maxAttempts} PCAP file(s). The connection may have been captured in a different file, or try a broader filter.`;
		}
	}

	// ---- Fetch TShark status on mount ----
	$effect(() => {
		fetchStatus();
	});

	async function fetchStatus() {
		statusLoading = true;
		statusFailed = false;
		try {
			status = await getTSharkStatus();
		} catch {
			status = null;
			statusFailed = true;
		} finally {
			statusLoading = false;
		}
	}

	// ---- Analysis ----
	async function runAnalysis() {
		if (!pcapPath.trim()) return;

		loading = true;
		errorMessage = '';
		result = null;
		selectedPacketIndex = -1;

		try {
			const res = await analyzePcap({
				pcap_path: pcapPath.trim(),
				display_filter: displayFilter || undefined,
				max_packets: maxPackets,
				output_format: outputFormat,
				// raw bytes for the hex dump pane (frame_raw); only JSON carries them per packet
				include_hex: outputFormat === 'json',
			});

			if (res.error) {
				errorMessage = res.error;
			}

			result = res;
		} catch (err) {
			errorMessage = err instanceof Error ? err.message : 'Analysis request failed';
		} finally {
			loading = false;
		}
	}

	function handleFilterSubmit(filter: string) {
		displayFilter = filter;
		// If we already have a pcap path, re-run analysis with new filter
		if (pcapPath.trim()) {
			runAnalysis();
		}
	}

	function handlePacketSelect(packet: any) {
		const idx = result?.packets.indexOf(packet) ?? -1;
		selectedPacketIndex = idx;
	}

	function handleAnalyzeKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			runAnalysis();
		}
	}

	// ---- PCAP file picker ----
	async function loadPcapFiles() {
		if (pcapFiles.length > 0) {
			showPcapPicker = !showPcapPicker;
			return;
		}
		pcapFilesLoading = true;
		pcapFilesFailed = false;
		showPcapPicker = true;
		try {
			const res = await getPcapFiles();
			pcapFiles = res.pcaps;
		} catch {
			pcapFiles = [];
			pcapFilesFailed = true;
		} finally {
			pcapFilesLoading = false;
		}
	}

	function selectPcap(pcap: PcapFile) {
		pcapPath = pcap.path;
		showPcapPicker = false;
	}

	function formatFileSize(bytes: number): string {
		// OLD CODE START — 2026-11-06 (NET-166): 1024-based under decimal labels
		// if (bytes < 1024) return `${bytes} B`;
		// if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		// if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		// return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
		// OLD CODE END
		if (bytes < 1e3) return `${bytes} B`;
		if (bytes < 1e6) return `${(bytes / 1e3).toFixed(1)} KB`;
		if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
		return `${(bytes / 1e9).toFixed(2)} GB`;
	}

	// OLD CODE START — the browser's locale printed "11/6/2026, 10:37:23 PM" (NET-192 PR 4: formatTime)
	// function formatFileDate(ts: number): string {
	// 	return new Date(ts * 1000).toLocaleString();
	// }
	// OLD CODE END
	const formatFileDate = (ts: number) => formatTime(ts * 1000);
</script>

<div class="analysis-panel">
	<!-- Header with status badge -->
	<div class="panel-header">
		<!-- the page head owns the h1; this names the panel -->
		<h2 class="card-title">Packet analysis</h2>
		<div class="status-badge-group">
			{#if statusLoading}
				<span class="chip">
					<span class="status-dot"></span>
					Checking…
				</span>
			{:else if status?.available}
				<span class="chip is-ok">
					<Icon name="check" />
					{versionLabel}
				</span>
			{:else if statusFailed}
				<span class="chip" title="The status request failed">
					<span class="status-dot"></span>
					TShark status unknown
				</span>
			{:else}
				<span class="chip is-bad">
					<Icon name="warn" />
					TShark unavailable
				</span>
			{/if}

			<button class="icon-btn" onclick={fetchStatus} title="Refresh TShark status" aria-label="Refresh TShark status">
				<Icon name="refresh" />
			</button>
		</div>
	</div>

	<!-- Controls card -->
	<div class="card">
		<div class="controls-grid">
			<!-- PCAP path input -->
			<div class="form-group pcap-group">
				<label class="label" for="pcap-path">PCAP file path</label>
				<div class="pcap-input-row">
					<input
						id="pcap-path"
						type="text"
						class="input mono"
						placeholder="/opt/nettap/pcap/capture.pcap"
						bind:value={pcapPath}
						onkeydown={handleAnalyzeKeydown}
						disabled={loading}
					/>
					<button
						class="btn"
						onclick={loadPcapFiles}
						disabled={loading}
						title="Browse available PCAP files"
					>
						{#if pcapFilesLoading}
							<span class="btn-spinner-sm"></span>
						{:else}
							<Icon name="pcap" />
						{/if}
						Browse
					</button>
				</div>
				{#if showPcapPicker}
					<div class="pcap-picker">
						{#if pcapFilesLoading}
							<div class="pcap-picker-loading">Loading PCAP files…</div>
						{:else if pcapFilesFailed}
							<div class="pcap-picker-empty">Couldn't load the PCAP file list: the request failed.</div>
						{:else if pcapFiles.length === 0}
							<div class="pcap-picker-empty">No PCAP files found in /opt/nettap/pcap</div>
						{:else}
							<div class="pcap-picker-header">
								<span>{pcapFiles.length} file{pcapFiles.length !== 1 ? 's' : ''} available</span>
								<button class="icon-btn ghost" onclick={() => (showPcapPicker = false)} aria-label="Close the file list">
									<Icon name="close" />
								</button>
							</div>
							<div class="pcap-picker-list">
								{#each pcapFiles as pcap}
									<button
										class="pcap-picker-item"
										class:selected={pcapPath === pcap.path}
										onclick={() => selectPcap(pcap)}
									>
										<span class="mono">{pcap.name}</span>
										<span class="pcap-meta">
											{formatFileSize(pcap.size_bytes)} &middot; {formatFileDate(pcap.modified)}
										</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Output format + Max packets -->
			<div class="controls-row">
				<div class="form-group">
					<label class="label" for="output-format">Output format</label>
					<select
						id="output-format"
						class="select"
						bind:value={outputFormat}
						disabled={loading}
					>
						<option value="json">JSON (structured)</option>
						<option value="text">Text (raw)</option>
					</select>
				</div>

				<div class="form-group">
					<label class="label" for="max-packets">Max packets</label>
					<input
						id="max-packets"
						type="number"
						class="input"
						min="1"
						max="10000"
						bind:value={maxPackets}
						disabled={loading}
					/>
				</div>

				<div class="form-group analyze-btn-group">
					<span class="label" aria-hidden="true">&nbsp;</span>
					<button
						class="btn primary analyze-btn"
						onclick={runAnalysis}
						disabled={loading || !pcapPath.trim()}
					>
						{#if loading}
							<span class="btn-spinner"></span>
							Analysing…
						{:else}
							<Icon name="play" />
							Analyse
						{/if}
					</button>
				</div>
			</div>

			<!-- Display filter -->
			<div class="form-group filter-group">
				<span class="label">Display filter</span>
				<!-- OLD CODE START — Analyze ignored a filter typed but not yet applied, and showed unfiltered packets (#65)
				<FilterInput onsubmit={handleFilterSubmit} disabled={loading} value={displayFilter} />
				OLD CODE END -->
				<FilterInput
					onsubmit={handleFilterSubmit}
					onchange={(f) => (displayFilter = f)}
					disabled={loading}
					value={displayFilter}
				/>
			</div>
		</div>
	</div>

	<!-- Error display -->
	{#if errorMessage}
		<div class="notice is-error">
			<Icon name="warn" />
			<span><strong>Error:</strong> {errorMessage}</span>
		</div>
	{/if}

	<!-- Results summary -->
	{#if result && !errorMessage}
		<div class="results-summary">
			<span class="chip num">
				{result.packet_count} packet{result.packet_count !== 1 ? 's' : ''}
			</span>
			<!-- OLD CODE START — 2026-11-03: a filter search cut short at its time limit with 0 found
			     read "more packets available" (batch 47's TShark check)
			{#if result.truncated}
				<span class="badge badge-warning">
					Truncated — more packets available
				</span>
			{/if}
			OLD CODE END -->
			{#if result.truncated}
				<span class="chip is-warn">
					<Icon name="warn" />
					{result.packet_count === 0
						? 'Stopped before the end of the file: matches may be further in'
						: 'Not the whole file: more packets may match'}
				</span>
			{/if}
			{#if result.tshark_version}
				<span class="summary-detail">TShark {result.tshark_version}</span>
			{/if}
		</div>
	{/if}

	<!-- OLD CODE START — replaced 2-panel split with PanelManager 3-pane layout
	<div class="results-layout">
		<div class="results-table-section">
			<PacketTable
				packets={result?.packets ?? []}
				{loading}
				onselect={handlePacketSelect}
				selectedIndex={selectedPacketIndex}
			/>
		</div>

		<div class="results-detail-section">
			<ProtocolTree packet={selectedPacket} />
		</div>
	</div>
	OLD CODE END -->

	<!-- 3-pane results layout -->
	<div class="results-layout">
		<PanelManager
			packets={result?.packets ?? []}
			{loading}
			selectedPacket={selectedPacket}
			{selectedPacketIndex}
			onPacketSelect={handlePacketSelect}
			rawHex={getRawHex(selectedPacket)}
		/>
	</div>
</div>

<style>
	.analysis-panel {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}

	.status-badge-group {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		min-width: 0;
	}

	/* the full version line is longer than a phone is wide */
	.status-badge-group .chip { white-space: normal; }

	/* "Checking" and "unknown": a grey dot that pulses while the status loads */
	.status-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background-color: var(--text-3);
		animation: pulse 1s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.controls-grid {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
	}

	.pcap-group {
		margin-bottom: 0;
	}

	.controls-row {
		display: flex;
		gap: var(--sp-4);
		align-items: flex-end;
		flex-wrap: wrap;
	}

	.controls-row .form-group {
		margin-bottom: 0;
		min-width: 140px;
	}

	.filter-group {
		margin-bottom: 0;
	}

	.analyze-btn-group {
		flex-shrink: 0;
	}

	.analyze-btn {
		min-width: 120px;
	}

	.btn-spinner {
		display: inline-block;
		width: 14px;
		height: 14px;
		border: 2px solid color-mix(in srgb, var(--on-accent) 30%, transparent);
		border-top-color: var(--on-accent);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}


	.results-summary {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		flex-wrap: wrap;
	}

	.summary-detail {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.results-layout {
		height: calc(100vh - 320px);
		min-height: 400px;
		position: relative;
	}

	.pcap-input-row {
		display: flex;
		gap: var(--sp-2);
	}

	.pcap-input-row .input {
		flex: 1;
	}

	.btn-spinner-sm {
		display: inline-block;
		width: 12px;
		height: 12px;
		border: 2px solid var(--text-3);
		border-top-color: var(--text-1);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	.pcap-picker {
		margin-top: var(--sp-1);
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		max-height: 240px;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.pcap-picker-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--sp-1) var(--sp-1) var(--sp-1) var(--sp-3);
		font-size: var(--text-xs);
		color: var(--text-3);
		border-bottom: 1px solid var(--line);
	}

	.pcap-picker-list {
		overflow-y: auto;
		max-height: 200px;
	}

	.pcap-picker-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: var(--sp-2) var(--sp-3);
		background: none;
		border: none;
		border-bottom: 1px solid var(--line);
		color: var(--text-1);
		cursor: pointer;
		text-align: left;
		font-size: var(--text-sm);
		transition: background-color var(--dur-fast);
	}

	.pcap-picker-item:hover {
		background: var(--row-hover);
	}

	.pcap-picker-item.selected {
		background: var(--surface-2);
		box-shadow: inset 0 0 0 1px var(--line-strong);
	}

	.pcap-picker-item:last-child {
		border-bottom: none;
	}

	.pcap-meta {
		font-size: var(--text-xs);
		color: var(--text-3);
		white-space: nowrap;
		margin-left: var(--sp-4);
	}

	.pcap-picker-loading,
	.pcap-picker-empty {
		padding: var(--sp-4);
		text-align: center;
		color: var(--text-3);
		font-size: var(--text-sm);
	}

	@media (max-width: 640px) {
		.controls-row {
			flex-direction: column;
			align-items: stretch;
		}

		.controls-row .form-group {
			min-width: unset;
		}
	}
</style>
