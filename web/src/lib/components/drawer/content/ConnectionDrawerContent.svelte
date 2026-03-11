<!--
  ConnectionDrawerContent.svelte — Details, TShark Analysis, and Raw JSON tabs.
  TShark runs inline in the drawer (no navigation to /tools/tshark).
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import { getWhois } from '$api/lookup';
	import type { WhoisResult } from '$api/lookup';
	import { buildTSharkFilter, getField, asString } from '$lib/utils/tshark-filter';
	import { analyzePcap, getTSharkStatus, getPcapFiles } from '$api/tshark';
	import type { TSharkPacket, PcapFile } from '$api/tshark';

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
	let selectedPacketIdx = $state<number | null>(null);
	let hexContent = $state('');
	let hexLoading = $state(false);
	let tsharkTabLoaded = $state(false);

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

	let rawJson = $derived(JSON.stringify(connection._source || connection, null, 2));

	// Connection state descriptions
	const STATE_DESC: Record<string, string> = {
		S0: 'Connection attempt seen, no reply',
		S1: 'Connection established, not terminated',
		SF: 'Normal establishment and termination',
		REJ: 'Connection attempt rejected',
		S2: 'Connection established, close attempted by originator',
		S3: 'Connection established, close attempted by responder',
		RSTO: 'Connection established, originator aborted',
		RSTR: 'Connection established, responder aborted',
		RSTOS0: 'Originator sent a SYN then RST, responder never replied',
		RSTRH: 'Responder sent a SYN ACK then RST, originator never replied',
		SH: 'Originator sent SYN then FIN, responder never replied (half-open)',
		SHR: 'Responder sent SYN ACK then FIN, originator never replied',
		OTH: 'No SYN seen, midstream traffic',
	};

	function formatDuration(val: unknown): string {
		if (val == null) return '--';
		const n = Number(val);
		if (isNaN(n)) return String(val);
		if (n < 1) return `${(n * 1000).toFixed(0)}ms`;
		if (n < 60) return `${n.toFixed(1)}s`;
		return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`;
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

	// TShark
	$effect(() => {
		if (activeTab === 'tshark' && !tsharkTabLoaded) {
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
				// Auto-analyze if PCAPs found
				if (pcapFiles.length > 0) {
					autoAnalyze();
				}
			} catch {
				tsharkError = 'Failed to load PCAP files';
			} finally {
				pcapLoading = false;
			}
		}
	}

	async function autoAnalyze() {
		if (pcapFiles.length === 0 || !displayFilter) return;

		// Sort PCAPs by closeness to connection timestamp
		const connTs = timestamp ? new Date(timestamp).getTime() : Date.now();
		const sorted = [...pcapFiles].sort((a, b) => {
			const da = Math.abs((a.modified * 1000) - connTs);
			const db = Math.abs((b.modified * 1000) - connTs);
			return da - db;
		});

		analyzing = true;
		tsharkError = '';
		packets = [];

		// Try up to 3 closest PCAPs
		for (const pcap of sorted.slice(0, 3)) {
			try {
				const result = await analyzePcap({
					pcap_path: pcap.path,
					display_filter: displayFilter,
					max_packets: 200,
					output_format: 'json',
				});

				if (result.error) continue;
				if (result.packets.length > 0) {
					packets = result.packets;
					break;
				}
			} catch {
				continue;
			}
		}

		if (packets.length === 0) {
			tsharkError = 'No matching packets found in available PCAPs';
		}
		analyzing = false;
	}

	async function fetchHexForPacket(idx: number) {
		selectedPacketIdx = idx;
		hexLoading = true;
		hexContent = '';

		const pkt = packets[idx];
		const frameNum = pkt?.['_source']?.['layers']?.['frame']?.['frame.number'] || (idx + 1);

		// Find the PCAP that had results — use the same sorted approach
		const connTs = timestamp ? new Date(timestamp).getTime() : Date.now();
		const sorted = [...pcapFiles].sort((a, b) => {
			return Math.abs((a.modified * 1000) - connTs) - Math.abs((b.modified * 1000) - connTs);
		});

		for (const pcap of sorted.slice(0, 3)) {
			try {
				const result = await analyzePcap({
					pcap_path: pcap.path,
					display_filter: `${displayFilter} && frame.number == ${frameNum}`,
					max_packets: 1,
					output_format: 'text',
				});

				if (result.error) continue;
				if (result.packets?.length > 0) {
					// Text output includes hex — extract it
					const raw = result.packets[0]?.raw || result.packets[0]?.['_raw'] || '';
					hexContent = typeof raw === 'string' ? raw : JSON.stringify(result.packets[0], null, 2);
					break;
				}
			} catch {
				continue;
			}
		}

		if (!hexContent) {
			hexContent = '(No hex data available for this packet)';
		}
		hexLoading = false;
	}

	function getPacketInfo(pkt: TSharkPacket): { no: string; time: string; src: string; dst: string; proto: string; len: string; info: string } {
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
</script>

{#if activeTab === 'details'}
	<div class="details-content">
		<DrawerSection title="Connection" defaultExpanded>
			<KVRow label="UID" value={uid} mono copyable />
			<KVRow label="Timestamp" value={timestamp} mono />
			<KVRow label="Source IP" value={srcIp} mono copyable />
			<KVRow label="Source Port" value={srcPort} mono />
			<KVRow label="Dest IP" value={dstIp} mono copyable />
			<KVRow label="Dest Port" value={dstPort} mono />
			<KVRow label="Protocol" value={proto?.toUpperCase()} />
			<KVRow label="Service" value={service} />
		</DrawerSection>

		<DrawerSection title="Traffic" defaultExpanded>
			<KVRow label="Duration" value={formatDuration(duration)} mono />
			<KVRow label="Orig Bytes" value={formatBytes(origBytes)} mono />
			<KVRow label="Resp Bytes" value={formatBytes(respBytes)} mono />
			<KVRow label="Orig Packets" value={origPkts} mono />
			<KVRow label="Resp Packets" value={respPkts} mono />
		</DrawerSection>

		<DrawerSection title="State" defaultExpanded={false}>
			<KVRow label="Conn State" value={connState} mono />
			{#if connState && STATE_DESC[connState]}
				<KVRow label="Description" value={STATE_DESC[connState]} />
			{/if}
			<KVRow label="History" value={history} mono copyable />
			<KVRow label="Community ID" value={communityId} mono copyable />
			<KVRow label="Index" value={connection._index} mono />
		</DrawerSection>

		<!-- WHOIS inline result -->
		{#if whoisResult}
			<DrawerSection title="WHOIS — {whoisIp}" defaultExpanded>
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
			<!-- Filter preview -->
			<div class="filter-preview">
				<span class="filter-label">Display filter:</span>
				<code class="filter-code">{displayFilter || '(none)'}</code>
			</div>

			{#if analyzing}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="text-muted">Analyzing packets...</p>
				</div>
			{:else if tsharkError}
				<div class="error-state">
					<p class="text-muted">{tsharkError}</p>
					<button class="btn btn-secondary btn-sm" onclick={autoAnalyze}>Retry</button>
				</div>
			{:else if packets.length > 0}
				<!-- Packet table -->
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
								{@const info = getPacketInfo(pkt)}
								<tr
									class="packet-row"
									class:selected={selectedPacketIdx === i}
									onclick={() => fetchHexForPacket(i)}
								>
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

				<!-- Hex dump -->
				<div class="hex-section">
					<h4 class="hex-title">Hex Dump</h4>
					{#if selectedPacketIdx === null}
						<p class="text-muted">Click a packet row to view hex dump</p>
					{:else if hexLoading}
						<div class="loading-state">
							<div class="loading-spinner"></div>
							<p class="text-muted">Loading hex...</p>
						</div>
					{:else}
						<pre class="raw-block hex-block">{hexContent}</pre>
					{/if}
				</div>
			{:else if pcapLoading}
				<div class="loading-state">
					<div class="loading-spinner"></div>
					<p class="text-muted">Loading PCAP files...</p>
				</div>
			{:else}
				<div class="empty-state">
					<p class="text-muted">No PCAP files available</p>
				</div>
			{/if}
		{/if}
	</div>

{:else if activeTab === 'raw'}
	<div class="raw-content">
		<div class="raw-header">
			<button class="btn btn-secondary btn-sm" onclick={copyJson}>
				{copied ? 'Copied!' : 'Copy JSON'}
			</button>
		</div>
		<pre class="raw-block">{rawJson}</pre>
	</div>
{/if}

<style>
	.details-content, .tshark-content, .raw-content {
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

	.raw-content {
		gap: var(--space-sm);
	}

	.raw-header {
		display: flex;
		justify-content: flex-end;
	}

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

	.filter-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		white-space: nowrap;
	}

	.filter-code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--accent);
		word-break: break-all;
	}

	.packet-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		margin-bottom: var(--space-md);
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

	.packet-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.packet-row:hover {
		background-color: var(--bg-tertiary);
	}

	.packet-row.selected {
		background-color: var(--accent-muted);
	}

	.packet-row.selected td {
		color: var(--accent);
	}

	.hex-section {
		margin-top: var(--space-sm);
	}

	.hex-title {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: var(--space-sm);
	}

	.hex-block {
		font-size: 11px;
		line-height: 1.6;
	}

	.whois-raw {
		margin-top: var(--space-sm);
	}

	.whois-raw summary {
		font-size: var(--text-xs);
		color: var(--text-muted);
		cursor: pointer;
		padding: var(--space-xs) 0;
	}

	.mono {
		font-family: var(--font-mono);
	}

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

	@keyframes spin {
		to { transform: rotate(360deg); }
	}
</style>
