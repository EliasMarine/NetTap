<script lang="ts">
	/**
	 * One Suricata rule: what it means, when it fired, which of your devices and which remote
	 * addresses were involved. Keyed by the exact rule name (the Alerts list's signature= filter);
	 * every figure comes from one snapshot (/api/alerts/rule/{name}) and links to the list built
	 * from the same filters over the response's own window.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/state'; // kit 3: $app/stores → $app/state; goto keepFocus + noScroll → reset: false, replaceState → replace (NET-315)
	import { goto } from '$app/navigation';
	import { getSuricataRule, type RuleAddresses, type RuleAddressRow, type RuleLink, type SuricataRuleFigures } from '$lib/api/drilldown';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { ipHref } from '$lib/stores/lan';
	import { namesByIp } from '$lib/utils/device-names';
	import {
		alertsHrefForSignature,
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
		suricataCategoryHref,
		withCount,
		type DrillRange,
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
	import { addressScope, dominantLevel, groupCount, ratingWords, roleOf } from './rule-view';

	type RuleRange = Pick<DrillRange, 'label' | 'hours' | 'words'> & { value: string };

	/** The stored name, as given: SvelteKit has decoded the path segment once. */
	const name = $derived((page.params as Record<string, string>).name ?? '');
	const params = $derived(page.url.searchParams);
	const custom = $derived(customRange(params.get('from'), params.get('to')));
	const baseRange = $derived(DRILL_RANGES.find((r) => r.value === params.get('range')) ?? DRILL_RANGES.find((r) => r.value === startRange('24h'))!);
	const range = $derived<RuleRange>(custom ?? baseRange);
	/** The activity list (alerts ET rates Informational or Unknown) instead of the counted one */
	const activity = $derived(params.get('activity') === 'true');
	const view = $derived(`${name}|${baseRange.value}|${custom?.from ?? ''}|${custom?.to ?? ''}|${activity}`);

	let loaded = $state<{ data: SuricataRuleFigures; range: RuleRange; base: string } | null>(null);
	let failure = $state<string | null>(null);
	let names = $state<Map<string, string>>(new Map());
	/** The view of the figures on screen (not reactive: only the loader reads it) */
	let loadedView = '';

	const data = $derived(loaded?.data ?? null);
	const shown = $derived(loaded?.range ?? range);
	const words = $derived(shown.words);
	const figuresWindow = $derived(loaded ? { from: loaded.data.from, to: loaded.data.to, range: loaded.base } : undefined);

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	$effect(() => {
		void view; // another rule, window or list
		untrack(() => refresh.run());
	});

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const [target, r, base, v, act] = [name, range, baseRange.value, view, activity];
		if (!target) return 'skipped';
		const win = custom ? { from: custom.from, to: custom.to } : rangeWindow(r.hours);
		// A refresh of the same view keeps its last good figures; another view must not show them
		if (v !== loadedView) {
			loaded = null;
			failure = null;
			loadedView = '';
		}
		const namesLoad = getRegistryDevices({ limit: 200 }).then(
			(res) => namesByIp(res.devices),
			() => null,
		);
		const results = await Promise.allSettled([getSuricataRule(target, win.from, win.to, bucketFor(Date.parse(win.from), Date.parse(win.to)).bucket, act)]);
		// Names are cosmetic: a failed registry load keeps the last names and isn't a failure
		const loadedNames = await namesLoad;
		if (!guard.current(g)) return 'skipped';
		if (loadedNames) names = loadedNames;
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

	/** This page with one setting changed (the other list, or a rolling range ending now). */
	function reopen(change: { range?: string; activity?: boolean }) {
		const q = new URLSearchParams(page.url.search);
		if (change.range) {
			q.delete('from');
			q.delete('to');
			q.set('range', change.range);
		}
		if (change.activity !== undefined) {
			if (change.activity) q.set('activity', 'true');
			else q.delete('activity');
		}
		void goto(`${page.url.pathname}?${q.toString()}`, { replace: true, reset: false });
	}

	/** The Alerts list holding a figure on screen: this rule, on this page's list, narrowed by `ip`, carrying that figure. */
	const listHref = (count: number, ip?: string): string =>
		loaded && figuresWindow ? withCount(alertsHrefForSignature(loaded.data.name, figuresWindow, { ip, activity: loaded.data.activity }), count) : '';

	// --- Figures ---

	const timeline = $derived(data?.timeline ?? []);
	const chart = $derived(data ? toTimeChart(data, timeline.map((p) => p.t), timeline.map((p) => p.n)) : null);
	const slot = $derived(bucketWords(data?.interval, 'slot'));
	function pickSlots(c: TimeChart, i: number, j: number) {
		if (!loaded) return;
		const href = alertsHrefForSignature(loaded.data.name, { ...pickWindow(c, i, j), range: loaded.base }, { activity: loaded.data.activity });
		void goto(withCount(href, pickedTotal(c, i, j)));
	}
	const busiest = $derived(timeline.reduce((best, p, i) => (p.n > (timeline[best]?.n ?? -1) ? i : best), -1));
	const timeOf = (t: number | string): string => chartTime(t, shown.hours);
	const chartLabel = $derived(busiest >= 0 ? `Busiest at ${timeOf(timeline[busiest].t)}, with ${fmt(timeline[busiest].n)} alerts` : 'No alerts in this window');
	const alertWord = (n: number) => (n === 1 ? 'alert' : 'alerts');
	const listWord = $derived(activity ? 'activity' : 'counted');
	/** The other list's total, when this one is empty and that one isn't */
	const otherTotal = $derived(data ? (data.activity ? data.counted_total : data.activity_total) : 0);
	const emptyTitle = $derived(`No ${listWord} alerts for this rule in the ${words}`);
	const level = $derived(data ? dominantLevel(data.severity) : null);
	const listOptions = $derived([
		{ value: 'counted', label: data ? `Counted · ${fmt(data.counted_total)}` : 'Counted' },
		{ value: 'activity', label: data ? `Activity · ${fmt(data.activity_total)}` : 'Activity' },
	]);

	// OLD CODE: const addressColumns = (label: string, withRole: boolean) … ...(withRole ? [role column] : []), (every table has the role)
	const addressColumns = (label: string): Column<RuleAddressRow>[] => [
		{ key: 'ip', label, cell: whoCell, sortValue: (r) => names.get(r.ip) ?? r.ip },
		{ key: 'role', label: 'Role', sortValue: (r) => roleOf(r), cell: roleCell },
		{ key: 'alerts', label: 'Alerts', numeric: true, cell: alertsCell },
		{ key: 'first_seen', label: 'First seen', sortValue: (r) => (r.first_seen ? Date.parse(r.first_seen) || 0 : 0), cell: firstCell },
		{ key: 'last_seen', label: 'Last seen', sortValue: (r) => (r.last_seen ? Date.parse(r.last_seen) || 0 : 0), cell: lastCell },
	];
	const deviceColumns = $derived(addressColumns('Device'));
	const remoteColumns = $derived(addressColumns('Address'));
