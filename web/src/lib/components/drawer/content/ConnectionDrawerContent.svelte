<!--
  ConnectionDrawerContent.svelte — 4-tab connection drawer:
  1. Summary + Threat Context (GeoIP/ASN enrichment, associated alerts)
  2. TShark Analysis (existing PCAP analysis)
  3. Related Connections (timeline of src↔dst connections)
  4. Network Flow (mini SVG flow diagram)
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import { getWhois } from '$api/lookup';
	import type { WhoisResult } from '$api/lookup';
	import { buildTSharkFilter, getField, asString } from '$lib/utils/tshark-filter';
	import { getTSharkStatus, getPcapFiles, analyzePcap } from '$api/tshark';
	import type { TSharkPacket, PcapFile } from '$api/tshark';
	import { analyzeConnection } from '$lib/utils/tshark-analyze';
	import type { AnalysisMode } from '$lib/utils/tshark-analyze';
	import { unwrap, getPacketSummary, formatDuration, formatBytes, CONN_STATE_DESC } from '$lib/utils/tshark-helpers';
	import { getRelatedConnections } from '$api/traffic';
	import type { RelatedConnectionsResponse } from '$api/traffic';
	import { getAlerts } from '$api/alerts';
	import type { Alert } from '$api/alerts';

	interface Connection {
		_id: string;
		_index?: string;
		_source?: Record<string, unknown>;
		[key: string]: unknown;
	}

	let {
		connection,
		activeTab,
		isMirrorMode = false,
	}: {
		connection: Connection;
		activeTab: string;
		isMirrorMode?: boolean;
	} = $props();

	// Copy state
	let copied = $state(false);

	// WHOIS state
	let whoisResult = $state<WhoisResult | null>(null);
	let whoisLoading = $state(false);
	let whoisIp = $state('');

	// TShark state
	let tsharkAvailable = $state<boolean | null>(null);
	let tsharkChecked = $state(false);
	let pcapFiles = $state<PcapFile[]>([]);
	let pcapLoading = $state(false);
	let packets = $state<TSharkPacket[]>([]);
	let analyzing = $state(false);
	let tsharkError = $state('');
	let tsharkMode = $state<AnalysisMode>('summary');
	let tsharkTextOutput = $state('');
	let selectedPacketIdx = $state<number | null>(null);
	let hexContent = $state('');
	let hexLoading = $state(false);
	let tsharkTabLoaded = $state(false);

	// Related connections state
	let relatedData = $state<RelatedConnectionsResponse | null>(null);
	let relatedLoading = $state(false);
	let relatedTabLoaded = $state(false);

	// Threat context state
	let threatAlerts = $state<Alert[]>([]);
	let threatLoading = $state(false);
	let threatLoaded = $state(false);

	// Derived connection fields
	let srcIp = $derived(asString(getField(connection, 'source.ip')));
	let dstIp = $derived(asString(getField(connection, 'destination.ip')));
	let srcPort = $derived(getField(connection, 'source.port') as string | number | null);
	let dstPort = $derived(getField(connection, 'destination.port') as string | number | null);
	let proto = $derived(asString(getField(connection, 'network.transport')));
	let service = $derived(asString(getField(connection, 'network.protocol') || getField(connection, 'zeek.conn.service')));
	let uid = $derived(asString(getField(connection, 'zeek.conn.uid') || getField(connection, 'zeek.uid')));
	let connState = $derived(asString(getField(connection, 'zeek.conn.conn_state')));
	let duration = $derived(getField(connection, 'event.duration') || getField(connection, 'zeek.conn.duration'));
	let origBytes = $derived(getField(connection, 'source.bytes') || getField(connection, 'zeek.conn.orig_bytes'));
	let respBytes = $derived(getField(connection, 'destination.bytes') || getField(connection, 'zeek.conn.resp_bytes'));
	let origPkts = $derived(getField(connection, 'zeek.conn.orig_pkts') as string | number | null);
	let respPkts = $derived(getField(connection, 'zeek.conn.resp_pkts') as string | number | null);
	let history = $derived(asString(getField(connection, 'zeek.conn.history')));
	let communityId = $derived(asString(getField(connection, 'network.community_id') || getField(connection, 'zeek.conn.community_id')));
	let timestamp = $derived(asString(getField(connection, '@timestamp')));
	let displayFilter = $derived(buildTSharkFilter(connection));

	// TShark tool URL
	let tsharkToolUrl = $derived.by(() => {
		const params = new URLSearchParams({ auto: '1' });
		if (displayFilter) params.set('filter', displayFilter);
		if (timestamp) params.set('ts', timestamp);
		return `/tools/tshark?${params}`;
	});

	// GeoIP/ASN enrichment from connection source
	let srcAsn = $derived(asString(getField(connection, 'source.as.full')));
	let dstAsn = $derived(asString(getField(connection, 'destination.as.full')));
	let srcCountry = $derived(asString(getField(connection, 'source.geo.country_name') || getField(connection, 'source.geo.country_iso_code')));
	let dstCountry = $derived(asString(getField(connection, 'destination.geo.country_name') || getField(connection, 'destination.geo.country_iso_code')));

	let rawJson = $derived(JSON.stringify(connection._source || connection, null, 2));

	// Bytes ratio for visual bar
	let origBytesNum = $derived(Number(origBytes) || 0);
	let respBytesNum = $derived(Number(respBytes) || 0);
	let totalBytes = $derived(origBytesNum + respBytesNum);
	let origPct = $derived(totalBytes > 0 ? Math.round((origBytesNum / totalBytes) * 100) : 50);

	// OLD CODE START — STATE_DESC moved to CONN_STATE_DESC in $lib/utils/tshark-helpers.ts
	// const STATE_DESC: Record<string, string> = {
	// 	S0: 'Connection attempt seen, no reply',
	// 	S1: 'Connection established, not terminated',
	// 	SF: 'Normal establishment and termination',
	// 	REJ: 'Connection attempt rejected',
	// 	S2: 'Connection established, close attempted by originator',
	// 	S3: 'Connection established, close attempted by responder',
	// 	RSTO: 'Connection established, originator aborted',
	// 	RSTR: 'Connection established, responder aborted',
	// 	RSTOS0: 'Originator sent a SYN then RST, responder never replied',
	// 	RSTRH: 'Responder sent a SYN ACK then RST, originator never replied',
	// 	SH: 'Originator sent SYN then FIN, responder never replied (half-open)',
	// 	SHR: 'Responder sent SYN ACK then FIN, originator never replied',
	// 	OTH: 'No SYN seen, midstream traffic',
	// };
	// OLD CODE END

	// Protocol colors for flow diagram
	const PROTO_COLORS: Record<string, string> = {
		tcp: 'var(--cyan)',
		udp: 'var(--green)',
		tls: 'var(--purple)',
		dns: 'var(--amber)',
		icmp: 'var(--red)',
		http: 'var(--blue)',
	};

	// OLD CODE START — formatDuration/formatBytes moved to $lib/utils/tshark-helpers.ts
	// function formatDuration(val: unknown): string {
	// 	if (val == null) return '--';
	// 	const n = Number(val);
	// 	if (isNaN(n)) return String(val);
	// 	if (n < 1) return `${(n * 1000).toFixed(0)}ms`;
	// 	if (n < 60) return `${n.toFixed(1)}s`;
	// 	return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`;
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

	function formatTimestamp(ts: string): string {
		if (!ts) return '--';
		try { return new Date(ts).toLocaleString(); } catch { return ts; }
	}

	function copyJson() {
		navigator.clipboard.writeText(rawJson);
		copied = true;
		setTimeout(() => { copied = false; }, 1500);
	}

	// WHOIS
	async function lookupWhois(ip: string) {
		whoisIp = ip;
		whoisLoading = true;
		whoisResult = null;
		try {
			whoisResult = await getWhois(ip);
		} finally {
			whoisLoading = false;
		}
	}

	// Load threat context on summary tab
	$effect(() => {
		if (activeTab === 'summary' && !threatLoaded && srcIp && dstIp) {
			threatLoaded = true;
			loadThreatContext();
		}
	});

	async function loadThreatContext() {
		threatLoading = true;
		try {
			const result = await getAlerts({ ip: srcIp || dstIp, size: 10 });
			threatAlerts = result.alerts || [];
		} catch {
			threatAlerts = [];
		} finally {
			threatLoading = false;
		}
	}

	// TShark
	$effect(() => {
		if (activeTab === 'tshark' && !tsharkTabLoaded) {
			tsharkTabLoaded = true;
			loadTSharkTab();
		}
	});

	async function loadTSharkTab() {
		if (!tsharkChecked) {
			tsharkChecked = true;
			try {
				const status = await getTSharkStatus();
				tsharkAvailable = status.available;
			} catch {
				tsharkAvailable = false;
			}
		}
		if (tsharkAvailable) {
			pcapLoading = true;
			try {
				const result = await getPcapFiles();
				pcapFiles = result.pcaps || [];
				if (pcapFiles.length > 0) runAnalysis('summary');
			} catch {
				tsharkError = 'Failed to load PCAP files';
			} finally {
				pcapLoading = false;
			}
		}
	}

	async function runAnalysis(mode?: AnalysisMode) {
		const useMode = mode || tsharkMode;
		analyzing = true;
		tsharkError = '';
		tsharkTextOutput = '';
		packets = [];
		selectedPacketIdx = null;
		hexContent = '';

		try {
			const result = await analyzeConnection({
				pcapFiles,
				displayFilter,
				timestamp,
				mode: useMode,
				proto: proto || 'tcp',
				maxAttempts: 5,
			});

			if (result.error) {
				tsharkError = result.error;
			} else if (useMode === 'summary') {
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

	async function fetchHexForPacket(idx: number) {
		selectedPacketIdx = idx;
		hexLoading = true;
		hexContent = '';
		const pkt = packets[idx];
		const frameNum = unwrap(pkt?.['_source']?.['layers']?.['frame']?.['frame.number']) || (idx + 1);
		const connTs = timestamp ? new Date(timestamp).getTime() : Date.now();
		const sorted = [...pcapFiles].sort((a, b) =>
			Math.abs((a.modified * 1000) - connTs) - Math.abs((b.modified * 1000) - connTs)
		);
		for (const pcap of sorted.slice(0, 3)) {
			try {
				const result = await analyzePcap({
					pcap_path: pcap.path,
					display_filter: `${displayFilter} && frame.number == ${frameNum}`,
					max_packets: 1, output_format: 'text',
				});
				if (result.error) continue;
				if (result.packets?.length > 0) {
					const raw = result.packets[0]?.raw || result.packets[0]?.['_raw'] || '';
					hexContent = typeof raw === 'string' ? raw : JSON.stringify(result.packets[0], null, 2);
					break;
				}
			} catch { continue; }
		}
		if (!hexContent) hexContent = '(No hex data available for this packet)';
		hexLoading = false;
	}

	// OLD CODE START — unwrap/getPacketInfo moved to unwrap/getPacketSummary in $lib/utils/tshark-helpers.ts
	// getPacketInfo returned {no, time, src, dst, proto, len} — getPacketSummary
	// is a superset that also includes `info`. Both drawers now share getPacketSummary.
	// /** Unwrap TShark -T json array-wrapped values (e.g. ["1"] -> "1") */
	// function unwrap(val: unknown): string {
	// 	if (Array.isArray(val)) return String(val[0] ?? '');
	// 	if (val == null) return '';
	// 	return String(val);
	// }
	//
	// function getPacketInfo(pkt: TSharkPacket) {
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
	// 	};
	// }
	// OLD CODE END

	// Related connections
	$effect(() => {
		if (activeTab === 'related' && !relatedTabLoaded && srcIp && dstIp) {
			relatedTabLoaded = true;
			loadRelated();
		}
	});

	async function loadRelated() {
		relatedLoading = true;
		try {
			relatedData = await getRelatedConnections(srcIp, dstIp);
		} catch {
			relatedData = null;
		} finally {
			relatedLoading = false;
		}
	}

	// Related timeline layout
	let relatedMaxBytes = $derived(
		relatedData
			? Math.max(1, ...relatedData.connections.map((c) => {
				const sb = (c as Record<string, unknown>)?.source as { bytes?: number } | undefined;
				const db = (c as Record<string, unknown>)?.destination as { bytes?: number } | undefined;
				return (sb?.bytes || 0) + (db?.bytes || 0);
			}))
			: 1
	);

	function protoColor(p: string): string {
		return PROTO_COLORS[p?.toLowerCase()] || 'var(--accent)';
	}
</script>

<!-- ======================================================================= -->
<!-- Tab 1: Summary + Threat Context                                          -->
<!-- ======================================================================= -->
{#if activeTab === 'summary'}
	<div class="details-content">
		<DrawerSection title="Connection Identity" defaultExpanded>
			<KVRow label="UID" value={uid} mono copyable />
			<KVRow label="Community ID" value={communityId} mono copyable />
			<KVRow label="Timestamp" value={formatTimestamp(timestamp)} mono />
		</DrawerSection>

		<DrawerSection title="Source" defaultExpanded>
			<KVRow label="IP" value={srcIp} mono copyable />
			<KVRow label="Port" value={srcPort} mono />
			{#if srcCountry}
				<KVRow label="Country" value={srcCountry} />
			{/if}
			{#if srcAsn}
				<KVRow label="ASN / Org" value={srcAsn} />
			{/if}
		</DrawerSection>

		<DrawerSection title="Destination" defaultExpanded>
			<KVRow label="IP" value={dstIp} mono copyable />
			<KVRow label="Port" value={dstPort} mono />
			{#if dstCountry}
				<KVRow label="Country" value={dstCountry} />
			{/if}
			{#if dstAsn}
				<KVRow label="ASN / Org" value={dstAsn} />
			{/if}
		</DrawerSection>

		<DrawerSection title="Traffic Metrics" defaultExpanded>
			<KVRow label="Protocol" value={proto?.toUpperCase()} />
			<KVRow label="Service" value={service} />
			<KVRow label="Duration" value={formatDuration(duration)} mono />
			<KVRow label="Bytes In (Orig)" value={formatBytes(origBytes)} mono />
			<KVRow label="Bytes Out (Resp)" value={formatBytes(respBytes)} mono />
			<KVRow label="Packets In" value={origPkts} mono />
			<KVRow label="Packets Out" value={respPkts} mono />
			<!-- Traffic ratio bar -->
			{#if totalBytes > 0}
				<div class="ratio-row">
					<span class="ratio-label">Traffic Ratio</span>
					<div class="ratio-bar">
						<div class="ratio-in" style="width: {origPct}%;" title="Inbound: {origPct}%"></div>
						<div class="ratio-out" style="width: {100 - origPct}%;" title="Outbound: {100 - origPct}%"></div>
					</div>
					<span class="ratio-text">{origPct}% in</span>
				</div>
			{/if}
		</DrawerSection>

		<DrawerSection title="State" defaultExpanded={false}>
			<KVRow label="Conn State" value={connState} mono />
			{#if connState && CONN_STATE_DESC[connState]}
				<KVRow label="Description" value={CONN_STATE_DESC[connState]} />
			{/if}
			<KVRow label="History" value={history} mono copyable />
			<KVRow label="Index" value={connection._index} mono />
		</DrawerSection>

		<!-- Threat Context -->
		<DrawerSection title="Threat Context" defaultExpanded>
			{#if threatLoading}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="text-muted">Checking for alerts...</p>
				</div>
			{:else if threatAlerts.length > 0}
				<div class="threat-list">
					{#each threatAlerts.slice(0, 5) as alert}
						<div class="threat-item">
							<span class="threat-severity" class:sev-high={alert.alert?.severity === 1 || alert.alert?.severity === 2} class:sev-med={alert.alert?.severity === 3}>
								{alert.alert?.severity === 1 ? 'HIGH' : alert.alert?.severity === 2 ? 'HIGH' : alert.alert?.severity === 3 ? 'MED' : 'LOW'}
							</span>
							<span class="threat-sig">{alert.alert?.signature || alert.rule_name || 'Unknown alert'}</span>
						</div>
					{/each}
					{#if threatAlerts.length > 5}
						<p class="text-muted" style="margin-top: var(--space-xs);">+ {threatAlerts.length - 5} more alerts</p>
					{/if}
				</div>
			{:else}
				<p class="text-muted no-threats">No associated alerts found</p>
			{/if}
		</DrawerSection>

		<!-- WHOIS inline result -->
		{#if whoisResult}
			<DrawerSection title="WHOIS \u2014 {whoisIp}" defaultExpanded>
				{#if whoisResult.error}
					<p class="text-danger">{whoisResult.error}</p>
				{:else}
					{#each Object.entries(whoisResult.parsed) as [key, val]}
						<KVRow label={key} value={val} copyable />
					{/each}
					{#if whoisResult.raw}
						<details class="whois-raw">
							<summary>Raw WHOIS output</summary>
							<pre class="raw-block">{whoisResult.raw}</pre>
						</details>
					{/if}
				{/if}
			</DrawerSection>
		{/if}
	</div>

<!-- ======================================================================= -->
<!-- Tab 2: TShark Analysis (existing)                                        -->
<!-- ======================================================================= -->
{:else if activeTab === 'tshark'}
	<div class="tshark-content">
		{#if tsharkAvailable === false}
			<div class="empty-state">
				<p class="text-muted">TShark is not available</p>
				<p class="text-dim">The TShark container is not running or not configured.</p>
			</div>
		{:else if tsharkAvailable === null}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="text-muted">Checking TShark...</p>
			</div>
		{:else}
			<div class="filter-preview">
				<span class="filter-label">Display filter:</span>
				<code class="filter-code">{displayFilter || '(none)'}</code>
			</div>

			<!-- Mode buttons + Analyze -->
			<div class="tshark-controls">
				<button
					class="tshark-btn tshark-btn-primary"
					onclick={() => runAnalysis()}
					disabled={analyzing || tsharkAvailable === false}
				>
					{analyzing ? 'Analyzing...' : '\u25B6 Analyze'}
				</button>
				<button
					class="tshark-btn tshark-btn-mode"
					class:active={tsharkMode === 'summary'}
					onclick={() => tsharkMode = 'summary'}
				>Summary</button>
				<button
					class="tshark-btn tshark-btn-mode"
					class:active={tsharkMode === 'verbose'}
					onclick={() => tsharkMode = 'verbose'}
				>Verbose (-V)</button>
				<button
					class="tshark-btn tshark-btn-mode"
					class:active={tsharkMode === 'follow'}
					onclick={() => tsharkMode = 'follow'}
				>Follow Stream</button>
				<a href={tsharkToolUrl} class="tshark-btn tshark-btn-mode">Open in TShark Tool &rarr;</a>
			</div>

			{#if analyzing}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="text-muted">Analyzing packets...</p>
				</div>
			{:else if tsharkError}
				<div class="error-state">
					<p class="text-muted">{tsharkError}</p>
					<button class="btn btn-secondary btn-sm" onclick={() => runAnalysis()}>Retry</button>
				</div>
			{:else if tsharkMode === 'summary' && packets.length > 0}
				<div class="packet-table-wrap">
					<table class="packet-table">
						<thead>
							<tr><th>No.</th><th>Time</th><th>Source</th><th>Destination</th><th>Proto</th><th>Len</th></tr>
						</thead>
						<tbody>
							{#each packets as pkt, i}
								{@const info = getPacketSummary(pkt)}
								<tr class="packet-row" class:selected={selectedPacketIdx === i} onclick={() => fetchHexForPacket(i)}>
									<td class="mono">{info.no}</td><td class="mono">{info.time}</td>
									<td class="mono">{info.src}</td><td class="mono">{info.dst}</td>
									<td>{info.proto}</td><td class="mono">{info.len}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<div class="hex-section">
					<h4 class="hex-title">Hex Dump</h4>
					{#if selectedPacketIdx === null}
						<p class="text-muted">Click a packet row to view hex dump</p>
					{:else if hexLoading}
						<div class="loading-state"><div class="loading-spinner"></div><p class="text-muted">Loading hex...</p></div>
					{:else}
						<pre class="raw-block hex-block">{hexContent}</pre>
					{/if}
				</div>
			{:else if (tsharkMode === 'verbose' || tsharkMode === 'follow') && tsharkTextOutput}
				<pre class="raw-block tshark-text-block">{tsharkTextOutput}</pre>
			{:else if pcapLoading}
				<div class="loading-state"><div class="loading-spinner"></div><p class="text-muted">Loading PCAP files...</p></div>
			{:else if pcapFiles.length === 0}
				<div class="empty-state"><p class="text-muted">No PCAP files available</p></div>
			{:else if !analyzing && packets.length === 0 && !tsharkTextOutput && !tsharkError}
				<div class="empty-state">
					<p class="text-muted">Click "Analyze" to inspect packets for this connection.</p>
					<p class="text-dim">{pcapFiles.length} PCAP file{pcapFiles.length !== 1 ? 's' : ''} available.</p>
				</div>
			{/if}
		{/if}
	</div>

<!-- ======================================================================= -->
<!-- Tab 3: Related Connections                                               -->
<!-- ======================================================================= -->
{:else if activeTab === 'related'}
	<div class="related-content">
		{#if relatedLoading}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="text-muted">Loading related connections...</p>
			</div>
		{:else if relatedData}
			<!-- Summary stats -->
			<div class="related-summary">
				<div class="related-stat">
					<span class="stat-value">{relatedData.total_connections}</span>
					<span class="stat-label">Total Sessions</span>
				</div>
				<div class="related-stat">
					<span class="stat-value">{formatBytes(relatedData.total_bytes)}</span>
					<span class="stat-label">Total Bytes</span>
				</div>
				<div class="related-stat">
					<span class="stat-value">
						{#each relatedData.protocols as p}
							<span class="proto-badge" style="background: {protoColor(p)};">{p.toUpperCase()}</span>
						{/each}
					</span>
					<span class="stat-label">Protocols</span>
				</div>
			</div>
			{#if relatedData.first_seen && relatedData.last_seen}
				<div class="related-timerange">
					<KVRow label="First Seen" value={formatTimestamp(relatedData.first_seen)} mono />
					<KVRow label="Last Seen" value={formatTimestamp(relatedData.last_seen)} mono />
				</div>
			{/if}

			<!-- Mini timeline SVG -->
			{#if relatedData.connections.length > 0}
				<div class="related-timeline">
					<h4 class="section-title">Connection Timeline</h4>
					<svg viewBox="0 0 400 {Math.min(200, relatedData.connections.length * 12 + 20)}" width="100%" height={Math.min(200, relatedData.connections.length * 12 + 20)}>
						{#each relatedData.connections.slice(0, 15) as conn, i}
							{@const sb = ((conn as Record<string, unknown>)?.source as { bytes?: number })?.bytes || 0}
							{@const db = ((conn as Record<string, unknown>)?.destination as { bytes?: number })?.bytes || 0}
							{@const connBytes = sb + db}
							{@const barW = Math.max(4, (connBytes / relatedMaxBytes) * 300)}
							{@const connProto = ((conn as Record<string, unknown>)?.network as { transport?: string })?.transport || ''}
							<rect
								x="80" y={i * 12 + 4}
								width={barW} height="8" rx="3"
								fill={protoColor(connProto)}
								opacity="0.7"
							/>
							<text x="0" y={i * 12 + 11} fill="var(--text-muted)" font-size="9" font-family="var(--font-mono)">
								{formatTimestamp((conn as Record<string, unknown>)?.['@timestamp'] as string || '').split(',')[1]?.trim() || ''}
							</text>
						{/each}
					</svg>
					{#if relatedData.connections.length > 15}
						<p class="text-muted" style="font-size: var(--text-xs);">Showing 15 of {relatedData.connections.length} connections</p>
					{/if}
				</div>
			{/if}
		{:else}
			<div class="empty-state">
				<p class="text-muted">No related connections found</p>
			</div>
		{/if}
	</div>

<!-- ======================================================================= -->
<!-- Tab 4: Network Flow Diagram (mini SVG)                                   -->
<!-- ======================================================================= -->
{:else if activeTab === 'flow'}
	<div class="flow-content">
		<svg viewBox="0 0 380 160" width="100%" height="160">
			<!-- Source node -->
			<rect x="10" y="50" width="100" height="60" rx="8" fill="var(--cyan)" opacity="0.2" stroke="var(--cyan)" stroke-width="1.5" />
			<text x="60" y="72" text-anchor="middle" fill="var(--text-primary)" font-size="11" font-weight="600">
				{srcIp || 'Source'}
			</text>
			{#if srcPort}
				<text x="60" y="88" text-anchor="middle" fill="var(--text-muted)" font-size="10">:{srcPort}</text>
			{/if}
			{#if srcCountry}
				<text x="60" y="102" text-anchor="middle" fill="var(--text-muted)" font-size="9">{srcCountry}</text>
			{/if}

			<!-- Protocol node -->
			<rect x="150" y="55" width="80" height="50" rx="8" fill={protoColor(proto)} opacity="0.2" stroke={protoColor(proto)} stroke-width="1.5" />
			<text x="190" y="78" text-anchor="middle" fill="var(--text-primary)" font-size="12" font-weight="600">
				{proto?.toUpperCase() || '?'}
			</text>
			{#if service}
				<text x="190" y="94" text-anchor="middle" fill="var(--text-muted)" font-size="10">{service}</text>
			{/if}

			<!-- Destination node -->
			<rect x="270" y="50" width="100" height="60" rx="8" fill="var(--green)" opacity="0.2" stroke="var(--green)" stroke-width="1.5" />
			<text x="320" y="72" text-anchor="middle" fill="var(--text-primary)" font-size="11" font-weight="600">
				{dstIp || 'Dest'}
			</text>
			{#if dstPort}
				<text x="320" y="88" text-anchor="middle" fill="var(--text-muted)" font-size="10">:{dstPort}</text>
			{/if}
			{#if dstCountry}
				<text x="320" y="102" text-anchor="middle" fill="var(--text-muted)" font-size="9">{dstCountry}</text>
			{/if}
			{#if dstAsn}
				<text x="320" y="130" text-anchor="middle" fill="var(--text-dim)" font-size="8">
					{dstAsn.length > 25 ? dstAsn.slice(0, 24) + '\u2026' : dstAsn}
				</text>
			{/if}

			<!-- Arrows -->
			<line x1="110" y1="80" x2="148" y2="80" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arrowhead)" />
			<line x1="230" y1="80" x2="268" y2="80" stroke="var(--text-muted)" stroke-width="1.5" marker-end="url(#arrowhead)" />

			<!-- Arrow markers -->
			<defs>
				<marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
					<polygon points="0 0, 8 3, 0 6" fill="var(--text-muted)" />
				</marker>
			</defs>

			<!-- Bytes labels on arrows -->
			<text x="129" y="72" text-anchor="middle" fill="var(--accent)" font-size="9" font-weight="500">{formatBytes(origBytes)}</text>
			<text x="249" y="72" text-anchor="middle" fill="var(--accent)" font-size="9" font-weight="500">{formatBytes(respBytes)}</text>

			<!-- Alert indicator -->
			{#if threatAlerts.length > 0}
				<circle cx="190" cy="35" r="8" fill="var(--red)" opacity="0.8" />
				<text x="190" y="38" text-anchor="middle" fill="var(--text-primary)" font-size="9" font-weight="700">{threatAlerts.length}</text>
				<text x="210" y="38" fill="var(--red)" font-size="8">alerts</text>
			{/if}
		</svg>

		<!-- Connection details below diagram -->
		<div class="flow-details">
			<KVRow label="Duration" value={formatDuration(duration)} mono />
			<KVRow label="Total Bytes" value={formatBytes(totalBytes)} mono />
			<KVRow label="State" value={connState} mono />
			{#if communityId}
				<KVRow label="Community ID" value={communityId} mono copyable />
			{/if}
		</div>
	</div>
{/if}

<style>
	.details-content, .tshark-content, .raw-content, .related-content, .flow-content {
		display: flex;
		flex-direction: column;
	}

	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xl) 0;
	}

	.error-state, .empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xl) 0;
		text-align: center;
	}

	.raw-content { gap: var(--space-sm); }
	.raw-header { display: flex; justify-content: flex-end; }

	.raw-block {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-primary);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		overflow-x: auto;
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 600px;
		overflow-y: auto;
		line-height: 1.5;
	}

	/* Traffic ratio bar */
	.ratio-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) 0;
	}

	.ratio-label {
		flex-shrink: 0;
		width: 160px;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.ratio-bar {
		flex: 1;
		display: flex;
		height: 10px;
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.ratio-in { background: var(--cyan); }
	.ratio-out { background: var(--amber); }

	.ratio-text {
		font-size: var(--text-xs);
		color: var(--text-muted);
		white-space: nowrap;
		min-width: 40px;
	}

	/* Threat context */
	.threat-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.threat-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs);
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
	}

	.threat-severity {
		flex-shrink: 0;
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.05em;
		background: var(--bg-secondary);
		color: var(--text-muted);
	}

	.threat-severity.sev-high { background: var(--red); color: var(--text-primary); }
	.threat-severity.sev-med { background: var(--amber); color: var(--bg-primary); }

	.threat-sig {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.no-threats {
		font-size: var(--text-xs);
		padding: var(--space-sm) 0;
	}

	/* TShark controls */
	.tshark-controls {
		display: flex;
		gap: var(--space-xs);
		margin-bottom: var(--space-md);
		flex-wrap: wrap;
	}

	.tshark-btn {
		padding: 5px 12px;
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
		background: var(--accent);
		color: var(--bg-primary);
		border-color: var(--accent);
	}

	.tshark-btn-primary:hover { box-shadow: 0 0 12px rgba(0, 212, 255, 0.3); }
	.tshark-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }

	.tshark-btn-mode {
		background: transparent;
		color: var(--text-secondary);
		border-color: var(--border-default);
	}

	.tshark-btn-mode:hover {
		border-color: var(--border-bright);
		color: var(--text-primary);
	}

	.tshark-btn-mode.active {
		border-color: var(--accent);
		color: var(--accent);
		background: var(--accent-muted);
	}

	.tshark-text-block {
		font-size: 11px;
		line-height: 1.6;
		max-height: 500px;
	}

	/* TShark styles */
	.filter-preview {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-md);
	}

	.filter-label { font-size: var(--text-xs); color: var(--text-muted); white-space: nowrap; }
	.filter-code { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--accent); word-break: break-all; }

	.packet-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-md);
	}

	.packet-table { width: 100%; border-collapse: collapse; font-size: var(--text-xs); }

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

	.packet-row { cursor: pointer; transition: background-color var(--transition-fast); }
	.packet-row:hover { background-color: var(--bg-tertiary); }
	.packet-row.selected { background-color: var(--accent-muted); }
	.packet-row.selected td { color: var(--accent); }

	.hex-section { margin-top: var(--space-sm); }

	.hex-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-sm);
	}

	.hex-block { font-size: 11px; line-height: 1.6; }

	/* Related connections */
	.related-summary {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
		padding: var(--space-md) 0;
	}

	.related-stat {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
	}

	.stat-value {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
		font-family: var(--font-mono);
		display: flex;
		gap: var(--space-xs);
		flex-wrap: wrap;
		justify-content: center;
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.proto-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: var(--radius-sm);
		font-size: 10px;
		font-weight: 600;
		color: var(--bg-primary);
	}

	.related-timerange {
		border-top: 1px solid var(--border-dim);
		padding-top: var(--space-sm);
	}

	.related-timeline {
		padding-top: var(--space-md);
	}

	.section-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-sm);
	}

	/* Flow diagram */
	.flow-content {
		gap: var(--space-md);
	}

	.flow-details {
		border-top: 1px solid var(--border-dim);
		padding-top: var(--space-sm);
	}

	/* Utility */
	.whois-raw { margin-top: var(--space-sm); }
	.whois-raw summary { font-size: var(--text-xs); color: var(--text-muted); cursor: pointer; padding: var(--space-xs) 0; }
	.mono { font-family: var(--font-mono); }
	.text-danger { color: var(--danger); }
	.text-muted { color: var(--text-muted); font-size: var(--text-sm); }
	.text-dim { color: var(--text-dim); font-size: var(--text-xs); }

	.loading-spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }
</style>
