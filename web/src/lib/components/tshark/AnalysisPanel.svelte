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
	import PacketTable from './PacketTable.svelte';
	import ProtocolTree from './ProtocolTree.svelte';
	import {
		analyzePcap,
		getTSharkStatus,
		type TSharkAnalyzeResponse,
		type TSharkStatus,
	} from '$api/tshark';

	// ---- State ----
	let pcapPath = $state('');
	let displayFilter = $state('');
	let maxPackets = $state(100);
	let outputFormat = $state<'json' | 'text'>('json');

	let loading = $state(false);
	let result = $state<TSharkAnalyzeResponse | null>(null);
	let errorMessage = $state('');

	let selectedPacketIndex = $state(-1);
	let selectedPacket = $derived(
		result && selectedPacketIndex >= 0 ? result.packets[selectedPacketIndex] ?? null : null
	);

	let status = $state<TSharkStatus | null>(null);
	let statusLoading = $state(true);

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
				<input
					id="pcap-path"
					type="text"
					class="input mono-input"
					placeholder="/opt/nettap/pcap/capture.pcap"
					bind:value={pcapPath}
					onkeydown={handleAnalyzeKeydown}
					disabled={loading}
				/>
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

	<!-- Split view: packet table + protocol tree -->
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
		display: grid;
		grid-template-columns: 1fr 380px;
		gap: var(--space-md);
		min-height: 300px;
	}

	.results-table-section {
		min-width: 0;
	}

	.results-detail-section {
		min-width: 0;
	}

	select.input {
		appearance: auto;
		cursor: pointer;
	}

	@media (max-width: 1024px) {
		.results-layout {
			grid-template-columns: 1fr;
		}
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
