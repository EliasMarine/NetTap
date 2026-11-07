<!--
  AlertDrawerContent.svelte — Summary, Related Events, and Raw JSON tabs.
  Lifts content from AlertDetailPanel.svelte into the unified drawer.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import { suricataLevel } from '$lib/utils/severity';
	import IPAddress from '$components/IPAddress.svelte';
	import type { Alert } from '$api/alerts';
	import { formatTime } from '$lib/utils/time';

	let {
		alert,
		activeTab,
		onacknowledge = (_id: string) => {},
	}: {
		alert: Alert;
		activeTab: string;
		onacknowledge?: (id: string) => void;
	} = $props();

	// Related events state
	let relatedLogs = $state<Array<{ _id: string; _source: Record<string, unknown> }>>([]);
	let relatedLoading = $state(false);
	let relatedError = $state('');
	let relatedLoaded = $state(false);

	// Copy state
	let copied = $state(false);

	// Derived
	let severityLabel = $derived.by(() => {
		if (!alert?.alert?.severity) return 'Info';
		switch (alert.alert.severity) {
			case 1: return 'High';
			case 2: return 'Medium';
			case 3: return 'Low';
			default: return 'Info';
		}
	});

	// OLD CODE START — 2026-11-03: the badge is the shared SeverityPill, which takes the level, not a class
	// let severityClass = $derived.by(() => {
	// 	if (!alert?.alert?.severity) return 'sev sev-info';
	// 	switch (alert.alert.severity) {
	// 		case 1: return 'sev sev-high';
	// 		case 2: return 'sev sev-medium';
	// 		case 3: return 'sev sev-low';
	// 		default: return 'sev sev-info';
	// 	}
	// });
	// OLD CODE END
	// OLD CODE START — the same mapping now lives once in $lib/utils/severity (NET-146)
	// let severityLevel = $derived.by((): SeverityLevel => {
	// 	switch (alert?.alert?.severity) {
	// 		case 1: return 'high';
	// 		case 2: return 'medium';
	// 		case 3: return 'low';
	// 		default: return 'info';
	// 	}
	// });
	// OLD CODE END
	let severityLevel = $derived(suricataLevel(alert?.alert?.severity));

	let rawJson = $derived(JSON.stringify(alert, null, 2));

	// OLD CODE START — the browser's locale printed "Nov 6, 2026, 10:37:23 PM" (NET-192 PR 4: formatTime)
	// function formatTimestamp(ts: string | undefined): string {
	// 	if (!ts) return '--';
	// 	try {
	// 		return new Date(ts).toLocaleString(undefined, {
	// 			year: 'numeric', month: 'short', day: 'numeric',
	// 			hour: '2-digit', minute: '2-digit', second: '2-digit',
	// 		});
	// 	} catch {
	// 		return ts;
	// 	}
	// }
	// OLD CODE END
	const formatTimestamp = (ts: string | undefined) => formatTime(ts);

	function protoLabel(proto: string | undefined): string {
		return proto ? proto.toUpperCase() : '?';
	}

	function copyJson() {
		navigator.clipboard.writeText(rawJson);
		copied = true;
		setTimeout(() => { copied = false; }, 1500);
	}

	function viewDevice(ip: string) {
		goto(`/devices/${encodeURIComponent(ip)}`);
	}

	function viewInLogExplorer() {
		const ips = [alert.src_ip, alert.dest_ip].filter(Boolean);
		const query = ips.map(ip => `(source.ip:"${ip}" OR destination.ip:"${ip}")`).join(' OR ');
		goto(`/logs?query=${encodeURIComponent(query)}`);
	}

	// Lazy load related events
	$effect(() => {
		if (activeTab === 'related' && !relatedLoaded) {
			relatedLoaded = true;
			fetchRelated();
		}
	});

	async function fetchRelated() {
		relatedLoading = true;
		relatedError = '';
		try {
			const ips = [alert.src_ip, alert.dest_ip].filter(Boolean);
			if (ips.length === 0) {
				relatedLoading = false;
				return;
			}
			// OLD CODE START — replaced 2026-11-01: .keyword sub-fields only existed while
			// malcolm_template didn't apply; with Malcolm's mapping source/destination.ip
			// are ip fields with no .keyword (Chain 24).
			// const ipClauses = ips.map(ip => `(source.ip.keyword:"${ip}" OR destination.ip.keyword:"${ip}")`).join(' OR ');
			// OLD CODE END
			const ipClauses = ips.map(ip => `(source.ip:"${ip}" OR destination.ip:"${ip}")`).join(' OR ');
			// Exclude this alert from results
			const query = `(${ipClauses}) AND NOT _id:"${alert._id}"`;
			// Time window: ±1 hour around the alert timestamp
			const alertTime = new Date(alert.timestamp);
			const from = new Date(alertTime.getTime() - 3600_000).toISOString();
			const to = new Date(alertTime.getTime() + 3600_000).toISOString();
			const params = new URLSearchParams({ query, size: '20', from, to });
			const res = await fetch(`/api/logs/search?${params.toString()}`);
			if (res.ok) {
				const data = await res.json();
				relatedLogs = data.hits || [];
			} else {
				relatedError = 'Failed to fetch related events';
			}
		} catch {
			relatedError = 'Network error fetching related events';
		} finally {
			relatedLoading = false;
		}
	}
</script>

