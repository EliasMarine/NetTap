<script lang="ts">
	/**
	 * One device's failed DNS lookups, from the Threats page's NXDOMAIN spike row. Every figure comes
	 * from /api/threats/failed-lookups/{ip}, which reads the DNS check's own records; the words come
	 * from $lib/utils/dns-anomaly and say only what was read.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { getFailedLookups, type FailedLookups } from '$lib/api/threats';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { ipHref } from '$lib/stores/lan';
	import { chartTime, DRILL_RANGES, fmt, formatWhen, isHostName, rangeWindow, startRange, type DrillRange } from '$lib/utils/drilldown';
	import { bucketWords } from '$lib/utils/narrow-page';
	import { namesByIp } from '$lib/utils/device-names';
	import { loadFailed } from '$lib/utils/load-failed';
	import { failedTodo, failedWhy, findingHref, KIND_WORDS } from '$lib/utils/dns-anomaly';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';

	const ip = $derived(($page.params as Record<string, string>).ip ?? '');
	const range = $derived<DrillRange>(DRILL_RANGES.find((r) => r.value === $page.url.searchParams.get('range')) ?? DRILL_RANGES.find((r) => r.value === startRange('24h'))!);
	const view = $derived(`${ip}|${range.value}`);

	let loaded = $state<{ data: FailedLookups; range: DrillRange } | null>(null);
	let failure = $state<string | null>(null);
	let names = $state<Map<string, string>>(new Map());
	/** The view of the figures on screen (only the loader reads it) */
	let loadedView = '';

	const data = $derived(loaded?.data ?? null);
	const shown = $derived(loaded?.range ?? range);
	const words = $derived(shown.words);
	const who = $derived(names.get(ip) ? `${names.get(ip)} (${ip})` : ip);

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	$effect(() => {
		void view;
		untrack(() => refresh.run());
	});

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const [target, r, v] = [ip, range, view];
		if (!target) return 'skipped';
		if (v !== loadedView) {
			loaded = null;
			failure = null;
			loadedView = '';
		}
		const win = rangeWindow(r.hours);
		const [res, registry] = await Promise.allSettled([getFailedLookups(target, win.from, win.to, r.bucket), getRegistryDevices({ limit: 200 })]);
		if (!guard.current(g)) return 'skipped';
		if (registry.status === 'fulfilled') names = namesByIp(registry.value.devices);
		if (res.status === 'fulfilled') {
			loaded = { data: res.value, range: r };
			loadedView = v;
			failure = null;
		} else {
			failure = res.reason instanceof Error ? res.reason.message : '';
		}
		// device names are cosmetic: only the lookups decide the outcome
		return outcome([res]);
	}

	function pickRange(value: string) {
		void goto(`${$page.url.pathname}?range=${value}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// --- Figures ---

	const share = (part: number, whole: number) => (whole > 0 ? `${Math.round((part / whole) * 100)}%` : '—');
	const why = $derived(data ? failedWhy(data, who, words) : []);
	const todo = $derived(data ? failedTodo(data, who) : []);
	const timeline = $derived(data?.timeline ?? []);
	const timeOf = (t: number | string): string => chartTime(t, shown.hours);
	const busiest = $derived(timeline.reduce((best, p, i) => (p.failed > (timeline[best]?.failed ?? -1) ? i : best), -1));
	const chartLabel = $derived(busiest >= 0 ? `Most failures at ${timeOf(timeline[busiest].t)}, with ${fmt(timeline[busiest].failed)} of ${fmt(timeline[busiest].n)} lookups failed` : 'No lookups in this window');
	const rcodeItems = $derived(
		(data?.rcodes ?? []).map((r, i) => ({
			key: `${i}`,
			label: r.rcode ?? 'No response code',
			value: r.lookups,
			display: fmt(r.lookups),
			detail: share(r.lookups, data?.lookups ?? 0),
			colour: r.rcode === 'NXDOMAIN' ? (2 as const) : (1 as const),
		})),
	);

	type NameRow = FailedLookups['failed_names'][number];
	/** The domain page in finding mode over this reply's exact window, so its counts match these. */
	const nameHref = (name: string) => (data ? findingHref(name, { from: data.from, to: data.to, range: shown.value }) : '');
	const columns: Column<NameRow>[] = [
		{ key: 'name', label: 'Name', cell: nameCell },
		{ key: 'kind', label: 'Kind', sortValue: (r) => KIND_WORDS[r.kind].label, cell: kindCell },
		{ key: 'lookups', label: 'Failed lookups', numeric: true, cell: lookupsCell },
		{ key: 'last_seen', label: 'Last seen', sortValue: (r) => (r.last_seen ? Date.parse(r.last_seen) || 0 : 0), cell: seenCell },
	];
	const namesSub = $derived(
		!data
			? words
			: data.failed_names_complete && data.failed_names.length === data.failed_names_read
				? `All ${fmt(data.failed_names_read)} ${data.failed_names_read === 1 ? 'name' : 'names'}, by failed lookups · ${words}`
				: data.failed_names_complete
					? `The ${fmt(data.failed_names.length)} busiest of the ${fmt(data.failed_names_read)} names · ${words}`
				: `The ${fmt(data.failed_names.length)} busiest of the first ${fmt(data.failed_names_read)} names read, in name order · ${words}`,
	);
</script>

<!-- A name that isn't a host name (no domain page) stays plain text -->
{#snippet nameCell(r: NameRow)}
	{#if isHostName(r.name)}<a class="mono" href={nameHref(r.name)} title="This name's lookups over the same window">{r.name}</a>
	{:else}<span class="mono">{r.name}</span>{/if}
{/snippet}
{#snippet kindCell(r: NameRow)}{KIND_WORDS[r.kind].label}{/snippet}
{#snippet lookupsCell(r: NameRow)}{fmt(r.lookups)}{/snippet}
{#snippet seenCell(r: NameRow)}<span class="num">{formatWhen(r.last_seen)}</span>{/snippet}

{#snippet lookupState(what: string)}
	{#if !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
	{/if}
{/snippet}

<svelte:head>
	<title>Failed lookups from {ip} | Threats | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<p class="eyebrow"><a href="/threats">Threats</a> · DNS anomalies</p>
		<h1 class="page-title">Failed lookups from {who}</h1>
		<p class="page-sub">DNS lookups that came back as “no such name” (NXDOMAIN) · {words}</p>
	</div>
	<div class="head-actions">
		<Pills options={DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }))} value={range.value} onchange={pickRange} ariaLabel="Time range" />
	</div>
</header>

<div class="grid">
	{#if failure && data}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('these lookups', true)} {failure}</span></p>
	{/if}
	{#if data?.excluded}
		<p class="notice c-12" role="status"><Icon name="filter" /><span>This device is excluded in Settings, so most pages leave it out; the Threats checks include it.</span></p>
	{/if}
	<KpiCard class="c-3" label="Lookups" icon="dns" value={data ? fmt(data.lookups) : '—'} sub={data ? `in the ${words}` : undefined} />
	<KpiCard class="c-3" label="Failed" icon="warn" value={data ? fmt(data.failed) : '—'} sub={data ? '“no such name”' : undefined} />
	<KpiCard class="c-3" label="Share failed" icon="bandwidth" value={data ? share(data.failed, data.lookups) : '—'} sub={data ? 'listed above 40%' : undefined} />
	<KpiCard
		class="c-3"
		label="Names that failed"
		icon="search"
		value={data ? `${data.failed_names_complete ? '' : 'at least '}${fmt(data.failed_names_read)}` : '—'}
		sub={data ? (data.failed_names_complete ? 'distinct names' : 'too many to read them all') : undefined}
	/>
</div>

<div class="grid">
	<Card class="c-8" hero col title="Lookups over time" sub="Lookups per {bucketWords(data?.interval, shown.bucketWords)} · {words}">
		{#if !data}
			{@render lookupState('the lookups')}
		{:else if data.lookups === 0}
			<CardState state="empty" icon="dns" title="No lookups from {ip} in the {words}" message="Try a longer range." />
		{:else}
			<AreaChart
				series={[
					{ key: 'all', label: 'All lookups', colour: 1, points: timeline.map((p) => ({ t: p.t, v: p.n })) },
					{ key: 'failed', label: 'Failed', colour: 2, points: timeline.map((p) => ({ t: p.t, v: p.failed })) },
				]}
				formatX={timeOf}
				formatY={fmt}
				formatTip={(i) => `${timeOf(timeline[i].t)} · ${fmt(timeline[i].failed)} of ${fmt(timeline[i].n)} failed`}
				highlightIndex={busiest}
				ariaLabel={chartLabel}
			/>
		{/if}
	</Card>

	<Card class="c-4" title="Response codes" sub="Lookups per answer · {words}">
		{#if !data}
			{@render lookupState('the response codes')}
		{:else if rcodeItems.length === 0}
			<CardState state="empty" icon="dns" title="No lookups from {ip} in the {words}" />
		{:else}
			<BarList items={rcodeItems} />
		{/if}
	</Card>
</div>

<div class="grid">
	<Card class="c-12" title="Why NetTap lists this device" sub="From the lookups read for this page · {words}">
		{#if !data}
			{@render lookupState('the explanation')}
		{:else if data.lookups === 0}
			<CardState state="empty" icon="dns" title="No lookups from {ip} in the {words}" message="NetTap lists a device when more than 40% of more than 50 lookups fail. Try a longer range." />
		{:else}
			<div class="story">
				{#each why as line, i (i)}<p>{line}</p>{/each}
			</div>
			<div class="todo">
				<b>What to do</b>
				<ul>{#each todo as step, i (i)}<li>{step}</li>{/each}</ul>
			</div>
			<p class="links">
				<a href={$ipHref(ip)}>Everything about {ip}</a> · <a href="/dns">The DNS page</a>
			</p>
		{/if}
	</Card>

	<Card class="c-12" title="Names that failed" sub={namesSub}>
		{#if !data}
			{@render lookupState('the names')}
		{:else if data.failed_names.length === 0}
			<CardState state="empty" icon="dns" title="No failed lookups from {ip} in the {words}" />
		{:else}
			{#if !data.failed_names_complete}
				<p class="notice is-warn" role="status">
					<Icon name="warn" /><span>More names failed than NetTap reads at once, so these are the busiest of the first {fmt(data.failed_names_read)} in name order. A busier name may be missing.</span>
				</p>
			{/if}
			<DataTable {columns} rows={data.failed_names} ariaLabel="Names that failed" rowKey={(r) => r.name} initialSort={{ key: 'lookups', dir: 'desc' }} />
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.eyebrow { margin: 0 0 var(--sp-1); }
	/* a full IPv6 address has no space to break at */
	.page-title { overflow-wrap: anywhere; }
	.notice { margin-bottom: var(--sp-3); }
	.story p { margin: 0 0 var(--sp-3); color: var(--text-2); font-size: var(--text-sm); }
	.todo ul { margin: 0; padding-left: var(--sp-4); }
	.links { margin: var(--sp-3) 0 0; font-size: var(--text-sm); color: var(--text-3); }
</style>
