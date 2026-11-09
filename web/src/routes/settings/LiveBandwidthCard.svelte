<!--
  Settings › Capture › Live bandwidth (NET-205): the opt-in switch for live rates on device pages,
  off by default. The daemon holds the setting and enforces it; the switch only ever shows the
  daemon's answer. After a turn-off the daemon removes its counters in the background, and this
  card follows that clean-up until it is done.
-->
<script lang="ts">
	// TODO(NET-205): the measured cost from the G11 bench goes here
	const COST_NOTE =
		"While a device page is open, NetTap counts that device's packets in the kernel. This uses some CPU at high traffic. Nothing runs while no device page is open.";
	import { onDestroy, onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import {
		getLiveBandwidthSetting,
		setLiveBandwidthSetting,
		LiveBandwidthError,
		type LiveBandwidthSetting,
	} from '$lib/api/live-bandwidth';

	/** How often the card asks about a running clean-up, and after a failed ask */
	const FOLLOW_MS = 2_000;
	const BACKOFF_MS = 10_000;

	let phase = $state<'loading' | 'ready' | 'failed'>('loading');
	let setting = $state<LiveBandwidthSetting | null>(null);
	let saving = $state(false);
	let message = $state('');
	let followFailed = $state(false);

	let timer: ReturnType<typeof setTimeout> | undefined;
	let destroyed = false;
	/** Bumped by each save, so a clean-up check sent before it can't overwrite its answer */
	let epoch = 0;

	/** Show the daemon's answer, and keep asking while its clean-up runs */
	function apply(next: LiveBandwidthSetting, delay = FOLLOW_MS) {
		setting = next;
		phase = 'ready';
		clearTimeout(timer);
		timer = undefined;
		if (!destroyed && next.cleanup.state !== 'idle') timer = setTimeout(follow, delay);
	}

	async function follow() {
		const mine = epoch;
		try {
			const next = await getLiveBandwidthSetting();
			if (destroyed || mine !== epoch) return;
			followFailed = false;
			apply(next);
		} catch {
			if (destroyed || mine !== epoch || !setting) return;
			followFailed = true;
			apply(setting, BACKOFF_MS);
		}
	}

	// leaves the card as it is until the answer, so a re-fetch after a failed save keeps the switch (and its focus)
	async function load() {
		try {
			const next = await getLiveBandwidthSetting();
			if (!destroyed) apply(next);
		} catch {
			if (!destroyed) phase = 'failed';
		}
	}

	async function toggle(e: MouseEvent) {
		// the API decides the state: the click is cancelled and the switch follows the answer
		e.preventDefault();
		if (!setting || saving) return;
		const want = !setting.enabled;
		saving = true;
		message = '';
		followFailed = false;
		epoch++;
		clearTimeout(timer);
		try {
			apply(await setLiveBandwidthSetting(want));
		} catch (err) {
			if (destroyed) return;
			message = err instanceof LiveBandwidthError ? err.message : "Couldn't save the setting: the request failed.";
			if (err instanceof LiveBandwidthError && err.enabled !== undefined) apply({ ...setting, enabled: err.enabled });
			// no answer about the setting (network, timeout, proxy): show what the daemon has now
			else await load();
		} finally {
			saving = false;
		}
	}

	onMount(load);
	onDestroy(() => {
		destroyed = true;
		clearTimeout(timer);
	});

	const failures = $derived(Object.entries(setting?.cleanup.failed ?? {}));
	const stateLine = $derived.by(() => {
		if (!setting) return '';
		if (failures.length) return `Couldn't remove the counters ${failures.map(([iface, why]) => `on ${iface}: ${why}`).join('; ')}; retrying`;
		if (setting.cleanup.state !== 'idle') return 'Removing the counters…';
		return setting.enabled ? 'On — measures while a device page is open' : 'Off';
	});
</script>

<Card title="Live bandwidth" sub="Each device page's download and upload rate, every 2 seconds · mirror mode" class="c-12">
	{#if phase === 'loading'}
		<CardState state="loading" title="Loading the live bandwidth setting" />
	{:else if phase === 'failed' || !setting}
		<CardState state="error" title="Couldn't load the live bandwidth setting, so changes are off." onaction={load} />
	{:else}
		<div class="stack">
			{#if message}
				<div class="notice is-error" role="alert"><Icon name="warn" />{message}</div>
			{/if}
			{#if followFailed}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Couldn't check the clean-up; retrying</span></p>
			{/if}
			<div class="switch-row">
				<input
					type="checkbox"
					role="switch"
					class="switch"
					id="live-bandwidth-toggle"
					checked={setting.enabled}
					disabled={saving}
					aria-describedby="live-bandwidth-help"
					onclick={toggle}
				/>
				<div>
					<label class="label" for="live-bandwidth-toggle">Live bandwidth on device pages</label>
					<p class="state-line" role="status">{stateLine}</p>
					{#if !setting.supported}
						<p class="field-help">
							{setting.reason}
							{#if setting.mode !== 'mirror'}The setting takes effect in mirror mode.{/if}
						</p>
					{/if}
					<p class="field-help" id="live-bandwidth-help">{COST_NOTE}</p>
				</div>
			</div>
		</div>
	{/if}
</Card>

<style>
	/* the same row as the PCAP switch on the Settings page */
	.switch-row {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-3);
	}
	.switch-row .label {
		margin-bottom: 0;
	}
	.state-line {
		font-size: var(--text-sm);
		color: var(--text-2);
	}
</style>
