<script lang="ts">
	/**
	 * A domain (NET-160): who looked the name up, what it resolved to, its TLS sessions and the
	 * alerts tagged with it, in the window. Every figure comes from /api/domains/{name}, which
	 * matches the name exactly, ignoring case and a trailing dot. Lookups and devices mean what
	 * they mean on DNS analytics (the same exclusions). A list too long to count withholds its KPI.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { getDomainSummary, type DomainAnswer, type DomainAsker, type DomainSummary } from '$lib/api/drilldown';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { domainHref, ipHref } from '$lib/stores/lan';
	import { namesByIp } from '$lib/utils/device-names';
	import { DRILL_RANGES, certificatesHref, fmt, rangeWindow, type DrillRange, type DrillRangeValue } from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';
	import IPAddress from '$components/IPAddress.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import { formatWhen, statusList } from '../../certificates/cert-view';
	import { alertCoverage } from './domain-view';

	interface TlsPeer {
		ip: string;
		lan: boolean;
		sessions: number;
	}

	/** The name as the daemon matches it: one trailing dot dropped, lower case. */
	const name = $derived(decodeURIComponent(($page.params as Record<string, string>).name ?? '').trim().replace(/\.$/, '').toLowerCase());

	let rangeValue = $state<DrillRangeValue>('24h');
	const range = $derived(DRILL_RANGES.find((r) => r.value === rangeValue) ?? DRILL_RANGES[0]);
	let span = $state<{ from: string; to: string }>({ from: '', to: '' });
	let loaded = $state<{ data: DomainSummary; range: DrillRange } | null>(null);
	let failure = $state<string | null>(null);
	let names = $state<ReadonlyMap<string, string>>(new Map());
	/** name|range of the figures on screen (not reactive: only the loader reads it) */
	let loadedView = '';

	const data = $derived(loaded?.data ?? null);
	const words = $derived(loaded?.range.words ?? range.words);

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);

	$effect(() => {
		void name; // another domain
		void rangeValue; // another window
		untrack(() => refresh.run());
	});

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const target = name;
		const r = range;
		if (!target) return 'skipped';
		const s = rangeWindow(r.hours);
		const view = `${target}|${r.value}`;
		// A refresh of the same view keeps its last good figures; another view must not show them
		if (view !== loadedView) {
			loaded = null;
			failure = null;
		}
		span = s;
		const namesLoad = getRegistryDevices({ limit: 200 }).then(
			(res) => namesByIp(res.devices),
			() => null,
		);
		const results = await Promise.allSettled([getDomainSummary(target, s.from, s.to)]);
		// Names are cosmetic: a failed registry load keeps the last names and isn't a failure
		const loadedNames = await namesLoad;
		if (!guard.current(g)) return 'skipped';
		const [summaryRes] = results;
		if (loadedNames) names = loadedNames;
		if (summaryRes.status === 'fulfilled') {
			loaded = { data: summaryRes.value, range: r };
			loadedView = view;
			failure = null;
		} else {
			failure = summaryRes.reason instanceof Error ? summaryRes.reason.message : '';
		}
		return outcome(results);
	}

	// --- Figures ---

	const timeline = $derived(data?.dns.timeline ?? []);
	const busiest = $derived(timeline.reduce((best, p, i) => (p.n > (timeline[best]?.n ?? -1) ? i : best), -1));
	const chartTime = (t: number | string): string => {
		const d = new Date(t);
		return range.hours <= 24
			? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
			: d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
	};
	const chartLabel = $derived(
		busiest >= 0 ? `Busiest at ${chartTime(timeline[busiest].t)}, with ${fmt(timeline[busiest].n)} lookups` : 'No lookups in this window',
	);
	const rcodeBars = $derived(
		(data?.dns.rcodes ?? []).map((r) => ({ key: r.rcode ?? '(none)', label: r.rcode ?? 'No response code', value: r.lookups, display: fmt(r.lookups) })),
	);
	const KIND_WORDS: Record<DomainAnswer['kind'], string> = { ip: 'Address', name: 'Name', other: 'Other record' };

	const askerColumns: Column<DomainAsker>[] = [
		{ key: 'ip', label: 'Device', sortValue: (a) => names.get(a.ip) ?? a.ip, cell: askerCell },
		{ key: 'lookups', label: 'Lookups', numeric: true, cell: askerLookupsCell },
		{ key: 'last_seen', label: 'Last seen', sortValue: (a) => Date.parse(a.last_seen) || 0, cell: askerSeenCell },
	];
	const answerColumns: Column<DomainAnswer>[] = [
		{ key: 'value', label: 'Answer', cell: answerCell },
		{ key: 'kind', label: 'Kind', sortValue: (a) => KIND_WORDS[a.kind], cell: answerKindCell },
		{ key: 'lookups', label: 'Lookups', numeric: true, cell: answerLookupsCell },
	];
	const tlsColumns: Column<TlsPeer>[] = [
		{ key: 'ip', label: 'Address', sortValue: (p) => names.get(p.ip) ?? p.ip, cell: tlsPeerCell },
		{ key: 'sessions', label: 'Sessions', numeric: true, cell: tlsSessionsCell },
	];
	const httpLogs = $derived(`/logs?query=${encodeURIComponent(`zeek.http.host:"${name}"`)}`);
