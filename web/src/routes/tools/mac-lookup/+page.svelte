<script lang="ts">
	/**
	 * MAC Lookup — Look up the vendor/manufacturer for a MAC address (OUI).
	 *
	 * A form card for the address (any format), then a result card with .facts:
	 * the normalised MAC, OUI prefix, vendor, and whether the vendor was found.
	 */

	import { macLookup } from '$api/tools';
	import type { MacLookupResult } from '$api/tools';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let mac = $state('');
	let result = $state<MacLookupResult | null>(null);
	let loading = $state(false);
	let error = $state('');

	// ---------------------------------------------------------------------------
	// Lookup
	// ---------------------------------------------------------------------------

	async function handleLookup() {
		const trimmed = mac.trim();
		if (!trimmed) return;

		loading = true;
		error = '';
		result = null;

		try {
			result = await macLookup(trimmed);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Lookup failed';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleLookup();
		}
	}
</script>

<svelte:head>
	<title>MAC address lookup | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">MAC address lookup</h1>
		<p class="page-sub">Name the vendor or maker of any MAC address from the IEEE OUI database.</p>
	</div>
</div>

<div class="grid">
	<Card title="Look up an address" sub="One MAC address, in any common format" class="c-4">
		<div class="field">
			<label class="label" for="mac-input">MAC address</label>
			<input
				id="mac-input"
				type="text"
				class="input mono"
				placeholder="AA:BB:CC:DD:EE:FF"
				aria-describedby="mac-hint"
				bind:value={mac}
				onkeydown={handleKeydown}
			/>
			<span class="field-help" id="mac-hint">Accepts AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF</span>
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleLookup} disabled={loading || !mac.trim()}>
				<Icon name="search" />{loading ? 'Looking up…' : 'Lookup'}
			</button>
		</div>
	</Card>

	<Card title="Result" sub="Vendor from the OUI prefix" class="c-8">
		{#if loading}
			<CardState state="loading" title="Looking up the vendor" />
		{:else if error}
			<CardState state="error" title="Lookup failed" message={error} />
		{:else if result}
			<dl class="facts">
				<dt>Normalised MAC</dt>
				<dd class="mono">{result.mac}</dd>
				<dt>OUI prefix</dt>
				<dd class="mono">{result.oui_prefix || '—'}</dd>
				<dt>Vendor or maker</dt>
				<dd>{result.vendor || 'Unknown vendor'}</dd>
				<dt>In the OUI database</dt>
				<dd>{#if result.found}<span class="chip is-ok"><Icon name="check" />Found</span>{:else}<span class="chip">Not found</span>{/if}</dd>
			</dl>
		{:else}
			<CardState state="empty" icon="devices" title="Enter a MAC address" message="Type a MAC address and press Enter, or choose Lookup, to name its vendor." />
		{/if}
	</Card>
</div>
