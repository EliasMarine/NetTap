<!--
  ConnectionDrawer.svelte — Self-contained slide-in drawer for connection
  drill-down. Shows connection details, TShark packet analysis, and
  related activity links. 560px wide, slides from right with backdrop.

  Uses Svelte 5 runes ($props, $state, $derived, $effect).
-->
<script lang="ts">
	import { getField, asString, buildTSharkFilter } from '$lib/utils/tshark-filter';
	import { analyzePcap, getPcapFiles, getTSharkStatus } from '$api/tshark';
	import type { TSharkPacket, PcapFile } from '$api/tshark';

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
	let duration = $derived(() => {
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
	let subtitle = $derived(() => {
		const src = srcIp ? `${srcIp}${srcPort != null ? ':' + srcPort : ''}` : '?';
		const dst = dstIp ? `${dstIp}${dstPort != null ? ':' + dstPort : ''}` : '?';
		return `${src} \u2192 ${dst}`;
	});

	// BPF filter
	let bpfFilter = $derived(connection ? buildBpfFilter(connection) : '');
	let displayFilter = $derived(connection ? buildTSharkFilter(connection) : '');

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
		if (pcapFiles.length === 0) {
			tsharkError = 'No PCAP files available on the appliance.';
			return;
		}
		if (!displayFilter) {
			tsharkError = 'Could not build a display filter from this connection.';
			return;
		}

		analyzing = true;
		tsharkError = '';
		tsharkTextOutput = '';
		packets = [];

		// Sort PCAPs by modification time (most recent first)
		const sorted = [...pcapFiles].sort((a, b) => b.modified - a.modified);
		const pcap = sorted[0];

		const maxPackets = tsharkMode === 'follow' ? 500 : 50;
		const outputFormat = tsharkMode === 'summary' ? 'json' : 'text';

		try {
			const result = await analyzePcap({
				pcap_path: pcap.path,
				display_filter: displayFilter,
				max_packets: maxPackets,
				output_format: outputFormat,
			});

			if (result.error) {
				tsharkError = result.error;
			} else if (outputFormat === 'json') {
				packets = result.packets;
				if (packets.length === 0) {
					tsharkError = 'No matching packets found in the most recent PCAP.';
				}
			} else {
				// Text mode — packets array may contain text representations
				if (result.packets && result.packets.length > 0) {
					tsharkTextOutput = result.packets
						.map((p) => {
							if (typeof p === 'string') return p;
							return p?.raw || p?.text || JSON.stringify(p, null, 2);
						})
						.join('\n');
				} else {
					tsharkError = 'No matching packets found in the most recent PCAP.';
				}
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
			<div class="header-text">
				<h3 class="drawer-title">Connection Detail</h3>
				<p class="drawer-subtitle mono">{subtitle()}</p>
			</div>
			<button class="close-btn" onclick={onclose} aria-label="Close panel">
				<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
				</svg>
			</button>
		</div>

		<!-- ====== Tabs ====== -->
		<div class="drawer-tabs">
			<button class="tab-btn" class:active={activeTab === 'detail'} onclick={() => activeTab = 'detail'}>Detail</button>
			<button class="tab-btn" class:active={activeTab === 'tshark'} onclick={() => activeTab = 'tshark'}>TShark</button>
			<button class="tab-btn" class:active={activeTab === 'related'} onclick={() => activeTab = 'related'}>Related</button>
		</div>

		<!-- ====== Scrollable body ====== -->
		<div class="drawer-body">

			<!-- ======================================= -->
			<!-- Tab 1: Detail                           -->
			<!-- ======================================= -->
			{#if activeTab === 'detail'}
				<div class="detail-tab">
					<!-- Connection info -->
					<section class="section">
						<h4 class="section-title">Connection</h4>
						<div class="kv-grid">
							<span class="kv-label">Source</span>
							<span class="kv-value mono">{srcIp}{srcPort != null ? ':' + srcPort : ''}</span>

							<span class="kv-label">Destination</span>
							<span class="kv-value mono">{dstIp}{dstPort != null ? ':' + dstPort : ''}</span>

							<span class="kv-label">Protocol</span>
							<span class="kv-value">{proto ? proto.toUpperCase() : '--'}{service ? ' / ' + service : ''}</span>

							<span class="kv-label">Duration</span>
							<span class="kv-value mono">{formatDuration(duration())}</span>

							<span class="kv-label">Download</span>
							<span class="kv-value mono">{formatBytes(downloadBytes)}</span>

							<span class="kv-label">Upload</span>
							<span class="kv-value mono">{formatBytes(uploadBytes)}</span>

							<span class="kv-label">Session ID</span>
							<span class="kv-value mono">{sessionId || '--'}</span>

							<span class="kv-label">Community ID</span>
							<span class="kv-value mono">{communityId || '--'}</span>

							<span class="kv-label">Conn State</span>
							<span class="kv-value">
								{#if connState}
									<span class="mono">{connState}</span>
									{#if STATE_DESC[connState]}
										<span class="state-desc">{STATE_DESC[connState]}</span>
									{/if}
								{:else}
									--
								{/if}
							</span>

							<span class="kv-label">History</span>
							<span class="kv-value mono">{history || '--'}</span>
						</div>
					</section>

					<!-- Destination Enrichment -->
					{#if dstAsn || dstCountry}
						<section class="section">
							<h4 class="section-title">Destination Enrichment</h4>
							<div class="kv-grid">
								{#if dstAsn}
									<span class="kv-label">ASN</span>
									<span class="kv-value">{dstAsn}</span>
								{/if}
								{#if dstCountry}
									<span class="kv-label">Country</span>
									<span class="kv-value">{dstCountry}</span>
								{/if}
							</div>
						</section>
					{/if}

					<!-- TLS Details -->
					{#if hasTls}
						<section class="section">
							<h4 class="section-title">TLS Details</h4>
							<div class="kv-grid">
								{#if tlsSni}
									<span class="kv-label">SNI</span>
									<span class="kv-value mono">{tlsSni}</span>
								{/if}
								{#if tlsJa3}
									<span class="kv-label">JA3</span>
									<span class="kv-value mono">{tlsJa3}</span>
								{/if}
								{#if tlsVersion}
									<span class="kv-label">Version</span>
									<span class="kv-value">{tlsVersion}</span>
								{/if}
							</div>
						</section>
					{/if}
				</div>

			<!-- ======================================= -->
			<!-- Tab 2: TShark Analysis                  -->
			<!-- ======================================= -->
			{:else if activeTab === 'tshark'}
				<div class="tshark-tab">
					<!-- BPF filter display -->
					<div class="filter-bar">
						<span class="filter-label">BPF Filter:</span>
						<code class="filter-value">{bpfFilter || '(none)'}</code>
					</div>
					<div class="filter-bar">
						<span class="filter-label">Display Filter:</span>
						<code class="filter-value">{displayFilter || '(none)'}</code>
					</div>

					<!-- Mode buttons + Analyze -->
					<div class="tshark-controls">
						<div class="mode-btns">
							<button
								class="mode-btn"
								class:active={tsharkMode === 'summary'}
								onclick={() => tsharkMode = 'summary'}
							>Summary</button>
							<button
								class="mode-btn"
								class:active={tsharkMode === 'verbose'}
								onclick={() => tsharkMode = 'verbose'}
							>Verbose</button>
							<button
								class="mode-btn"
								class:active={tsharkMode === 'follow'}
								onclick={() => tsharkMode = 'follow'}
							>Follow Stream</button>
						</div>
						<button
							class="btn btn-primary btn-sm analyze-btn"
							onclick={runAnalysis}
							disabled={analyzing || tsharkAvailable === false}
						>
							{analyzing ? 'Analyzing...' : 'Analyze'}
						</button>
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
						<!-- Summary: packet table -->
						<div class="packet-table-wrap">
							<table class="packet-table">
								<thead>
									<tr>
										<th>No.</th>
										<th>Time</th>
										<th>Source</th>
										<th>Destination</th>
										<th>Proto</th>
										<th>Len</th>
									</tr>
								</thead>
								<tbody>
									{#each packets as pkt, i}
										{@const info = getPacketSummary(pkt)}
										<tr class="pkt-row">
											<td class="mono">{info.no}</td>
											<td class="mono">{info.time}</td>
											<td class="mono">{info.src}</td>
											<td class="mono">{info.dst}</td>
											<td>{info.proto}</td>
											<td class="mono">{info.len}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
						<p class="packet-count">{packets.length} packet{packets.length !== 1 ? 's' : ''} matched</p>
					{:else if (tsharkMode === 'verbose' || tsharkMode === 'follow') && tsharkTextOutput}
						<!-- Text output: terminal-style -->
						<div class="terminal-output">{tsharkTextOutput}</div>
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
					<section class="section">
						<h4 class="section-title">Related Activity</h4>
						<p class="related-desc">Explore activity related to this connection's endpoints.</p>

						<div class="related-links">
							{#if dstIp}
								<a href="/connections?ip={encodeURIComponent(dstIp)}" class="related-link">
									<span class="link-icon">
										<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z" />
										</svg>
									</span>
									<span class="link-text">
										<span class="link-title">Other connections to {dstIp}</span>
										<span class="link-hint">View all connections to this destination</span>
									</span>
									<span class="link-arrow">
										<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<polyline points="9 18 15 12 9 6" />
										</svg>
									</span>
								</a>
							{/if}

							{#if deviceIp}
								<a href="/logs?query=dns AND source.ip:{encodeURIComponent(deviceIp)}" class="related-link">
									<span class="link-icon">
										<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
										</svg>
									</span>
									<span class="link-text">
										<span class="link-title">DNS queries for {deviceIp}</span>
										<span class="link-hint">View DNS lookups in Log Explorer</span>
									</span>
									<span class="link-arrow">
										<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<polyline points="9 18 15 12 9 6" />
										</svg>
									</span>
								</a>

								<a href="/alerts?ip={encodeURIComponent(deviceIp)}" class="related-link">
									<span class="link-icon">
										<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
										</svg>
									</span>
									<span class="link-text">
										<span class="link-title">Alerts for {deviceIp}</span>
										<span class="link-hint">View IDS alerts involving this device</span>
									</span>
									<span class="link-arrow">
										<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<polyline points="9 18 15 12 9 6" />
										</svg>
									</span>
								</a>
							{/if}

							{#if srcIp && srcIp !== deviceIp}
								<a href="/devices/{encodeURIComponent(srcIp)}" class="related-link">
									<span class="link-icon">
										<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<rect x="2" y="3" width="20" height="14" rx="2" ry="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
										</svg>
									</span>
									<span class="link-text">
										<span class="link-title">Device: {srcIp}</span>
										<span class="link-hint">View source device detail page</span>
									</span>
									<span class="link-arrow">
										<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
											<polyline points="9 18 15 12 9 6" />
										</svg>
									</span>
								</a>
							{/if}
						</div>
					</section>
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
		background-color: var(--bg-overlay);
		backdrop-filter: blur(2px);
		-webkit-backdrop-filter: blur(2px);
		border: none;
		cursor: pointer;
		animation: backdropIn 200ms ease-out;
	}

	@keyframes backdropIn {
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
		background-color: var(--bg-primary);
		border-left: 1px solid var(--border-default);
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform var(--transition-normal);
		box-shadow: -4px 0 24px rgba(0, 0, 0, 0.4);
	}

	.conn-drawer.open {
		transform: translateX(0);
	}

	/* ================================================================== */
	/* Header                                                             */
	/* ================================================================== */

	.drawer-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-default);
		background-color: var(--bg-secondary);
		flex-shrink: 0;
		gap: var(--space-sm);
	}

	.header-text {
		flex: 1;
		min-width: 0;
	}

	.drawer-title {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
		line-height: 1.3;
	}

	.drawer-subtitle {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: 2px;
		word-break: break-all;
	}

	.close-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		cursor: pointer;
		transition: all var(--transition-fast);
		flex-shrink: 0;
	}

	.close-btn:hover {
		background-color: var(--bg-tertiary);
		color: var(--text-primary);
	}

	/* ================================================================== */
	/* Tabs                                                               */
	/* ================================================================== */

	.drawer-tabs {
		display: flex;
		border-bottom: 1px solid var(--border-default);
		background-color: var(--bg-secondary);
		flex-shrink: 0;
		padding: 0 var(--space-lg);
		gap: 0;
	}

	.tab-btn {
		position: relative;
		padding: var(--space-sm) var(--space-md);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-muted);
		background: none;
		border: none;
		cursor: pointer;
		transition: color var(--transition-fast);
		white-space: nowrap;
	}

	.tab-btn:hover {
		color: var(--text-primary);
	}

	.tab-btn.active {
		color: var(--accent);
	}

	.tab-btn.active::after {
		content: '';
		position: absolute;
		bottom: -1px;
		left: var(--space-md);
		right: var(--space-md);
		height: 2px;
		background-color: var(--accent);
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

	/* ================================================================== */
	/* Detail tab — sections + key-value grid                             */
	/* ================================================================== */

	.section {
		margin-bottom: var(--space-lg);
		padding-bottom: var(--space-lg);
		border-bottom: 1px solid var(--border-dim);
	}

	.section:last-child {
		border-bottom: none;
		margin-bottom: 0;
		padding-bottom: 0;
	}

	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-sm);
	}

	.kv-grid {
		display: grid;
		grid-template-columns: 120px 1fr;
		gap: var(--space-xs) var(--space-md);
		font-size: var(--text-sm);
	}

	.kv-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding-top: 2px;
	}

	.kv-value {
		color: var(--text-primary);
		word-break: break-all;
		line-height: 1.4;
	}

	.state-desc {
		display: block;
		font-size: var(--text-xs);
		color: var(--text-secondary);
		margin-top: 2px;
	}

	/* ================================================================== */
	/* TShark tab                                                         */
	/* ================================================================== */

	.tshark-tab {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	.filter-bar {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.filter-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		white-space: nowrap;
		padding-top: 1px;
	}

	.filter-value {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--accent);
		word-break: break-all;
	}

	.tshark-controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.mode-btns {
		display: flex;
		gap: 0;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.mode-btn {
		padding: var(--space-xs) var(--space-sm);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-secondary);
		background: var(--bg-elevated);
		border: none;
		border-right: 1px solid var(--border-default);
		cursor: pointer;
		transition: all var(--transition-fast);
		white-space: nowrap;
	}

	.mode-btn:last-child {
		border-right: none;
	}

	.mode-btn:hover {
		color: var(--text-primary);
		background: var(--bg-tertiary);
	}

	.mode-btn.active {
		color: var(--accent);
		background: var(--accent-muted);
	}

	.analyze-btn {
		flex-shrink: 0;
	}

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
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Packet table */
	.packet-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.packet-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-xs);
	}

	.packet-table th {
		padding: var(--space-xs) var(--space-sm);
		text-align: left;
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		background-color: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-default);
		white-space: nowrap;
	}

	.packet-table td {
		padding: var(--space-xs) var(--space-sm);
		border-bottom: 1px solid var(--border-dim);
		color: var(--text-primary);
		white-space: nowrap;
	}

	.pkt-row {
		transition: background-color var(--transition-fast);
	}

	.pkt-row:hover {
		background-color: var(--bg-tertiary);
	}

	.packet-count {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-align: right;
	}

	/* Terminal output */
	.terminal-output {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--green);
		background-color: var(--bg-void);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		overflow-x: auto;
		overflow-y: auto;
		max-height: 500px;
		white-space: pre-wrap;
		word-break: break-all;
		line-height: 1.5;
	}

	/* ================================================================== */
	/* Related tab                                                        */
	/* ================================================================== */

	.related-desc {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		margin-bottom: var(--space-md);
	}

	.related-links {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.related-link {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		text-decoration: none;
		transition: all var(--transition-fast);
	}

	.related-link:hover {
		border-color: var(--border-bright);
		background-color: var(--bg-tertiary);
	}

	.link-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-sm);
		background-color: var(--accent-muted);
		color: var(--accent);
		flex-shrink: 0;
	}

	.link-text {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.link-title {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.link-hint {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.link-arrow {
		color: var(--text-dim);
		flex-shrink: 0;
		transition: color var(--transition-fast);
	}

	.related-link:hover .link-arrow {
		color: var(--accent);
	}

	/* ================================================================== */
	/* Shared utility classes (scoped)                                    */
	/* ================================================================== */

	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}

	/* ================================================================== */
	/* Button classes matching global design system                       */
	/* ================================================================== */

	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-sm);
		padding: 6px var(--space-md);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		background-color: var(--bg-elevated);
		color: var(--text-primary);
		cursor: pointer;
		transition: all var(--transition-fast);
		line-height: 1.4;
		white-space: nowrap;
	}

	.btn:hover {
		background-color: var(--border-default);
	}

	.btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.btn-primary {
		background-color: var(--accent);
		border-color: var(--accent);
		color: #000;
		font-weight: 600;
	}

	.btn-primary:hover {
		background-color: var(--accent-hover);
		border-color: var(--accent-hover);
	}

	.btn-sm {
		padding: 3px 8px;
		font-size: var(--text-xs);
	}

	/* ================================================================== */
	/* Responsive                                                         */
	/* ================================================================== */

	@media (max-width: 640px) {
		.conn-drawer {
			width: 100vw;
		}
	}
</style>
