<script lang="ts">
	/**
	 * NET-262: the DNS page's "Compare resolvers" tab. Asks up to six resolvers the same question at
	 * once, then says in plain English whether they agree, with each reply in a DataTable.
	 * Labels never leave the browser; the last resolver list is kept in localStorage.
	 */
	import { onMount } from 'svelte';
	import { dnsCompare } from '$api/tools';
	import type { DnsCompareReply, DnsCompareResult } from '$api/tools';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { compareVerdict, labeller, MAX_RESOLVERS, saveResolvers, savedResolvers, type ResolverRow } from './dns-compare';

	interface Props {
		recordTypes: { type: string; label: string }[];
	}

	let { recordTypes }: Props = $props();

	let name = $state('');
	let recordType = $state('A');
	let rows = $state<ResolverRow[]>([
		{ ip: '', label: '' },
		{ ip: '', label: '' },
	]);
	let asked = $state<ResolverRow[]>([]);
	let result = $state<DnsCompareResult | null>(null);
	let loading = $state(false);
	let error = $state('');

	// After mount, so the server's empty rows and the browser's first render match
	onMount(() => {
		rows = savedResolvers();
	});

	const filled = $derived(rows.filter((r) => r.ip.trim()));
	const nameOf = $derived(labeller(asked));
	const verdict = $derived(result ? compareVerdict(result.results, nameOf) : null);

	function setRow(index: number, field: keyof ResolverRow, value: string) {
		rows = rows.map((r, i) => (i === index ? { ...r, [field]: value } : r));
	}

	async function compare() {
		const trimmed = name.trim();
		if (!trimmed || filled.length === 0 || loading) return;
		loading = true;
		error = '';
		result = null;
		asked = filled;
		saveResolvers(filled);
		try {
			result = await dnsCompare(trimmed, recordType, filled.map((r) => r.ip.trim()));
		} catch (e) {
			error = e instanceof Error ? e.message : 'The resolver compare failed.';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') compare();
	}

	const columns: Column<DnsCompareReply>[] = [
		{ key: 'resolver', label: 'Resolver', cell: resolverCell, sortValue: (r) => nameOf(r.resolver) },
		{ key: 'status', label: 'Status', cell: statusCell },
		{ key: 'answers', label: 'Answers', cell: answersCell, sortValue: (r) => r.answers.map((a) => a.value).join(' ') },
		{ key: 'ttl', label: 'TTL', numeric: true, cell: ttlCell },
		{ key: 'latency_ms', label: 'Latency', numeric: true, cell: latencyCell },
	];
</script>

{#snippet resolverCell(r: DnsCompareReply)}
	{#if nameOf(r.resolver) !== r.resolver}<span class="who-label">{nameOf(r.resolver)}</span>{/if}
	<span class="mono">{r.resolver}</span>
{/snippet}
{#snippet statusCell(r: DnsCompareReply)}
	{#if r.status}<span class="mono">{r.status}</span>{:else}<span class="chip is-caution">No reply</span>{/if}
{/snippet}
{#snippet answersCell(r: DnsCompareReply)}
	{#if r.error}
		<span class="dim">{r.error}</span>
	{:else if r.answers.length === 0}
		<span class="dim">None</span>
	{:else}
		<ul class="answers">
			{#each r.answers as a, i (i)}
				<li>
					{#if a.type !== result?.record_type}<span class="dim mono">{a.type}</span>{/if}
					<span class="mono value">{a.value}</span>
					{#if a.scope}<span class="dim">{a.scope}</span>{/if}
				</li>
			{/each}
		</ul>
	{/if}
{/snippet}
{#snippet ttlCell(r: DnsCompareReply)}{r.ttl ?? '—'}{/snippet}
{#snippet latencyCell(r: DnsCompareReply)}{r.latency_ms ?? '—'}{/snippet}

<div class="grid">
	<Card title="Compare resolvers" sub="One name · up to {MAX_RESOLVERS} resolvers, asked at the same time" class="c-12">
		<div class="form-grid">
			<div class="field">
				<label class="label" for="compare-name">Name</label>
				<input id="compare-name" class="input mono" type="text" placeholder="example.com" bind:value={name} onkeydown={handleKeydown} />
			</div>
			<div class="field">
				<label class="label" for="compare-type">Record type</label>
				<select id="compare-type" class="select" bind:value={recordType}>
					{#each recordTypes as def (def.type)}
						<option value={def.type}>{def.type} · {def.label}</option>
					{/each}
				</select>
			</div>
		</div>
		<div class="field resolvers">
			<span class="label" id="compare-resolvers">Resolvers</span>
			<div class="rows" role="group" aria-labelledby="compare-resolvers">
				{#each rows as row, i (i)}
					<div class="row">
						<input
							class="input mono"
							type="text"
							aria-label="Resolver {i + 1} address"
							placeholder={i === 0 ? '192.168.1.1' : '9.9.9.9'}
							value={row.ip}
							oninput={(e) => setRow(i, 'ip', e.currentTarget.value)}
							onkeydown={handleKeydown}
						/>
						<input
							class="input"
							type="text"
							aria-label="Resolver {i + 1} label"
							placeholder="Label, such as Pi-hole"
							value={row.label}
							oninput={(e) => setRow(i, 'label', e.currentTarget.value)}
							onkeydown={handleKeydown}
						/>
						<button
							class="icon-btn ghost"
							type="button"
							aria-label="Remove resolver {i + 1}"
							disabled={rows.length === 1}
							onclick={() => (rows = rows.filter((_, j) => j !== i))}><Icon name="close" /></button
						>
					</div>
				{/each}
			</div>
			<span class="field-help">An IPv4 or IPv6 address each. Labels stay in this browser; NetTap is sent only the addresses.</span>
		</div>
		<div class="form-actions">
			<button class="btn" type="button" disabled={rows.length >= MAX_RESOLVERS} onclick={() => (rows = [...rows, { ip: '', label: '' }])}>
				Add resolver
			</button>
			<button class="btn primary" type="button" onclick={compare} disabled={loading || !name.trim() || filled.length === 0}>
				<Icon name="search" />{loading ? 'Comparing…' : 'Compare'}
			</button>
		</div>
	</Card>

	{#if loading}
		<Card title="Replies" sub="One row per resolver" class="c-12">
			<CardState state="loading" title="Asking each resolver" />
		</Card>
	{:else if error}
		<Card title="Replies" sub="One row per resolver" class="c-12">
			<CardState state="error" title="The compare failed" message={error} />
		</Card>
	{:else if result && verdict}
		<div class={['notice', 'c-12', verdict.agree ? 'is-ok' : 'is-warn']} role="status">
			<Icon name={verdict.agree ? 'check' : 'warn'} />
			<div class="verdict">
				{#each verdict.lines as line, i (i)}<p>{line}</p>{/each}
			</div>
		</div>
		<Card title="Replies" sub="{result.name} · {result.record_type} · TTL in seconds · latency in ms" class="c-12">
			<DataTable {columns} rows={result.results} ariaLabel="Resolver replies" rowKey={(r) => r.resolver} />
		</Card>
	{:else}
		<Card title="Replies" sub="One row per resolver" class="c-12">
			<CardState state="empty" icon="dns" title="Choose the resolvers" message="Enter a name and up to six resolver addresses, then choose Compare." />
		</Card>
	{/if}
</div>

<style>
	/* Layout glue: one line per resolver (address, label, remove); answers stack in their cell */
	.resolvers { margin-top: var(--sp-4); }
	.rows { display: flex; flex-direction: column; gap: var(--sp-2); }
	.row { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) auto; gap: var(--sp-2); align-items: center; }
	.answers { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-1); }
	.value { white-space: normal; overflow-wrap: anywhere; }
	.who-label { display: block; color: var(--text-1); font-weight: 600; }
	.verdict { display: flex; flex-direction: column; gap: var(--sp-1); }
	.verdict p:first-child { font-weight: 600; }
</style>
