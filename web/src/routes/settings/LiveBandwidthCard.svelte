<!--
  Settings › Capture › Live bandwidth (NET-205): the opt-in switch for live rates on device pages,
  off by default. The daemon holds the setting and enforces it; the switch only ever shows the
  daemon's answer. After a turn-off the daemon removes its counters in the background, and this
  card follows that clean-up until it is done.
-->
<script lang="ts">
	// Measured on the G11 by verify_live_bandwidth.py bench (2026-11-09): median cost per frame at
	// 1 Gbit/s, one watch 6.7-7.9% of a core with full-size frames, 29-39% with IMIX; eight about 2x.
	// capture-safety (2 runs, 3 pairs each, ~330 Mbit/s): eight watches 38-91 rx_missed_errors/min in
	// 4 of 6 arms, meter off 0 in all 6
	const COST_NOTE =
		'While a device page is open, NetTap checks every packet on the capture port to count that device\'s traffic. On the G11 at 1 Gbit/s this costs about 7% of one CPU core with large packets, and up to about 40% with a typical mix of sizes; eight open pages cost about twice that. The cost falls with traffic (a tenth at 100 Mbit/s), and nothing runs while no device page is open. With eight pages open during a 330 Mbit/s download, the G11\'s network card also dropped up to about 90 packets a minute (under 0.01%) before capture saw them; with no page open it dropped none.';
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
