<script lang="ts">
	/**
	 * One beaconing pair from the Threats page: a device calling one server and port. Every figure
	 * comes from /api/threats/beaconing/pair, which reads the beaconing scan's records and times them
	 * with the scan's own rule; the words come from $lib/utils/beacon. GeoIP and device names are
	 * context only, so their failure never blanks the page.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { getBeaconPair, type BeaconPair } from '$lib/api/threats';
	import { lookupGeoIP, type GeoIPResult } from '$lib/api/geoip';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { ipHref } from '$lib/stores/lan';
	import { blocklistWords, chartTime, DRILL_RANGES, fmt, formatWhen, logsHrefForQuery, rangeWindow, startRange, type DrillRange } from '$lib/utils/drilldown';
	import { bucketWords } from '$lib/utils/narrow-page';
	import { namesByIp } from '$lib/utils/device-names';
	import { loadFailed } from '$lib/utils/load-failed';
	// OLD CODE: import { beaconStory, beaconTodo, blocklistWords, CONFIDENCE_HOW, hostPort, intervalWords, type BeaconContext } from '$lib/utils/beacon'; (blocklistWords moved; pct shared)
	import { beaconStory, beaconTodo, CONFIDENCE_HOW, hostPort, intervalWords, pct, type BeaconContext } from '$lib/utils/beacon';
	import IPAddress from '$components/IPAddress.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';

	const STATUS_WORDS = { irregular: 'not steady enough to list', too_few: 'too few calls to judge', capped: "couldn't be timed" } as const;

	const params = $derived($page.params as Record<string, string>);
	const device = $derived(params.device ?? '');
	const server = $derived(params.server ?? '');
	/** The port from the path, or null when it isn't one (no request is sent; the daemon checks again). */
	const port = $derived(/^\d{1,5}$/.test(params.port ?? '') && Number(params.port) <= 65535 ? Number(params.port) : null);
	const range = $derived<DrillRange>(DRILL_RANGES.find((r) => r.value === $page.url.searchParams.get('range')) ?? DRILL_RANGES.find((r) => r.value === startRange('24h'))!);
	const view = $derived(`${device}|${server}|${port}|${range.value}`);

	let loaded = $state<{ data: BeaconPair; range: DrillRange } | null>(null);
	let failure = $state<string | null>(null);
	let geo = $state<GeoIPResult | null>(null);
	let names = $state<Map<string, string>>(new Map());
	/** The view of the figures on screen (only the loader reads it) */
	let loadedView = '';

	const data = $derived(loaded?.data ?? null);
	const shown = $derived(loaded?.range ?? range);
	const words = $derived(shown.words);
	const deviceName = $derived(names.get(device) ?? null);
	const deviceLabel = $derived(deviceName ? `${deviceName} (${device})` : device);
	const target = $derived(port === null ? server : hostPort(server, port));

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	$effect(() => {
		void view;
		untrack(() => refresh.run());
	});

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const [d, s, p, r, v] = [device, server, port, range, view];
		if (!d || !s || p === null) return 'skipped';
		// A refresh of the same view keeps its last good figures; another view must not show them
		if (v !== loadedView) {
			loaded = null;
			failure = null;
			geo = null;
			loadedView = '';
		}
		const win = rangeWindow(r.hours);
		const [pair, where, registry] = await Promise.allSettled([
			getBeaconPair(d, s, p, win.from, win.to, r.bucket),
			lookupGeoIP(s),
			getRegistryDevices({ limit: 200 }),
		]);
		if (!guard.current(g)) return 'skipped';
		if (where.status === 'fulfilled') geo = where.value;
		if (registry.status === 'fulfilled') names = namesByIp(registry.value.devices);
		if (pair.status === 'fulfilled') {
			loaded = { data: pair.value, range: r };
			loadedView = v;
			failure = null;
		} else {
			failure = pair.reason instanceof Error ? pair.reason.message : '';
		}
		// GeoIP and names are context: only the pair decides the outcome
		return outcome([pair]);
	}

	function pickRange(value: string) {
		void goto(`${$page.url.pathname}?range=${value}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// --- Figures ---

	const timing = $derived(data?.timing ?? null);
	// OLD CODE START — the reply's beacon object repeated mean_gap_seconds and jitter; it carries confidence alone now
	// const beacon = $derived(timing?.beacon ?? null);
	// const pct = (ratio: number) => `${(ratio * 100).toFixed(1)}%`;
	// const intervalValue = $derived(beacon ? intervalWords(beacon.interval_seconds) : timing?.mean_gap_seconds != null ? `~${intervalWords(timing.mean_gap_seconds)}` : '—');
	// const jitter = $derived(beacon ? beacon.jitter_coefficient : (timing?.jitter ?? null));
	// OLD CODE END
	const confidence = $derived(timing?.confidence ?? null);
	const meanGap = $derived(timing?.mean_gap_seconds ?? null);
	// a steady schedule's interval; otherwise only an average
	const intervalValue = $derived(meanGap === null ? '—' : timing?.status === 'periodic' ? intervalWords(meanGap) : `~${intervalWords(meanGap)}`);
	const intervalSub = $derived(!timing ? undefined : timing.status === 'periodic' ? 'between calls' : `average gap · ${STATUS_WORDS[timing.status]}`);
	const jitter = $derived(timing?.jitter ?? null);
	const owner = $derived(geo?.organization ? `${geo.organization}${geo.asn ? ` (AS${geo.asn})` : ''}` : null);
	const ctx = $derived<BeaconContext>({ words, deviceName, owner, anycast: geo?.anycast ?? false });
	const story = $derived(data ? beaconStory(data, ctx) : []);
	const todo = $derived(data ? beaconTodo(data, ctx) : []);
	const blocklist = $derived(data ? blocklistWords(data.threat_intel) : null);

	const timeline = $derived(data?.timeline ?? []);
	const busiest = $derived(timeline.reduce((best, p, i) => (p.n > (timeline[best]?.n ?? -1) ? i : best), -1));
	const timeOf = (t: number | string): string => chartTime(t, shown.hours);
	const callWord = (n: number) => (n === 1 ? 'call' : 'calls');
	const chartLabel = $derived(busiest >= 0 ? `Busiest at ${timeOf(timeline[busiest].t)}, with ${fmt(timeline[busiest].n)} ${callWord(timeline[busiest].n)}` : 'No calls in this window');
	const gapItems = $derived(
		(timing?.gaps ?? []).map((gap) => ({ key: String(gap.seconds), label: intervalWords(gap.seconds), value: gap.count, display: fmt(gap.count), detail: gap.count === 1 ? 'gap' : 'gaps' })),
	);
	const listed = (rows: { name: string | null }[]) => rows.flatMap((r) => (r.name ? [r.name] : [])).join(', ');
	const logsHref = $derived(
		data && port !== null ? `${logsHrefForQuery([`source.ip:"${device}"`, `destination.ip:"${server}"`, `destination.port:${port}`], data, shown.value)}&type=zeek.conn` : '',
	);
	const emptyTitle = $derived(`No calls from ${device} to ${target} in the ${words}`);
</script>

{#snippet pairState(what: string)}
	{#if port === null}
		<CardState state="error" title="That isn't a port number." message="Open this pair again from the Threats page." />
	{:else if !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
	{/if}
{/snippet}

<svelte:head>
	<title>Beaconing to {target} | Threats | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<p class="eyebrow"><a href="/threats">Threats</a> · Beaconing</p>
		<h1 class="page-title">Beaconing to {target}</h1>
		<p class="page-sub">
			From <a href={$ipHref(device)}>{deviceLabel}</a> · {words}. Worked out now, so it can differ a little from the Threats page's last check.
		</p>
	</div>
	<div class="head-actions">
		<Pills options={DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }))} value={range.value} onchange={pickRange} ariaLabel="Time range" />
	</div>
</header>

<div class="grid">
	{#if failure && data}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('this pair', true)} {failure}</span></p>
	{/if}
	{#if data?.device_excluded}
		<p class="notice c-12" role="status"><Icon name="filter" /><span>This device is excluded in Settings, so most pages leave it out; the Threats checks include it.</span></p>
	{/if}
	<KpiCard class="c-3" label="Interval" icon="changelog" value={intervalValue} sub={intervalSub} />
	<KpiCard class="c-3" label="Jitter" icon="bandwidth" value={jitter === null ? '—' : pct(jitter)} sub={data ? 'how much the gaps vary' : undefined} />
	<!-- OLD CODE: value={beacon ? String(Math.round(beacon.confidence)) : '—'} unit={beacon ? '/ 100' : undefined} sub={data && !beacon ? … } (timing.confidence) -->
	<KpiCard class="c-3" label="Confidence" icon="threats" value={confidence === null ? '—' : String(Math.round(confidence))} unit={confidence === null ? undefined : '/ 100'} sub={data && confidence === null ? 'only for a steady schedule' : undefined}>
		{#snippet foot()}
			<details class="how">
				<summary>How it's scored</summary>
				<p>{CONFIDENCE_HOW}</p>
			</details>
		{/snippet}
	</KpiCard>
	<KpiCard class="c-3" label="Calls" icon="connections" value={data ? fmt(data.connections) : '—'} sub={data ? `in the ${words}` : undefined} href={logsHref || undefined} title={logsHref ? 'These calls in Log Explorer' : undefined} />
</div>

<div class="grid">
	<Card class="c-8" hero col title="Calls over time" sub="Calls per {bucketWords(data?.interval, shown.bucketWords)} · {words}">
		{#if !data}
			{@render pairState('the calls')}
		{:else if data.connections === 0}
			<CardState state="empty" icon="connections" title={emptyTitle} message="Try a longer range." />
		{:else}
			<AreaChart
				series={[{ key: 'calls', label: 'Calls', colour: 1, points: timeline.map((p) => ({ t: p.t, v: p.n })) }]}
				formatX={timeOf}
				formatY={fmt}
				formatTip={(i) => `${timeOf(timeline[i].t)} · ${fmt(timeline[i].n)} ${callWord(timeline[i].n)}`}
				highlightIndex={busiest}
				ariaLabel={chartLabel}
			/>
			<p class="dim small">First {formatWhen(data.first_seen)} · last {formatWhen(data.last_seen)}</p>
		{/if}
	</Card>

	<Card class="c-4" title="Gaps between calls" sub="The most common, to the nearest 10 seconds · {words}">
		{#if !data}
			{@render pairState('the gaps')}
		{:else if timing?.status === 'capped'}
			<CardState state="empty" icon="changelog" title="Too many calls to time" message="Choose a shorter range so the gaps can be measured." />
		{:else if gapItems.length === 0}
			<CardState state="empty" icon="changelog" title={data.connections === 0 ? emptyTitle : 'Not enough calls to measure a gap'} />
		{:else}
			<BarList items={gapItems} />
		{/if}
	</Card>
</div>

<div class="grid">
	<Card class="c-8" title="What this means" sub="From the figures on this page · {words}">
		{#if !data}
			{@render pairState('the explanation')}
		{:else if data.connections === 0}
			<CardState state="empty" icon="connections" title={emptyTitle} message="NetTap needs at least {data.timing.min_calls} calls to judge a schedule. Try a longer range." />
		{:else}
			<div class="story">
				{#each story as line, i (i)}<p>{line}</p>{/each}
			</div>
			<div class="todo">
				<b>What to do</b>
				<ul>{#each todo as step, i (i)}<li>{step}</li>{/each}</ul>
			</div>
			<p class="links">
				{#if logsHref}<a href={logsHref}>These calls in Log Explorer</a> ·{/if}
				<a href="/connections?ip={encodeURIComponent(device)}">All of this device's connections</a> ·
				<a href={$ipHref(server)}>Everything about {server}</a>
			</p>
		{/if}
	</Card>

	<Card class="c-4" title="Who the server is" sub="Network from GeoIP · names from this device's own traffic">
		{#if !data}
			{@render pairState('the server')}
		{:else}
			<dl class="facts">
				<dt>Address</dt><dd class="mono"><IPAddress ip={server} /></dd>
				<dt>Network</dt><dd>{geo?.anycast ? 'Anycast' : (owner ?? 'Unknown')}</dd>
				{#if geo?.country}<dt>Country</dt><dd>{geo.country}</dd>{/if}
				<dt>Looked up as</dt><dd class="mono">{listed(data.dns_names) || 'No lookup in this window'}{data.dns_complete ? '' : ' (and more)'}</dd>
				<dt>TLS name</dt><dd class="mono">{listed(data.tls_names) || 'None sent'}{data.tls_complete ? '' : ' (and more)'}</dd>
			</dl>
			{#if blocklist}
				<div class="blocklist">
					<span class={['chip', blocklist.tone === 'bad' && 'is-bad', blocklist.tone === 'ok' && 'is-ok']}
						>{#if blocklist.tone === 'bad'}<Icon name="warn" />{:else if blocklist.tone === 'ok'}<Icon name="check" />{/if}{blocklist.chip}</span
					>
					{#if blocklist.note}<span class="dim small">{blocklist.note}</span>{/if}
				</div>
			{/if}
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.eyebrow { margin: 0 0 var(--sp-1); }
	/* a full IPv6 server address has no space to break at */
	.page-title { overflow-wrap: anywhere; }
	.notice { margin-bottom: var(--sp-3); }
	.small { font-size: var(--text-sm); }
	.story p { margin: 0 0 var(--sp-3); color: var(--text-2); font-size: var(--text-sm); }
	.todo ul { margin: 0; padding-left: var(--sp-4); }
	.links { margin: var(--sp-3) 0 0; font-size: var(--text-sm); color: var(--text-3); }
	.blocklist { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-1); margin-top: var(--sp-4); }
	.how { margin-top: var(--sp-2); font-size: var(--text-xs); color: var(--text-3); }
	.how summary { cursor: pointer; color: var(--text-2); }
	.how p { margin: var(--sp-2) 0 0; }
</style>
