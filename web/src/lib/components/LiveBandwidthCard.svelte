<!--
  LiveBandwidthCard: a device's download and upload rate right now, every 2 s, with the last
  5 minutes as a chart (NET-205). The daemon measures only while this card polls it.
  The MAC page passes {mac}, the IP page {ip}: each page counts by its own identity.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import {
		getLiveBandwidth,
		LiveBandwidthError,
		type LiveBandwidthKey,
		type LiveBandwidthSupported,
	} from '$api/live-bandwidth';
	import { formatBitRate } from '$lib/utils/bitrate';
	import { formatTime } from '$lib/utils/time';
	import { loadFailed } from '$lib/utils/load-failed';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import LiveChip from '$lib/components/ui/LiveChip.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import AreaChart, { type AreaSeries } from '$lib/components/ui/charts/AreaChart.svelte';

	let { key }: { key: LiveBandwidthKey } = $props();

	/** The next poll starts this long after the previous one settles. */
	const POLL_MS = 2_000;
	/** A figure older than this is not "now" (the daemon's own limit). */
	const FRESH_MS = 5_000;

	let data = $state<LiveBandwidthSupported | null>(null);
	let unsupported = $state<string | null>(null);
	let failure = $state<LiveBandwidthError | null>(null);
	/** The current rates, only while the latest reading is fresh. */
	let headline = $state<{ down: number; up: number } | null>(null);
	/** Why there is no headline, from the latest reading. */
	let latestReason = $state<string | null>(null);
	/** performance.now() of the last valid reading */
	let lastValidAt = $state<number | null>(null);
	/** performance.now() when the card last updated, for "last measured N s ago" */
	let now = $state(0);
	/** Try again for the poller of the current key. */
	let retry = $state<() => void>(() => {});

	const valid = (v: number | null | undefined): v is number => Number.isFinite(v);

	// Compared as a string, so a new {ip} object with the same address doesn't restart polling
	const keyId = $derived('mac' in key ? `mac=${key.mac}` : `ip=${key.ip}`);

	// Polling is local, not registerPageRefresh: pageRefresh takes one loader per page, and the page has it.
	$effect(() => {
		keyId; // restart for another device
		const current = untrack(() => key);
		data = null;
		unsupported = null;
		failure = null;
		latestReason = null;
		lastValidAt = null;
		const poller = startPolling(current);
		retry = poller.retry;
		return poller.stop;
	});

	function startPolling(k: LiveBandwidthKey) {
		let stopped = false;
		/** 400 or unsupported: asking again gets the same answer */
		let halted = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		let expiry: ReturnType<typeof setTimeout> | undefined;
		let ctrl: AbortController | null = null;

		function clearHeadline() {
			clearTimeout(expiry);
			headline = null;
		}

		function show(res: LiveBandwidthSupported, sentAt: number) {
			const received = performance.now();
			now = received;
			clearHeadline();
			const l = res.latest;
			const age = res.latest_age_s;
			lastValidAt = valid(res.last_valid_age_s) ? sentAt - res.last_valid_age_s * 1000 : null;
			// the whole network delay counts against the figure's 5 s, so the send time is the base
			const left = sentAt + FRESH_MS - (age ?? Infinity) * 1000 - received;
			if (l && valid(l.down_bps) && valid(l.up_bps) && left > 0) {
				headline = { down: l.down_bps, up: l.up_bps };
				latestReason = null;
				expiry = setTimeout(() => {
					headline = null;
					now = performance.now();
				}, left);
			} else {
				latestReason = l?.reason ?? null;
			}
		}

		async function poll() {
			timer = undefined;
			if (stopped || halted || ctrl || document.hidden) return;
			ctrl = new AbortController();
			const sentAt = performance.now();
			try {
				const res = await getLiveBandwidth(k, ctrl.signal);
				if (stopped) return;
				failure = null;
				if (res.supported) {
					unsupported = null;
					data = res;
					show(res, sentAt);
				} else {
					halted = true;
					data = null;
					clearHeadline();
					unsupported = res.reason;
				}
			} catch (e) {
				if (stopped) return;
				failure = e instanceof LiveBandwidthError ? e : new LiveBandwidthError(e instanceof Error ? e.message : String(e), 0);
				if (failure.status === 400) halted = true;
			} finally {
				ctrl = null;
			}
			// 2 s after this one settled, so polls never overlap
			if (!stopped && !halted && !document.hidden) timer = setTimeout(poll, POLL_MS);
		}

		// Paused while the tab is hidden; back at once when it shows (the daemon stops a watch after 15 s unpolled)
		function onvisibility() {
			if (!document.hidden && timer === undefined) void poll();
		}

		document.addEventListener('visibilitychange', onvisibility);
		void poll();

		return {
			retry() {
				clearTimeout(timer);
				timer = undefined;
				failure = null;
				void poll();
			},
			stop() {
				stopped = true;
				clearTimeout(timer);
				clearHeadline();
				ctrl?.abort();
				document.removeEventListener('visibilitychange', onvisibility);
			},
		};
	}

	const validCount = $derived(data ? data.samples.filter((s) => valid(s.down_bps) || valid(s.up_bps)).length : 0);
	const stepMs = $derived((data?.interval_s ?? 2) * 1000);
	/** Slot times from the last slot with a wall time: the slot index is the time, to the nearest tick */
	const times = $derived.by(() => {
		const samples = data?.samples ?? [];
		const anchor = samples.findLastIndex((s) => s.t !== null);
		const t0 = anchor >= 0 ? (samples[anchor].t as number) : Date.now();
		return samples.map((_, i) => t0 + (i - (anchor >= 0 ? anchor : samples.length - 1)) * stepMs);
	});
	const series = $derived<AreaSeries[]>(
		data
			? [
					{ key: 'down', label: 'Download', colour: 1, points: data.samples.map((s, i) => ({ t: times[i], v: s.down_bps ?? Number.NaN })) },
					{ key: 'up', label: 'Upload', colour: 2, points: data.samples.map((s, i) => ({ t: times[i], v: s.up_bps ?? Number.NaN })) },
				]
			: [],
	);
	const clock = (t: number | string) => formatTime(Number(t), 'clock');
	function tip(i: number): string {
		const s = data?.samples[i];
		if (!s) return '';
		return `${clock(times[i])} · ↓ ${formatBitRate(s.down_bps ?? Number.NaN)} · ↑ ${formatBitRate(s.up_bps ?? Number.NaN)}`;
	}

	const stats = $derived([
		{ key: 'down', label: 'Download', value: headline ? formatBitRate(headline.down) : '—' },
		{ key: 'up', label: 'Upload', value: headline ? formatBitRate(headline.up) : '—' },
	]);
	function ago(ms: number): string {
		const s = Math.max(0, Math.round(ms / 1000));
		return s < 90 ? `${s} s` : `${Math.round(s / 60)} min`;
	}
	const staleLine = $derived(
		`${latestReason ?? 'Not measured just now'} · ${lastValidAt === null ? 'not measured yet' : `last measured ${ago(now - lastValidAt)} ago`}`,
	);
	const chartLabel = $derived(
		`Download and upload over the last 5 minutes. ${
			headline ? `Now ${formatBitRate(headline.down)} down and ${formatBitRate(headline.up)} up.` : `${latestReason ?? 'Not measured just now'}.`
		}`,
	);
