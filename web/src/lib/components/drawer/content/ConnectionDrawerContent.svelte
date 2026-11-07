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
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import { suricataLevel } from '$lib/utils/severity';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { getWhois } from '$api/lookup';
	import type { WhoisResult } from '$api/lookup';
	import { buildTSharkFilter, getField, asString } from '$lib/utils/tshark-filter';
	import { getTSharkStatus, getPcapFiles, analyzePcap } from '$api/tshark';
	import type { TSharkPacket, PcapFile } from '$api/tshark';
	import { analyzeConnection } from '$lib/utils/tshark-analyze';
	import type { AnalysisMode } from '$lib/utils/tshark-analyze';
	import { unwrap, getPacketSummary, formatDuration, formatBytes, CONN_STATE_DESC } from '$lib/utils/tshark-helpers';
	import { partOfWhole } from '$lib/utils/part-of-whole';
	import { connectionDurationMs } from '$lib/utils/connection-duration';
	import { getRelatedConnections } from '$api/traffic';
	import type { RelatedConnectionsResponse } from '$api/traffic';
	import { getAlerts } from '$api/alerts';
	import type { Alert } from '$api/alerts';
	import { alertsHrefForSignature } from '$lib/utils/drilldown';
	import { lanPolicy } from '$lib/stores/lan';
	import { packetsHrefFor } from '$lib/utils/connection-ref';

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
	// #96: a failed load must not read as "No related connections found"
	let relatedFailed = $state(false);

	// Threat context state
	let threatAlerts = $state<Alert[]>([]);
	let threatLoading = $state(false);
	// #96: a failed lookup must not read as "No associated alerts found"
	let threatFailed = $state(false);
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
	// OLD CODE START — #144: event.duration is nanoseconds (ECS), read here as seconds: 255 ms showed ~70,943 h
	// let duration = $derived(getField(connection, 'event.duration') || getField(connection, 'zeek.conn.duration'));
	// OLD CODE END
	let duration = $derived.by(() => {
		const ms = connectionDurationMs(connection);
		return ms === null ? null : ms / 1000;
	});
	let origBytes = $derived(getField(connection, 'source.bytes') || getField(connection, 'zeek.conn.orig_bytes'));
	let respBytes = $derived(getField(connection, 'destination.bytes') || getField(connection, 'zeek.conn.resp_bytes'));
	let origPkts = $derived(getField(connection, 'zeek.conn.orig_pkts') as string | number | null);
	let respPkts = $derived(getField(connection, 'zeek.conn.resp_pkts') as string | number | null);
	let history = $derived(asString(getField(connection, 'zeek.conn.history')));
	let communityId = $derived(asString(getField(connection, 'network.community_id') || getField(connection, 'zeek.conn.community_id')));
	let timestamp = $derived(asString(getField(connection, '@timestamp')));
	let displayFilter = $derived(buildTSharkFilter(connection));

	// OLD CODE START — NET-188: /tools/tshark became Packet analysis; this link opened it with the
	// IPs + service port and the record's timestamp, not the exact connection or its window
	// // TShark tool URL
	// let tsharkToolUrl = $derived.by(() => {
	// 	const params = new URLSearchParams({ auto: '1' });
	// 	if (displayFilter) params.set('filter', displayFilter);
	// 	if (timestamp) params.set('ts', timestamp);
	// 	return `/tools/tshark?${params}`;
	// });
	// OLD CODE END
	/** The exact five-tuple over the connection's own window (NET-188); null when the record can't say */
	let packetsHref = $derived(packetsHrefFor(connection, $lanPolicy));

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
		tcp: 'var(--data-1)',
		udp: 'var(--data-5)',
		tls: 'var(--data-4)',
		dns: 'var(--data-2)',
		icmp: 'var(--data-6)',
		http: 'var(--data-3)',
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
			threatFailed = false;
		} catch {
			threatAlerts = [];
			threatFailed = true;
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
				// OLD CODE START — #96: a failed check read as "TShark is not available"
				// tsharkAvailable = false;
				// OLD CODE END
				tsharkError = "Couldn't check whether TShark is available: the request failed.";
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
		relatedFailed = false;
		try {
			relatedData = await getRelatedConnections(srcIp, dstIp);
		} catch {
			relatedData = null;
			relatedFailed = true;
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
		<DrawerSection title="Connection identity" defaultExpanded>
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

		<DrawerSection title="Traffic metrics" defaultExpanded>
			<KVRow label="Protocol" value={proto?.toUpperCase()} />
			<KVRow label="Service" value={service} />
			<KVRow label="Duration" value={formatDuration(duration)} mono />
			<!-- OLD CODE START — I3: orig is what the source sent, so "in"/"out" were swapped for outbound sessions
			<KVRow label="Bytes in (orig)" value={formatBytes(origBytes)} mono />
			<KVRow label="Bytes out (resp)" value={formatBytes(respBytes)} mono />
			<KVRow label="Packets in" value={origPkts} mono />
			<KVRow label="Packets out" value={respPkts} mono />
			OLD CODE END -->
			<KVRow label="Sent by source" value={formatBytes(origBytes)} mono />
			<KVRow label="Sent by destination" value={formatBytes(respBytes)} mono />
			<KVRow label="Packets from source" value={origPkts} mono />
			<KVRow label="Packets from destination" value={respPkts} mono />
			<!-- Traffic ratio bar -->
			{#if totalBytes > 0}
				<div class="ratio-row">
					<span class="ratio-label">Traffic ratio</span>
					<div class="ratio-bar">
						<!-- OLD CODE START — I3: the split is source/destination, not in/out
						<div class="ratio-in" style="width: {origPct}%;" title="Inbound: {origPct}%"></div>
						<div class="ratio-out" style="width: {100 - origPct}%;" title="Outbound: {100 - origPct}%"></div>
					</div>
					<span class="ratio-text num">{origPct}% in</span>
						OLD CODE END -->
						<div class="ratio-in" style="width: {origPct}%;" title="Sent by source: {origPct}%"></div>
						<div class="ratio-out" style="width: {100 - origPct}%;" title="Sent by destination: {100 - origPct}%"></div>
					</div>
					<span class="ratio-text num">{origPct}% from source</span>
				</div>
			{/if}
		</DrawerSection>

		<DrawerSection title="State" defaultExpanded={false}>
			<KVRow label="Conn state" value={connState} mono />
			{#if connState && CONN_STATE_DESC[connState]}
				<KVRow label="Description" value={CONN_STATE_DESC[connState]} />
			{/if}
			<KVRow label="History" value={history} mono copyable />
			<KVRow label="Index" value={connection._index} mono />
		</DrawerSection>

		<!-- Threat Context -->
		<DrawerSection title="Threat context" defaultExpanded>
			{#if threatLoading}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="dim">Checking for alerts…</p>
				</div>
			{:else if threatAlerts.length > 0}
				<div class="threat-list">
					{#each threatAlerts.slice(0, 5) as alert}
						<!-- OLD CODE: severity 1 and 2 read High, 3 Medium, anything else Low, so severity 2 disagreed
						     with the Live drawer and the Alerts page (NET-146) -->
						{@const level = suricataLevel(alert.alert?.severity)}
						<div class="threat-item">
							<SeverityPill {level} />
							<!-- OLD CODE: <span class="threat-sig">{alert.alert?.signature || alert.rule_name || 'Unknown alert'}</span> (slice 2a: not a link) -->
							{#if alert.alert?.signature}
								<a class="threat-sig" href={alertsHrefForSignature(alert.alert.signature)}>{alert.alert.signature}</a>
							{:else}
								<span class="threat-sig">{alert.rule_name || 'Unknown alert'}</span>
							{/if}
						</div>
					{/each}
					{#if threatAlerts.length > 5}
						<p class="dim more-note">+ {threatAlerts.length - 5} more alerts</p>
					{/if}
				</div>
			{:else if threatFailed}
				<p class="dim no-threats">Couldn't check for associated alerts: the request failed.</p>
			{:else}
				<p class="dim no-threats">No associated alerts found</p>
			{/if}
		</DrawerSection>

		<!-- WHOIS inline result -->
		{#if whoisResult}
			<DrawerSection title="WHOIS — {whoisIp}" defaultExpanded>
				{#if whoisResult.error}
					<p class="error-text">{whoisResult.error}</p>
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
				<p class="state-head">TShark is not available</p>
				<p class="dim">The TShark container is not running or not configured.</p>
			</div>
		{:else if tsharkAvailable === null && tsharkError}
			<div class="empty-state">
				<p class="dim">{tsharkError}</p>
			</div>
		{:else if tsharkAvailable === null}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="dim">Checking TShark…</p>
			</div>
		{:else}
			<div class="filter-preview">
				<span class="filter-label">Display filter:</span>
				<code class="filter-code">{displayFilter || '(none)'}</code>
			</div>

			<!-- Mode buttons + Analyse -->
			<div class="tshark-controls">
				<button
					class="btn primary"
					type="button"
					onclick={() => runAnalysis()}
					disabled={analyzing}
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
				<!-- OLD CODE: <a href={tsharkToolUrl} class="btn">Open in TShark tool</a> (NET-188: Packet analysis) -->
				{#if packetsHref}<a href={packetsHref} class="btn">Open these packets</a>{/if}
			</div>

			{#if analyzing}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="dim">Analysing packets…</p>
				</div>
			{:else if tsharkError}
				<div class="error-state">
					<p class="dim">{tsharkError}</p>
					<button class="btn" type="button" onclick={() => runAnalysis()}>Retry</button>
				</div>
			{:else if tsharkMode === 'summary' && packets.length > 0}
				<div class="tbl-wrap packet-table-wrap">
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
					<h4 class="eyebrow hex-title">Hex dump</h4>
					{#if selectedPacketIdx === null}
						<p class="dim">Click a packet row to view hex dump</p>
					{:else if hexLoading}
						<div class="loading-state"><div class="loading-spinner"></div><p class="dim">Loading hex…</p></div>
					{:else}
						<pre class="raw-block hex-block">{hexContent}</pre>
					{/if}
				</div>
			{:else if (tsharkMode === 'verbose' || tsharkMode === 'follow') && tsharkTextOutput}
				<pre class="raw-block tshark-text-block">{tsharkTextOutput}</pre>
			{:else if pcapLoading}
				<div class="loading-state"><div class="loading-spinner"></div><p class="dim">Loading PCAP files…</p></div>
			{:else if pcapFiles.length === 0}
				<div class="empty-state"><p class="dim">No PCAP files available</p></div>
			{:else if !analyzing && packets.length === 0 && !tsharkTextOutput && !tsharkError}
				<div class="empty-state">
					<p class="dim">Click "Analyse" to inspect packets for this connection.</p>
					<p class="dim small">{pcapFiles.length} PCAP file{pcapFiles.length !== 1 ? 's' : ''} available.</p>
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
				<p class="dim">Loading related connections…</p>
			</div>
		{:else if relatedData}
			<!-- Summary stats -->
			<div class="related-summary">
				<div class="related-stat">
					<span class="stat-value num">{relatedData.total_connections}</span>
					<span class="stat-label">Total sessions</span>
				</div>
				<div class="related-stat">
					<span class="stat-value num">{formatBytes(relatedData.total_bytes)}</span>
					<span class="stat-label">Total bytes</span>
				</div>
				<div class="related-stat">
					<span class="stat-protos">
						{#each relatedData.protocols as p}
							<span class="tag proto-tag"><span class="sw" style="--c: {protoColor(p)};"></span>{p.toUpperCase()}</span>
						{/each}
					</span>
					<span class="stat-label">Protocols</span>
				</div>
			</div>
			{#if relatedData.first_seen && relatedData.last_seen}
				<div class="related-timerange">
					<KVRow label="First seen" value={formatTimestamp(relatedData.first_seen)} mono />
					<KVRow label="Last seen" value={formatTimestamp(relatedData.last_seen)} mono />
				</div>
			{/if}

			<!-- Mini timeline SVG -->
			{#if relatedData.connections.length > 0}
				<div class="related-timeline">
					<h4 class="eyebrow section-title">Connection timeline</h4>
					<svg
						viewBox="0 0 400 {Math.min(200, relatedData.connections.length * 12 + 20)}"
						width="100%"
						height={Math.min(200, relatedData.connections.length * 12 + 20)}
						role="img"
						aria-label="Bytes per connection, latest {Math.min(15, relatedData.connections.length)} connections, coloured by protocol"
					>
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
							<text class="ax" x="0" y={i * 12 + 11}>
								{formatTimestamp((conn as Record<string, unknown>)?.['@timestamp'] as string || '').split(',')[1]?.trim() || ''}
							</text>
						{/each}
					</svg>
					{#if relatedData.connections.length > 15}
						<!-- OLD CODE START — #96: the list holds at most 200 rows; the total counts the whole window
						<p class="text-muted" style="font-size: var(--text-xs);">Showing 15 of {relatedData.connections.length} connections</p>
						OLD CODE END -->
						<p class="dim small">Showing {partOfWhole(15, relatedData.total_connections ?? relatedData.connections.length)} connections</p>
					{/if}
				</div>
			{/if}
		{:else if relatedFailed}
			<div class="empty-state">
				<p class="error-text">Couldn't load related connections: the request failed.</p>
			</div>
		{:else}
			<div class="empty-state">
				<p class="dim">No related connections found</p>
			</div>
		{/if}
	</div>

<!-- ======================================================================= -->
<!-- Tab 4: Network Flow Diagram (mini SVG)                                   -->
<!-- ======================================================================= -->
{:else if activeTab === 'flow'}
	<div class="flow-content">
		<svg
			class="flow-svg"
			viewBox="0 0 380 160"
			width="100%"
			height="160"
			role="img"
			aria-label="{srcIp || 'Source'} to {dstIp || 'destination'} over {proto?.toUpperCase() || 'an unknown protocol'}, {formatBytes(totalBytes)} in total"
		>
			<!-- Source node -->
			<rect class="node node-src" x="10" y="50" width="100" height="60" rx="8" />
			<text class="n-title" x="60" y="72" text-anchor="middle">
				{srcIp || 'Source'}
			</text>
			{#if srcPort}
				<text class="n-meta" x="60" y="88" text-anchor="middle">:{srcPort}</text>
			{/if}
			{#if srcCountry}
				<text class="n-meta" x="60" y="102" text-anchor="middle">{srcCountry}</text>
			{/if}

			<!-- Protocol node -->
			<rect class="node" x="150" y="55" width="80" height="50" rx="8" style="--c: {protoColor(proto)};" />
			<text class="n-title" x="190" y="78" text-anchor="middle">
				{proto?.toUpperCase() || '?'}
			</text>
			{#if service}
				<text class="n-meta" x="190" y="94" text-anchor="middle">{service}</text>
			{/if}

			<!-- Destination node -->
			<rect class="node node-dst" x="270" y="50" width="100" height="60" rx="8" />
			<text class="n-title" x="320" y="72" text-anchor="middle">
				{dstIp || 'Dest'}
			</text>
			{#if dstPort}
				<text class="n-meta" x="320" y="88" text-anchor="middle">:{dstPort}</text>
			{/if}
			{#if dstCountry}
				<text class="n-meta" x="320" y="102" text-anchor="middle">{dstCountry}</text>
			{/if}
			{#if dstAsn}
				<text class="n-meta" x="320" y="130" text-anchor="middle">
					<!-- OLD CODE START — 24 characters fit at the old 8 px; the 11 px token fits 16
					{dstAsn.length > 25 ? dstAsn.slice(0, 24) + '…' : dstAsn}
					OLD CODE END -->
					{dstAsn.length > 17 ? dstAsn.slice(0, 16) + '…' : dstAsn}
				</text>
			{/if}

			<!-- Arrows -->
			<line x1="110" y1="80" x2="148" y2="80" stroke="var(--text-3)" stroke-width="1.5" marker-end="url(#arrowhead)" />
			<line x1="230" y1="80" x2="268" y2="80" stroke="var(--text-3)" stroke-width="1.5" marker-end="url(#arrowhead)" />

			<!-- Arrow markers -->
			<defs>
				<marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
					<polygon points="0 0, 8 3, 0 6" fill="var(--text-3)" />
				</marker>
			</defs>

			<!-- Bytes labels on arrows -->
			<text class="n-bytes" x="129" y="72" text-anchor="middle">{formatBytes(origBytes)}</text>
			<text class="n-bytes" x="249" y="72" text-anchor="middle">{formatBytes(respBytes)}</text>

			<!-- Alert indicator: the critical diamond, the count and the word -->
			{#if threatAlerts.length > 0}
				<path class="alert-mark" d="M190 26 199 35 190 44 181 35z" />
				<text class="alert-count" x="190" y="38.5" text-anchor="middle">{threatAlerts.length}</text>
				<text class="alert-word" x="204" y="38.5">alerts</text>
			{/if}
		</svg>

		<!-- Connection details below diagram -->
		<div class="flow-details">
			<KVRow label="Duration" value={formatDuration(duration)} mono />
			<KVRow label="Total bytes" value={formatBytes(totalBytes)} mono />
			<KVRow label="State" value={connState} mono />
			{#if communityId}
				<KVRow label="Community ID" value={communityId} mono copyable />
			{/if}
		</div>
	</div>
{/if}

<style>
	.details-content, .tshark-content, .related-content, .flow-content {
		display: flex;
		flex-direction: column;
	}

	.loading-state, .error-state, .empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-8) 0;
		text-align: center;
		font-size: var(--text-sm);
	}

	.state-head { color: var(--text-2); }
	.small { font-size: var(--text-xs); }
	.error-text { color: var(--sev-critical); font-size: var(--text-sm); }


	/* Global pre styles give the surface, border, radius and padding. */
	.raw-block {
		font-size: var(--text-xs);
		color: var(--text-1);
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 600px;
		overflow-y: auto;
		line-height: 1.5;
	}

	/* Traffic ratio bar: two series, labelled by the row text */
	.ratio-row {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-1) 0;
		font-size: var(--text-sm);
	}

	.ratio-label {
		flex-shrink: 0;
		color: var(--text-3);
	}

	.ratio-bar {
		flex: 1;
		display: flex;
		gap: 2px;
		height: 8px;
	}

	.ratio-in, .ratio-out { border-radius: var(--r-pill); }
	.ratio-in { background: var(--data-1); }
	.ratio-out { background: var(--data-2); }

	.ratio-text {
		font-size: var(--text-xs);
		color: var(--text-3);
		white-space: nowrap;
		min-width: 40px;
	}

	/* Threat context */
	.threat-list {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}

	.threat-item {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-2);
		border-radius: var(--r-md);
		background: var(--surface-2);
	}

	.threat-sig {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.more-note { margin-top: var(--sp-1); font-size: var(--text-xs); }

	.no-threats {
		font-size: var(--text-xs);
		padding: var(--sp-2) 0;
	}

	/* TShark controls */
	.tshark-controls {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		margin-bottom: var(--sp-4);
		flex-wrap: wrap;
	}

	.tshark-text-block, .hex-block {
		font-size: var(--text-micro);
		line-height: 1.6;
	}

	.tshark-text-block { max-height: 500px; }

	.filter-preview {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-2) var(--sp-4);
		background-color: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		margin-bottom: var(--sp-4);
	}

	.filter-label { font-size: var(--text-xs); color: var(--text-3); white-space: nowrap; }
	.filter-code { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--accent-strong); word-break: break-all; }

	/* Packet table: the system table, compacted for packet rows */
	.packet-table-wrap { margin-bottom: var(--sp-4); }
	.packet-table { font-size: var(--text-xs); }
	.packet-table th, .packet-table td { padding: var(--sp-1) var(--sp-2); }
	.packet-row { cursor: pointer; }
	.packet-row.selected td { background-color: var(--surface-2); color: var(--text-1); }

	.hex-section { margin-top: var(--sp-2); }
	.hex-title, .section-title { margin-bottom: var(--sp-2); }

	/* Related connections */
	.related-summary {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--sp-4);
		padding: var(--sp-4) 0;
	}

	.related-stat {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-1);
		text-align: center;
	}

	.stat-value {
		font: 300 var(--text-xl)/1.15 var(--font-display);
		letter-spacing: -0.03em;
		color: var(--text-1);
	}

	.stat-protos {
		display: flex;
		gap: var(--sp-1);
		flex-wrap: wrap;
		justify-content: center;
	}

	.proto-tag {
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
	}

	.stat-label {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.related-timerange {
		border-top: 1px solid var(--line);
		padding-top: var(--sp-2);
	}

	.related-timeline {
		padding-top: var(--sp-4);
	}

	/* Flow diagram */
	.flow-content {
		gap: var(--sp-4);
	}

	.flow-svg .node {
		--c: var(--data-3);
		fill: color-mix(in srgb, var(--c) 20%, transparent);
		stroke: var(--c);
		stroke-width: 1.5;
	}

	.flow-svg .node-src { --c: var(--data-1); }
	.flow-svg .node-dst { --c: var(--data-2); }

	.flow-svg .n-title {
		fill: var(--text-1);
		font-family: var(--font-mono);
		font-size: var(--text-micro);
		font-weight: 600;
	}

	.flow-svg .n-meta {
		fill: var(--text-3);
		font-family: var(--font-body);
		font-size: var(--text-micro);
	}

	.flow-svg .n-bytes {
		fill: var(--accent-strong);
		font-family: var(--font-body);
		font-size: var(--text-micro);
		font-weight: 600;
	}

	.flow-svg .alert-mark { fill: var(--sev-critical); }

	.flow-svg .alert-count {
		fill: var(--bg);
		font-family: var(--font-body);
		font-size: var(--text-micro);
		font-weight: 700;
	}

	.flow-svg .alert-word {
		fill: var(--sev-critical);
		font-family: var(--font-body);
		font-size: var(--text-micro);
		font-weight: 700;
	}

	.flow-details {
		border-top: 1px solid var(--line);
		padding-top: var(--sp-2);
	}

	/* Utility */
	.whois-raw { margin-top: var(--sp-2); }
	.whois-raw summary { font-size: var(--text-xs); color: var(--text-3); cursor: pointer; padding: var(--sp-1) 0; }

	.loading-spinner {
		width: 24px;
		height: 24px;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }
</style>