{#if activeTab === 'summary'}
	<div class="summary-content">
		<!-- Severity and category -->
		<div class="alert-badges">
			<SeverityPill level={severityLevel} />
			{#if alert.alert?.category}
				<span class="chip">{alert.alert.category}</span>
			{/if}
		</div>

		<!-- Signature -->
		<DrawerSection title="Alert" defaultExpanded>
			<h3 class="alert-signature">{alert.alert?.signature || 'Unknown alert'}</h3>
			<KVRow label="Timestamp" value={formatTimestamp(alert.timestamp)} mono />
			<KVRow label="Signature ID" value={alert.alert?.signature_id} mono />
			<KVRow label="Severity" value={severityLabel} />
		</DrawerSection>

		<!-- Description -->
		{#if alert.plain_description}
			<DrawerSection title="What happened" defaultExpanded>
				<p class="section-body">{alert.plain_description}</p>
			</DrawerSection>
		{/if}

		<!-- Risk context -->
		{#if alert.risk_context}
			<DrawerSection title="Risk context" defaultExpanded>
				<p class="section-body">{alert.risk_context}</p>
			</DrawerSection>
		{/if}

		<!-- Recommendation -->
		{#if alert.recommendation}
			<DrawerSection title="Recommendation" defaultExpanded={false}>
				<div class="todo"><b>What to do</b>{alert.recommendation}</div>
			</DrawerSection>
		{/if}

		<!-- Flow visualization -->
		<DrawerSection title="Network flow" defaultExpanded>
			<div class="flow-visualization">
				<div class="flow-endpoint">
					<span class="eyebrow">Source</span>
					<span class="flow-ip">
						{#if alert.src_ip}
							<IPAddress ip={alert.src_ip} />
						{:else}
							<span class="dim">--</span>
						{/if}
					</span>
					{#if alert.src_port}
						<span class="flow-port mono">:{alert.src_port}</span>
					{/if}
				</div>

				<div class="flow-arrow">
					<svg viewBox="0 0 48 24" width="48" height="24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
						<line x1="4" y1="12" x2="40" y2="12" />
						<polyline points="34 6 40 12 34 18" />
					</svg>
					{#if alert.proto}
						<span class="tag">{protoLabel(alert.proto)}</span>
					{/if}
				</div>

				<div class="flow-endpoint">
					<span class="eyebrow">Destination</span>
					<span class="flow-ip">
						{#if alert.dest_ip}
							<IPAddress ip={alert.dest_ip} />
						{:else}
							<span class="dim">--</span>
						{/if}
					</span>
					{#if alert.dest_port}
						<span class="flow-port mono">:{alert.dest_port}</span>
					{/if}
				</div>
			</div>
		</DrawerSection>

		<!-- Metadata -->
		<DrawerSection title="Metadata" defaultExpanded={false}>
			<KVRow label="Alert ID" value={alert._id} mono copyable />
			<KVRow label="Index" value={alert._index} mono />
			<KVRow label="Status" value={alert.acknowledged ? 'Acknowledged' : 'Unacknowledged'} />
			{#if alert.acknowledged_at}
				<KVRow label="Acknowledged at" value={formatTimestamp(alert.acknowledged_at)} mono />
			{/if}
		</DrawerSection>
	</div>

{:else if activeTab === 'related'}
	<div class="related-content">
		{#if relatedLoading}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="dim">Searching related events…</p>
			</div>
		{:else if relatedError}
			<div class="error-state">
				<p class="error-text">{relatedError}</p>
				<button class="btn" type="button" onclick={fetchRelated}>Retry</button>
			</div>
		{:else if relatedLogs.length === 0}
			<div class="empty-state">
				<p class="dim">No related events found</p>
			</div>
		{:else}
			<div class="tbl-wrap">
				<table>
					<thead>
						<tr>
							<th>Timestamp</th>
							<th>Type</th>
							<th>Source</th>
							<th>Destination</th>
						</tr>
					</thead>
					<tbody>
						{#each relatedLogs as log}
							<tr class="related-row" onclick={() => goto(`/logs?query=_id:${log._id}`)}>
								<td class="mono">{formatTimestamp(String(log._source['@timestamp'] || ''))}</td>
								<td>{log._source['event.dataset'] || log._source['event.provider'] || '--'}</td>
								<td class="mono">{log._source['source.ip'] || '--'}</td>
								<td class="mono">{log._source['destination.ip'] || '--'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>

{:else if activeTab === 'raw'}
	<div class="raw-content">
		<div class="raw-header">
			<button class="btn" type="button" onclick={copyJson}>
				{copied ? 'Copied' : 'Copy JSON'}
			</button>
		</div>
		<pre class="raw-block">{rawJson}</pre>
	</div>
{/if}

<style>
	.summary-content, .related-content, .raw-content {
		display: flex;
		flex-direction: column;
	}

	.alert-badges {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
		margin-bottom: var(--sp-4);
	}

	.alert-signature {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-1);
		line-height: 1.4;
		overflow-wrap: anywhere;
		margin-bottom: var(--sp-2);
	}

	.section-body {
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.6;
	}

	/* Flow visualization */
	.flow-visualization {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-4);
		background-color: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		flex-wrap: wrap;
		justify-content: center;
	}

	.flow-endpoint {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
	}

	.flow-ip {
		font-size: var(--text-sm);
		color: var(--text-1);
		overflow-wrap: anywhere;
		text-align: center;
	}

	.flow-port {
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.flow-arrow {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		color: var(--text-3);
		flex-shrink: 0;
	}

	/* Related events table (system table styles) */
	.related-row {
		cursor: pointer;
	}

	/* Common */
	.loading-state, .error-state, .empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		padding: var(--sp-8) 0;
		text-align: center;
		font-size: var(--text-sm);
	}

	.error-text { color: var(--sev-critical); }

	.raw-content { gap: var(--sp-2); }

	.raw-header {
		display: flex;
		justify-content: flex-end;
	}

	.raw-block {
		font-size: var(--text-xs);
		color: var(--text-1);
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 600px;
		overflow-y: auto;
		line-height: 1.5;
	}

	.loading-spinner {
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
</style>
