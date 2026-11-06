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
	import { connectionDurationMs } from '$lib/utils/connection-duration';
	import { unwrap, getPacketSummary, formatDuration, formatBytes, CONN_STATE_DESC } from '$lib/utils/tshark-helpers';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { domainHref, ipHref, isLan } from '$lib/stores/lan';

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
	// OLD CODE START — #144: epoch-ms event.start/end read as Invalid Date, and the fallback read
	// event.duration's nanoseconds as seconds
	// let duration = $derived.by(() => {
	// 	if (!connection) return null;
	// 	const start = asString(getField(connection, 'event.start'));
	// 	const end = asString(getField(connection, 'event.end'));
	// 	if (start && end) {
	// 		const ms = new Date(end).getTime() - new Date(start).getTime();
	// 		if (!isNaN(ms)) return ms / 1000;
	// 	}
	// 	const zeekDur = getField(connection, 'zeek.conn.duration') || getField(connection, 'event.duration');
	// 	if (zeekDur != null) return Number(zeekDur);
	// 	return null;
	// });
	// OLD CODE END
	let duration = $derived.by(() => {
		const ms = connection ? connectionDurationMs(connection) : null;
		return ms === null ? null : ms / 1000;
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

	// OLD CODE START — STATE_DESC moved to CONN_STATE_DESC in $lib/utils/tshark-helpers.ts
	// const STATE_DESC: Record<string, string> = {
	// 	S0: 'Connection attempt seen, no reply',
	// 	S1: 'Connection established, not terminated',
	// 	SF: 'Normal establishment and termination',
	// 	REJ: 'Connection attempt rejected',
	// 	S2: 'Established, close attempted by originator',
	// 	S3: 'Established, close attempted by responder',
	// 	RSTO: 'Established, originator aborted',
	// 	RSTR: 'Established, responder aborted',
	// 	RSTOS0: 'Originator sent SYN then RST, no reply',
	// 	RSTRH: 'Responder sent SYN ACK then RST, no reply',
	// 	SH: 'Originator sent SYN then FIN, no reply (half-open)',
	// 	SHR: 'Responder sent SYN ACK then FIN, no reply',
	// 	OTH: 'No SYN seen, midstream traffic',
	// };
	// OLD CODE END

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

	// OLD CODE START — formatDuration/formatBytes moved to $lib/utils/tshark-helpers.ts
	// function formatDuration(val: unknown): string {
	// 	if (val == null) return '--';
	// 	const n = Number(val);
	// 	if (isNaN(n)) return String(val);
	// 	if (n < 0.001) return `${(n * 1_000_000).toFixed(0)}\u00b5s`;
	// 	if (n < 1) return `${(n * 1000).toFixed(0)}ms`;
	// 	if (n < 60) return `${n.toFixed(1)}s`;
	// 	if (n < 3600) return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`;
	// 	return `${Math.floor(n / 3600)}h ${Math.floor((n % 3600) / 60)}m`;
	// }
	//
	// function formatBytes(val: unknown): string {
	// 	if (val == null) return '--';
	// 	const n = Number(val);
	// 	if (isNaN(n)) return String(val);
	// 	if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`;
	// 	if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
	// 	if (n >= 1_024) return `${(n / 1_024).toFixed(1)} KB`;
	// 	return `${n} B`;
	// }
	// OLD CODE END

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
		// OLD CODE START — #96: checked once ever, so a failed check was never retried
		// if (!tsharkChecked) {
		// OLD CODE END
		if (tsharkAvailable === null) {
			tsharkChecked = true;
			try {
				const status = await getTSharkStatus();
				tsharkAvailable = status.available;
			} catch {
				// OLD CODE START — #96: a failed check read as "TShark is not available"
				// tsharkAvailable = false;
				// OLD CODE END
				tsharkError = "Couldn't check whether TShark is available: the request failed.";
			}
		}

		// Load PCAP files and auto-run analysis
		if (tsharkAvailable) {
			pcapLoading = true;
			try {
				const result = await getPcapFiles();
				pcapFiles = result.pcaps || [];
				if (pcapFiles.length > 0) runAnalysis();
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

	// OLD CODE START — unwrap/getPacketSummary moved to $lib/utils/tshark-helpers.ts
	// /** Unwrap TShark -T json array-wrapped values (e.g. ["1"] -> "1") */
	// function unwrap(val: unknown): string {
	// 	if (Array.isArray(val)) return String(val[0] ?? '');
	// 	if (val == null) return '';
	// 	return String(val);
	// }
	//
	// function getPacketSummary(pkt: TSharkPacket): { no: string; time: string; src: string; dst: string; proto: string; len: string; info: string } {
	// 	const layers = pkt?.['_source']?.['layers'] || pkt;
	// 	const frame = layers?.['frame'] || {};
	// 	const ip = layers?.['ip'] || layers?.['ipv6'] || {};
	// 	const protocols = unwrap(frame['frame.protocols']);
	// 	return {
	// 		no: unwrap(frame['frame.number']) || '?',
	// 		time: unwrap(frame['frame.time_relative']) || unwrap(frame['frame.time']) || '?',
	// 		src: unwrap(ip['ip.src']) || unwrap(ip['ipv6.src']) || '?',
	// 		dst: unwrap(ip['ip.dst']) || unwrap(ip['ipv6.dst']) || '?',
	// 		proto: protocols.split(':').pop() || '?',
	// 		len: unwrap(frame['frame.len']) || '?',
	// 		info: unwrap(pkt?.['_source']?.['layers']?.['_ws.col']?.['_ws.col.Info']) || '',
	// 	};
	// }
	// OLD CODE END

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
				<span class="drawer-title type-drawer-title">Connection detail</span>
				<span class="drawer-subtitle mono">{subtitle}</span>
			</div>
			<button class="icon-btn" type="button" onclick={onclose} aria-label="Close panel"><Icon name="close" /></button>
		</div>

		<!-- ====== Tabs ====== -->
		<div class="drawer-tabs">
			<div class="pills">
				<button class="pill" type="button" aria-pressed={activeTab === 'detail'} onclick={() => activeTab = 'detail'}>Detail</button>
				<button class="pill" type="button" aria-pressed={activeTab === 'tshark'} onclick={() => activeTab = 'tshark'}>TShark analysis</button>
				<button class="pill" type="button" aria-pressed={activeTab === 'related'} onclick={() => activeTab = 'related'}>Related activity</button>
			</div>
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
							<span class="detail-value">{formatBytes(downloadBytes)}</span>
						</div>
						<div class="detail-item">
							<span class="detail-label">Upload</span>
							<span class="detail-value">{formatBytes(uploadBytes)}</span>
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
							<span class="detail-label">Conn state</span>
							<span class="detail-value">
								{#if connState}
									{connState}{#if CONN_STATE_DESC[connState]} ({CONN_STATE_DESC[connState].split(',')[0]}){/if}
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
						<div class="detail-section-title eyebrow">Destination enrichment</div>
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
						<div class="detail-section-title eyebrow">TLS details</div>
						<div class="detail-grid">
							{#if tlsVersion}
								<div class="detail-item">
									<span class="detail-label">TLS version</span>
									<span class="detail-value">{tlsVersion}</span>
								</div>
							{/if}
							{#if tlsSni}
								<div class="detail-item">
									<span class="detail-label">SNI</span>
									<!-- OLD CODE START: <span class="detail-value">{tlsSni}</span> (NET-160: not a link) OLD CODE END -->
									<a class="detail-value" href={domainHref(tlsSni)}>{tlsSni}</a>
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
					<div class="tshark-filter-label eyebrow">Auto-generated BPF filter</div>
					<div class="tshark-filter">{bpfFilter || '(none)'}</div>

					{#if displayFilter && displayFilter !== bpfFilter}
						<div class="tshark-filter-label eyebrow">Display filter</div>
						<div class="tshark-filter">{displayFilter}</div>
					{/if}

					<!-- Mode buttons + Analyse -->
					<div class="tshark-controls">
						<button
							class="btn primary"
							type="button"
							onclick={runAnalysis}
							disabled={analyzing || tsharkAvailable === false}
						>
							{#if analyzing}Analysing…{:else}<Icon name="play" />Analyse{/if}
						</button>
						<div class="pills" role="group" aria-label="Output mode">
							<button
								class="pill"
								type="button"
								aria-pressed={tsharkMode === 'summary'}
								onclick={() => tsharkMode = 'summary'}
							>Summary</button>
							<button
								class="pill"
								type="button"
								aria-pressed={tsharkMode === 'verbose'}
								onclick={() => tsharkMode = 'verbose'}
							>Verbose (-V)</button>
							<button
								class="pill"
								type="button"
								aria-pressed={tsharkMode === 'follow'}
								onclick={() => tsharkMode = 'follow'}
							>Follow stream</button>
						</div>
						<a href={tsharkToolUrl} class="btn">Open in TShark tool</a>
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
							<p class="status-text">Checking TShark availability…</p>
						</div>
					{:else if pcapLoading}
						<div class="tshark-status">
							<div class="spinner"></div>
							<p class="status-text">Loading PCAP files…</p>
						</div>
					{:else if analyzing}
						<div class="tshark-status">
							<div class="spinner"></div>
							<p class="status-text">Analysing packets…</p>
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
							<p class="status-text">Click "Analyse" to inspect packets for this connection.</p>
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
					<div class="detail-section-title eyebrow">Related activity</div>

					<div class="related-list">
						{#if dstIp}
							<a href="/connections?ip={encodeURIComponent(dstIp)}" class="related-item">
								<span class="tag related-type">Conn</span>
								<span class="related-text">Other connections to {dstIp}</span>
								<Icon name="back" class="chev related-arrow" />
							</a>
						{/if}

						{#if deviceIp}
							<a href="/logs?filter={encodeURIComponent(deviceIp)}" class="related-item">
								<span class="tag related-type">DNS</span>
								<span class="related-text">DNS queries for {deviceIp}</span>
								<Icon name="back" class="chev related-arrow" />
							</a>

							<a href="/alerts?ip={encodeURIComponent(deviceIp)}" class="related-item">
								<span class="tag related-type">Alert</span>
								<span class="related-text">Alerts for {deviceIp}</span>
								<Icon name="back" class="chev related-arrow" />
							</a>
						{/if}

						{#if srcIp && srcIp !== deviceIp}
							<!-- OLD CODE START (NET-160: the device page for internet sources too)
							<a href="/devices/{encodeURIComponent(srcIp)}" class="related-item">
								<span class="tag related-type">Conn</span>
								<span class="related-text">Device: {srcIp}</span>
							OLD CODE END -->
							<a href={$ipHref(srcIp)} class="related-item">
								<span class="tag related-type">Conn</span>
								<span class="related-text">{$isLan(srcIp) === true ? 'Device' : 'Address'}: {srcIp}</span>
								<Icon name="back" class="chev related-arrow" />
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
		background: var(--scrim);
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
	/* Drawer panel: a surface-1 card docked to the right edge            */
	/* ================================================================== */

	.conn-drawer {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: 560px;
		max-width: 100vw;
		z-index: 999;
		background: var(--surface-1);
		border-left: 1px solid var(--line);
		box-shadow: var(--sheen), var(--shadow-pop);
		display: flex;
		flex-direction: column;
		transform: translateX(100%);
		transition: transform 0.25s var(--ease);
	}

	.conn-drawer.open {
		transform: translateX(0);
	}

	/* ================================================================== */
	/* Header and tabs                                                    */
	/* ================================================================== */

	.drawer-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--sp-3);
		padding: var(--sp-5) var(--sp-5) var(--sp-4);
		flex-shrink: 0;
	}

	.drawer-title-area {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		min-width: 0;
	}

	.drawer-title {
		color: var(--text-1);
	}

	.drawer-subtitle {
		font-size: var(--text-xs);
		color: var(--text-3);
		overflow-wrap: anywhere;
	}

	.drawer-tabs {
		padding: 0 var(--sp-5) var(--sp-4);
		flex-shrink: 0;
		overflow-x: auto;
	}

	/* ================================================================== */
	/* Scrollable body                                                    */
	/* ================================================================== */

	.drawer-body {
		flex: 1;
		overflow-y: auto;
		padding: var(--sp-5);
		border-top: 1px solid var(--line);
	}

	/* ================================================================== */
	/* Detail tab — 2-column grid layout                                  */
	/* ================================================================== */

	.detail-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--sp-3) var(--sp-6);
		margin-bottom: var(--sp-6);
	}

	.detail-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.detail-label {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.detail-value {
		font-size: var(--text-sm);
		color: var(--text-1);
		font-family: var(--font-mono);
		overflow-wrap: anywhere;
	}

	.detail-value--small {
		font-size: var(--text-micro);
	}

	.detail-section-title {
		display: block;
		margin-bottom: var(--sp-3);
		margin-top: var(--sp-6);
		padding-bottom: var(--sp-2);
		border-bottom: 1px solid var(--line);
	}

	/* ================================================================== */
	/* TShark tab                                                         */
	/* ================================================================== */

	.tshark-tab {
		display: flex;
		flex-direction: column;
		gap: 0;
	}

	.tshark-filter-label {
		margin-bottom: var(--sp-1);
	}

	.tshark-filter {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		padding: var(--sp-2) var(--sp-4);
		background: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		color: var(--accent-strong);
		margin-bottom: var(--sp-4);
		overflow-wrap: anywhere;
	}

	.tshark-controls {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		margin-bottom: var(--sp-4);
		flex-wrap: wrap;
	}

	/* TShark status messages */
	.tshark-status {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-8) 0;
		text-align: center;
	}

	.status-text {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.status-text.error {
		color: var(--sev-critical);
	}

	.status-hint {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Terminal output: machine text on the page black */
	.tshark-terminal {
		background: var(--bg);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		padding: var(--sp-4);
		font-family: var(--font-mono);
		font-size: var(--text-micro);
		line-height: 1.7;
		color: var(--text-2);
		max-height: 400px;
		overflow: auto;
		white-space: pre;
		tab-size: 4;
	}

	.tshark-line {
		display: block;
	}

	.tshark-line-no {
		color: var(--text-3);
		user-select: none;
	}

	.tshark-timestamp,
	.tshark-arrow {
		color: var(--text-3);
	}

	.tshark-src {
		color: var(--accent-strong);
	}

	.tshark-dst {
		color: var(--data-2);
	}

	.tshark-proto {
		color: var(--data-3);
		font-weight: 600;
	}

	.tshark-info {
		color: var(--text-2);
	}

	.packet-count {
		font-size: var(--text-xs);
		color: var(--text-3);
		text-align: right;
		margin-top: var(--sp-1);
	}

	/* ================================================================== */
	/* Related tab — tagged link list                                     */
	/* ================================================================== */

	.related-list {
		display: flex;
		flex-direction: column;
	}

	.related-item {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-3) 0;
		border-bottom: 1px solid var(--line);
		font-size: var(--text-sm);
		text-decoration: none;
		color: var(--text-2);
		transition: color var(--dur-fast);
	}

	.related-item:last-child {
		border-bottom: none;
	}

	.related-item:hover {
		color: var(--text-1);
	}

	.related-type {
		min-width: 44px;
		text-align: center;
		flex-shrink: 0;
	}

	.related-text {
		flex: 1;
		color: inherit;
	}

	.related-item :global(.related-arrow) {
		width: 16px;
		height: 16px;
		color: var(--text-3);
		transition: color var(--dur-fast);
	}

	.related-item:hover :global(.related-arrow) {
		color: var(--accent-strong);
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
