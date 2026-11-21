<!--
  WatchedDevicesCard.svelte (NET-331): each watched device's state, from GET /api/devices/watched.
  Presentational: the Devices page's guarded loader fetches the list with its own and passes it in,
  so this card never registers a page refresh. "Stop watching" clears one watch, drops its row, says
  so, and reloads only this list. Hidden in bridge mode, where every device carries the router's MAC,
  with that reason.
-->
<script lang="ts">
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import { formatTime } from '$lib/utils/time';
	import {
		setWatch,
		watchLabel,
		WATCH_BRIDGE_NOTE,
		type WatchCheck,
		type WatchedDevice,
		type WatchedDevicesResponse,
		type WatchState,
	} from '$api/devices-watched';

	// OLD CODE: failed: boolean; onreload: () => void; (review M4: the reason shows; L1: only this list reloads)
	interface Props {
		/** The last list loaded, or null before the first. */
		data: WatchedDevicesResponse | null;
		/** Why the latest read failed, or null (the last list, if any, stays on screen). */
		error: string | null;
		bridge: boolean;
		/** Reads the list again: Try again, and after a watch is stopped. Never rejects. */
		onreload: () => Promise<void>;
	}

	let { data, error, bridge, onreload }: Props = $props();

	/** A check older than this (three missed runs of the 5-minute job) makes the states doubtful. */
	const STALE_MS = 15 * 60 * 1000;
	const PAUSED: Record<NonNullable<WatchCheck['skipped']>, string> = {
		pipeline: 'Watching is paused: no new traffic has been indexed for 10 minutes, so NetTap reports nothing until it is.',
		mode: "Watching is paused: capture isn't ready. Check the capture status on the System page.",
		store: "Watching is paused: the device details file can't be read.",
	};
	const STATE: Record<WatchState, { word: string; chip: string; icon: 'check' | 'warn' | 'changelog'; rank: number }> = {
		down: { word: 'Offline', chip: 'chip is-bad', icon: 'warn', rank: 2 },
		unknown: { word: 'Waiting for first sighting', chip: 'chip', icon: 'changelog', rank: 1 },
		up: { word: 'Online', chip: 'chip is-ok', icon: 'check', rank: 0 },
	};

	let stopping = $state<string | null>(null);
	let stopError = $state<string | null>(null);
	/** Review M2: said politely once a stop has saved. */
	let stopDone = $state<string | null>(null);
	// Review M2: a stopped watch's row goes at once, even if the reload fails. shortcut: kept for the card's
	// life, so a device watched again from another tab stays hidden here until the page is reopened.
	let stopped = $state<readonly string[]>([]);
	let root = $state<HTMLElement>();
	const rows = $derived(data ? data.devices.filter((d) => !stopped.includes(d.mac)) : []);

	const check = $derived(data?.check ?? null);
	// OLD CODE: const paused = $derived(check?.skipped ? PAUSED[check.skipped] : null); (the daemon now says why capture isn't ready)
	const paused = $derived(
		check?.skipped === 'mode' && check.reason ? `Checks are paused: ${check.reason}.` : check?.skipped ? PAUSED[check.skipped] : null,
	);
	const stale = $derived.by(() => {
		if (!check) return null;
		const last = check.success_at ? ` The states below are from ${formatTime(check.success_at, 'short')}.` : '';
		if (check.error) return `Couldn't check the watched devices: ${check.error}${last}`;
		if (paused || !check.success_at) return null;
		const age = Date.now() - Date.parse(check.success_at);
		return age > STALE_MS ? `The last check was over 15 minutes ago, so these states may be out of date.${last}` : null;
	});

	const name = (d: WatchedDevice): string => d.name ?? d.mac;

	// OLD CODE START — review M2: the row stayed until the page's reload landed, nothing was said, and focus was lost
	// async function stop(d: WatchedDevice): Promise<void> {
	// 	if (stopping) return;
	// 	stopping = d.mac;
	// 	stopError = null;
	// 	try {
	// 		await setWatch(d.mac, null);
	// 		onreload();
	// 	} catch (e) {
	// 		stopError = `Couldn't stop watching ${name(d)}. ${e instanceof Error ? e.message : 'The request failed.'}`;
	// 	} finally {
	// 		stopping = null;
	// 	}
	// }
	// OLD CODE END
	async function stop(d: WatchedDevice): Promise<void> {
		if (stopping) return;
		stopping = d.mac;
		stopError = null;
		stopDone = null;
		try {
			await setWatch(d.mac, null);
		} catch (e) {
			stopError = `Couldn't stop watching ${name(d)}. ${e instanceof Error ? e.message : 'The request failed.'}`;
			return;
		} finally {
			stopping = null;
		}
		stopped = [...stopped, d.mac];
		stopDone = `Stopped watching ${name(d)}.`;
		await onreload();
		// the clicked button has gone with its row: the card's heading takes focus
		const heading = root?.querySelector<HTMLElement>('.card-title');
		heading?.setAttribute('tabindex', '-1');
		heading?.focus();
	}

	const columns: Column<WatchedDevice>[] = [
		{ key: 'device', label: 'Device', sortValue: name, cell: deviceCell },
		{ key: 'state', label: 'State', sortValue: (d) => STATE[d.state]?.rank ?? -1, cell: stateCell },
		{ key: 'after_min', label: 'Alert after', numeric: true, sortValue: (d) => d.after_min, cell: afterCell },
		{ key: 'seen_at', label: 'Last seen', sortValue: (d) => d.seen_at ?? '', cell: seenCell },
		{ key: 'since', label: 'Since', sortValue: (d) => d.since ?? '', cell: sinceCell },
		{ key: 'stop', label: 'Action', sortValue: name, cell: stopCell },
	];
