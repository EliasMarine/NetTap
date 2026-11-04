<script lang="ts">
	import { goto } from '$app/navigation';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	let searchIp = $state('');

	function handleSearch() {
		const trimmed = searchIp.trim();
		if (trimmed) goto(`/lookup/whois/${encodeURIComponent(trimmed)}`);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleSearch();
	}
</script>

<svelte:head>
	<title>WHOIS lookup | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">WHOIS lookup</h1>
		<p class="page-sub">See who an IP address is registered to: owner, ASN, CIDR range, registrar and contacts.</p>
	</div>
</div>

<div class="grid">
	<Card title="Look up an address" sub="One IPv4 or IPv6 address" class="c-4">
		<div class="field">
			<label class="label" for="whois-ip">IP address</label>
			<input id="whois-ip" type="text" class="input mono" placeholder="e.g. 8.8.8.8" bind:value={searchIp} onkeydown={handleKeydown} />
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleSearch} disabled={!searchIp.trim()}><Icon name="search" />Lookup</button>
		</div>
	</Card>
	<Card title="Result" sub="Registration fields and the raw WHOIS reply" class="c-8">
		<CardState state="empty" icon="search" title="Enter an IP address" message="Type an IP address and press Enter, or choose Lookup, to query WHOIS data." />
	</Card>
</div>