</script>

{#snippet who(ip: string)}
	{@const known = names.get(ip)}
	{#if known}
		<span class="two"><a href={$ipHref(ip)}>{known}</a><span class="mono dim">{ip}</span></span>
	{:else}
		<IPAddress {ip} />
	{/if}
{/snippet}
{#snippet askerCell(a: DomainAsker)}{@render who(a.ip)}{/snippet}
{#snippet askerLookupsCell(a: DomainAsker)}{fmt(a.lookups)}{/snippet}
{#snippet askerSeenCell(a: DomainAsker)}<span class="num">{formatWhen(a.last_seen)}</span>{/snippet}
{#snippet answerCell(a: DomainAnswer)}
	{#if a.kind === 'ip'}<IPAddress ip={a.value} />
	{:else if a.kind === 'name'}<a class="mono" href={domainHref(a.value)}>{a.value}</a>
	{:else}<span class="mono trunc" title={a.value}>{a.value}</span>{/if}
{/snippet}
{#snippet answerKindCell(a: DomainAnswer)}{KIND_WORDS[a.kind]}{/snippet}
{#snippet answerLookupsCell(a: DomainAnswer)}{fmt(a.lookups)}{/snippet}
{#snippet tlsPeerCell(p: TlsPeer)}{@render who(p.ip)}{/snippet}
{#snippet tlsSessionsCell(p: TlsPeer)}{fmt(p.sessions)}{/snippet}

{#snippet summaryState(what: string)}
	{#if !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
	{/if}
{/snippet}

{#snippet incomplete(what: string, shown: number)}
	<p class="notice is-warn" role="status"><Icon name="warn" /><span>Too many {what} to list them all: showing the first {fmt(shown)}.</span></p>
{/snippet}

<svelte:head>
	<title>{name} | Domain | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<h1 class="page-title mono">{name}</h1>
		<p class="page-sub">Who looked this name up, what it resolved to, and its TLS sessions. Matches the name exactly, ignoring case · {words}</p>
	</div>
	<div class="head-actions">
		<Pills options={DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }))} bind:value={rangeValue} ariaLabel="Time range" />
	</div>
</header>

<div class="grid">
	{#if failure && data}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('this domain', true)} {failure}</span></p>
	{/if}
	<KpiCard class="c-3" label="Lookups" icon="dns" value={data ? fmt(data.dns.lookups) : '—'} sub={data ? 'DNS queries for this name' : undefined} note={words} />
	<KpiCard
		class="c-3"
		label="Devices that looked it up"
		icon="devices"
		value={data && data.dns.askers_complete ? fmt(data.dns.askers.length) : '—'}
		sub={data ? (data.dns.askers_complete ? 'asked for this name' : 'too many to count') : undefined}
		note={words}
	/>
	<KpiCard
		class="c-3"
		label="Addresses it resolved to"
		icon="connections"
		value={data && data.dns.addresses !== null ? fmt(data.dns.addresses) : '—'}
		sub={data ? (data.dns.addresses === null ? 'too many to count' : 'distinct IP answers') : undefined}
		note={words}
	/>
	<KpiCard class="c-3" label="TLS sessions" icon="certs" value={data ? fmt(data.tls.sessions) : '—'} sub={data ? 'that asked for this name' : undefined} note={words} />
</div>

<div class="grid">
	<Card class="c-8" hero title="Lookups over time" sub="DNS lookups per interval · {words}">
		{#if !data}
			{@render summaryState('lookups over time')}
		{:else if data.dns.lookups === 0}
			<CardState state="empty" icon="dns" title="No lookups in the {words}" message="None of your devices asked for this name in this window. Try a longer range." />
		{:else}
			<AreaChart
				series={[{ key: 'lookups', label: 'Lookups', colour: 1, points: timeline.map((p) => ({ t: p.t, v: p.n })) }]}
				formatX={chartTime}
				formatY={fmt}
				formatTip={(i) => `${chartTime(timeline[i].t)} · ${fmt(timeline[i].n)} lookups`}
				highlightIndex={busiest}
				ariaLabel={chartLabel}
			/>
		{/if}
	</Card>

	<Card class="c-4" title="Alerts tagged with this name" sub="Suricata alerts whose host fields name it · {words}">
		{#if !data}
			{@render summaryState('the alerts tagged with this name')}
		{:else}
			<p class="big">{data.alerts.tagged === null ? 'Not recorded' : fmt(data.alerts.tagged)}</p>
			<p class="coverage">{alertCoverage(data.alerts)}</p>
			<p class="dim small">
				Counts alerts whose DNS question, TLS name, URL domain or related hosts equal this name. Alerts with no host name can't be matched, so
				this isn't every alert tied to the domain.
			</p>
			<a class="link" href="/alerts">Open alerts<Icon name="back" class="chev" /></a>
		{/if}
	</Card>
</div>

<div class="grid">
	<Card class="c-6" title="Devices that looked it up" sub={data ? `${fmt(data.dns.askers.length)} ${data.dns.askers.length === 1 ? 'device' : 'devices'} · lookups per device · ${words}` : 'Lookups per device'}>
		{#if !data}
			{@render summaryState('the devices that looked it up')}
		{:else if data.dns.askers.length === 0}
			<CardState state="empty" icon="devices" title="No device looked it up" message="Devices appear here once one asks for this name." />
		{:else}
			{#if !data.dns.askers_complete}{@render incomplete('devices', data.dns.askers.length)}{/if}
			<DataTable columns={askerColumns} rows={data.dns.askers} ariaLabel="Devices that looked it up" rowKey={(a) => a.ip} initialSort={{ key: 'lookups', dir: 'desc' }} />
		{/if}
	</Card>

	<Card class="c-6" title="What it resolved to" sub={data ? `Lookups whose answer held each value · ${words}` : 'Lookups per answer'}>
		{#if !data}
			{@render summaryState('what it resolved to')}
		{:else if data.dns.answers.length === 0}
			<CardState state="empty" icon="dns" title="No answers recorded" message="Answers appear here once a lookup for this name gets one." />
		{:else}
			{#if !data.dns.answers_complete}{@render incomplete('answers', data.dns.answers.length)}{/if}
			<DataTable columns={answerColumns} rows={data.dns.answers} ariaLabel="What it resolved to" rowKey={(a) => `${a.kind}:${a.value}`} initialSort={{ key: 'lookups', dir: 'desc' }} />
		{/if}
	</Card>

	<Card class="c-8" title="TLS" sub={data ? `${fmt(data.tls.sessions)} ${data.tls.sessions === 1 ? 'session' : 'sessions'} that asked for this name · ${words}` : 'Sessions that asked for this name'}>
		{#if !data}
			{@render summaryState('its TLS sessions')}
		{:else if data.tls.sessions === 0}
			<CardState state="empty" icon="certs" title="No TLS sessions for this name in the {words}" message="Sessions appear here once a device opens TLS and asks for this name." />
		{:else}
			<p class="dim small">Verification: {statusList(data.tls.statuses) || '—'}</p>
			<div class="tls-lists">
				<div>
					<h3 class="list-title">Servers</h3>
					{#if !data.tls.servers_complete}{@render incomplete('servers', data.tls.servers.length)}{/if}
					<DataTable columns={tlsColumns} rows={data.tls.servers} ariaLabel="Servers that answered for this name" rowKey={(p) => p.ip} initialSort={{ key: 'sessions', dir: 'desc' }} />
				</div>
				<div>
					<h3 class="list-title">Devices</h3>
					{#if !data.tls.clients_complete}{@render incomplete('devices', data.tls.clients.length)}{/if}
					<DataTable columns={tlsColumns} rows={data.tls.clients} ariaLabel="Devices that opened TLS to this name" rowKey={(p) => p.ip} initialSort={{ key: 'sessions', dir: 'desc' }} />
				</div>
			</div>
			<a class="link" href={certificatesHref({ site: name, ...span })}>Certificates seen for this name<Icon name="back" class="chev" /></a>
		{/if}
	</Card>

	<Card class="c-4" title="Response codes" sub="Lookups per DNS response code · {words}">
		{#if !data}
			{@render summaryState('response codes')}
		{:else if rcodeBars.length === 0}
			<CardState state="empty" icon="dns" title="No lookups in the {words}" />
		{:else}
			<BarList items={rcodeBars} />
		{/if}
	</Card>

	<Card class="c-6" title="HTTP" sub="Unencrypted web requests naming this host · {words}">
		{#if !data}
			{@render summaryState('HTTP requests')}
		{:else}
			<p class="big">{fmt(data.http.requests)}</p>
			<p class="dim small">{data.http.requests === 1 ? 'request' : 'requests'} with this host name, over plain HTTP</p>
			<!-- OLD CODE START — Log Explorer matches the exact spelling, so it can list fewer than the count above
			<a class="link" href={httpLogs}>Search them in Log Explorer<Icon name="back" class="chev" /></a>
			OLD CODE END -->
			<a class="link" href={httpLogs}>Search Log Explorer for “{name}”<Icon name="back" class="chev" /></a>
			<p class="dim small">Log Explorer matches this exact spelling, so it can list fewer requests than this count, which ignores case.</p>
		{/if}
	</Card>

	<Card class="c-6" title="Look it up now" sub="Live checks, not what was recorded">
		<div class="actions">
			<a class="btn" href="/tools/dns-recon?domain={encodeURIComponent(name)}"><Icon name="dns" />DNS records</a>
			<a class="btn" href="/tools/ssl-cert?host={encodeURIComponent(name)}"><Icon name="certs" />Its certificate now</a>
		</div>
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.two { display: inline-flex; flex-direction: column; line-height: 1.3; }
	.big { margin: 0; font-size: var(--text-xl); font-weight: 700; color: var(--text-1); font-variant-numeric: tabular-nums; }
	.coverage { margin: var(--sp-2) 0 0; color: var(--text-1); font-size: var(--text-sm); }
	.small { margin: var(--sp-2) 0 var(--sp-3); font-size: var(--text-sm); }
	.tls-lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--sp-4); margin-bottom: var(--sp-3); }
	.list-title { margin: 0 0 var(--sp-2); font-size: var(--text-sm); color: var(--text-2); }
</style>
