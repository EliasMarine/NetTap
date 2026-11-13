<script lang="ts">
	/**
	 * A moment (NET-249): what the network was doing over the window a chart point or range opened.
	 * The window comes from the link (?from=&to=, inclusive), is never widened or invented, and every
	 * link on the page carries it. Each card loads on its own from the endpoints the other pages use,
	 * plus /api/moment/devices for the device breakdown. When the link carried the figures clicked
	 * (down, up, local), the page says where its own totals differ (NET-183).
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import Card from '$components/ui/Card.svelte';
	import CardState from '$components/ui/CardState.svelte';
	import KpiCard from '$components/ui/KpiCard.svelte';
	import BarList from '$components/ui/BarList.svelte';
	import Icon from '$components/ui/Icon.svelte';
	import SeverityPill from '$components/ui/SeverityPill.svelte';
	import AreaChart, { type AreaSeries } from '$components/ui/charts/AreaChart.svelte';
	import MomentDevices from '$lib/components/moment/MomentDevices.svelte';
	import { getTrafficSummary, getBandwidthTimeSeries, getProtocolDistribution, getTrafficCategories } from '$api/traffic';
	import type { TrafficSummary, BandwidthPoint, ProtocolsResponse, TrafficCategory } from '$api/traffic';
	import { getAlertCount, getAlerts, type AlertCountResponse, type AlertsListResponse } from '$api/alerts';
	import { getDeviceCount, type DeviceCountResponse } from '$api/devices';
	import { getChangelogEvents, type ChangelogEvent } from '$api/changelog';
	import { getMomentDevices, type MomentDevicesResponse } from '$api/moment';
	import { formatBytes } from '$api/logs';
	import { registerPageRefresh, outcome, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import {
		alertsHrefForSignature, bucketFor, chartTime, connLogsHref, customRange, DRILL_RANGES, fmt, formatWhen, linkedCount,
		momentHref, RECORDS_CHANGE, serviceLabel, serviceLogsHref, windowQuery, windowWords, withCount, type BandwidthChart, type DrillWindow,
	} from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';
	import { upDownLocal } from '$lib/utils/up-down';
	import { suricataLevel } from '$lib/utils/severity';
	import { MAX_WINDOW_SECONDS, nsEpoch, packetsUrl } from '$lib/utils/packet-query';

	const MINUTE = 60_000;
	const HOUR = 60 * MINUTE;
	const TOP_SERVICES = 10;
	const NEW_DEVICES = 50;
	const SPLIT_DIFFERS =
		"The total matches the chart. Some IPv6 traffic is split between downloaded and uploaded differently over this shorter window, because NetTap saw your router's traffic elsewhere on the chart.";
	const CHECK_DAEMON = 'Check that the daemon is running on the System page, then try again.';

	const params = $derived($page.url.searchParams);
	const win = $derived(customRange(params.get('from'), params.get('to')));
	const windowKey = $derived(win ? `${win.from}|${win.to}` : '');
	const fromMs = $derived(win ? Date.parse(win.from) : 0);
	const toMs = $derived(win ? Date.parse(win.to) : 0);
	/** The range the link came from, for the words other pages fall back to; else the smallest that covers the window */
	const range = $derived(DRILL_RANGES.find((r) => r.value === params.get('range'))?.value ?? bucketFor(fromMs, toMs).value);
	const chartWin = $derived(customRange(params.get('chart_from'), params.get('chart_to')));
	const clicked = $derived({ down: linkedCount(params.get('down')), up: linkedCount(params.get('up')), local: linkedCount(params.get('local')) });
	const words = $derived(win ? windowWords(win.from, win.to) : '');

	type Source = 'summary' | 'alertCount' | 'deviceCount' | 'chart' | 'devices' | 'protocols' | 'categories' | 'alerts' | 'joined';
	let summary = $state<TrafficSummary | null>(null);
	let alertCount = $state<AlertCountResponse | null>(null);
	let deviceCount = $state<DeviceCountResponse | null>(null);
	let chart = $state<(Omit<BandwidthChart, 'series'> & { series: BandwidthPoint[]; words: string }) | null>(null);
	let devices = $state<MomentDevicesResponse | null>(null);
	let protocols = $state<ProtocolsResponse | null>(null);
	let categories = $state<TrafficCategory[] | null>(null);
	let alerts = $state<AlertsListResponse | null>(null);
	let joined = $state<ChangelogEvent[] | null>(null);
	/** Each failed request's reason, so a card says what failed and never shows 0 or "none" */
	let failed = $state<Partial<Record<Source, string>>>({});
	/** The window whose figures are on screen (not reactive: only the loader reads it) */
	let loadedKey = '';

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const w = win;
		if (!w) return 'skipped';
		const key = `${w.from}|${w.to}`;
		if (key !== loadedKey) {
			[summary, alertCount, deviceCount, chart, devices, protocols, categories, alerts, joined] = [null, null, null, null, null, null, null, null, null];
			failed = {};
			loadedKey = key;
		}
		const q = { from: w.from, to: w.to };
		const bucket = bucketFor(Date.parse(w.from), Date.parse(w.to));
		/** Writes what a request brings only while this load is the newest */
		const settle = <T,>(source: Source, request: Promise<T>, write: (value: T) => void): Promise<T> =>
			request.then(
				(value) => {
					if (guard.current(g)) {
						write(value);
						failed = { ...failed, [source]: undefined };
					}
					return value;
				},
				(e: unknown) => {
					if (guard.current(g)) failed = { ...failed, [source]: e instanceof Error ? e.message : '' };
					throw e;
				},
			);
		const results = await Promise.allSettled([
			settle('summary', getTrafficSummary(q), (v) => (summary = v)),
			settle('alertCount', getAlertCount(q), (v) => (alertCount = v)),
			settle('deviceCount', getDeviceCount(q), (v) => (deviceCount = v)),
			settle('chart', getBandwidthTimeSeries({ ...q, interval: bucket.bucket }), (v) => {
				chart = { series: v.series, from: v.from, to: v.to, step: bucket.bucketMs, words: bucket.bucketWords };
			}),
			settle('devices', getMomentDevices(q), (v) => (devices = v)),
			settle('protocols', getProtocolDistribution(q), (v) => (protocols = v)),
			settle('categories', getTrafficCategories(q), (v) => (categories = v.categories)),
			settle('alerts', getAlerts({ ...q, size: 10, sort: 'severity', order: 'desc' }), (v) => (alerts = v)),
			settle('joined', getChangelogEvents({ ...q, type: 'device_joined', limit: NEW_DEVICES }), (v) => (joined = v.events)),
		]);
		return guard.current(g) ? outcome(results) : 'skipped';
	}

	const handle = registerPageRefresh(load);
	onDestroy(handle.unregister);
	const retry = () => void handle.run();
	$effect(() => {
		void windowKey; // another window: a widen link or a pick on this page's chart
		untrack(() => handle.run());
	});

	const iso = (ms: number) => new Date(ms).toISOString();
	/** This page over another window, keeping the range and the chart window; the clicked figures don't carry over */
	function momentLink(a: number, b: number): string {
		const q = new URLSearchParams({ from: iso(a), to: iso(b), range });
		if (chartWin) {
			q.set('chart_from', chartWin.from);
			q.set('chart_to', chartWin.to);
		}
		return `/moment?${q.toString()}`;
	}
	const widen = $derived(
		win
			? [
					{ label: '±15 min', href: momentLink(fromMs - 15 * MINUTE, toMs + 15 * MINUTE) },
					{ label: '±1 h', href: momentLink(fromMs - HOUR, toMs + HOUR) },
					...(chartWin ? [{ label: 'Whole chart', href: momentLink(Date.parse(chartWin.from), Date.parse(chartWin.to)) }] : []),
				]
			: [],
	);

	const FIGURES = [
		['down', 'download_bytes', 'downloaded'],
		['up', 'upload_bytes', 'uploaded'],
		['local', 'local_bytes', 'on your network'],
	] as const;
	/** NET-183: where this window's totals differ from the figures clicked, per figure, and why */
	const clickedNote = $derived.by(() => {
		if (!summary) return null;
		const s = summary;
		const given = FIGURES.filter(([k]) => clicked[k] !== null);
		const lines = given
			.filter(([k, field]) => clicked[k] !== s[field])
			.map(([k, field, noun]) => {
				const [was, now] = [clicked[k]!, s[field]];
				return `You clicked ${formatBytes(was)} ${noun}. This window now shows ${formatBytes(now)} (${formatBytes(Math.abs(now - was))} ${now > was ? 'more' : 'less'}).`;
			});
		if (lines.length === 0) return null;
		const clickedTotal = given.reduce((sum, [k]) => sum + clicked[k]!, 0);
		const sameTotal = given.length === FIGURES.length && clickedTotal === s.download_bytes + s.upload_bytes + s.local_bytes;
		return [...lines, sameTotal ? SPLIT_DIFFERS : RECORDS_CHANGE].join(' ');
	});

	const exact = $derived<DrillWindow & { range: string }>({ from: win?.from ?? '', to: win?.to ?? '', range });
	const connHref = $derived(connLogsHref({ ...exact, excluded_ips: summary?.excluded_ips }, range));
	const total = $derived(summary ? formatBytes(summary.total_bytes).split(' ') : null);
	const kpiSub = (source: Source, what: string, value: string | null) =>
		failed[source] !== undefined ? loadFailed(what, value !== null) : (value ?? 'Loading…');

	const chartSeries = $derived<AreaSeries[]>(
		chart
			? [
					{ key: 'down', label: 'Downloaded', colour: 1, points: chart.series.map((p) => ({ t: p.timestamp, v: p.download_bytes })) },
					{ key: 'up', label: 'Uploaded', colour: 2, points: chart.series.map((p) => ({ t: p.timestamp, v: p.upload_bytes })) },
					{ key: 'local', label: 'On your network', colour: 3, points: chart.series.map((p) => ({ t: p.timestamp, v: p.local_bytes })) },
				]
			: [],
	);
	const spanHours = $derived(Math.max(1, (toMs - fromMs) / HOUR));
	const chartTip = (i: number) => {
		const p = chart?.series[i];
		return p ? `${chartTime(p.timestamp, spanHours)} · ${upDownLocal(p, formatBytes, false)}` : '';
	};
	const pick = (i: number, j: number) => chart && goto(momentHref(chart, i, j, range, chartWin ?? chart));

	const serviceItems = $derived(
		(protocols?.services ?? [])
			.filter((s) => s.count > 0)
			.sort((a, b) => b.count - a.count)
			.slice(0, TOP_SERVICES)
			.map((s) => ({
				key: s.name || 'unknown',
				label: serviceLabel(s.name),
				value: s.count,
				display: fmt(s.count),
				// every bar opens the records it counted, with its count to compare
				href: withCount(serviceLogsHref(s.name || 'unknown', exact, protocols?.excluded_ips ?? [], range), s.count),
			})),
	);
	const categoryItems = $derived(
		(categories ?? []).map((c) => ({ key: c.name, label: c.label, value: c.total_bytes, display: formatBytes(c.total_bytes), href: `/traffic/${encodeURIComponent(c.name)}` })),
	);

	const text = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
	/** A joined device's own page: by IP when the event has one, else by MAC */
	function joinedHref(e: ChangelogEvent): string | null {
		const ip = text(e.metadata.ip);
		const mac = text(e.metadata.mac);
		return ip ? `/devices/${encodeURIComponent(ip)}` : mac ? `/devices/mac/${encodeURIComponent(mac)}` : null;
	}

	const packetsHref = $derived(
		win && toMs > fromMs && toMs - fromMs <= MAX_WINDOW_SECONDS * 1000
			? packetsUrl({ filter: '', from: nsEpoch(BigInt(fromMs) * 1_000_000n), to: nsEpoch(BigInt(toMs) * 1_000_000n), limit: 100, device: null, conn: null })
			: null,
	);
