<!--
  Settings › Display (NET-273: moved from the Settings page): the theme, the default time range and
  the Live map, saved in this browser; and the time zone NetTap counts days in, saved on NetTap (F4).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import ThemePicker from '$lib/components/ThemePicker.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { getTimezone, setTimezone } from '$lib/api/usage';
	import { loadFailed } from '$lib/utils/load-failed';
	import { DISPLAY_SETTINGS_KEY, DRILL_RANGES, savedDefaultRange, savedLiveMap, type DrillRangeValue, type LiveMap } from '$lib/utils/drilldown';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** The range or the map differs from what this browser has saved (the theme applies at once). */
		dirty?: boolean;
	}

	let { dirty = $bindable(false) }: Props = $props();

	// --- Display state ---
	// OLD CODE START — NET-195: no page read these; each page owns its Auto toggle, and times are browser-local
	// let autoRefresh = $state('30');
	// let timezone = $state('local');
	// let defaultTimeRange = $state('1h');
	// OLD CODE END
	/** The range pages open on (NET-195); '' is each page's own. */
	let defaultRange = $state<DrillRangeValue | ''>('');
	let liveMap = $state<LiveMap>('globe');
	let displaySaving = $state(false);
	let displayMessage = $state('');
	let displayError = $state(false);
	// NET-273: the choices as last read or saved, so the page can guard an unsaved edit
	const displayForm = () => JSON.stringify([defaultRange, liveMap]);
	let displaySavedForm = $state(displayForm());
	const displayUnsaved = $derived(displayForm() !== displaySavedForm);

	// --- Time zone (F4, NET-329): the usage ledger counts days and months in it, on NetTap ---
	/** Every zone this browser knows, plus UTC (NetTap's default, missing from some browsers' lists) */
	const ZONES = [...new Set([...Intl.supportedValuesOf('timeZone'), 'UTC'])].sort();
	const TZ_WARNING =
		'Changing the time zone starts a new count in that zone. NetTap recounts every day it still has the raw data for; older days show as not counted, and Bandwidth says Still counting until it finishes.';
	let tz = $state('');
	/** The zone NetTap counts in; null until it loads */
	let tzSaved = $state<string | null>(null);
	let tzLoadFailed = $state(false);
	let tzSaving = $state(false);
	let tzMessage = $state('');
	let tzError = $state(false);
	const tzUnsaved = $derived(tzSaved !== null && tz !== tzSaved);
	// a zone NetTap knows but this browser doesn't still shows as chosen
	const zones = $derived(tzSaved && !ZONES.includes(tzSaved) ? [tzSaved, ...ZONES] : ZONES);

	async function loadTimezone() {
		tzLoadFailed = false;
		try {
			const owner = await getTimezone();
			tz = owner.tz;
			tzSaved = owner.tz;
		} catch {
			tzLoadFailed = true;
		}
	}

	async function saveTimezone() {
		tzSaving = true;
		tzMessage = '';
		const result = await setTimezone(tz);
		tzSaving = false;
		tzError = !result.ok;
		if (!result.ok) {
			tzMessage = `Couldn't save the time zone: ${result.error}`;
			return;
		}
		tz = tzSaved = result.data.tz;
		tzMessage = `NetTap counts days in ${result.data.tz} from now on.`;
	}

	$effect(() => {
		// OLD CODE: dirty = displayUnsaved; (F4: an unsaved time zone holds the tab too)
		dirty = displayUnsaved || tzUnsaved;
	});

	// OLD CODE START — NET-195: auto-refresh and timezone are gone, and the range is read as the pages read it
	// async function loadDisplaySettings() {
	// 	try {
	// 		const stored = localStorage.getItem('nettap-display-settings');
	// 		if (stored) {
	// 			const parsed = JSON.parse(stored);
	// 			autoRefresh = parsed.autoRefresh ?? '30';
	// 			timezone = parsed.timezone ?? 'local';
	// 			// OLD CODE: defaultTimeRange = parsed.defaultTimeRange ?? '1h'; (NET-192 PR 4: a saved 15m or 4h is no longer offered)
	// 			defaultTimeRange = ['1h', '6h', '24h', '7d', '30d'].includes(parsed.defaultTimeRange) ? parsed.defaultTimeRange : '1h';
	// 		}
	// 	} catch {
	// 		// Will use defaults
	// 	}
	// }
	// OLD CODE END
	function loadDisplaySettings() {
		defaultRange = savedDefaultRange() ?? '';
		liveMap = savedLiveMap();
		displaySavedForm = displayForm();
	}

	function saveDisplay() {
		displaySaving = true;
		displayMessage = '';
		displayError = false;
		try {
			// OLD CODE START — NET-195: the new field only; "Each page's own" saves nothing
			// localStorage.setItem(
			// 	'nettap-display-settings',
			// 	JSON.stringify({ autoRefresh, timezone, defaultTimeRange })
			// );
			// OLD CODE END
			// OLD CODE START — the Live map choice is saved beside the range now
			// if (defaultRange) localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify({ defaultRange }));
			// else localStorage.removeItem(DISPLAY_SETTINGS_KEY);
			// OLD CODE END
			// Only what differs from the default is saved; nothing at all removes the key
			const saved = { ...(defaultRange && { defaultRange }), ...(liveMap === 'flat' && { liveMap }) };
			if (Object.keys(saved).length) localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify(saved));
			else localStorage.removeItem(DISPLAY_SETTINGS_KEY);
			displaySavedForm = displayForm();
			displayMessage = 'Display settings saved.';
		} catch {
			displayMessage = 'Failed to save display settings.';
			displayError = true;
		} finally {
			displaySaving = false;
		}
	}

	onMount(() => {
		loadDisplaySettings();
		void loadTimezone();
	});
