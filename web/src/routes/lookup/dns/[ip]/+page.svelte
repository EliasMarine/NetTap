<script lang="ts">
	/**
	 * DNS lookup: reverse DNS and forward lookup data for an IP address.
	 * A form card to look up another address, then a result card with .facts and
	 * links to the related lookups. The lookup runs through the page refresh contract.
	 */

	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { ipHref, isLan } from '$lib/stores/lan';

	let ip = $derived($page.params.ip);
	let result = $state<{ ip: string; hostname: string | null; aliases: string[]; addresses: string[]; error: string | null } | null>(null);
	let loading = $state(true);
	let error = $state('');
	let searchIp = $state('');

	// OLD CODE START — the lookup now goes through the page refresh contract (PLAN.md §5.5):
	// it reports its result and a load guard drops a response that a newer load replaced
	// async function lookup(targetIp: string) {
	// 	loading = true;
	// 	error = '';
	// 	try {
	// 		const res = await fetch(`/api/lookup/dns/${encodeURIComponent(targetIp)}`);
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
			const res = await fetch(`/api/lookup/dns/${encodeURIComponent(targetIp)}`);
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
			goto(`/lookup/dns/${encodeURIComponent(trimmed)}`);
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
	<title>DNS lookup — {ip ? decodeURIComponent(ip) : ''} | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<button class="back" type="button" onclick={() => history.back()}><Icon name="back" />Back</button>
		<h1 class="page-title">DNS lookup</h1>
		<p class="page-sub">The host name behind an IP address, and the addresses that name points to.</p>
	</div>
</div>

<div class="grid">
	<Card title="Look up an address" sub="One IPv4 or IPv6 address" class="c-4">
		<div class="field">
			<label class="label" for="dns-ip">IP address</label>
			<input id="dns-ip" type="text" class="input mono" placeholder="Enter an IP address…" bind:value={searchIp} onkeydown={handleKeydown} />
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleSearch}><Icon name="search" />Lookup</button>
		</div>
	</Card>

	<Card title="Result" sub="Reverse (PTR) and forward lookup" class="c-8">
		{#if loading}
			<CardState state="loading" title="Looking up DNS records" />
		{:else if error}
			<CardState state="error" title="Lookup failed" message={error} />
		{:else if result}
			<dl class="facts">
				<dt>IP address</dt>
				<dd class="mono">{result.ip}</dd>
				<dt>Reverse DNS (PTR)</dt>
				<dd>
					{#if result.hostname}<span class="mono">{result.hostname}</span>{:else}<span class="dim">No reverse DNS record</span>{/if}
				</dd>
				<dt>Aliases</dt>
				<dd>
					{#if result.aliases && result.aliases.length > 0}<span class="mono">{result.aliases.join(', ')}</span>{:else}<span class="dim">None</span>{/if}
				</dd>
				<dt>Forward lookup addresses</dt>
				<dd>
					{#if result.addresses && result.addresses.length > 0}<span class="mono">{result.addresses.join(', ')}</span>{:else}<span class="dim">None</span>{/if}
				</dd>
			</dl>
			<div class="actions result-actions">
				<!-- OLD CODE START — NET-160: the device page for internet addresses too
				<a class="btn" href="/devices/{encodeURIComponent(result.ip ?? '')}">View device details</a>
				OLD CODE END -->
				<a class="btn" href={$ipHref(result.ip ?? '')}>{$isLan(result.ip ?? '') === true ? 'View device details' : 'Open address page'}</a>
				<a class="btn" href="/geoip/{encodeURIComponent(result.ip ?? '')}">GeoIP lookup</a>
				<a class="btn" href="/lookup/whois/{encodeURIComponent(result.ip ?? '')}">WHOIS lookup</a>
			</div>
		{/if}
	</Card>
</div>

<style>
	.result-actions { margin-top: var(--sp-4); }
	/* .back is styled for a link; this one is a button (it goes back in history) */
	button.back { background: none; border: 0; padding: 0; cursor: pointer; }
</style>