</script>

{#snippet deviceCell(d: WatchedDevice)}
	<a class={d.name ? undefined : 'mono'} href="/devices/mac/{encodeURIComponent(d.mac)}">{name(d)}</a>
{/snippet}
{#snippet stateCell(d: WatchedDevice)}
	{@const s = STATE[d.state] ?? STATE.unknown}
	<span class={s.chip}><Icon name={s.icon} />{s.word}</span>
{/snippet}
{#snippet afterCell(d: WatchedDevice)}{watchLabel(d.after_min)}{/snippet}
{#snippet seenCell(d: WatchedDevice)}{formatTime(d.seen_at, 'short')}{/snippet}
{#snippet sinceCell(d: WatchedDevice)}{formatTime(d.since, 'short')}{/snippet}
{#snippet stopCell(d: WatchedDevice)}
	<!-- OLD CODE: the button was named only "Stop watching" (review M3: say which device) -->
	<button class="btn" type="button" aria-label="Stop watching {name(d)}" onclick={() => stop(d)} disabled={stopping !== null}
		>{stopping === d.mac ? 'Stopping…' : 'Stop watching'}</button
	>
{/snippet}

{#if bridge}
	<p class="notice" role="note"><Icon name="infra" /><span>{WATCH_BRIDGE_NOTE}</span></p>
{:else}
	<!-- OLD CODE: failed in place of error, data.devices in place of rows, and no stop confirmation (review M2/M4) -->
	<div bind:this={root}>
		<Card title="Watched devices" sub={check?.success_at ? `Checked every 5 minutes · last check ${formatTime(check.success_at, 'short')}` : 'Checked every 5 minutes'}>
			{#if !data && !error}
				<CardState state="loading" title="Loading watched devices" />
			{:else if !data}
				<CardState state="error" title={loadFailed('watched devices')} message={error ?? undefined} onaction={onreload} />
			{:else}
				{#if error}<p class="notice is-warn card-note" role="status"><Icon name="warn" /><span>{loadFailed('watched devices', true)} {error}</span></p>{/if}
				{#if paused}<p class="notice is-warn card-note" role="status"><Icon name="pause" /><span>{paused}</span></p>{/if}
				{#if stale}<p class="notice is-warn card-note" role="status"><Icon name="warn" /><span>{stale}</span></p>{/if}
				{#if stopError}<p class="notice is-error card-note" role="alert"><Icon name="warn" /><span>{stopError}</span></p>{/if}
				{#if stopDone}<p class="notice is-ok card-note" role="status"><Icon name="check" /><span>{stopDone}</span></p>{/if}
				{#if rows.length === 0}
					<CardState state="empty" icon="devices" title="No devices are watched" message="Open a device and choose Watch." />
				{:else}
					<DataTable ariaLabel="Watched devices" {rows} rowKey={(d) => d.mac} initialSort={{ key: 'state', dir: 'desc' }} {columns} />
				{/if}
			{/if}
		</Card>
	</div>
{/if}

<style>
	.card-note { margin-bottom: var(--sp-3); }
</style>
