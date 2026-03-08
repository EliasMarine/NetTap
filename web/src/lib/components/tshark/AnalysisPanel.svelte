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
	// OLD CODE START — replaced PacketTable + ProtocolTree with PanelManager (3-pane layout)
	// import PacketTable from './PacketTable.svelte';
	// import ProtocolTree from './ProtocolTree.svelte';
	// OLD CODE END
	import PanelManager from './PanelManager.svelte';
	import {
		analyzePcap,
		getTSharkStatus,
		getPcapFiles,
		type TSharkAnalyzeResponse,
		type TSharkStatus,
		type PcapFile,
	} from '$api/tshark';
	import { page } from '$app/stores';

	// ---- State ----
	let pcapPath = $state('');
	let displayFilter = $state('');
	let maxPackets = $state(100);
	let outputFormat = $state<'json' | 'text'>('json');
	let pcapFiles = $state<PcapFile[]>([]);
	let pcapFilesLoading = $state(false);
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
		try {
			const res = await getPcapFiles();
			pcapFiles = res.pcaps;
		} catch {
			pcapFiles = [];
		} finally {
			pcapFilesLoading = false;
		}

		if (pcapFiles.length === 0) {
			errorMessage = 'No PCAP files found. Arkime may not be capturing packets, or the PCAP volume is empty.';
			return;
		}

		// Pick the PCAP whose modification time is closest to the connection timestamp
		if (connTimestamp && pcapFiles.length > 1) {
			const connTime = new Date(connTimestamp).getTime() / 1000;
			let bestIdx = 0;
			let bestDiff = Infinity;
			for (let i = 0; i < pcapFiles.length; i++) {
				const diff = Math.abs(pcapFiles[i].modified - connTime);
				if (diff < bestDiff) {
					bestDiff = diff;
					bestIdx = i;
				}
			}
			pcapPath = pcapFiles[bestIdx].path;
		} else {
			// Default to most recent
			pcapPath = pcapFiles[0].path;
		}

		// Auto-run analysis
		runAnalysis();
	}

	// ---- Fetch TShark status on mount ----
	$effect(() => {
		fetchStatus();
	});

	async function fetchStatus() {
		statusLoading = true;
		try {
			status = await getTSharkStatus();
		} catch {
			status = null;
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
		showPcapPicker = true;
		try {
			const res = await getPcapFiles();
			pcapFiles = res.pcaps;
		} catch {
			pcapFiles = [];
		} finally {
			pcapFilesLoading = false;
		}
	}

	function selectPcap(pcap: PcapFile) {
		pcapPath = pcap.path;
		showPcapPicker = false;
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}

	function formatFileDate(ts: number): string {
		return new Date(ts * 1000).toLocaleString();
	}
</script>

<div class="analysis-panel">
	<!-- Header with status badge -->
	<div class="panel-header">
		<h3 class="panel-title">Packet Analysis</h3>
		<div class="status-badge-group">
			{#if statusLoading}
				<span class="badge">
					<span class="status-dot checking"></span>
					Checking...
				</span>
			{:else if status?.available}
				<span class="badge badge-success">
					<span class="status-dot online"></span>
					TShark {status.version}
				</span>
			{:else}
				<span class="badge badge-danger">
					<span class="status-dot offline"></span>
					TShark Unavailable
				</span>
			{/if}

			<button class="btn btn-secondary btn-sm" onclick={fetchStatus} title="Refresh TShark status">
				<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
					<path d="M8 2.002a5.998 5.998 0 103.906 10.531.75.75 0 01.984 1.131A7.5 7.5 0 118 .5a7.47 7.47 0 015.217 2.118l.146-.152a.75.75 0 011.072 1.046l-2.038 2.094a.75.75 0 01-1.072.009L9.287 3.508a.75.75 0 011.07-1.05l.206.208A5.97 5.97 0 008 2.002z" />
				</svg>
			</button>
		</div>
	</div>

	<!-- Controls card -->
	<div class="card controls-card">
		<div class="controls-grid">
			<!-- PCAP path input -->
			<div class="form-group pcap-group">
				<label class="label" for="pcap-path">PCAP File Path</label>
				<div class="pcap-input-row">
					<input
						id="pcap-path"
						type="text"
						class="input mono-input"
						placeholder="/opt/nettap/pcap/capture.pcap"
						bind:value={pcapPath}
						onkeydown={handleAnalyzeKeydown}
						disabled={loading}
					/>
					<button
						class="btn btn-secondary btn-sm browse-btn"
						onclick={loadPcapFiles}
						disabled={loading}
						title="Browse available PCAP files"
					>
						{#if pcapFilesLoading}
							<span class="btn-spinner-sm"></span>
						{:else}
							<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
								<path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
							</svg>
						{/if}
						Browse
					</button>
				</div>
				{#if showPcapPicker}
					<div class="pcap-picker">
						{#if pcapFilesLoading}
							<div class="pcap-picker-loading">Loading PCAP files...</div>
						{:else if pcapFiles.length === 0}
							<div class="pcap-picker-empty">No PCAP files found in /opt/nettap/pcap</div>
						{:else}
							<div class="pcap-picker-header">
								<span>{pcapFiles.length} file{pcapFiles.length !== 1 ? 's' : ''} available</span>
								<button class="pcap-picker-close" onclick={() => (showPcapPicker = false)}>x</button>
							</div>
							<div class="pcap-picker-list">
								{#each pcapFiles as pcap}
									<button
										class="pcap-picker-item"
										class:selected={pcapPath === pcap.path}
										onclick={() => selectPcap(pcap)}
									>
										<span class="pcap-name">{pcap.name}</span>
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
					<label class="label" for="output-format">Output Format</label>
					<select
						id="output-format"
						class="input"
						bind:value={outputFormat}
						disabled={loading}
					>
						<option value="json">JSON (structured)</option>
						<option value="text">Text (raw)</option>
					</select>
				</div>

				<div class="form-group">
					<label class="label" for="max-packets">Max Packets</label>
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
						class="btn btn-primary analyze-btn"
						onclick={runAnalysis}
						disabled={loading || !pcapPath.trim()}
					>
						{#if loading}
							<span class="btn-spinner"></span>
							Analyzing...
						{:else}
							<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
								<path d="M11.28 3.22a.75.75 0 010 1.06L4.56 11H13.25a.75.75 0 010 1.5H2.75a.75.75 0 01-.53-1.28l8-8a.75.75 0 011.06 0z" />
							</svg>
							Analyze
						{/if}
					</button>
				</div>
			</div>

			<!-- Display filter -->
			<div class="form-group filter-group">
				<span class="label">Display Filter</span>
				<FilterInput onsubmit={handleFilterSubmit} disabled={loading} />
			</div>
		</div>
	</div>

	<!-- Error display -->
	{#if errorMessage}
		<div class="alert alert-danger">
			<strong>Error:</strong> {errorMessage}
		</div>
	{/if}

	<!-- Results summary -->
	{#if result && !errorMessage}
		<div class="results-summary">
			<span class="badge badge-accent">
				{result.packet_count} packet{result.packet_count !== 1 ? 's' : ''}
			</span>
			{#if result.truncated}
				<span class="badge badge-warning">
					Truncated — more packets available
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
		/>
	</div>
</div>

<style>
	.analysis-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-sm);
	}

	.panel-title {
		font-size: var(--text-xl);
		font-weight: 700;
		color: var(--text-primary);
	}

	.status-badge-group {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.status-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.status-dot.online {
		background-color: var(--success);
		box-shadow: 0 0 6px var(--success);
	}

	.status-dot.offline {
		background-color: var(--danger);
		box-shadow: 0 0 6px var(--danger);
	}

	.status-dot.checking {
		background-color: var(--text-muted);
		animation: pulse 1s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.controls-card {
		padding: var(--space-lg);
	}

	.controls-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.pcap-group {
		margin-bottom: 0;
	}

	.mono-input {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}

	.controls-row {
		display: flex;
		gap: var(--space-md);
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
		border: 2px solid rgba(255, 255, 255, 0.3);
		border-top-color: #fff;
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.results-summary {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.summary-detail {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.results-layout {
		height: calc(100vh - 320px);
		min-height: 400px;
		position: relative;
	}

	.pcap-input-row {
		display: flex;
		gap: var(--space-sm);
	}

	.pcap-input-row .input {
		flex: 1;
	}

	.browse-btn {
		white-space: nowrap;
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}

	.btn-spinner-sm {
		display: inline-block;
		width: 12px;
		height: 12px;
		border: 2px solid var(--text-muted);
		border-top-color: var(--text-primary);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	.pcap-picker {
		margin-top: var(--space-xs);
		background: var(--bg-primary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		max-height: 240px;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.pcap-picker-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 12px;
		font-size: var(--text-xs);
		color: var(--text-muted);
		border-bottom: 1px solid var(--border-dim);
	}

	.pcap-picker-close {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: var(--text-sm);
		padding: 0 4px;
	}

	.pcap-picker-close:hover {
		color: var(--text-primary);
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
		padding: 8px 12px;
		background: none;
		border: none;
		border-bottom: 1px solid var(--border-dim);
		color: var(--text-primary);
		cursor: pointer;
		text-align: left;
		font-size: var(--text-sm);
		transition: background-color var(--transition-fast);
	}

	.pcap-picker-item:hover {
		background: var(--bg-tertiary);
	}

	.pcap-picker-item.selected {
		background: var(--bg-tertiary);
		border-left: 3px solid var(--accent);
	}

	.pcap-picker-item:last-child {
		border-bottom: none;
	}

	.pcap-name {
		font-family: var(--font-mono);
		font-weight: 500;
	}

	.pcap-meta {
		font-size: var(--text-xs);
		color: var(--text-muted);
		white-space: nowrap;
		margin-left: var(--space-md);
	}

	.pcap-picker-loading,
	.pcap-picker-empty {
		padding: 16px;
		text-align: center;
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	select.input {
		appearance: auto;
		cursor: pointer;
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