</script>

{#snippet whoCell(r: RuleAddressRow)}
	{@const known = names.get(r.ip)}
	{#if known}
		<span class="two"><a href={$ipHref(r.ip)}>{known}</a><span class="mono dim">{r.ip}</span></span>
	{:else}
		<IPAddress ip={r.ip} />
	{/if}
{/snippet}
{#snippet roleCell(r: RuleAddressRow)}{roleOf(r)}{/snippet}
{#snippet alertsCell(r: RuleAddressRow)}<a href={listHref(r.alerts, r.ip)} title="These alerts with this address at either end, over the same window">{fmt(r.alerts)}</a>{/snippet}
{#snippet firstCell(r: RuleAddressRow)}<span class="num">{formatWhen(r.first_seen)}</span>{/snippet}
{#snippet lastCell(r: RuleAddressRow)}<span class="num">{formatWhen(r.last_seen)}</span>{/snippet}

{#snippet summaryState(what: string)}
	{#if !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
	{/if}
{/snippet}

{#snippet links(list: RuleLink[])}
	{#if list.length}
		<ul class="links">
			{#each list as link (link.url)}
				<li><a href={link.url} target="_blank" rel="noopener noreferrer">{link.label}</a> <span class="dim">· {link.source}</span></li>
			{/each}
		</ul>
	{/if}
{/snippet}

{#snippet group(g: RuleAddresses, columns: Column<RuleAddressRow>[], label: string, noneTitle: string)}
	{@const scope = addressScope(g)}
	{#if g.rows.length === 0}
		<CardState state="empty" icon="connections" title={noneTitle} />
	{:else}
		{#if scope.partial}
			<p class="notice is-warn" role="status"><Icon name="warn" /><span>{scope.text}</span></p>
		{:else}
			<p class="dim small">{scope.text}</p>
		{/if}
		<DataTable {columns} rows={g.rows} ariaLabel={label} rowKey={(r) => r.ip} initialSort={{ key: 'alerts', dir: 'desc' }} />
	{/if}
{/snippet}

<svelte:head>
	<title>{name} | Suricata rule | NetTap</title>
</svelte:head>

<header class="page-head">
	<div class="head-text">
		<p class="eyebrow">Suricata rule</p>
		<h1 class="page-title rule-name">{name}</h1>
		<p class="page-sub">What this rule means, when it fired and which addresses it involved · {words}</p>
	</div>
	<div class="head-actions">
		<Pills options={listOptions} value={activity ? 'activity' : 'counted'} onchange={(v) => reopen({ activity: v === 'activity' })} ariaLabel="Which alerts" />
		<Pills
			options={[...DRILL_RANGES, ...(custom ? [custom] : [])].map((r) => ({ value: r.value, label: r.label }))}
			value={range.value}
			onchange={(v) => v !== 'custom' && reopen({ range: v })}
			ariaLabel="Time range"
		/>
	</div>
</header>

<div class="grid">
	{#if failure && data}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('this rule', true)} {failure}</span></p>
	{/if}
	{#if activity}
		<p class="notice c-12" role="status"><Icon name="alerts" /><span>Activity: ET rates these rules Informational or Unknown, so NetTap doesn't count them as alerts.</span></p>
	{/if}
	<KpiCard
		class="c-3"
		label="Alerts"
		icon="alerts"
		value={data ? fmt(data.total) : '—'}
		sub={data ? `${listWord} alerts from this rule` : undefined}
		note={words}
		href={data ? listHref(data.total) : undefined}
		title={data ? 'These alerts in the Alerts list over the same window' : undefined}
	/>
	<KpiCard class="c-3" label="Your devices involved" icon="devices" value={data ? groupCount(data.devices) : '—'} note={words} />
	<KpiCard class="c-3" label="Remote addresses" icon="connections" value={data ? groupCount(data.remotes) : '—'} note={words} />
	<KpiCard class="c-3" label="Last seen" icon="live" value={data ? formatWhen(data.last_seen) : '—'} note={data?.first_seen ? `first ${formatWhen(data.first_seen)}` : words} />
</div>

<div class="grid">
	<Card class="c-8" hero col title="Alerts over time" sub="Alerts per {slot} · {words}">
		{#if !data}
			{@render summaryState('alerts over time')}
		{:else if data.total === 0}
			<CardState
				state="empty"
				icon="alerts"
				title={emptyTitle}
				message={otherTotal > 0 ? `The ${data.activity ? 'counted' : 'activity'} list has ${fmt(otherTotal)} ${alertWord(otherTotal)} from it.` : 'Try a longer range.'}
				actionLabel={otherTotal > 0 ? `Show the ${data.activity ? 'counted' : 'activity'} alerts` : undefined}
				onaction={otherTotal > 0 ? () => reopen({ activity: !data!.activity }) : undefined}
			/>
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
			{#if chart}<p class="card-sub pick-hint">Click a point or drag across the chart to see those alerts.</p>{/if}
		{/if}
	</Card>

	<Card class="c-4" title="What this rule means" sub="In plain English">
		{#if !data}
			{@render summaryState('the explanation')}
		{:else}
			{#if level}<div class="sev"><SeverityPill {level} /><span class="dim small-inline">most of these alerts</span></div>{/if}
			<p>{data.explanation.what}</p>
			<h3 class="sub-head">The risk</h3>
			<p>{data.explanation.risk}</p>
			<h3 class="sub-head">What to do</h3>
			<p>{data.explanation.todo}</p>
			{#if data.explanation.family === 'own'}<p><a class="link" href="/settings?tab=suricata-rules">Open your rules in Settings</a></p>{/if}
			{#if data.learn_more.length}
				<h3 class="sub-head">Learn more</h3>
				{@render links(data.learn_more)}
			{/if}
			{#if data.total > 0}<p><a class="link" href={listHref(data.total)}>Show these {fmt(data.total)} {alertWord(data.total)} in the list</a></p>{/if}
		{/if}
	</Card>
</div>

<div class="grid">
	<Card class="c-12" title="Rule details" sub="What each rule with this name records · its newest alert in the {words}">
		{#if !data}
			{@render summaryState('the rule details')}
		{:else if data.rules.length === 0 && data.no_sid === 0}
			<CardState state="empty" icon="alerts" title={emptyTitle} message="Details appear once the rule fires in this window." />
		{:else}
			{#if data.rules.length > 1}<p class="dim small">{fmt(data.rules.length)} rules share this name; each keeps its own details.</p>{/if}
			{#each data.rules as rule (rule.sid)}
				<section class="sid">
					<h3 class="sub-head">SID <span class="mono">{rule.sid}</span> · {fmt(rule.alerts)} {alertWord(rule.alerts)}</h3>
					<dl class="facts">
						<dt>ET rating</dt>
						<dd>{ratingWords(rule.et_ratings)}</dd>
						<!-- OLD CODE: {#if rule.categories.length}<dt>Category</dt><dd>{rule.categories.join(', ')}</dd>{/if} (each opens its category page) -->
						<!-- The category page counts only counted alerts, so the activity list doesn't link to it (as on Alerts) -->
						{#if rule.categories.length}
							<dt>Category</dt>
							<dd>
								{#each rule.categories as c, i (i)}{#if i > 0}, {/if}{#if data.activity}{c}{:else}<a href={suricataCategoryHref(c, figuresWindow)}>{c}</a>{/if}{/each}
							</dd>
						{/if}
						{#if rule.techniques.length || rule.tactics.length}
							<dt>MITRE ATT&CK</dt>
							<dd class="chips">
								{#each [...rule.techniques, ...rule.tactics] as t (t.id)}<span class="chip">{t.id}{t.name ? ` ${t.name}` : ''}</span>{/each}
							</dd>
						{/if}
						{#if rule.cves.length}<dt>Vulnerabilities</dt><dd class="mono">{rule.cves.join(', ')}</dd>{/if}
						{#if rule.cisa_kev}<dt>Known exploited</dt><dd><span class="chip is-warn"><Icon name="warn" />On CISA's known exploited list</span></dd>{/if}
						{#if rule.dbl_lists.length}<dt>IPFire DBL</dt><dd>{rule.dbl_lists.join(', ')}</dd>{/if}
						{#if rule.credential}<dt>Secret</dt><dd><span class="chip is-warn"><Icon name="warn" />Names a secret sent in the clear</span></dd>{/if}
					</dl>
					{#if rule.advice}<p>{rule.advice.what} {rule.advice.todo}</p>{/if}
					{@render links(rule.learn_more)}
				</section>
			{/each}
			{#if !data.rules_complete}<p class="notice is-warn" role="status"><Icon name="warn" /><span>Not every rule is listed: this name has more rules than the page shows.</span></p>{/if}
			{#if data.no_sid > 0}<p class="dim small">{fmt(data.no_sid)} {alertWord(data.no_sid)} had no SID, so {data.no_sid === 1 ? "it isn't" : "they aren't"} under any rule above.</p>{/if}
		{/if}
	</Card>

	<Card class="c-6" title="Your devices" sub="Alerts per device · {words}">
		{#if !data}
			{@render summaryState('your devices')}
		{:else}
			{@render group(data.devices, deviceColumns, 'Your devices in these alerts', `None of your devices in the ${words}`)}
			{#if data.devices.rows.length}
				<p class="dim small">Received it means the device was the destination. Some rules match a reply, so the device may have started that conversation.</p>
			{/if}
		{/if}
	</Card>

	<Card class="c-6" title="Remote addresses" sub="Alerts per address outside your network · {words}">
		{#if !data}
			{@render summaryState('the remote addresses')}
		{:else}
			{@render group(data.remotes, remoteColumns, 'Remote addresses in these alerts', `No remote address in the ${words}`)}
			{#if data.missing_address > 0}<p class="dim small">{fmt(data.missing_address)} {alertWord(data.missing_address)} had no address at either end.</p>{/if}
		{/if}
	</Card>

	{#if data && data.unplaced.rows.length}
		<Card class="c-12" title="Locality unknown" sub="IPv6 addresses in these alerts · {words}">
			<p class="dim small">NetTap's LAN rule covers IPv4 only, so it can't say whether these IPv6 addresses are your devices.</p>
			{@render group(data.unplaced, remoteColumns, 'IPv6 addresses in these alerts', '')}
		</Card>
	{/if}
</div>

<style>
	/* Layout glue the system lacks */
	.eyebrow { margin: 0 0 var(--sp-1); }
	.head-text { min-width: 0; }
	.rule-name { overflow-wrap: anywhere; }
	.head-actions { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
	.small { margin: 0 0 var(--sp-3); font-size: var(--text-sm); }
	.small-inline { font-size: var(--text-sm); }
	.notice { margin-bottom: var(--sp-3); }
	.pick-hint { margin-top: var(--sp-2); }
	.sev { display: flex; align-items: center; gap: var(--sp-2); margin-bottom: var(--sp-3); }
	.sub-head { margin: var(--sp-4) 0 var(--sp-1); font-size: var(--text-sm); color: var(--text-2); }
	.links { margin: 0 0 var(--sp-3); padding-left: var(--sp-4); display: grid; gap: var(--sp-1); font-size: var(--text-sm); overflow-wrap: anywhere; }
	.sid + .sid { margin-top: var(--sp-4); padding-top: var(--sp-3); border-top: 1px solid var(--line); }
	/* OLD CODE: .facts { …; grid-template-columns: max-content 1fr; … } (1fr can't shrink below a nowrap chip, so 390 px scrolled sideways) */
	.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: var(--sp-1) var(--sp-4); margin: 0 0 var(--sp-3); font-size: var(--text-sm); }
	.facts dt { color: var(--text-3); }
	.facts dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
	/* A technique's name, a CVE or the KEV chip wraps inside its cell at phone width */
	.facts .chip { white-space: normal; overflow-wrap: anywhere; min-width: 0; }
</style>
