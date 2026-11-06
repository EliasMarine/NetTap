<script lang="ts">
	/** DNS reconnaissance: a form card (domain and record types), then one card per record type with a DataTable. */
	import { page } from '$app/stores';
	import { dnsRecon } from '$api/tools';
	import type { DnsReconResult, DnsReconRecord } from '$api/tools';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// ---------------------------------------------------------------------------
	// Record type definitions with display metadata
	// ---------------------------------------------------------------------------

	interface RecordTypeDef {
		type: string;
		label: string;
		defaultSelected: boolean;
	}

	const recordTypeDefs: RecordTypeDef[] = [
		{ type: 'A', label: 'Address records', defaultSelected: true },
		{ type: 'AAAA', label: 'IPv6 address records', defaultSelected: true },
		{ type: 'CNAME', label: 'Canonical name records', defaultSelected: true },
		{ type: 'MX', label: 'Mail exchange records', defaultSelected: true },
		{ type: 'NS', label: 'Name server records', defaultSelected: true },
		{ type: 'TXT', label: 'Text records', defaultSelected: true },
		{ type: 'SOA', label: 'Start of authority', defaultSelected: true },
		{ type: 'PTR', label: 'Pointer records', defaultSelected: false },
		{ type: 'SRV', label: 'Service records', defaultSelected: false },
	];

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let domain = $state('');
	let selectedTypes = $state<Set<string>>(
		new Set(recordTypeDefs.filter((d) => d.defaultSelected).map((d) => d.type))
	);
	let result = $state<DnsReconResult | null>(null);
	let loading = $state(false);
	let error = $state('');

	// NET-160: the domain page's "Look it up now" fills the domain in; the lookup waits for the user
	// OLD CODE START — reran on every $page emission, so it could overwrite what the user had typed
	// $effect(() => {
	// 	const d = $page.url.searchParams.get('domain');
	// 	if (d) domain = d;
	// });
	// OLD CODE END
	let appliedUrl: URL | null = null;
	$effect(() => {
		const url = $page.url;
		if (url === appliedUrl) return; // the same navigation emitted again
		appliedUrl = url;
		const d = url.searchParams.get('domain');
		if (d) domain = d;
	});

	// ---------------------------------------------------------------------------
	// Actions
	// ---------------------------------------------------------------------------

	function toggleType(type: string) {
		const next = new Set(selectedTypes);
		if (next.has(type)) {
			next.delete(type);
		} else {
			next.add(type);
		}
		selectedTypes = next;
	}

	async function handleLookup() {
		const trimmed = domain.trim();
		if (!trimmed) return;

		loading = true;
		error = '';
		result = null;

		try {
			const types = [...selectedTypes];
			result = await dnsRecon(trimmed, types.length > 0 ? types : undefined);
			if (result.errors && result.errors.length > 0) {
				error = result.errors.join('; ');
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'DNS lookup failed';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleLookup();
		}
	}

	// Ordered record types to display (match order of recordTypeDefs)
	let orderedResultTypes = $derived(
		result
			? recordTypeDefs
					.map((d) => d.type)
					.filter((t) => result!.records[t] !== undefined)
			: []
	);

	function getTypeDef(type: string): RecordTypeDef {
		return recordTypeDefs.find((d) => d.type === type) || { type, label: type, defaultSelected: false };
	}

	// A record has no id of its own, so each row carries its position as the table key
	type RecordRow = DnsReconRecord & { i: number };
	const recordRows = (records: DnsReconRecord[]): RecordRow[] => records.map((r, i) => ({ ...r, i }));

	const recordColumns: Column<RecordRow>[] = [
		{ key: 'name', label: 'Name', cell: monoName },
		{ key: 'ttl', label: 'TTL', numeric: true },
		{ key: 'value', label: 'Value', cell: monoValue },
	];
</script>

{#snippet monoName(r: RecordRow)}<span class="mono">{r.name}</span>{/snippet}
{#snippet monoValue(r: RecordRow)}<span class="mono value">{r.value}</span>{/snippet}

<svelte:head>
	<title>DNS reconnaissance | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">DNS reconnaissance</h1>
		<p class="page-sub">List every DNS record a domain publishes, queried with dig.</p>
	</div>
</div>

<div class="grid">
	<Card title="Look up a domain" sub="One domain · the record types you choose" class="c-12">
		<div class="form-grid">
			<div class="field">
				<label class="label" for="recon-domain">Domain</label>
				<input id="recon-domain" class="input mono" type="text" placeholder="example.com" bind:value={domain} onkeydown={handleKeydown} />
			</div>
			<div class="field">
				<span class="label" id="recon-types">Record types</span>
				<div class="pills types" role="group" aria-labelledby="recon-types">
					{#each recordTypeDefs as def (def.type)}
						<button class="pill mono" type="button" aria-pressed={selectedTypes.has(def.type)} title={def.label} onclick={() => toggleType(def.type)}>
							{def.type}
						</button>
					{/each}
				</div>
			</div>
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleLookup} disabled={loading || !domain.trim()}>
				<Icon name="search" />{loading ? 'Looking up…' : 'Lookup'}
			</button>
		</div>
	</Card>

	{#if loading}
		<Card title="Records" sub="Querying each record type" class="c-12">
			<CardState state="loading" title="Looking up DNS records" />
		</Card>
	{/if}

	{#if error && !loading}
		<p class="notice is-error c-12" role="alert"><Icon name="warn" />{error}</p>
	{/if}

	{#if result && !loading}
		<div class="chips c-12">
			<span class="chip">{result.total_records} records found</span>
			<span class="chip">{result.record_types_queried.length} queries</span>
		</div>
		{#each orderedResultTypes as type (type)}
			{@const records = result.records[type] || []}
			{@const def = getTypeDef(type)}
			<Card title="{type} · {def.label}" sub="{records.length} record{records.length !== 1 ? 's' : ''} · TTL in seconds" class="c-12">
				{#if records.length > 0}
					<DataTable columns={recordColumns} rows={recordRows(records)} ariaLabel="{type} records" rowKey={(r) => r.i} />
				{:else}
					<p class="dim none">No {type} records found</p>
				{/if}
			</Card>
		{/each}
	{:else if !loading && !error}
		<Card title="Records" sub="Grouped by record type" class="c-12">
			<CardState state="empty" icon="dns" title="Enter a domain" message="Type a domain, choose the record types, then choose Lookup." />
		</Card>
	{/if}
</div>

<style>
	/* Layout glue: the record-type toggles wrap; long TXT values wrap inside their cell */
	.types { flex-wrap: wrap; align-self: flex-start; }
	.value { white-space: normal; overflow-wrap: anywhere; }
	.none { font-size: var(--text-sm); }
</style>