</script>

<svelte:head>
	<title>Moment | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">What your network was doing</h1>
		<p class="page-sub">{win ? words : 'No window to show'}</p>
	</div>
	{#if widen.length}
		<div class="head-actions">
			{#each widen as w (w.label)}<a class="btn" href={w.href}>{w.label}</a>{/each}
		</div>
	{/if}
</div>

{#snippet staleNote(what: string)}
	<p class="notice is-warn stale" role="status"><Icon name="warn" /><span>{loadFailed(what, true)}</span></p>
{/snippet}

{#if !win}
	<Card title="This link has no window" sub="It needs a start and an end, with the start no later than the end">
		<CardState state="empty" icon="warn" title="There's no moment to show" message="Open one from a chart: click a point or drag across it." href="/" actionLabel="Go to the overview" />
	</Card>
{:else}
	{#if clickedNote}<p class="notice" role="status">{clickedNote}</p>{/if}

	<div class="grid">
		<KpiCard
			class="c-3"
			label="Bandwidth"
			icon="bandwidth"
			value={total?.[0] ?? '—'}
			unit={total?.[1]}
			sub={kpiSub('summary', 'traffic totals', summary && upDownLocal(summary, formatBytes))}
			foot={connRecords}
		/>
		<KpiCard
			class="c-3"
			label="Connections"
			icon="connections"
			href={withCount(connHref, summary?.connection_count)}
			value={summary ? fmt(summary.connection_count) : '—'}
			sub={kpiSub('summary', 'connection totals', summary && `Top protocol: ${summary.top_protocol}`)}
		/>
		<KpiCard
			class="c-3"
			label="Alerts"
			icon="alerts"
			href={withCount(`/alerts?${windowQuery(exact, range)}`, alertCount?.counts.total)}
			value={alertCount ? fmt(alertCount.counts.total) : '—'}
			sub={kpiSub('alertCount', 'the alert count', alertCount && `${fmt(alertCount.counts.high)} high, ${fmt(alertCount.counts.medium)} med, ${fmt(alertCount.counts.low)} low`)}
		/>
		<KpiCard
			class="c-3"
			label="Active devices"
			icon="devices"
			href={withCount(`/devices?view=all&${windowQuery(exact, range)}`, deviceCount?.count)}
			value={deviceCount ? fmt(deviceCount.count) : '—'}
			sub={kpiSub('deviceCount', 'the device count', deviceCount && 'Devices seen on the network')}
		/>

		<Card title="Bandwidth in this window" sub="Bytes per {chart?.words ?? bucketFor(fromMs, toMs).bucketWords} · {words}" hero col class="c-8">
			{#snippet actions()}
				<ul class="legend">
					<li><span class="sw line c-d1"></span>Downloaded</li>
					<li><span class="sw line c-d2"></span>Uploaded</li>
					<li><span class="sw line c-d3"></span>On your network</li>
				</ul>
			{/snippet}
			{#if chart?.series.length}
				<AreaChart
					series={chartSeries}
					bytes
					formatX={(t) => chartTime(t, spanHours)}
					formatY={(v) => (v ? formatBytes(v) : '0')}
					formatTip={chartTip}
					ariaLabel="Bandwidth {words}"
					height={260}
					onpick={pick}
				/>
				<p class="card-sub hint">Click a point or drag across the chart to see that moment.</p>
				{#if failed.chart !== undefined}{@render staleNote('bandwidth in this window')}{/if}
			{:else if failed.chart !== undefined}
				<CardState state="error" title={loadFailed('bandwidth in this window')} message={CHECK_DAEMON} onaction={retry} />
			{:else if !chart}
				<CardState state="loading" title="Loading bandwidth in this window" />
			{:else}
				<CardState state="empty" title="No bandwidth data for this window" message="Traffic appears here once Zeek logs connections." />
			{/if}
		</Card>

		<Card title="Protocols" sub="Connections by service · {words}" class="c-4">
			{#if serviceItems.length}
				{#if failed.protocols !== undefined}{@render staleNote('protocols')}{/if}
				<BarList items={serviceItems} />
			{:else if failed.protocols !== undefined}
				<CardState state="error" title={loadFailed('protocols')} message={CHECK_DAEMON} onaction={retry} />
			{:else if !protocols}
				<CardState state="loading" title="Loading protocols" />
			{:else}
				<CardState state="empty" title="No connections in this window" message="Protocols appear here once Zeek logs connections." />
			{/if}
		</Card>

		<MomentDevices
			reply={devices}
			error={failed.devices}
			window={exact}
			{range}
			{words}
			onretry={retry}
		/>

		<Card title="Traffic categories" sub="Bytes to internet services · {words} · local traffic isn't counted" class="c-4">
			{#if categoryItems.length}
				{#if failed.categories !== undefined}{@render staleNote('traffic categories')}{/if}
				<BarList items={categoryItems} />
			{:else if failed.categories !== undefined}
				<CardState state="error" title={loadFailed('traffic categories')} message={CHECK_DAEMON} onaction={retry} />
			{:else if !categories}
				<CardState state="loading" title="Loading traffic categories" />
			{:else}
				<CardState state="empty" title="No category data for this window" message="Categories appear once Zeek captures ASN-tagged connections." />
			{/if}
		</Card>

		<Card title="Alerts" sub="Most severe first · {words}" class="c-6">
			{#snippet actions()}
				{#if alerts && alerts.total > 0}
					<a class="link" href={withCount(`/alerts?${windowQuery(exact, range)}`, alerts.total)}>All {fmt(alerts.total)} alerts</a>
				{/if}
			{/snippet}
			{#if alerts?.alerts.length}
				{#if failed.alerts !== undefined}{@render staleNote('alerts')}{/if}
				<ul class="rows">
					{#each alerts.alerts as a (a._id)}
						<li>
							<a class="row" href={alertsHrefForSignature(a.rule?.name || null, exact)}>
								<SeverityPill level={suricataLevel(a.alert?.severity)} />
								<span class="what">{a.alert?.signature ?? a.rule?.name ?? 'Alert with no rule name'}</span>
								<span class="when">{formatWhen(a.timestamp)}</span>
							</a>
						</li>
					{/each}
				</ul>
			{:else if failed.alerts !== undefined}
				<CardState state="error" title={loadFailed('alerts')} message={CHECK_DAEMON} onaction={retry} />
			{:else if !alerts}
				<CardState state="loading" title="Loading alerts" />
			{:else}
				<CardState state="empty" title="No alerts in this window" message="Counted rule matches appear here." />
			{/if}
		</Card>

		<Card title="New devices" sub="First seen in this window, from the changelog" class="c-6">
			{#if joined?.length}
				{#if failed.joined !== undefined}{@render staleNote('new devices')}{/if}
				<ul class="rows">
					{#each joined as e (e._id)}
						{@const href = joinedHref(e)}
						<li>
							<svelte:element this={href ? 'a' : 'div'} class="row" {href}>
								<span class="what mono">{text(e.metadata.mac) ?? e.title}</span>
								<span class="mono dim">{text(e.metadata.ip) ?? ''}</span>
								<span class="when">{formatWhen(e['@timestamp'])}</span>
							</svelte:element>
						</li>
					{/each}
				</ul>
			{:else if failed.joined !== undefined}
				<CardState state="error" title={loadFailed('new devices')} message={CHECK_DAEMON} onaction={retry} />
			{:else if !joined}
				<CardState state="loading" title="Loading new devices" />
			{:else}
				<CardState state="empty" title="No new devices joined in this window" />
			{/if}
		</Card>

		<Card title="Look closer" sub="The raw records for {words}" class="c-12">
			<div class="onward">
				<a class="btn" href={connHref}>Open in Log Explorer</a>
				{#if packetsHref}<a class="btn" href={packetsHref}>Search packets in this window</a>{/if}
			</div>
		</Card>
	</div>
{/if}

{#snippet connRecords()}
	<a class="link" href={connHref}>View connection records</a>
{/snippet}

<style>
	/* Layout glue the system lacks */
	.stale { margin-top: var(--sp-3); }
	.hint { margin-top: var(--sp-2); }
	.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-1); }
	.row { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-2); border-radius: var(--r-md); color: var(--text-1); text-decoration: none; min-width: 0; }
	a.row:hover { background: var(--row-hover); }
	.what { flex: 1; min-width: 0; overflow-wrap: anywhere; }
	.when { color: var(--text-3); font-size: var(--text-sm); white-space: nowrap; }
	.dim { color: var(--text-3); }
	.onward { display: flex; flex-wrap: wrap; gap: var(--sp-3); }
</style>
