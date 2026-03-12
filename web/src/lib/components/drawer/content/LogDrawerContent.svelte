<!--
  LogDrawerContent.svelte — Fields and Raw JSON tabs for log entries.
  Fetches full document on mount, groups fields by category prefix.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import DrawerSection from '../DrawerSection.svelte';
	import KVRow from '../KVRow.svelte';
	import { getWhois } from '$api/lookup';
	import type { WhoisResult } from '$api/lookup';

	interface LogHit {
		_id: string;
		_index?: string;
		_source: Record<string, unknown>;
		sort?: unknown[];
	}

	let {
		hit,
		activeTab,
		timeRange = '',
	}: {
		hit: LogHit;
		activeTab: string;
		timeRange?: string;
	} = $props();

	// Full doc state
	let fullDoc = $state<Record<string, unknown> | null>(null);
	let fullDocLoading = $state(true);
	let fullDocError = $state('');

	// WHOIS state
	let whoisResult = $state<WhoisResult | null>(null);
	let whoisLoading = $state(false);
	let whoisIp = $state('');

	// Copy state
	let copied = $state(false);

	// Field grouping
	const GROUP_ORDER = ['source', 'destination', 'network', 'event', 'zeek', 'suricata', 'system'];
	const GROUP_LABELS: Record<string, string> = {
		source: 'Source',
		destination: 'Destination',
		network: 'Network',
		event: 'Event',
		zeek: 'Zeek',
		suricata: 'Suricata',
		system: 'System',
	};

	interface FieldEntry {
		key: string;
		value: unknown;
	}

	let groupedFields = $derived.by(() => {
		const doc = fullDoc ?? hit._source;
		const flat = flattenObject(doc);
		const groups: Record<string, FieldEntry[]> = {};

		for (const [key, value] of Object.entries(flat)) {
			const prefix = key.split('.')[0];
			const group = GROUP_ORDER.includes(prefix) ? prefix : 'system';
			if (!groups[group]) groups[group] = [];
			groups[group].push({ key, value });
		}

		return GROUP_ORDER
			.filter((g) => groups[g]?.length)
			.map((g) => ({ group: g, label: GROUP_LABELS[g] || g, fields: groups[g] }));
	});

	let rawJson = $derived(JSON.stringify(fullDoc ?? hit._source, null, 2));

	function flattenObject(obj: Record<string, unknown>, prefix = ''): Record<string, unknown> {
		const result: Record<string, unknown> = {};
		for (const [key, value] of Object.entries(obj)) {
			const fullKey = prefix ? `${prefix}.${key}` : key;
			if (value && typeof value === 'object' && !Array.isArray(value)) {
				Object.assign(result, flattenObject(value as Record<string, unknown>, fullKey));
			} else {
				result[fullKey] = value;
			}
		}
		return result;
	}

	function formatValue(val: unknown): string {
		if (val == null) return '--';
		if (Array.isArray(val)) return val.join(', ');
		return String(val);
	}

	function isMonoField(key: string): boolean {
		return key.includes('ip') || key.includes('port') || key.includes('mac')
			|| key.includes('bytes') || key.includes('duration') || key === '_id'
			|| key.includes('uid') || key.includes('hash');
	}

	async function fetchFullDocument() {
		fullDocLoading = true;
		fullDocError = '';
		try {
			const params = new URLSearchParams();
			params.set('query', `_id:${hit._id}`);
			params.set('size', '1');
			if (timeRange) params.set('from', timeRange);
			params.set('to', new Date().toISOString());
			const res = await fetch(`/api/logs/search?${params.toString()}`);
			if (res.ok) {
				const data = await res.json();
				if (data.hits?.length > 0) {
					fullDoc = data.hits[0]._source;
				}
			}
		} catch {
			fullDocError = 'Failed to fetch full document';
		} finally {
			fullDocLoading = false;
		}
	}

	function copyJson() {
		navigator.clipboard.writeText(rawJson);
		copied = true;
		setTimeout(() => { copied = false; }, 1500);
	}

	function getSourceIp(): string | null {
		const doc = fullDoc ?? hit._source;
		const flat = flattenObject(doc);
		const ip = flat['source.ip'];
		if (Array.isArray(ip)) return String(ip[0]);
		return ip ? String(ip) : null;
	}

	async function lookupWhois() {
		const ip = getSourceIp();
		if (!ip) return;
		whoisIp = ip;
		whoisLoading = true;
		whoisResult = null;
		try {
			whoisResult = await getWhois(ip);
		} finally {
			whoisLoading = false;
		}
	}

	function viewSourceDevice() {
		const ip = getSourceIp();
		if (ip) goto(`/devices/${encodeURIComponent(ip)}`);
	}

	onMount(() => {
		fetchFullDocument();
	});
</script>

{#if activeTab === 'fields'}
	<div class="fields-content">
		{#if fullDocLoading}
			<div class="loading-state">
				<div class="loading-spinner"></div>
				<p class="text-muted">Loading fields...</p>
			</div>
		{:else if fullDocError}
			<div class="error-state">
				<p class="text-danger">{fullDocError}</p>
				<button class="btn btn-secondary btn-sm" onclick={fetchFullDocument}>Retry</button>
			</div>
		{:else}
			{#each groupedFields as { label, fields }, i}
				<DrawerSection title={label} defaultExpanded={i < 3}>
					{#each fields as { key, value }}
						<KVRow label={key} value={formatValue(value)} mono={isMonoField(key)} copyable />
					{/each}
				</DrawerSection>
			{/each}
		{/if}

		<!-- WHOIS inline result -->
		{#if whoisResult}
			<DrawerSection title="WHOIS — {whoisIp}" defaultExpanded>
				{#if whoisResult.error}
					<p class="text-danger" style="font-size: var(--text-sm);">{whoisResult.error}</p>
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
	.fields-content {
		display: flex;
		flex-direction: column;
	}

	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-2xl) 0;
	}

	.error-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-lg) 0;
	}

	.raw-content {
		display: flex;
		flex-direction: column;
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

	.whois-raw {
		margin-top: var(--space-sm);
	}

	.whois-raw summary {
		font-size: var(--text-xs);
		color: var(--text-muted);
		cursor: pointer;
		padding: var(--space-xs) 0;
	}

	.text-danger {
		color: var(--danger);
	}

	.text-muted {
		color: var(--text-muted);
	}

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
