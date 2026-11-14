<!--
  Settings › Network › Network location: where this network is, so the Live page's globe can fly
  packets between it and each destination. Saved on NetTap (every browser sees the same place).
  "Use my WAN location" asks NetTap to look up its internet address once, on click, and only fills
  the fields: nothing is saved until Save.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import {
		getHomeLocation,
		saveHomeLocation,
		clearHomeLocation,
		lookupWanLocation,
		checkHomeLocation,
		type HomeLocation,
	} from '$lib/api/home-location';

	interface Props {
		/** NET-273: the fields differ from the saved location (a looked-up place counts until it is saved). */
		dirty?: boolean;
		/** NET-273: a save or clear is running, so Settings holds a tab switch until it lands. */
		writing?: boolean;
	}

	let { dirty = $bindable(false), writing = $bindable(false) }: Props = $props();

	let phase = $state<'loading' | 'ready' | 'failed'>('loading');
	let saved = $state<HomeLocation | null>(null);
	let label = $state('');
	let lat = $state('');
	let lon = $state('');
	let busy = $state<'' | 'save' | 'clear' | 'lookup'>('');
	const fields = (home: HomeLocation | null) => JSON.stringify([home?.label ?? '', home ? String(home.lat) : '', home ? String(home.lon) : '']);
	const unsaved = $derived(phase === 'ready' && JSON.stringify([label, lat, lon]) !== fields(saved));
	$effect(() => {
		dirty = unsaved;
		writing = busy === 'save' || busy === 'clear';
	});
	let message = $state('');
	let isError = $state(false);

	function fill(home: HomeLocation | null) {
		label = home?.label ?? '';
		lat = home ? String(home.lat) : '';
		lon = home ? String(home.lon) : '';
	}

	function say(text: string, error = false) {
		message = text;
		isError = error;
	}

	onMount(async () => {
		try {
			saved = await getHomeLocation();
			fill(saved);
			phase = 'ready';
		} catch {
			phase = 'failed';
		}
	});

	async function lookup() {
		busy = 'lookup';
		say('');
		try {
			const found = await lookupWanLocation();
			fill(found);
			say(`Found ${found.label || 'a location'} from your internet address. Save to keep it.`);
		} catch (err) {
			say(err instanceof Error ? err.message : "Couldn't look up your WAN location.", true);
		} finally {
			busy = '';
		}
	}

	async function save() {
		const checked = checkHomeLocation({ label, lat, lon });
		if (typeof checked === 'string') return say(checked, true);
		busy = 'save';
		say('');
		try {
			saved = await saveHomeLocation(checked);
			fill(saved);
			say('Location saved. The Live page uses it on its next load.');
		} catch (err) {
			say(err instanceof Error ? err.message : "Couldn't save the location.", true);
		} finally {
			busy = '';
		}
	}

	async function clear() {
		busy = 'clear';
		say('');
		try {
			await clearHomeLocation();
			saved = null;
			fill(null);
			say('Location cleared. The globe shows destinations only.');
		} catch (err) {
			say(err instanceof Error ? err.message : "Couldn't clear the location.", true);
		} finally {
			busy = '';
		}
	}
</script>

<Card title="Network location" sub="Where this network is · draws the Live page's globe from here" class="c-12">
	{#if phase === 'loading'}
		<CardState state="loading" title="Loading the network location" />
	{:else if phase === 'failed'}
		<CardState state="error" title="Couldn't load the network location, so changes are off." message="Reload the page to try again." />
	{:else}
		<div class="stack">
			<p class="field-help">
				The Live page's globe flies packets between this point and the places your devices reach. A town is close enough.
				"Use my WAN location" asks an outside service (ipinfo.io) where your internet address is, once, when you press it.
			</p>
			{#if message}
				<div class={['notice', isError ? 'is-error' : 'is-ok']} role={isError ? 'alert' : 'status'}>
					<Icon name={isError ? 'warn' : 'check'} />{message}
				</div>
			{/if}
			<div class="form-grid">
				<div class="field">
					<label class="label" for="home-label">Name</label>
					<input class="input" id="home-label" type="text" maxlength="80" bind:value={label} placeholder="e.g. Home, London" />
				</div>
				<div class="field">
					<label class="label" for="home-lat">Latitude</label>
					<input class="input mono" id="home-lat" type="text" bind:value={lat} placeholder="51.5074" />
					<p class="field-help">−90 to 90, north is positive.</p>
				</div>
				<div class="field">
					<label class="label" for="home-lon">Longitude</label>
					<input class="input mono" id="home-lon" type="text" bind:value={lon} placeholder="-0.1278" />
					<p class="field-help">−180 to 180, east is positive.</p>
				</div>
			</div>
			<div class="form-actions">
				{#if unsaved}<span class="unsaved">Unsaved changes</span>{/if}
				<button class="btn" type="button" onclick={lookup} disabled={busy !== ''}>
					{busy === 'lookup' ? 'Looking up…' : 'Use my WAN location'}
				</button>
				<button class="btn primary" type="button" onclick={save} disabled={busy !== ''}>
					{busy === 'save' ? 'Saving…' : 'Save location'}
				</button>
				{#if saved}
					<button class="btn" type="button" onclick={clear} disabled={busy !== ''}>
						{busy === 'clear' ? 'Clearing…' : 'Clear'}
					</button>
				{/if}
			</div>
		</div>
	{/if}
</Card>
