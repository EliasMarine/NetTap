<!--
  AlertDrawerContent.svelte — Summary, Related Events, and Raw JSON tabs.
  Lifts content from AlertDetailPanel.svelte into the unified drawer.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import type { Alert } from '$api/alerts';

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
		if (!alert?.alert?.severity) return 'INFO';
		switch (alert.alert.severity) {
			case 1: return 'HIGH';
			case 2: return 'MEDIUM';
			case 3: return 'LOW';
			default: return 'INFO';
		}
	});

	let severityClass = $derived.by(() => {
		if (!alert?.alert?.severity) return 'badge';
		switch (alert.alert.severity) {
			case 1: return 'badge badge-danger';
			case 2: return 'badge badge-warning';
			case 3: return 'badge badge-accent';
			default: return 'badge';
		}
	});

	let rawJson = $derived(JSON.stringify(alert, null, 2));

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '--';
		try {
			return new Date(ts).toLocaleString(undefined, {
				year: 'numeric', month: 'short', day: 'numeric',
				hour: '2-digit', minute: '2-digit', second: '2-digit',
			});
		} catch {
			return ts;
		}
	}

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
			// Use .keyword sub-fields for reliable IP matching on ip-typed fields
			const ipClauses = ips.map(ip => `(source.ip.keyword:"${ip}" OR destination.ip.keyword:"${ip}")`).join(' OR ');
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
			<span class={severityClass}>{severityLabel}</span>
			{#if alert.alert?.category}
				<span class="badge">{alert.alert.category}</span>
			{/if}
		</div>

		<!-- Signature -->
		<DrawerSection title="Alert" defaultExpanded>
			<h3 class="alert-signature">{alert.alert?.signature || 'Unknown Alert'}</h3>
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
				<p class="section-body">{alert.recommendation}</p>
			</DrawerSection>
		{/if}

		<!-- Flow visualization -->
		<DrawerSection title="Network flow" defaultExpanded>
			<div class="flow-visualization">
				<div class="flow-endpoint">
					<span class="flow-label">Source</span>
					<span class="flow-ip">
						{#if alert.src_ip}
							<IPAddress ip={alert.src_ip} />
						{:else}
							<span class="text-muted">--</span>
						{/if}
					</span>
					{#if alert.src_port}
						<span class="flow-port mono">:{alert.src_port}</span>
					{/if}
				</div>

				<div class="flow-arrow">
					<svg viewBox="0 0 48 24" width="48" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<line x1="4" y1="12" x2="40" y2="12" />
						<polyline points="34 6 40 12 34 18" />
					</svg>
					{#if alert.proto}
						<span class="badge flow-proto-badge">{protoLabel(alert.proto)}</span>
					{/if}
				</div>

				<div class="flow-endpoint">
					<span class="flow-label">Destination</span>
					<span class="flow-ip">
						{#if alert.dest_ip}
							<IPAddress ip={alert.dest_ip} />
						{:else}
							<span class="text-muted">--</span>
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
				<KVRow label="Ack Time" value={formatTimestamp(alert.acknowledged_at)} mono />
			{/if}
		</DrawerSection>
	</div>

{:else if activeTab === 'related'}
	<div class="related-content">
		{#if relatedLoading}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="text-muted">Searching related events...</p>
			</div>
		{:else if relatedError}
			<div class="error-state">
				<p class="text-danger">{relatedError}</p>
				<button class="btn btn-secondary btn-sm" onclick={fetchRelated}>Retry</button>
			</div>
		{:else if relatedLogs.length === 0}
			<div class="empty-state">
				<p class="text-muted">No related events found</p>
			</div>
		{:else}
			<div class="related-table-wrap">
				<table class="related-table">
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
			<button class="btn btn-secondary btn-sm" onclick={copyJson}>
				{copied ? 'Copied!' : 'Copy JSON'}
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
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.alert-signature {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
		line-height: 1.3;
		margin-bottom: var(--space-sm);
	}

	.section-body {
		font-size: var(--text-sm);
		color: var(--text-primary);
		line-height: 1.6;
	}

	/* Flow visualization */
	.flow-visualization {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-md);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		flex-wrap: wrap;
		justify-content: center;
	}

	.flow-endpoint {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
	}

	.flow-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 600;
	}

	.flow-ip {
		font-size: var(--text-sm);
		color: var(--accent);
		word-break: break-all;
		text-align: center;
	}

	.flow-port {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.flow-arrow {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.flow-proto-badge {
		font-size: 10px;
		padding: 1px 6px;
	}

	/* Related events table */
	.related-table-wrap {
		overflow-x: auto;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.related-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-xs);
	}

	.related-table th {
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

	.related-table td {
		padding: var(--space-xs) var(--space-sm);
		border-bottom: 1px solid var(--border-dim);
		color: var(--text-primary);
	}

	.related-row {
		cursor: pointer;
		transition: background-color var(--transition-fast);
	}

	.related-row:hover {
		background-color: var(--bg-tertiary);
	}

	/* Common */
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

	.mono { font-family: var(--font-mono); }
	.text-danger { color: var(--danger); font-size: var(--text-sm); }
	.text-muted { color: var(--text-muted); font-size: var(--text-sm); }

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
