<!--
  ConnectionDrawer.svelte — Self-contained slide-in drawer for connection
  drill-down. Shows connection details, TShark packet analysis, and
  related activity links. 560px wide, slides from right with backdrop.

  Uses Svelte 5 runes ($props, $state, $derived, $effect).
-->
<script lang="ts">
	import { getField, asString, buildTSharkFilter } from '$lib/utils/tshark-filter';
	import { getPcapFiles, getTSharkStatus } from '$api/tshark';
	import type { TSharkPacket, PcapFile } from '$api/tshark';
	import { analyzeConnection } from '$lib/utils/tshark-analyze';

	// ---------------------------------------------------------------------------
	// Props
	// ---------------------------------------------------------------------------

	let {
		connection = null,
		deviceIp = '',
		onclose = () => {},
	}: {
		connection: Record<string, unknown> | null;
		deviceIp: string;
		onclose: () => void;
	} = $props();

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	type TabId = 'detail' | 'tshark' | 'related';

	let activeTab = $state<TabId>('detail');

	// TShark state
	let tsharkAvailable = $state<boolean | null>(null);
	let tsharkChecked = $state(false);
	let pcapFiles = $state<PcapFile[]>([]);
	let pcapLoading = $state(false);
	let packets = $state<TSharkPacket[]>([]);
	let analyzing = $state(false);
	let tsharkError = $state('');
	let tsharkMode = $state<'summary' | 'verbose' | 'follow'>('summary');
	let tsharkTextOutput = $state('');
	let tsharkTabLoaded = $state(false);

	// ---------------------------------------------------------------------------
	// Derived — connection fields from raw ECS object
	// ---------------------------------------------------------------------------

	let isOpen = $derived(connection != null);

	let srcIp = $derived(connection ? asString(getField(connection, 'source.ip')) : '');
	let srcPort = $derived(connection ? getField(connection, 'source.port') : null);
	let dstIp = $derived(connection ? asString(getField(connection, 'destination.ip')) : '');
	let dstPort = $derived(connection ? getField(connection, 'destination.port') : null);
	let proto = $derived(connection ? asString(getField(connection, 'network.transport')) : '');
	let service = $derived(
		connection
			? asString(getField(connection, 'network.protocol') || getField(connection, 'zeek.conn.service'))
			: ''
	);

	// Duration: computed from event.start / event.end, fallback to zeek.conn.duration
	let duration = $derived.by(() => {
		if (!connection) return null;
		const start = asString(getField(connection, 'event.start'));
		const end = asString(getField(connection, 'event.end'));
		if (start && end) {
			const ms = new Date(end).getTime() - new Date(start).getTime();
			if (!isNaN(ms)) return ms / 1000;
		}
		const zeekDur = getField(connection, 'zeek.conn.duration') || getField(connection, 'event.duration');
		if (zeekDur != null) return Number(zeekDur);
		return null;
	});

	let downloadBytes = $derived(
		connection
			? getField(connection, 'destination.bytes') || getField(connection, 'server.bytes') || getField(connection, 'zeek.conn.resp_bytes')
			: null
	);
	let uploadBytes = $derived(
		connection
			? getField(connection, 'source.bytes') || getField(connection, 'client.bytes') || getField(connection, 'zeek.conn.orig_bytes')
			: null
	);

	let sessionId = $derived(
		connection
			? asString(getField(connection, 'zeek.session_id') || getField(connection, 'zeek.conn.uid') || getField(connection, 'zeek.uid'))
			: ''
	);
	let communityId = $derived(
		connection
			? asString(getField(connection, 'network.community_id') || getField(connection, 'zeek.conn.community_id'))
			: ''
	);
	let connState = $derived(
		connection ? asString(getField(connection, 'zeek.conn.conn_state') || getField(connection, 'zeek.conn.state')) : ''
	);
	let history = $derived(
		connection ? asString(getField(connection, 'zeek.conn.history')) : ''
	);

	// Destination enrichment
	let dstAsn = $derived(connection ? asString(getField(connection, 'destination.as.full')) : '');
	let dstCountry = $derived(connection ? asString(getField(connection, 'destination.geo.country_name')) : '');

	// TLS details
	let tlsSni = $derived(
		connection
			? asString(
					getField(connection, 'tls.client.server_name') ||
					getField(connection, 'zeek.ssl.server_name')
				)
			: ''
	);
	let tlsJa3 = $derived(connection ? asString(getField(connection, 'zeek.ssl.ja3')) : '');
	let tlsVersion = $derived(connection ? asString(getField(connection, 'tls.version')) : '');
	let hasTls = $derived(tlsSni !== '' || tlsJa3 !== '' || tlsVersion !== '');

	// Subtitle for header
	let subtitle = $derived.by(() => {
		const src = srcIp ? `${srcIp}${srcPort != null ? ':' + srcPort : ''}` : '?';
		const dst = dstIp ? `${dstIp}${dstPort != null ? ':' + dstPort : ''}` : '?';
		return `${src} \u2192 ${dst}`;
	});

	// Timestamp
	let timestamp = $derived(connection ? asString(getField(connection, '@timestamp')) : '');

	// BPF filter
	let bpfFilter = $derived(connection ? buildBpfFilter(connection) : '');
	let displayFilter = $derived(connection ? buildTSharkFilter(connection) : '');

	// TShark tool URL
	let tsharkToolUrl = $derived.by(() => {
		const params = new URLSearchParams({ auto: '1' });
		if (displayFilter) params.set('filter', displayFilter);
		if (timestamp) params.set('ts', timestamp);
		return `/tools/tshark?${params}`;
	});

	// Connection state descriptions
	const STATE_DESC: Record<string, string> = {
		S0: 'Connection attempt seen, no reply',
		S1: 'Connection established, not terminated',
		SF: 'Normal establishment and termination',
		REJ: 'Connection attempt rejected',
		S2: 'Established, close attempted by originator',
		S3: 'Established, close attempted by responder',
		RSTO: 'Established, originator aborted',
		RSTR: 'Established, responder aborted',
		RSTOS0: 'Originator sent SYN then RST, no reply',
		RSTRH: 'Responder sent SYN ACK then RST, no reply',
		SH: 'Originator sent SYN then FIN, no reply (half-open)',
		SHR: 'Responder sent SYN ACK then FIN, no reply',
		OTH: 'No SYN seen, midstream traffic',
	};

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function asStringVal(val: unknown): string {
		if (Array.isArray(val)) return String(val[0] ?? '');
		if (val == null) return '';
		return String(val);
	}

	function buildBpfFilter(conn: Record<string, unknown>): string {
		const sIp = asString(getField(conn, 'source.ip'));
		const dIp = asString(getField(conn, 'destination.ip'));
		const dPort = getField(conn, 'destination.port');
		const p = asString(getField(conn, 'network.transport'));
		const parts: string[] = [];
		if (sIp) parts.push(`host ${sIp}`);
		if (dIp) parts.push(`host ${dIp}`);
		if (dPort) parts.push(`port ${asStringVal(dPort)}`);
		if (p) parts.push(p.toLowerCase());
		return parts.join(' and ');
	}

	function formatDuration(val: unknown): string {
		if (val == null) return '--';
		const n = Number(val);
		if (isNaN(n)) return String(val);
		if (n < 0.001) return `${(n * 1_000_000).toFixed(0)}\u00b5s`;
		if (n < 1) return `${(n * 1000).toFixed(0)}ms`;
		if (n < 60) return `${n.toFixed(1)}s`;
		if (n < 3600) return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`;
		return `${Math.floor(n / 3600)}h ${Math.floor((n % 3600) / 60)}m`;
	}

	function formatBytes(val: unknown): string {
		if (val == null) return '--';
		const n = Number(val);
		if (isNaN(n)) return String(val);
		if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`;
		if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
		if (n >= 1_024) return `${(n / 1_024).toFixed(1)} KB`;
		return `${n} B`;
	}

	// ---------------------------------------------------------------------------
	// Tab switching + TShark logic
	// ---------------------------------------------------------------------------

	// Reset tab when connection changes
	$effect(() => {
		if (connection) {
			activeTab = 'detail';
			tsharkTabLoaded = false;
			packets = [];
			tsharkError = '';
			tsharkTextOutput = '';
			tsharkMode = 'summary';
		}
	});

	// Load TShark tab on first activation
	$effect(() => {
		if (activeTab === 'tshark' && !tsharkTabLoaded && connection) {
			tsharkTabLoaded = true;
			loadTSharkTab();
		}
	});

	async function loadTSharkTab() {
		// Check availability
		if (!tsharkChecked) {
			tsharkChecked = true;
			try {
				const status = await getTSharkStatus();
				tsharkAvailable = status.available;
			} catch {
				tsharkAvailable = false;
			}
		}

		// Load PCAP files
		if (tsharkAvailable) {
			pcapLoading = true;
			try {
				const result = await getPcapFiles();
				pcapFiles = result.pcaps || [];
			} catch {
				tsharkError = 'Failed to load PCAP files';
			} finally {
				pcapLoading = false;
			}
		}
	}

	async function runAnalysis() {
		analyzing = true;
		tsharkError = '';
		tsharkTextOutput = '';
		packets = [];

		try {
			const result = await analyzeConnection({
				pcapFiles,
				displayFilter,
				timestamp,
				mode: tsharkMode,
				proto: proto || 'tcp',
				maxAttempts: 5,
			});

			if (result.error) {
				tsharkError = result.error;
			} else if (tsharkMode === 'summary') {
				packets = result.packets;
			} else {
				tsharkTextOutput = result.textOutput;
			}
		} catch (err) {
			tsharkError = `Analysis failed: ${err instanceof Error ? err.message : 'Unknown error'}`;
		} finally {
			analyzing = false;
		}
	}

	function getPacketSummary(pkt: TSharkPacket): { no: string; time: string; src: string; dst: string; proto: string; len: string; info: string } {
		const layers = pkt?.['_source']?.['layers'] || pkt;
		const frame = layers?.['frame'] || {};
		const ip = layers?.['ip'] || layers?.['ipv6'] || {};
		return {
			no: frame['frame.number'] || '?',
			time: frame['frame.time_relative'] || frame['frame.time'] || '?',
			src: ip['ip.src'] || ip['ipv6.src'] || '?',
			dst: ip['ip.dst'] || ip['ipv6.dst'] || '?',
			proto: frame['frame.protocols']?.split(':').pop() || '?',
			len: frame['frame.len'] || '?',
			info: pkt?.['_source']?.['layers']?.['_ws.col']?.['_ws.col.Info'] || '',
		};
	}

	// ---------------------------------------------------------------------------
	// Keyboard handler
	// ---------------------------------------------------------------------------

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && isOpen) {
			onclose();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop -->
{#if isOpen}
	<button
		class="drawer-backdrop"
		onclick={onclose}
		aria-label="Close connection detail"
		tabindex="-1"
	></button>
{/if}

<!-- Drawer panel -->
<aside class="conn-drawer" class:open={isOpen} aria-label="Connection detail panel">
	{#if isOpen && connection}
		<!-- ====== Header ====== -->
		<div class="drawer-header">
			<div class="drawer-title-area">
				<span class="drawer-title">Connection Detail</span>
				<span class="drawer-subtitle">{subtitle}</span>
			</div>
			<button class="drawer-close" onclick={onclose} aria-label="Close panel">&times;</button>
		</div>

		<!-- ====== Tabs ====== -->
		<div class="drawer-tabs">
			<button class="drawer-tab" class:active={activeTab === 'detail'} onclick={() => activeTab = 'detail'}>Detail</button>
			<button class="drawer-tab" class:active={activeTab === 'tshark'} onclick={() => activeTab = 'tshark'}>TShark Analysis</button>
			<button class="drawer-tab" class:active={activeTab === 'related'} onclick={() => activeTab = 'related'}>Related Activity</button>
		</div>

		<!-- ====== Scrollable body ====== -->
		<div class="drawer-body">

			<!-- ======================================= -->
			<!-- Tab 1: Detail                           -->
			<!-- ======================================= -->
			{#if activeTab === 'detail'}
				<div class="detail-tab">
					<!-- Connection info — 2-column grid -->
					<div class="detail-grid">
						<div class="detail-item">
							<span class="detail-label">Source</span>
							<span class="detail-value">{srcIp}{srcPort != null ? ':' + srcPort : ''}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Destination</span>
							<span class="detail-value">{dstIp}{dstPort != null ? ':' + dstPort : ''}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Protocol</span>
							<span class="detail-value">{proto ? proto.toUpperCase() : '--'}{service ? ' / ' + service : ''}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Duration</span>
							<span class="detail-value">{formatDuration(duration)}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Download</span>
							<span class="detail-value detail-value--download">{formatBytes(downloadBytes)}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Upload</span>
							<span class="detail-value detail-value--upload">{formatBytes(uploadBytes)}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Session ID</span>
							<span class="detail-value">{sessionId || '--'}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Community ID</span>
							<span class="detail-value">{communityId || '--'}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Conn State</span>
							<span class="detail-value">
								{#if connState}
									{connState}{#if STATE_DESC[connState]} ({STATE_DESC[connState].split(',')[0]}){/if}
								{:else}
									--
								{/if}
							</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">History</span>
							<span class="detail-value">{history || '--'}</span>
						</div>
					</div>

					<!-- Destination Enrichment -->
					{#if dstAsn || dstCountry}
						<div class="detail-section-title">Destination Enrichment</div>
						<div class="detail-grid">
							{#if dstAsn}
								<div class="detail-item">
									<span class="detail-label">ASN</span>
									<span class="detail-value">{dstAsn}</span>
								</div>
							{/if}
							{#if dstCountry}
								<div class="detail-item">
									<span class="detail-label">Country</span>
									<span class="detail-value">{dstCountry}</span>
								</div>
							{/if}
						</div>
					{/if}

					<!-- TLS Details -->
					{#if hasTls}
						<div class="detail-section-title">TLS Details</div>
						<div class="detail-grid">
							{#if tlsVersion}
								<div class="detail-item">
									<span class="detail-label">TLS Version</span>
									<span class="detail-value">{tlsVersion}</span>
								</div>
							{/if}
							{#if tlsSni}
								<div class="detail-item">
									<span class="detail-label">SNI</span>
									<span class="detail-value">{tlsSni}</span>
								</div>
							{/if}
							{#if tlsJa3}
								<div class="detail-item">
									<span class="detail-label">JA3</span>
									<span class="detail-value detail-value--small">{tlsJa3}</span>
								</div>
							{/if}
						</div>
					{/if}
				</div>

			<!-- ======================================= -->
			<!-- Tab 2: TShark Analysis                  -->
			<!-- ======================================= -->
			{:else if activeTab === 'tshark'}
				<div class="tshark-tab">
					<!-- BPF filter display box -->
					<div class="tshark-filter-label">Auto-Generated BPF Filter</div>
					<div class="tshark-filter">{bpfFilter || '(none)'}</div>

					{#if displayFilter && displayFilter !== bpfFilter}
						<div class="tshark-filter-label">Display Filter</div>
						<div class="tshark-filter">{displayFilter}</div>
					{/if}

					<!-- Mode buttons + Analyze -->
					<div class="tshark-controls">
						<button
							class="tshark-btn tshark-btn-primary"
							onclick={runAnalysis}
							disabled={analyzing || tsharkAvailable === false}
						>
							{analyzing ? 'Analyzing...' : '\u25B6 Analyze'}
						</button>
						<button
							class="tshark-btn tshark-btn-secondary"
							class:active={tsharkMode === 'summary'}
							onclick={() => tsharkMode = 'summary'}
						>Summary</button>
						<button
							class="tshark-btn tshark-btn-secondary"
							class:active={tsharkMode === 'verbose'}
							onclick={() => tsharkMode = 'verbose'}
						>Verbose (-V)</button>
						<button
							class="tshark-btn tshark-btn-secondary"
							class:active={tsharkMode === 'follow'}
							onclick={() => tsharkMode = 'follow'}
						>Follow Stream</button>
						<a href={tsharkToolUrl} class="tshark-btn tshark-btn-secondary">Open in TShark Tool &rarr;</a>
					</div>

					<!-- Status / output -->
					{#if tsharkAvailable === false}
						<div class="tshark-status">
							<p class="status-text">TShark is not available.</p>
							<p class="status-hint">The TShark container is not running or not configured.</p>
						</div>
					{:else if tsharkAvailable === null && !tsharkChecked}
						<div class="tshark-status">
							<div class="spinner"></div>
							<p class="status-text">Checking TShark availability...</p>
						</div>
					{:else if pcapLoading}
						<div class="tshark-status">
							<div class="spinner"></div>
							<p class="status-text">Loading PCAP files...</p>
						</div>
					{:else if analyzing}
						<div class="tshark-status">
							<div class="spinner"></div>
							<p class="status-text">Analyzing packets...</p>
						</div>
					{:else if tsharkError}
						<div class="tshark-status">
							<p class="status-text error">{tsharkError}</p>
						</div>
					{:else if tsharkMode === 'summary' && packets.length > 0}
						<!-- Summary: terminal-style colored output -->
						<div class="tshark-terminal">
							{#each packets as pkt, i}
								{@const info = getPacketSummary(pkt)}
								<div class="tshark-line"><span class="tshark-line-no">{String(i + 1).padStart(3, ' ')} </span><span class="tshark-timestamp">{info.time}</span> <span class="tshark-src">{info.src}</span> <span class="tshark-arrow">&rarr;</span> <span class="tshark-dst">{info.dst}</span>  <span class="tshark-proto">{info.proto}</span>  <span class="tshark-info">{info.info || `Len=${info.len}`}</span></div>
							{/each}
						</div>
						<p class="packet-count">{packets.length} packet{packets.length !== 1 ? 's' : ''} matched</p>
					{:else if (tsharkMode === 'verbose' || tsharkMode === 'follow') && tsharkTextOutput}
						<!-- Text output: terminal-style -->
						<div class="tshark-terminal">{tsharkTextOutput}</div>
					{:else if !analyzing && tsharkAvailable && pcapFiles.length > 0}
						<div class="tshark-status">
							<p class="status-text">Click "Analyze" to inspect packets for this connection.</p>
							<p class="status-hint">{pcapFiles.length} PCAP file{pcapFiles.length !== 1 ? 's' : ''} available.</p>
						</div>
					{:else if !analyzing && tsharkAvailable && pcapFiles.length === 0}
						<div class="tshark-status">
							<p class="status-text">No PCAP files available on the appliance.</p>
						</div>
					{/if}
				</div>

			<!-- ======================================= -->
			<!-- Tab 3: Related Activity                 -->
			<!-- ======================================= -->
			{:else if activeTab === 'related'}
				<div class="related-tab">
					<div class="detail-section-title">Related Activity</div>

					<div class="related-list">
						{#if dstIp}
							<a href="/connections?ip={encodeURIComponent(dstIp)}" class="related-item">
								<span class="related-type rt-conn">CONN</span>
								<span class="related-text">Other connections to {dstIp}</span>
								<span class="related-arrow">&rsaquo;</span>
							</a>
						{/if}

						{#if deviceIp}
							<a href="/logs?filter={encodeURIComponent(deviceIp)}" class="related-item">
								<span class="related-type rt-dns">DNS</span>
								<span class="related-text">DNS queries for {deviceIp}</span>
								<span class="related-arrow">&rsaquo;</span>
							</a>

							<a href="/alerts?ip={encodeURIComponent(deviceIp)}" class="related-item">
								<span class="related-type rt-alert">ALERT</span>
								<span class="related-text">Alerts for {deviceIp}</span>
								<span class="related-arrow">&rsaquo;</span>
							</a>
						{/if}

						{#if srcIp && srcIp !== deviceIp}
							<a href="/devices/{encodeURIComponent(srcIp)}" class="related-item">
								<span class="related-type rt-conn">CONN</span>
								<span class="related-text">Device: {srcIp}</span>
								<span class="related-arrow">&rsaquo;</span>
							</a>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</aside>

<style>
	/* ================================================================== */
	/* Backdrop                                                           */
	/* ================================================================== */

	.drawer-backdrop {
		position: fixed;
		inset: 0;
		z-index: 998;
		background: rgba(0, 0, 0, 0.5);
		backdrop-filter: blur(4px);
		-webkit-backdrop-filter: blur(4px);
		border: none;
		cursor: pointer;
		animation: fadeIn 0.2s ease;
	}

	@keyframes fadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	/* ================================================================== */
	/* Drawer panel                                                       */
	/* ================================================================== */

	.conn-drawer {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: 560px;
		max-width: 100vw;
		z-index: 999;
		background: var(--bg-primary);
		border-left: 1px solid var(--border-dim);
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform 0.25s ease;
		box-shadow: -8px 0 32px rgba(0, 0, 0, 0.5);
	}

	.conn-drawer.open {
		transform: translateX(0);
	}

	/* ================================================================== */
	/* Header                                                             */
	/* ================================================================== */

	.drawer-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
		background: var(--bg-secondary);
		flex-shrink: 0;
	}

	.drawer-title-area {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.drawer-title {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
	}

	.drawer-subtitle {
		font-size: var(--text-xs);
		color: var(--text-muted);
		font-family: var(--font-mono);
		word-break: break-all;
	}

	.drawer-close {
		width: 32px;
		height: 32px;
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--text-muted);
		font-size: 18px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all var(--transition-fast);
		flex-shrink: 0;
	}

	.drawer-close:hover {
		border-color: var(--border-bright);
		color: var(--text-primary);
	}

	/* ================================================================== */
	/* Tabs                                                               */
	/* ================================================================== */

	.drawer-tabs {
		display: flex;
		background: var(--bg-secondary);
		border-bottom: 1px solid var(--border-dim);
		flex-shrink: 0;
	}

	.drawer-tab {
		padding: var(--space-sm) var(--space-lg);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-muted);
		background: none;
		border: none;
		cursor: pointer;
		position: relative;
		transition: color var(--transition-fast);
		white-space: nowrap;
	}

	.drawer-tab:hover {
		color: var(--text-secondary);
	}

	.drawer-tab.active {
		color: var(--cyan);
	}

	.drawer-tab.active::after {
		content: '';
		position: absolute;
		bottom: 0;
		left: var(--space-lg);
		right: var(--space-lg);
		height: 2px;
		background: var(--cyan);
		border-radius: 1px;
	}

	/* ================================================================== */
	/* Scrollable body                                                    */
	/* ================================================================== */

	.drawer-body {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-lg);
	}

	.drawer-body::-webkit-scrollbar { width: 6px; }
	.drawer-body::-webkit-scrollbar-track { background: transparent; }
	.drawer-body::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 3px; }

	/* ================================================================== */
	/* Detail tab — 2-column grid layout                                  */
	/* ================================================================== */

	.detail-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-sm) var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.detail-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.detail-label {
		font-size: 10px;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-weight: 500;
	}

	.detail-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-family: var(--font-mono);
		word-break: break-all;
	}

	.detail-value--download {
		color: var(--cyan);
	}

	.detail-value--upload {
		color: var(--purple);
	}

	.detail-value--small {
		font-size: 10px;
	}

	.detail-section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-muted);
		margin-bottom: var(--space-sm);
		margin-top: var(--space-lg);
		padding-bottom: var(--space-xs);
		border-bottom: 1px solid var(--border-dim);
	}

	/* ================================================================== */
	/* TShark tab                                                         */
	/* ================================================================== */

	.tshark-tab {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	/* Filter display box */
	.tshark-filter-label {
		font-size: 10px;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin-bottom: 4px;
		font-weight: 500;
	}

	.tshark-filter {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: var(--space-sm) var(--space-md);
		background: var(--bg-tertiary);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-sm);
		color: var(--cyan);
		margin-bottom: var(--space-md);
		word-break: break-all;
	}

	/* TShark control buttons */
	.tshark-controls {
		display: flex;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
		flex-wrap: wrap;
	}

	.tshark-btn {
		padding: 6px 14px;
		border-radius: var(--radius-sm);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 600;
		cursor: pointer;
		transition: all var(--transition-fast);
		border: 1px solid;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		white-space: nowrap;
	}

	.tshark-btn-primary {
		background: var(--cyan);
		color: var(--bg-void);
		border-color: var(--cyan);
	}

	.tshark-btn-primary:hover {
		box-shadow: 0 0 12px rgba(0, 212, 255, 0.3);
	}

	.tshark-btn-primary:disabled {
		opacity: 0.4;
		cursor: not-allowed;
		box-shadow: none;
	}

	.tshark-btn-secondary {
		background: transparent;
		color: var(--text-secondary);
		border-color: var(--border-default);
	}

	.tshark-btn-secondary:hover {
		border-color: var(--border-bright);
		color: var(--text-primary);
	}

	.tshark-btn-secondary.active {
		border-color: var(--cyan);
		color: var(--cyan);
		background: var(--cyan-dim);
	}

	/* TShark status messages */
	.tshark-status {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xl) 0;
		text-align: center;
	}

	.status-text {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	.status-text.error {
		color: var(--red);
	}

	.status-hint {
		font-size: var(--text-xs);
		color: var(--text-dim);
	}

	.spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--border-default);
		border-top-color: var(--cyan);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Terminal output — matches mockup exactly */
	.tshark-terminal {
		background: var(--bg-void);
		border: 1px solid var(--border-dim);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		font-family: var(--font-mono);
		font-size: 11px;
		line-height: 1.7;
		color: var(--text-secondary);
		max-height: 400px;
		overflow: auto;
		white-space: pre;
		tab-size: 4;
	}

	.tshark-terminal::-webkit-scrollbar { width: 6px; height: 6px; }
	.tshark-terminal::-webkit-scrollbar-track { background: transparent; }
	.tshark-terminal::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 3px; }

	/* Terminal line color coding */
	.tshark-line {
		display: block;
	}

	.tshark-line-no {
		color: var(--text-dim);
		user-select: none;
	}

	.tshark-timestamp {
		color: var(--text-muted);
	}

	.tshark-src {
		color: var(--cyan);
	}

	.tshark-dst {
		color: var(--purple);
	}

	.tshark-proto {
		color: var(--amber);
		font-weight: 600;
	}

	.tshark-info {
		color: var(--text-secondary);
	}

	.tshark-arrow {
		color: var(--text-dim);
	}

	.packet-count {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
		margin-top: var(--space-xs);
	}

	/* ================================================================== */
	/* Related tab — badge-based list                                     */
	/* ================================================================== */

	.related-list {
		display: flex;
		flex-direction: column;
	}

	.related-item {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-dim);
		font-size: var(--text-sm);
		text-decoration: none;
		color: var(--text-secondary);
		transition: color var(--transition-fast);
	}

	.related-item:last-child {
		border-bottom: none;
	}

	.related-item:hover {
		color: var(--text-primary);
	}

	.related-type {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		min-width: 40px;
		text-align: center;
		flex-shrink: 0;
	}

	.rt-conn {
		background: var(--cyan-dim);
		color: var(--cyan);
	}

	.rt-dns {
		background: var(--purple-dim);
		color: var(--purple);
	}

	.rt-alert {
		background: var(--red-dim);
		color: var(--red);
	}

	.related-text {
		flex: 1;
		color: inherit;
	}

	.related-arrow {
		color: var(--text-dim);
		font-size: var(--text-lg);
		flex-shrink: 0;
		transition: color var(--transition-fast);
	}

	.related-item:hover .related-arrow {
		color: var(--cyan);
	}

	/* ================================================================== */
	/* Responsive                                                         */
	/* ================================================================== */

	@media (max-width: 640px) {
		.conn-drawer {
			width: 100vw;
		}

		.detail-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
