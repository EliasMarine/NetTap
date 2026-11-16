<script lang="ts">
	/**
	 * The DNS page's "Devices that looked it up" card: which devices asked for the domain picked in
	 * any list on the page, over that list's own window (GET /api/domains/{name}, as the domain page
	 * reads it). The page owns the loading; this card only shows its states.
	 */
	import type { DomainAsker, DomainSummary } from '$lib/api/drilldown';
	import { domainHref, ipHref } from '$lib/stores/lan';
	import { fmt, formatWhen } from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	interface Props {
		/** The domain picked, or null before any pick */
		name: string | null;
		/** The last answer for it; kept while a refresh of the same pick is out */
		askers: DomainSummary['dns'] | null;
		loading: boolean;
		/** The failure's reason ('' when it gave none), or null */
		failed: string | null;
		names: Map<string, string>;
		/** The window, in words */
		words: string;
		onretry: () => void;
		onclear: () => void;
		oncopy: (name: string) => void;
	}

	let { name, askers, loading, failed, names, words, onretry, onclear, oncopy }: Props = $props();

	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';
	const what = $derived(`the devices that looked up ${name}`);
	const columns: Column<DomainAsker>[] = [
		{ key: 'ip', label: 'Device', sortValue: (a) => names.get(a.ip) ?? a.ip, cell: whoCell },
		{ key: 'lookups', label: 'Lookups', numeric: true, cell: lookupsCell },
		{ key: 'last_seen', label: 'Last seen', sortValue: (a) => Date.parse(a.last_seen) || 0, cell: seenCell },
	];
</script>

{#snippet whoCell(a: DomainAsker)}
	{@const known = names.get(a.ip)}
	{#if known}
		<span class="two"><a href={$ipHref(a.ip)}>{known}</a><span class="mono dim">{a.ip}</span></span>
	{:else}
		<IPAddress ip={a.ip} />
	{/if}
{/snippet}
{#snippet lookupsCell(a: DomainAsker)}{fmt(a.lookups)}{/snippet}
{#snippet seenCell(a: DomainAsker)}<span class="num">{formatWhen(a.last_seen)}</span>{/snippet}

<Card class="c-12" title="Devices that looked it up" sub={name ? `${name} · lookups per device · ${words}` : `Lookups per device · ${words}`}>
	<span id="domain-askers" class="anchor"></span>
	{#if !name}
		<CardState state="empty" icon="dns" title="No domain chosen" message="Pick a domain in any list on this page to see which devices looked it up." />
	{:else}
		<div class="chips selected">
			<span class="chip">Selected domain: <span class="mono">{name}</span></span>
			<a class="link" href={domainHref(name)}>Open domain page</a>
			<button class="link" type="button" onclick={() => oncopy(name)}>Copy</button>
			<button class="link" type="button" onclick={onclear}>Clear</button>
		</div>
		<!-- OLD CODE: {#if !askers && failed !== null} (a new pick still loading kept the last pick's error) -->
		{#if !askers && failed !== null && !loading}
			<CardState state="error" title={loadFailed(what)} message={failed || RETRY_HINT} onaction={onretry} />
		{:else if !askers}
			<CardState state="loading" title="Loading {what}" />
		{:else}
			{#if failed !== null && !loading}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed(what, true)} {failed}</span></p>
			{/if}
			{#if askers.askers.length === 0}
				<CardState state="empty" icon="devices" title="No device looked it up in the {words}" message="Only plain DNS lookups show here: lookups over DoH or DoT are encrypted." />
			{:else}
				{#if !askers.askers_complete}
					<p class="notice is-warn" role="status"><Icon name="warn" /><span>Too many devices to list them all: showing the first {fmt(askers.askers.length)}.</span></p>
				{/if}
				<DataTable {columns} rows={askers.askers} ariaLabel="Devices that looked up {name}" rowKey={(a) => a.ip} initialSort={{ key: 'lookups', dir: 'desc' }} />
			{/if}
		{/if}
	{/if}
</Card>

<style>
	/* Layout glue the system lacks */
	/* As the DNS page's own .anchor and .selected */
	.anchor { display: block; scroll-margin-top: calc(var(--sp-8) * 3); }
	.selected { align-items: center; margin-bottom: var(--sp-3); }
	.notice { margin-bottom: var(--sp-3); }
</style>
