<script lang="ts">
	/**
	 * GeoIP lookup: geolocation data for an IP address.
	 * A form card to look up another address, a result card with .facts (country, city,
	 * coordinates linked to Google Maps, ASN, organisation, private or public), the
	 * OpenStreetMap embed when there are coordinates, and links to the related pages.
	 * The lookup runs through the page refresh contract.
	 * NET-237: the answer says its source and age; coordinates only for a city estimate, to
	 * one decimal (GeoLite2 has no accuracy radius), none for country-only or anycast answers.
	 */

	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { lookupGeoIP, geoEstimate } from '$api/geoip';
	import { getVersions, type ComponentVersion } from '$api/updates';
	import { formatTime } from '$lib/utils/time';
	import { ipHref, isLan } from '$lib/stores/lan';
	import type { GeoIPResult } from '$api/geoip';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, outcome, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';

	let ip = $derived($page.params.ip);
	let result = $state<GeoIPResult | null>(null);
	let loading = $state(true);
	let error = $state('');
	let searchIp = $state('');
	/** The installed GeoLite2 file (`geoip-db` in the daemon's version list); null = not reported */
	let installedDb = $state<ComponentVersion | null>(null);
	let installedDbFailed = $state(false);

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

	// OLD CODE START — NET-237: the lookup alone; the installed database date loads beside it
	// async function lookup(guard: LoadGuard): Promise<LoadResult> {
	// 	const g = guard.begin();
	// 	const targetIp = decodeURIComponent(ip ?? '');
	// 	loading = true;
	// 	error = '';
	// 	try {
	// 		const data = await lookupGeoIP(targetIp);
	// 		if (!guard.current(g)) return 'skipped';
	// 		result = data;
	// 		return 'ok';
	// 	} catch (e) {
	// 		if (!guard.current(g)) return 'skipped';
	// 		error = e instanceof Error ? e.message : 'Lookup failed';
	// 		result = null;
	// 		return 'failed';
	// 	} finally {
	// 		if (guard.current(g)) loading = false;
	// 	}
	// }
	// OLD CODE END
	async function lookup(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const targetIp = decodeURIComponent(ip ?? '');
		loading = true;
		error = '';
		// Both start now; the answer shows as soon as it lands, since a cold version scan can take seconds
		const geoP = lookupGeoIP(targetIp);
		const versionsP = getVersions();
		const [geoRes] = await Promise.allSettled([geoP]);
		if (!guard.current(g)) return 'skipped';
		loading = false;
		if (geoRes.status === 'rejected') {
			error = geoRes.reason instanceof Error ? geoRes.reason.message : 'Lookup failed';
			result = null;
			versionsP.catch(() => {}); // not shown without an answer
			return 'failed';
		}
		result = geoRes.value;
		const [versionsRes] = await Promise.allSettled([versionsP]);
		if (!guard.current(g)) return 'skipped';
		installedDbFailed = versionsRes.status === 'rejected';
		// The daemon sends a list; Object.values reads it and the typed record alike
		// OLD CODE: Object.values(versionsRes.value?.versions ?? {}).find(…) (NET-237: getVersions is now typed as the list it is)
		installedDb = versionsRes.status === 'fulfilled' ? (versionsRes.value?.versions?.find((v) => v?.name === 'geoip-db') ?? null) : null;
		return outcome([geoRes, versionsRes]);
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

	// OLD CODE: const mapsUrl = (r: GeoIPResult) => `https://www.google.com/maps/search/?api=1&query=${r.latitude},${r.longitude}`; (NET-237: a pin on a city centre)
	const mapsUrl = (r: GeoIPResult) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([r.city, r.country].filter(Boolean).join(', '))}`;

	let estimate = $derived(result ? geoEstimate(result.latitude, result.longitude, result.city, result.anycast) : null);

	function sourceWords(r: GeoIPResult): string {
		switch (r.source) {
			case 'traffic':
				return `Malcolm's GeoLite2 lookup, stored with traffic${r.seen_at ? ` seen ${formatTime(r.seen_at, 'short')}` : ''}. The database version used then isn't recorded.`;
			case 'maxmind':
				return 'A local GeoLite2 file';
			case 'builtin':
				return "NetTap's built-in list of well-known services, not a database lookup";
			case 'private':
				return 'Private address, not looked up';
			default:
				return 'No traffic with this address has a location yet';
		}
	}

	function installedDbWords(): string {
		if (installedDbFailed) return "Couldn't read the installed database date";
		if (!installedDb || installedDb.status !== 'ok') return 'Not reported';
		const from = installedDb.details?.source ?? installedDb.details?.db_file;
		// the daemon's UTC file date as given: read as a time, it would shift a day west of UTC
		return `GeoLite2 file dated ${installedDb.current_version}, installed now${from ? ` · ${from}` : ''}`;
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
				<!-- OLD CODE: <dd>{result.city || '—'}</dd> (NET-237: anycast has no one city) -->
				<dd>{result.anycast ? 'Anycast: location varies' : result.city || '—'}</dd>
				<dt>Coordinates</dt>
				<dd>
					<!-- OLD CODE START — NET-237 (GEO-2): a city or country centre shown to 11 m with a pin
					{#if result.latitude != null && result.longitude != null}
						<a class="link mono" href={mapsUrl(result)} target="_blank" rel="noopener noreferrer"
							>{result.latitude.toFixed(4)}, {result.longitude.toFixed(4)}<Icon name="up" /></a
						>
					{:else}
						—
					{/if}
					OLD CODE END -->
					{#if estimate?.coordinates}
						<a class="link mono" href={mapsUrl(result)} target="_blank" rel="noopener noreferrer">{estimate.coordinates}<Icon name="up" /></a>
						<span class="dim"> · {estimate.note}</span>
					{:else}
						{result.anycast ? '—' : estimate?.note}
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
				<dt>Source</dt>
				<dd>{sourceWords(result)}</dd>
				{#if result.source === 'traffic' || result.source === 'maxmind'}
					<dt>Installed database</dt>
					<dd>{installedDbWords()}</dd>
				{/if}
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

	<!-- OLD CODE START — NET-237 (GEO-2): a local map and pin for any coordinates, a country centre's included
	{#if !loading && !error && result && result.latitude != null && result.longitude != null}
		<Card title="Map" sub="OpenStreetMap · centred on the coordinates" class="c-12">
	OLD CODE END -->
	{#if !loading && !error && result && estimate?.coordinates && result.latitude != null && result.longitude != null}
		<Card title="Map" sub="OpenStreetMap · approximate area around a city estimate, not an exact location" class="c-12">
			<div class="map">
				<!-- OLD CODE: the src ended &marker={result.latitude},{result.longitude} (NET-237: no pin on an estimate) -->
				<iframe
					title="GeoIP location map"
					width="100%"
					height="300"
					frameborder="0"
					scrolling="no"
					src="https://www.openstreetmap.org/export/embed.html?bbox={result.longitude - 0.5},{result.latitude - 0.3},{result.longitude + 0.5},{result.latitude + 0.3}&layer=mapnik"
				></iframe>
			</div>
			{#snippet foot()}
				<div class="foot-stat">
					<!-- OLD CODE: <span class="mono">{result?.latitude?.toFixed(4)}, {result?.longitude?.toFixed(4)}</span> (NET-237) -->
					<span class="mono">{estimate?.coordinates}</span><span class="dim">{estimate?.note}</span>
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