</script>

<!-- what is counted; shown once the daemon has said where it measures -->
{#snippet info()}
	{@const d = data!}
	<p>
		{#if 'mac' in key}
			Everything this device sends and the traffic addressed to it, by hardware address <span class="mono">{key.mac}</span>.
		{:else}
			Everything this address sends and the traffic addressed to it (IPv4 only).
		{/if}
		Broadcast and multicast it receives aren't included. Traffic between two devices that never crosses the watched link isn't
		included. Measured on <span class="mono">{d.interface}</span>.
		{#if d.offloads?.gro}The capture interface merges packets (GRO is on), so figures may read about 3% low.{/if}
	</p>
{/snippet}

<Card class="c-12" title="Live bandwidth" sub="bit/s · last 5 minutes, every 2 seconds" foot={data ? info : undefined}>
	{#snippet actions()}
		{#if data && validCount >= 2}
			<div class="head-row">
				{#if headline}<LiveChip paused={false} />{/if}
				<ul class="legend">
					<li><span class="sw c-d1"></span>Download</li>
					<li><span class="sw c-d2"></span>Upload</li>
				</ul>
			</div>
		{/if}
	{/snippet}

	{#if unsupported}
		<CardState state="empty" icon="bandwidth" title="Live bandwidth isn't available" message={unsupported} />
	{:else if failure && !data}
		{#if failure.status === 400}
			<CardState state="error" title="Can't measure this device" message={failure.message} />
		{:else if failure.status === 503}
			<CardState state="error" title={failure.message} onaction={retry} />
		{:else}
			<CardState state="error" title={loadFailed('live bandwidth')} message={failure.message} onaction={retry} />
		{/if}
	{:else if !data}
		<CardState state="loading" title="Loading live bandwidth" />
	{:else if validCount < 2}
		<CardState state="empty" icon="bandwidth" title="Measuring…" message="The first figures appear in a few seconds." />
	{:else}
		{#if failure}
			<p class="notice is-warn" role="status">
				<Icon name="warn" /><span>{failure.message}</span>
				{#if failure.status !== 400}<button class="btn" type="button" onclick={retry}>Try again</button>{/if}
			</p>
		{/if}
		<StatStrip {stats} />
		<!-- not a live region: it changes every poll, and would be read out every 2 s -->
		{#if !headline}<p class="dim stale">{staleLine}</p>{/if}
		<AreaChart gaps {series} formatX={clock} formatY={formatBitRate} formatTip={tip} ariaLabel={chartLabel} height={180} />
	{/if}
</Card>

<style>
	.head-row {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
	}
	.stale {
		margin: var(--sp-2) 0 0;
		font-size: var(--text-sm);
	}
	.notice .btn {
		margin-left: auto;
	}
</style>