</script>

<div class="grid">
	<!-- OLD CODE: sub="Theme, refresh and time settings · saved in this browser" (NET-195: the refresh and timezone controls are gone) -->
	<!-- OLD CODE: sub="Theme and the default time range · saved in this browser" (the Live map choice joined them) -->
	<Card title="Display preferences" sub="Theme, the default time range and the Live map · saved in this browser" class="c-12">
		<div class="stack">
			<ThemePicker />
			<Feedback message={displayMessage} isError={displayError} />

			<div class="form-grid">
				<!-- OLD CODE START — NET-195: no page read these; each page owns its Auto toggle, and times are browser-local
				<div class="field">
					<label class="label" for="auto-refresh">Auto-refresh interval</label>
					<select class="select" id="auto-refresh" bind:value={autoRefresh}>
						<option value="0">Off</option>
						<option value="10">10 seconds</option>
						<option value="30">30 seconds</option>
						<option value="60">1 minute</option>
						<option value="300">5 minutes</option>
					</select>
					<p class="field-help">How often dashboards auto-refresh data.</p>
				</div>
				<div class="field">
					<label class="label" for="timezone">Timezone</label>
					<select class="select" id="timezone" bind:value={timezone}>
						<option value="utc">UTC</option>
						<option value="local">Local (browser)</option>
					</select>
					<p class="field-help">Timezone used for displaying timestamps.</p>
				</div>
				OLD CODE END -->
				<div class="field">
					<label class="label" for="default-range">Default time range</label>
					<!-- OLD CODE: bind:value={defaultTimeRange} (NET-195: saved as defaultRange, '' for each page's own) -->
					<select class="select" id="default-range" bind:value={defaultRange}>
						<!-- OLD CODE START — NET-192 PR 4: one range set across the app (1h 6h 24h 7d 30d)
						<option value="15m">Last 15 minutes</option>
						<option value="1h">Last 1 hour</option>
						<option value="4h">Last 4 hours</option>
						<option value="24h">Last 24 hours</option>
						<option value="7d">Last 7 days</option>
						OLD CODE END -->
						<!-- OLD CODE START — NET-195: from DRILL_RANGES, after "Each page's own"
						<option value="1h">Last hour</option>
						<option value="6h">Last 6 hours</option>
						<option value="24h">Last 24 hours</option>
						<option value="7d">Last 7 days</option>
						<option value="30d">Last 30 days</option>
						OLD CODE END -->
						<option value="">Each page's own (most open on 24 hours)</option>
						{#each DRILL_RANGES as r (r.value)}
							<option value={r.value}>{r.words.charAt(0).toUpperCase() + r.words.slice(1)}</option>
						{/each}
					</select>
					<!-- OLD CODE: <p class="field-help">Default time window for traffic and alert views.</p> (NET-195) -->
					<p class="field-help">
						The window traffic, alert and device pages open on. A link from a figure still opens on that figure's window.
						PCAP and Certificates keep their own (1 hour, 7 days).
					</p>
				</div>
				<div class="field">
					<label class="label" for="live-map">Live map</label>
					<select class="select" id="live-map" bind:value={liveMap}>
						<option value="globe">3D globe</option>
						<option value="flat">Flat map (lighter on this computer)</option>
					</select>
					<p class="field-help">
						The globe draws with WebGPU, or WebGL 2 where WebGPU is missing, and shows the flat map by itself when this browser can do
						neither. Pick the flat map to save this computer's graphics and battery.
					</p>
				</div>
			</div>

			<div class="form-actions">
				{#if displayUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
				<button class="btn primary" type="button" onclick={saveDisplay} disabled={displaySaving}>
					{displaySaving ? 'Saving…' : 'Save display settings'}
				</button>
			</div>
		</div>
	</Card>

	<Card title="Time zone" sub="The days and months NetTap counts usage in · saved on NetTap" class="c-12">
		{#if tzSaved !== null}
			<div class="stack">
				<Feedback message={tzMessage} isError={tzError} />
				<div class="form-grid">
					<div class="field">
						<label class="label" for="owner-tz">Your time zone</label>
						<select class="select" id="owner-tz" bind:value={tz}>
							{#each zones as zone (zone)}
								<option value={zone}>{zone}</option>
							{/each}
						</select>
						<p class="field-help">Bandwidth counts each day and month in this zone. Until you choose one, NetTap counts in UTC.</p>
					</div>
				</div>
				{#if tzUnsaved}
					<p class="notice is-warn" role="status"><Icon name="warn" /><span>{TZ_WARNING}</span></p>
				{/if}
				<div class="form-actions">
					{#if tzUnsaved}<span class="unsaved">Unsaved changes</span>{/if}
					<button class="btn primary" type="button" onclick={saveTimezone} disabled={tzSaving || !tzUnsaved}>
						{tzSaving ? 'Saving…' : 'Save time zone'}
					</button>
				</div>
			</div>
		{:else if tzLoadFailed}
			<CardState
				state="error"
				title={loadFailed('your time zone')}
				message="Check that NetTap is running on the System page, then try again."
				onaction={() => void loadTimezone()}
			/>
		{:else}
			<CardState state="loading" title="Loading your time zone" />
		{/if}
	</Card>
</div>
