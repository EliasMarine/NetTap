<script lang="ts">
	/**
	 * WHOIS lookup: registration data for an IP address.
	 * A form card to look up another address, then a result card with the parsed fields
	 * as .facts, the raw reply behind a toggle, and links to the related lookups.
	 * The lookup runs through the page refresh contract.
	 */

	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';

	let ip = $derived($page.params.ip);
	let result = $state<{ ip: string; raw: string; parsed: Record<string, string>; error: string | null } | null>(null);
	let loading = $state(true);
	let error = $state('');
	let searchIp = $state('');
	let showRaw = $state(false);

	// OLD CODE START — the lookup now goes through the page refresh contract (PLAN.md §5.5):
	// it reports its result and a load guard drops a response that a newer load replaced
	// async function lookup(targetIp: string) {
	// 	loading = true;
	// 	error = '';
	// 	try {
	// 		const res = await fetch(`/api/lookup/whois/${encodeURIComponent(targetIp)}`);
	// 		if (!res.ok) throw new Error('Lookup failed');
	// 		result = await res.json();
	// 		if (result?.error) error = result.error;
	// 	} catch (e) {
	// 		error = e instanceof Error ? e.message : 'Lookup failed';
	// 		result = null;
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// OLD CODE END

	async function lookup(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const targetIp = decodeURIComponent(ip ?? '');
		loading = true;
		error = '';
		try {
			const res = await fetch(`/api/lookup/whois/${encodeURIComponent(targetIp)}`);
			if (!res.ok) throw new Error('Lookup failed');
			const data = await res.json();
			if (!guard.current(g)) return 'skipped';
			result = data;
			if (result?.error) error = result.error;
			return error ? 'failed' : 'ok';
		} catch (e) {
			if (!guard.current(g)) return 'skipped';
			error = e instanceof Error ? e.message : 'Lookup failed';
			result = null;
			return 'failed';
		} finally {
			if (guard.current(g)) loading = false;
		}
	}

	const refresh = registerPageRefresh(lookup);
	onDestroy(refresh.unregister);

	function handleSearch() {
		const trimmed = searchIp.trim();
		if (trimmed) {
			goto(`/lookup/whois/${encodeURIComponent(trimmed)}`);
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleSearch();
		}
	}

	// Look up again whenever the route's IP changes
	$effect(() => {
		if (ip) {
			searchIp = decodeURIComponent(ip);
			refresh.run();
		}
	});
</script>

<svelte:head>
	<title>WHOIS lookup — {ip ? decodeURIComponent(ip) : ''} | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<button class="back" type="button" onclick={() => history.back()}><Icon name="back" />Back</button>
		<h1 class="page-title">WHOIS lookup</h1>
		<p class="page-sub">Who an IP address is registered to, as the registry reports it.</p>
	</div>
</div>

<div class="grid">
	<Card title="Look up an address" sub="One IPv4 or IPv6 address" class="c-4">
		<div class="field">
			<label class="label" for="whois-ip">IP address</label>
			<input id="whois-ip" type="text" class="input mono" placeholder="Enter an IP address…" bind:value={searchIp} onkeydown={handleKeydown} />
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleSearch}><Icon name="search" />Lookup</button>
		</div>
	</Card>

	<Card title="Result" sub="Registration fields as the registry returns them" class="c-8">
		{#if loading}
			<CardState state="loading" title="Looking up WHOIS data" />
		{:else if error}
			<CardState state="error" title="Lookup failed" message={error} />
		{:else if result}
			<dl class="facts">
				<dt>IP address</dt>
				<dd class="mono">{result.ip}</dd>
				{#if result.parsed && Object.keys(result.parsed).length > 0}
					{#each Object.entries(result.parsed) as [key, value] (key)}
						<dt>{key}</dt>
						<dd class="mono">{value || '—'}</dd>
					{/each}
				{/if}
			</dl>
			{#if !result.parsed || Object.keys(result.parsed).length === 0}
				<p class="dim note">No parsed WHOIS fields available.</p>
			{/if}

			{#if result.raw}
				<div class="actions result-actions">
					<button class="btn" type="button" aria-expanded={showRaw} aria-controls="whois-raw" onclick={() => (showRaw = !showRaw)}>
						{showRaw ? 'Hide' : 'Show'} raw WHOIS output
					</button>
				</div>
				{#if showRaw}
					<pre class="raw mono" id="whois-raw">{result.raw}</pre>
				{/if}
			{/if}

			<div class="actions result-actions">
				<a class="btn" href="/devices/{encodeURIComponent(result.ip ?? '')}">View device details</a>
				<a class="btn" href="/geoip/{encodeURIComponent(result.ip ?? '')}">GeoIP lookup</a>
				<a class="btn" href="/lookup/dns/{encodeURIComponent(result.ip ?? '')}">DNS lookup</a>
			</div>
		{/if}
	</Card>
</div>

<style>
	.result-actions, .note { margin-top: var(--sp-4); }
	.note { font-size: var(--text-sm); }
	/* Layout glue: the raw reply as an inset, scrollable block */
	.raw {
		margin: var(--sp-3) 0 0; padding: var(--sp-3) var(--sp-4); max-height: 420px; overflow: auto;
		white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-xs); color: var(--text-2);
		background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--r-md);
	}
	/* .back is styled for a link; this one is a button (it goes back in history) */
	button.back { background: none; border: 0; padding: 0; cursor: pointer; }
</style>
