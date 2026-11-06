<script lang="ts">
	/**
	 * GeoIP lookup: geolocation data for an IP address.
	 * A form card to look up another address, a result card with .facts (country, city,
	 * coordinates linked to Google Maps, ASN, organisation, private or public), the
	 * OpenStreetMap embed when there are coordinates, and links to the related pages.
	 * The lookup runs through the page refresh contract.
	 */

	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { lookupGeoIP } from '$api/geoip';
	import { ipHref, isLan } from '$lib/stores/lan';
	import type { GeoIPResult } from '$api/geoip';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';

	let ip = $derived($page.params.ip);
	let result = $state<GeoIPResult | null>(null);
	let loading = $state(true);
	let error = $state('');
	let searchIp = $state('');

	// OLD CODE START — the lookup now goes through the page refresh contract (PLAN.md §5.5):
	// it reports its result and a load guard drops a response that a newer load replaced
	// async function lookup(targetIp: string) {
	// 	loading = true;
	// 	error = '';
	// 	try {
	// 		result = await lookupGeoIP(targetIp);
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
			const data = await lookupGeoIP(targetIp);
			if (!guard.current(g)) return 'skipped';
			result = data;
			return 'ok';
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
			goto(`/geoip/${encodeURIComponent(trimmed)}`);
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleSearch();
		}
	}

	// OLD CODE START — the design system allows no emoji, so the country shows its name and code only
	// function countryCodeToFlag(code: string): string {
	// 	if (!code || code.length !== 2 || code === 'XX') return '';
	// 	const upper = code.toUpperCase();
	// 	const codePoints = [...upper].map(
	// 		(c) => 0x1f1e6 + c.charCodeAt(0) - 65
	// 	);
	// 	return String.fromCodePoint(...codePoints);
	// }
	// OLD CODE END

	const mapsUrl = (r: GeoIPResult) => `https://www.google.com/maps/search/?api=1&query=${r.latitude},${r.longitude}`;

	// Look up again whenever the route's IP changes
	$effect(() => {
		if (ip) {
			searchIp = decodeURIComponent(ip);
			refresh.run();
		}
	});
</script>

<svelte:head>
	<title>GeoIP lookup — {ip ? decodeURIComponent(ip) : ''} | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<button class="back" type="button" onclick={() => history.back()}><Icon name="back" />Back</button>
		<h1 class="page-title">GeoIP lookup</h1>
		<p class="page-sub">Where an IP address is, and the network that owns it.</p>
	</div>
</div>

<div class="grid">
	<Card title="Look up an address" sub="One IPv4 or IPv6 address" class="c-4">
		<div class="field">
			<label class="label" for="geoip-ip">IP address</label>
			<input id="geoip-ip" type="text" class="input mono" placeholder="Enter an IP address…" bind:value={searchIp} onkeydown={handleKeydown} />
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleSearch}><Icon name="search" />Lookup</button>
		</div>
	</Card>

	<Card title="Result" sub="Location, network and owner" class="c-8">
		{#if loading}
			<CardState state="loading" title="Looking up the location" />
		{:else if error}
			<CardState state="error" title="Lookup failed" message={error} />
		{:else if result}
			<dl class="facts">
				<dt>IP address</dt>
				<dd class="mono">{result.ip}</dd>
				<dt>Country</dt>
				<dd>
					{result.country || '—'}
					{#if result.country_code && result.country_code !== 'XX'}<span class="dim mono">({result.country_code})</span>{/if}
				</dd>
				<dt>City</dt>
				<dd>{result.city || '—'}</dd>
				<dt>Coordinates</dt>
				<dd>
					{#if result.latitude != null && result.longitude != null}
						<a class="link mono" href={mapsUrl(result)} target="_blank" rel="noopener noreferrer"
							>{result.latitude.toFixed(4)}, {result.longitude.toFixed(4)}<Icon name="up" /></a
						>
					{:else}
						—
					{/if}
				</dd>
				<dt>ASN</dt>
				<dd class="mono">{result.asn != null ? `AS${result.asn}` : '—'}</dd>
				<dt>Organisation</dt>
				<dd>{result.organization || '—'}</dd>
				<dt>Private address</dt>
				<dd>
					{#if result.is_private}<span class="chip">Yes</span>{:else}<span class="chip">No (public)</span>{/if}
				</dd>
			</dl>
			<div class="actions result-actions">
				<!-- OLD CODE START — NET-160: the device page for internet addresses, and ?filter= the Connections page never read
				<a class="btn" href="/devices/{encodeURIComponent(result.ip ?? '')}">View device details</a>
				<a class="btn" href="/connections?filter=ip.src=={encodeURIComponent(result.ip ?? '')}">Filter connections from</a>
				<a class="btn" href="/connections?filter=ip.dst=={encodeURIComponent(result.ip ?? '')}">Filter connections to</a>
				OLD CODE END -->
				<a class="btn" href={$ipHref(result.ip ?? '')}>{$isLan(result.ip ?? '') === true ? 'View device details' : 'Open address page'}</a>
				<a class="btn" href="/connections?ip={encodeURIComponent(result.ip ?? '')}">Connections with this address</a>
			</div>
		{/if}
	</Card>

	{#if !loading && !error && result && result.latitude != null && result.longitude != null}
		<Card title="Map" sub="OpenStreetMap · centred on the coordinates" class="c-12">
			<div class="map">
				<iframe
					title="GeoIP location map"
					width="100%"
					height="300"
					frameborder="0"
					scrolling="no"
					src="https://www.openstreetmap.org/export/embed.html?bbox={result.longitude - 0.5},{result.latitude - 0.3},{result.longitude + 0.5},{result.latitude + 0.3}&layer=mapnik&marker={result.latitude},{result.longitude}"
				></iframe>
			</div>
			{#snippet foot()}
				<div class="foot-stat">
					<span class="mono">{result?.latitude?.toFixed(4)}, {result?.longitude?.toFixed(4)}</span>
					{#if result}<a class="btn" href={mapsUrl(result)} target="_blank" rel="noopener noreferrer">Open in Google Maps</a>{/if}
				</div>
			{/snippet}
		</Card>
	{/if}
</div>

<style>
	.result-actions { margin-top: var(--sp-4); }
	/* Layout glue: the embedded map sits in an inset with the card's inner radius; the
	   filter darkens the light OpenStreetMap tiles to sit on the dark card */
	.map { border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; }
	.map iframe { display: block; filter: invert(0.9) hue-rotate(180deg) saturate(0.5) brightness(1.1); }
	/* .back is styled for a link; this one is a button (it goes back in history) */
	button.back { background: none; border: 0; padding: 0; cursor: pointer; }
</style>
