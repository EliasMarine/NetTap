<script lang="ts">
	/**
	 * A raw Suricata category (NET-160 slice 2b-2): how many alerts carry it, at what severity, over
	 * time, which rules and addresses, and which other categories the same alerts carry. Every figure
	 * comes from one snapshot (/api/alerts/suricata/{name}, an exact match on rule.category) and links
	 * to the Alerts list built from the same filters over the response's own window.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { getSuricataCategory, type SuricataAddressRow, type SuricataCategoryFigures, type SuricataRuleRow, type SuricataTopList } from '$lib/api/drilldown';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	// OLD CODE: import { chartTime, customRange, fmt, formatWhen, rangeWindow, suricataAlertsHref, suricataCategoryHref, type SuricataNarrow } from '$lib/utils/drilldown'; (section D)
	// OLD CODE: import { chartTime, customRange, fmt, formatWhen, rangeWindow, startRange, suricataAlertsHref, suricataCategoryHref, withCount, type SuricataNarrow } from '$lib/utils/drilldown'; (NET-249: picks)
	import {
		bucketFor,
		chartTime,
		customRange,
		DRILL_RANGES,
		fmt,
		formatWhen,
		pickedTotal,
		pickWindow,
		rangeWindow,
		startRange,
		suricataAlertsHref,
		suricataCategoryHref,
		withCount,
		type SuricataNarrow,
		type TimeChart,
	} from '$lib/utils/drilldown';
	import { toTimeChart } from '$lib/utils/chart-pick';
	import { bucketWords } from '$lib/utils/narrow-page';
	import { loadFailed } from '$lib/utils/load-failed';
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import { CATEGORY_RANGES, listScope, slotWords, type CategoryRange } from './suricata-view';

	type Level = 'high' | 'medium' | 'low' | 'info';
	const LEVELS: readonly Level[] = ['high', 'medium', 'low', 'info'];

	/** The stored value, as given: SvelteKit has decoded the path segment once. */
	const name = $derived(($page.params as Record<string, string>).name ?? '');
	const params = $derived($page.url.searchParams);
	/** The exact window a link brought (?from=&to=), shown as "Custom". */
	const custom = $derived(customRange(params.get('from'), params.get('to')));
	/** The URL's standard range (without one, the saved default, else 24h): a Custom window's links carry it for their words. */
	// OLD CODE: ?? CATEGORY_RANGES[4]); (NET-192 PR 4: 15m and 4h dropped, 24h is index 2)
	// OLD CODE: ?? CATEGORY_RANGES[2] (NET-192 PR 4: the default by value, not by position)
	// OLD CODE: … ?? CATEGORY_RANGES.find((r) => r.value === '24h')!); (NET-195: a link's range, else Settings › Display's default)
	const baseRange = $derived(CATEGORY_RANGES.find((r) => r.value === params.get('range')) ?? CATEGORY_RANGES.find((r) => r.value === startRange('24h'))!);
	const range = $derived<CategoryRange>(custom ?? baseRange);
	const view = $derived(`${name}|${baseRange.value}|${custom?.from ?? ''}|${custom?.to ?? ''}`);

	/** The figures on screen, with the range they answer and the URL range their links carry. */
	let loaded = $state<{ data: SuricataCategoryFigures; range: CategoryRange; base: string } | null>(null);
	let failure = $state<string | null>(null);
	/** The view of the figures on screen (not reactive: only the loader reads it) */
	let loadedView = '';

	const data = $derived(loaded?.data ?? null);
	const shown = $derived(loaded?.range ?? range);
	const words = $derived(shown.words);
	/** The response's own window: every link opens the list over exactly the bounds it counted. */
	const figuresWindow = $derived(loaded ? { from: loaded.data.from, to: loaded.data.to, range: loaded.base } : undefined);

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	$effect(() => {
		void view; // another category or window
		untrack(() => refresh.run());
	});

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const target = name;
		const r = range;
		const base = baseRange.value;
		const v = view;
		if (!target) return 'skipped';
		const win = custom ? { from: custom.from, to: custom.to } : rangeWindow(r.hours);
		// A refresh of the same view keeps its last good figures; another view must not show them
		if (v !== loadedView) {
			loaded = null;
			failure = null;
			// PR #190 review: else Back to the last good view skipped this reset and kept the failed view's error
			loadedView = '';
		}
		// OLD CODE: const results = await Promise.allSettled([getSuricataCategory(target, win.from, win.to)]); (NET-249: the owner's bucket for the window)
		const results = await Promise.allSettled([getSuricataCategory(target, win.from, win.to, bucketFor(Date.parse(win.from), Date.parse(win.to)).bucket)]);
		if (!guard.current(g)) return 'skipped';
		const [res] = results;
		if (res.status === 'fulfilled') {
			loaded = { data: res.value, range: r, base };
			loadedView = v;
			failure = null;
		} else {
			failure = res.reason instanceof Error ? res.reason.message : '';
		}
		return outcome(results);
	}

	/** A range pill: a rolling window ending now, so the link's exact window (Custom) goes. */
	function pickRange(value: string) {
		if (value !== 'custom') void goto(`${$page.url.pathname}?range=${value}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	// OLD CODE START (section D: the link carries the figure it opens, so the list can say if it differs)
	// /** The Alerts list holding a figure on screen: this category, narrowed as the figure was. */
	// const listHref = (narrow: SuricataNarrow = {}): string => (loaded && figuresWindow ? suricataAlertsHref(loaded.data.name, figuresWindow, narrow) : '');
	// OLD CODE END
	/** The Alerts list holding a figure on screen: this category, narrowed as the figure was, carrying that figure. */
	const listHref = (narrow: SuricataNarrow, count: number): string =>
		loaded && figuresWindow ? withCount(suricataAlertsHref(loaded.data.name, figuresWindow, narrow), count) : '';

	// --- Figures ---

	const timeline = $derived(data?.timeline ?? []);
	/** The timeline as a pickable chart (NET-249): null when the reply's bucket isn't one a pick can open */
	const chart = $derived(data ? toTimeChart(data, timeline.map((p) => p.t), timeline.map((p) => p.n)) : null);
	/** The slot in words, as the reply says it counted it; an older daemon's own bucket otherwise */
	// OLD CODE: const slot = $derived(DRILL_RANGES.find((r) => r.bucket === data?.interval)?.bucketWords ?? slotWords(shown.hours)); (NET-249: narrow-page's bucketWords, the one helper)
	const slot = $derived(bucketWords(data?.interval, slotWords(shown.hours)));

	/** A pick opens the Alerts list for this category over the picked slots, carrying their figure (NET-249). */
	function pickSlots(c: TimeChart, i: number, j: number) {
		if (!loaded) return;
		void goto(withCount(suricataAlertsHref(loaded.data.name, { ...pickWindow(c, i, j), range: loaded.base }), pickedTotal(c, i, j)));
	}
	const busiest = $derived(timeline.reduce((best, p, i) => (p.n > (timeline[best]?.n ?? -1) ? i : best), -1));
	const timeOf = (t: number | string): string => chartTime(t, shown.hours);
	const chartLabel = $derived(busiest >= 0 ? `Busiest at ${timeOf(timeline[busiest].t)}, with ${fmt(timeline[busiest].n)} alerts` : 'No alerts in this window');
	const emptyTitle = $derived(data ? `No alerts in “${data.name}” over the ${words}` : '');

	/** Keyed by position: a null and an empty rule name are separate rows that read the same */
	type RuleRow = SuricataRuleRow & { key: number };
	const ruleRows = $derived((data?.rules.rows ?? []).map((r, i): RuleRow => ({ ...r, key: i })));
	const ruleColumns: Column<RuleRow>[] = [
		{ key: 'rule_name', label: 'Rule', sortValue: (r) => r.rule_name ?? '', cell: ruleCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: ruleCountCell },
		{ key: 'last_seen', label: 'Last seen', sortValue: (r) => (r.last_seen ? Date.parse(r.last_seen) || 0 : 0), cell: ruleSeenCell },
	];
	const sourceColumns: Column<SuricataAddressRow>[] = [
		{ key: 'ip', label: 'Source', cell: ipCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: sourceCountCell },
	];
	const targetColumns: Column<SuricataAddressRow>[] = [
		{ key: 'ip', label: 'Target', cell: ipCell },
		{ key: 'count', label: 'Alerts', numeric: true, cell: targetCountCell },
	];
	type TaggedRow = { category: string; count: number };
	const taggedColumns: Column<TaggedRow>[] = [
		{ key: 'category', label: 'Category', cell: taggedNameCell },
		{ key: 'count', label: 'Carrying both', numeric: true, cell: taggedCountCell },
	];
	const alertWord = (n: number) => (n === 1 ? 'alert' : 'alerts');
</script>

<!-- No rule name: the list can't filter on a missing or empty rule.name, so a link would open the whole category -->
{#snippet ruleCell(r: RuleRow)}
	{#if r.rule_name}<a class="mono" href={listHref({ signature: r.rule_name }, r.count)} title="These alerts with this rule over the same window">{r.rule_name}</a>
	{:else}<span class="dim">No rule name</span>{/if}
{/snippet}
{#snippet ruleCountCell(r: RuleRow)}{fmt(r.count)}{/snippet}
{#snippet ruleSeenCell(r: RuleRow)}<span class="num">{formatWhen(r.last_seen)}</span>{/snippet}
{#snippet ipCell(r: SuricataAddressRow)}<IPAddress ip={r.ip} />{/snippet}
{#snippet sourceCountCell(r: SuricataAddressRow)}<a href={listHref({ src: r.ip }, r.count)} title="These alerts from this address over the same window">{fmt(r.count)}</a>{/snippet}
{#snippet targetCountCell(r: SuricataAddressRow)}<a href={listHref({ dst: r.ip }, r.count)} title="These alerts to this address over the same window">{fmt(r.count)}</a>{/snippet}
{#snippet taggedNameCell(c: TaggedRow)}<a href={suricataCategoryHref(c.category, figuresWindow)}>{c.category}</a>{/snippet}
<!-- Plain: the other category's page counts every alert carrying it, not only these -->
{#snippet taggedCountCell(c: TaggedRow)}{fmt(c.count)} of these {alertWord(c.count)}{/snippet}

{#snippet summaryState(what: string)}
	{#if !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
	{/if}
{/snippet}

{#snippet scope(list: SuricataTopList<unknown>, noun: string)}
	{#if list.complete && list.distinct !== null}
		<p class="dim small">{listScope(list, noun)}</p>
	{:else}
		<p class="notice is-warn" role="status"><Icon name="warn" /><span>{listScope(list, noun)}.</span></p>
	{/if}
{/snippet}

{#snippet addresses(list: SuricataCategoryFigures['sources'], columns: Column<SuricataAddressRow>[], label: string, side: string)}
	{#if list.rows.length === 0}
		<CardState state="empty" icon="connections" title="No {side} addresses in the {words}" message={list.missing > 0 ? `${fmt(list.missing)} ${alertWord(list.missing)} had no ${side} address.` : undefined} />
	{:else}
		{@render scope(list, 'addresses')}
		<DataTable {columns} rows={list.rows} ariaLabel={label} rowKey={(r) => r.ip} initialSort={{ key: 'count', dir: 'desc' }} />
		{#if list.missing > 0}<p class="dim small">{fmt(list.missing)} {alertWord(list.missing)} had no {side} address, so {list.missing === 1 ? "it isn't" : "they aren't"} listed.</p>{/if}
	{/if}
{/snippet}

<svelte:head>
	<title>{name} | Suricata category | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<p class="eyebrow">Suricata category</p>
		<h1 class="page-title">{name}</h1>
		<p class="page-sub">
			Suricata's own classification of the rules that fired. An alert can carry more than one: Malcolm adds the rule's MITRE ATT&CK tactic beside
			it, so category totals overlap · {words}
		</p>
	</div>
	<div class="head-actions">
		<Pills options={[...CATEGORY_RANGES, ...(custom ? [custom] : [])].map((r) => ({ value: r.value, label: r.label }))} value={range.value} onchange={pickRange} ariaLabel="Time range" />
	</div>
</header>

<div class="grid">
	{#if failure && data}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('this category', true)} {failure}</span></p>
	{/if}
	<KpiCard
		class="c-4"
		label="Alerts"
		icon="alerts"
		value={data ? fmt(data.total) : '—'}
		sub={data ? 'carrying this category' : undefined}
		note={words}
		href={data ? listHref({}, data.total) : undefined}
		title={data ? 'Every alert in this category over the same window' : undefined}
	/>
	<Card class="c-8" title="By severity" sub="Alerts · {words}, by Suricata severity">
		{#if !data}
			{@render summaryState('the severity counts')}
		{:else}
			<div class="sev-counts" style:--sev-chars={Math.max(...LEVELS.map((l) => fmt(data.severity[l]).length))}>
				{#each LEVELS as level (level)}
					<a class="sev-tile" href={listHref({ severity: level }, data.severity[level])} aria-label="Show the {level} alerts in this category ({fmt(data.severity[level])})">
						<SeverityPill {level} count={data.severity[level]} />
					</a>
				{/each}
			</div>
		{/if}
	</Card>
</div>

<div class="grid">
	<!-- OLD CODE: sub="Alerts per {slotWords(shown.hours)} · {words}" (NET-249: the bucket the reply says it used) -->
	<Card class="c-8" hero col title="Alerts over time" sub="Alerts per {slot} · {words}">
		{#if !data}
			{@render summaryState('alerts over time')}
		{:else if data.total === 0}
			<CardState state="empty" icon="alerts" title={emptyTitle} message="Try a longer range." />
		{:else}
			<AreaChart
				series={[{ key: 'alerts', label: 'Alerts', colour: 1, points: timeline.map((p) => ({ t: p.t, v: p.n })) }]}
				formatX={timeOf}
				formatY={fmt}
				formatTip={(i) => `${timeOf(timeline[i].t)} · ${fmt(timeline[i].n)} ${alertWord(timeline[i].n)}`}
				highlightIndex={busiest}
				ariaLabel={chartLabel}
				onpick={chart ? (i, j) => pickSlots(chart!, i, j) : undefined}
			/>
			{#if chart}<p class="card-sub pick-hint">Click a point or drag across the chart to see that moment.</p>{/if}
		{/if}
	</Card>

	<Card class="c-4" title="Also tagged" sub="Other categories these alerts carry · {words}">
		{#if !data}
			{@render summaryState('the other categories')}
		{:else if data.also_tagged.rows.length === 0}
			<CardState state="empty" icon="alerts" title={data.total === 0 ? emptyTitle : 'No other category on these alerts'} />
		{:else}
			{@render scope(data.also_tagged, 'categories')}
			<DataTable columns={taggedColumns} rows={data.also_tagged.rows} ariaLabel="Other categories these alerts carry" rowKey={(c) => c.category} initialSort={{ key: 'count', dir: 'desc' }} />
			<p class="dim small">A count here is the alerts carrying both categories. That category's own page counts every alert carrying it, so its total can be higher.</p>
		{/if}
	</Card>
</div>

<div class="grid">
	<Card class="c-12" title="Rules" sub="Alerts per rule · {words}">
		{#if !data}
			{@render summaryState('the rules')}
		{:else if ruleRows.length === 0}
			<CardState state="empty" icon="alerts" title={emptyTitle} message="Rules appear here once one of them fires in this window." />
		{:else}
			{@render scope(data.rules, 'rules')}
			<DataTable columns={ruleColumns} rows={ruleRows} ariaLabel="Rules in this category" rowKey={(r) => r.key} initialSort={{ key: 'count', dir: 'desc' }} />
		{/if}
	</Card>

	<Card class="c-6" title="Sources" sub="Alerts per source address · {words}">
		{#if !data}
			{@render summaryState('the sources')}
		{:else}
			{@render addresses(data.sources, sourceColumns, 'Sources of these alerts', 'source')}
		{/if}
	</Card>

	<Card class="c-6" title="Targets" sub="Alerts per destination address · {words}">
		{#if !data}
			{@render summaryState('the targets')}
		{:else}
			{@render addresses(data.targets, targetColumns, 'Targets of these alerts', 'destination')}
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.eyebrow { margin: 0 0 var(--sp-1); }
	.sev-tile { all: unset; display: flex; cursor: pointer; color: var(--text-1); border-radius: var(--r-md); }
	.sev-tile > :global(.sev-count) { flex: 1; transition: background var(--dur-fast); }
	.sev-tile:hover > :global(.sev-count) { background: var(--surface-3); }
	.sev-tile:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.small { margin: 0 0 var(--sp-3); font-size: var(--text-sm); }
	.notice { margin-bottom: var(--sp-3); }
	.pick-hint { margin-top: var(--sp-2); }
</style>
