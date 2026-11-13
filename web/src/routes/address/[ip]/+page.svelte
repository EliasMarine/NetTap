<script lang="ts">
	/**
	 * An address (NET-160): what one IP did on your network in the window. Which devices talked to
	 * it, on which ports, the names it served over TLS, its alerts, who it is, and every connection.
	 * Every figure comes from /api/addresses/{ip}, exact for the window or saying it isn't: a byte
	 * total missing some measurements is "at least", a list too long to count withholds its KPI.
	 */
	import { onDestroy, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { getAddressSummary, type AddressPeer, type AddressPort, type AddressSummary, type TlsName } from '$lib/api/drilldown';
	import { getDeviceConnections, type DeviceConnection, type DeviceConnectionSort } from '$lib/api/devices';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { lookupGeoIP, type GeoIPResult } from '$lib/api/geoip';
	import { getDnsReverse, getWhois, type DnsResult, type WhoisResult } from '$lib/api/lookup';
	import { formatBytes } from '$lib/api/logs';
	import { createLoadGuard, outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { domainHref, ipHref } from '$lib/stores/lan';
	import { connectionDurationMs } from '$lib/utils/connection-duration';
	import { namesByIp } from '$lib/utils/device-names';
	// OLD CODE: import { DRILL_RANGES, byteFigure, certificatesHref, chartTime as timeLabel, fmt, isHostName, logsHrefForIp, measuredNote, rangeWindow, type DrillRange, type DrillRangeValue } from '$lib/utils/drilldown'; (slice 2a)
	// OLD CODE: import { DRILL_RANGES, byteFigure, certificatesHref, chartTime as timeLabel, fmt, isHostName, logsHrefForIp, logsHrefForQuery, measuredNote, rangeWindow, type DrillRange, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown'; (section D)
	// OLD CODE: import { DRILL_RANGES, byteFigure, …, withCount, type DrillRange, type DrillRangeValue, type DrillWindow } from '$lib/utils/drilldown'; (NET-249: the chart picks)
	import { DRILL_RANGES, byteFigure, certificatesHref, chartTime as timeLabel, fmt, isHostName, logsHrefForIp, logsHrefForQuery, measuredNote, pickedTotal, pickWindow, rangeWindow, startRange, windowQuery, withCount, type DrillRange, type DrillRangeValue, type DrillWindow, type TimeChart } from '$lib/utils/drilldown';
	import { toTimeChart } from '$lib/utils/chart-pick';
	import { bucketWords } from '$lib/utils/narrow-page';
	import { goto } from '$app/navigation';
	import { loadFailed } from '$lib/utils/load-failed';
	import { asString, getField } from '$lib/utils/tshark-filter';
	import type { SortDir } from '$lib/utils/table-sort.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import { formatWhen, statusList } from '../../certificates/cert-view';

	const CONN_PAGE_SIZE = 25;
	/** The connections endpoint pages through at most this many rows (daemon/api/devices.py). */
	const CONN_REACH = 10_000;

	// OLD CODE START — SvelteKit has already decoded the param; decoding again threw on a zone id's "%" (fe80::1%eth0)
	// const ip = $derived(decodeURIComponent(($page.params as Record<string, string>).ip ?? ''));
	// OLD CODE END
	const ip = $derived(($page.params as Record<string, string>).ip ?? '');

	// OLD CODE: let rangeValue = $state<DrillRangeValue>('24h'); (NET-195: Settings › Display's default, read where the range starts)
	let rangeValue = $state<DrillRangeValue>(startRange('24h'));
	// OLD CODE: ?? DRILL_RANGES[0]); (NET-192 PR 4: 1h and 6h added, 24h is index 2)
	// OLD CODE: ?? DRILL_RANGES[2] (NET-192 PR 4: the default by value, not by position)
	const range = $derived(DRILL_RANGES.find((r) => r.value === rangeValue) ?? DRILL_RANGES.find((r) => r.value === '24h')!);
	/** The window of the last load: links and connection pages use it, so they never slide in time. */
	let span = $state<{ from: string; to: string }>({ from: '', to: '' });

	// OLD CODE: let loaded = $state<{ data: AddressSummary; range: DrillRange } | null>(null); (slice 2a: the figures keep their window)
	/** The figures on screen, with the range and exact window they were counted over. */
	let loaded = $state<{ data: AddressSummary; range: DrillRange; window: DrillWindow } | null>(null);
	let failure = $state<string | null>(null);
	let geo = $state<GeoIPResult | null>(null);
	let geoFailed = $state(false);
	let rdns = $state<DnsResult | null>(null);
	let names = $state<ReadonlyMap<string, string>>(new Map());
	/** ip|range of the figures on screen, and the address the lookups are for (not reactive: only the loader reads them) */
	let loadedView = '';
	let lookedUp = '';

	let whois = $state<WhoisResult | null>(null);
	// OLD CODE START — a flag, not tied to the address: opening another one mid-lookup left its button disabled
	// let whoisLoading = $state(false);
	// OLD CODE END
	/** The address each click-to-run lookup is running for; null when none is */
	let whoisFor = $state<string | null>(null);
	let rdnsFor = $state<string | null>(null);

	let connections = $state<DeviceConnection[]>([]);
	let connTotal = $state(0);
	let connPage = $state(1);
	let connPages = $state(0);
	let connLoaded = $state(false);
	let connFailed = $state(false);
	let connSortKey = $state<DeviceConnectionSort>('time');
	let connSortDir = $state<SortDir>('desc');
	/** The window the connections on screen (and their total) were counted over. */
	let connWindow = $state<DrillWindow | null>(null);

	const data = $derived(loaded?.data ?? null);
	const shown = $derived(loaded?.range ?? range);
	const words = $derived(shown.words);
	/** NET-160 slice 2a: the window of the figures on screen, which their links carry; null before any land. */
	const addressWindow = $derived(loaded?.window ?? null);

	// --- Loading ---

	const connGuard = createLoadGuard();
	const refresh = registerPageRefresh(load);
	onDestroy(() => {
		refresh.unregister();
		connGuard.invalidate();
	});

	$effect(() => {
		void ip; // another address
		void rangeValue; // another window
		// the loader writes and reads state; untracked so those writes can't rerun this effect
		untrack(() => refresh.run());
	});

	/** Reverse DNS answers 200 with an error when there's no name; only its own failures count. */
	const rdnsFailed = (r: DnsResult) => !!r.error && (r.error.startsWith('HTTP ') || r.error === 'Network error');

	/* OLD CODE START — waited on every lookup before writing any, so a slow one held the figures on
	   Loading; looked up reverse DNS on every visit, which tells whoever runs the address that we looked;
	   and kept the last address's connections on screen while the next one loaded
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const target = ip;
		const r = range;
		if (!target) return 'skipped';
		const s = rangeWindow(r.hours);
		const view = `${target}|${r.value}`;
		// A refresh of the same view keeps its last good figures; another view must not show them
		if (view !== loadedView) {
			loaded = null;
			failure = null;
		}
		if (target !== lookedUp) {
			geo = null;
			geoFailed = false;
			rdns = null;
			whois = null;
		}
		span = s;
		const connLoad = loadConnections(1, s, target);
		const namesLoad = getRegistryDevices({ limit: 200 }).then(
			(res) => namesByIp(res.devices),
			() => null,
		);
		const results = await Promise.allSettled([
			getAddressSummary(target, s.from, s.to),
			lookupGeoIP(target),
			getDnsReverse(target).then((res) => {
				if (rdnsFailed(res)) throw new Error(res.error ?? '');
				return res;
			}),
		]);
		// Names are cosmetic: a failed registry load keeps the last names and isn't a failure
		const loadedNames = await namesLoad;
		if (!guard.current(g)) return 'skipped';
		const [summaryRes, geoRes, rdnsRes] = results;
		if (loadedNames) names = loadedNames;
		if (summaryRes.status === 'fulfilled') {
			loaded = { data: summaryRes.value, range: r };
			loadedView = view;
			failure = null;
		} else {
			failure = summaryRes.reason instanceof Error ? summaryRes.reason.message : '';
		}
		lookedUp = target;
		if (geoRes.status === 'fulfilled') geo = geoRes.value;
		geoFailed = geoRes.status === 'rejected';
		rdns = rdnsRes.status === 'fulfilled' ? rdnsRes.value : { ip: target, hostname: null, aliases: [], addresses: [], error: rdnsRes.reason instanceof Error ? rdnsRes.reason.message : 'Lookup failed' };

		const connRes = await connLoad;
		if (!guard.current(g)) return 'skipped';
		return outcome([...results, connRes]);
	}
	OLD CODE END */

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const target = ip;
		const r = range;
		if (!target) return 'skipped';
		const s = rangeWindow(r.hours);
		const view = `${target}|${r.value}`;
		// A refresh of the same view keeps its last good figures and its page of connections;
		// another view must not show them
		const sameView = view === loadedView;
		if (!sameView) {
			loaded = null;
			failure = null;
			connections = [];
			connTotal = 0;
			connPage = 1;
			connPages = 0;
			connLoaded = false;
			connFailed = false;
		}
		if (target !== lookedUp) {
			geo = null;
			geoFailed = false;
			rdns = null;
			whois = null;
			lookedUp = target;
		}
		span = s;
		/** Writes what a request brings only while this load is the newest, as soon as it lands */
		function landed<T>(p: Promise<T>, apply: (v: T) => void, fail: (e: unknown) => void = () => {}): Promise<void> {
			return p.then(
				(v) => {
					if (guard.current(g)) apply(v);
				},
				(e: unknown) => {
					if (guard.current(g)) fail(e);
					throw e;
				},
			);
		}
		const connLoad = loadConnections(sameView ? connPage : 1, s, target);
		// Names are cosmetic: a failed registry load keeps the last names and isn't a failure
		landed(getRegistryDevices({ limit: 200 }), (res) => (names = namesByIp(res.devices))).catch(() => {});
		const results = await Promise.allSettled([
			landed(
				// OLD CODE: getAddressSummary(target, s.from, s.to), (NET-249: the owner's bucket for the range)
				getAddressSummary(target, s.from, s.to, r.bucket),
				(d) => {
					// OLD CODE: loaded = { data: d, range: r }; (slice 2a)
					loaded = { data: d, range: r, window: s };
					loadedView = view;
					failure = null;
				},
				(e) => (failure = e instanceof Error ? e.message : ''),
			),
			landed(
				lookupGeoIP(target),
				(res) => {
					geo = res;
					geoFailed = false;
				},
				() => (geoFailed = true),
			),
		]);
		const connRes = await connLoad;
		if (!guard.current(g)) return 'skipped';
		return outcome([...results, connRes]);
	}

	/** One page of connections; a newer page, sort or load drops this one's reply. */
	async function loadConnections(pg: number, s = span, target = ip): Promise<PromiseSettledResult<unknown>> {
		const g = connGuard.begin();
		const [res] = await Promise.allSettled([
			getDeviceConnections(target, { ...s, page: pg, size: CONN_PAGE_SIZE, sort: connSortKey, order: connSortDir }),
		]);
		if (!connGuard.current(g)) return res;
		if (res.status === 'fulfilled') {
			connections = res.value.connections;
			connTotal = res.value.total;
			connPage = res.value.page;
			connPages = res.value.total_pages;
			connWindow = s;
		} else {
			// rows are specific to this page of results, so they are not kept as stale
			connections = [];
			connPages = 0;
		}
		connFailed = res.status === 'rejected';
		connLoaded = true;
		return res;
	}

	function sortConnections(key: string, dir: SortDir) {
		connSortKey = key as DeviceConnectionSort;
		connSortDir = dir;
		void loadConnections(1);
	}

	// OLD CODE START — the loading flag wasn't tied to the address it was for
	// async function lookUpWhois() {
	// 	const target = ip;
	// 	whoisLoading = true;
	// 	const res = await getWhois(target);
	// 	whoisLoading = false;
	// 	// another address opened meanwhile: its card must not show this one's record
	// 	if (target === ip) whois = res;
	// }
	// OLD CODE END
	async function lookUpWhois() {
		const target = ip;
		whoisFor = target;
		try {
			const res = await getWhois(target);
			// another address opened meanwhile: its card must not show this one's record
			if (target === ip) whois = res;
		} finally {
			if (whoisFor === target) whoisFor = null;
		}
	}

	/** Reverse DNS runs only when asked: the lookup reaches the DNS server of whoever runs the address. */
	async function lookUpName() {
		const target = ip;
		rdnsFor = target;
		try {
			const res = await getDnsReverse(target);
			if (target === ip) rdns = res;
		} finally {
			if (rdnsFor === target) rdnsFor = null;
		}
	}

	// --- Figures ---

	const lanPeers = $derived(data?.peers.filter((p) => p.lan).length ?? 0);
	const peerRows = $derived(
		// LAN devices first, busiest first; the table re-sorts on any header
		[...(data?.peers ?? [])].sort((a, b) => Number(b.lan) - Number(a.lan) || b.connections - a.connections),
	);
	const peerName = (p: AddressPeer): string | undefined => names.get(p.ip);
	const timeline = $derived(data?.timeline ?? []);
	/** The chart as a pickable reply (NET-249): null when the bucket it echoes isn't one a pick can open */
	const chart = $derived(data ? toTimeChart(data, timeline.map((p) => p.t), timeline.map((p) => p.n)) : null);
	/** The slot in words, as the reply says it counted it; an older daemon's own bucket otherwise */
	// OLD CODE: const slot = $derived(DRILL_RANGES.find((r) => r.bucket === data?.interval)?.bucketWords ?? shown.interval); (NET-249: narrow-page's bucketWords, the one helper)
	const slot = $derived(bucketWords(data?.interval, shown.interval));

	/** A pick opens Log Explorer's conn records with this address at either end over the picked slots, carrying their figure (NET-249). */
	function pickSlots(c: TimeChart, i: number, j: number) {
		void goto(withCount(logsHrefForIp(ip, shown.value, pickWindow(c, i, j), 'zeek.conn'), pickedTotal(c, i, j)));
	}
	const busiest = $derived(timeline.reduce((best, p, i) => (p.n > (timeline[best]?.n ?? -1) ? i : best), -1));
	// OLD CODE START — moved to utils/drilldown.ts: a week of 6-hour buckets needs the hour as well as the day
	// const chartTime = (t: number | string): string => {
	// 	const d = new Date(t);
	// 	return range.hours <= 24
	// 		? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
	// 		: d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
	// };
	// OLD CODE END
	const chartTime = (t: number | string): string => timeLabel(t, shown.hours);
	const chartLabel = $derived(
		busiest >= 0 ? `Busiest at ${chartTime(timeline[busiest].t)}, with ${fmt(timeline[busiest].n)} connections` : 'No connections in this window',
	);
	const dataNotes = $derived(
		data
			? [
					measuredNote(data.bytes_to) && `To it: ${measuredNote(data.bytes_to)}`,
					measuredNote(data.bytes_from) && `from it: ${measuredNote(data.bytes_from)}`,
				].filter(Boolean)
			: [],
	);

	const peerColumns: Column<AddressPeer>[] = [
		{ key: 'ip', label: 'Device or address', sortValue: (p) => peerName(p) ?? p.ip, cell: peerCell },
		{ key: 'lan', label: 'Network', sortValue: (p) => (p.lan ? 1 : 0), cell: peerLanCell },
		{ key: 'connections', label: 'Connections', numeric: true, cell: peerConnCell },
		{ key: 'bytes_to', label: 'Data to it', numeric: true, cell: peerToCell },
		{ key: 'bytes_from', label: 'Data from it', numeric: true, cell: peerFromCell },
		{ key: 'last_seen', label: 'Last seen', sortValue: (p) => Date.parse(p.last_seen) || 0, cell: peerSeenCell },
	];
	const portColumns: Column<AddressPort>[] = [
		{ key: 'port', label: 'Port', numeric: true, cell: portCell },
		// a missing port, transport or service is null; the table sorts blanks last
		{ key: 'transport', label: 'Transport', cell: transportCell },
		// OLD CODE START: { key: 'service', label: 'Service', sortValue: (p) => p.service ?? '', cell: serviceCell }, — one service per row OLD CODE END
		{ key: 'services', label: 'Services', sortValue: (p) => p.services.join(', '), cell: servicesCell },
		{ key: 'connections', label: 'Connections', numeric: true, cell: portConnCell },
	];
	const tlsColumns: Column<TlsName>[] = [
		{ key: 'name', label: 'Name', sortValue: (t) => t.name ?? '', cell: tlsNameCell },
		{ key: 'sessions', label: 'Sessions', numeric: true, cell: tlsSessionsCell },
		{ key: 'statuses', label: 'Verification', sortValue: (t) => statusList(t.statuses), cell: tlsStatusCell },
		{ key: 'certificates', label: 'Certificates', sortValue: (t) => t.name ?? '', cell: tlsCertCell },
	];
	// the rows of one server-sorted page, keyed by position so a missing _id can't collide
	interface ConnRow {
		c: DeviceConnection;
		key: string;
	}
	const connRows = $derived(connections.map((c, i): ConnRow => ({ c, key: `${String(c._id)}-${i}` })));
	// keys are the daemon's sort names: the table only reports the sort, the daemon applies it
	const connColumns: Column<ConnRow>[] = [
		{ key: 'time', label: 'Time', cell: connTimeCell },
		{ key: 'direction', label: 'Opened by', cell: connDirectionCell },
		{ key: 'source', label: 'Source', cell: connSourceCell },
		{ key: 'destination', label: 'Destination', cell: connDestCell },
		{ key: 'proto', label: 'Protocol', cell: connProtoCell },
		{ key: 'service', label: 'Service', cell: connServiceCell },
		{ key: 'duration', label: 'Duration', numeric: true, cell: connDurationCell },
		{ key: 'dl', label: 'Data to it', numeric: true, cell: connToCell },
		{ key: 'ul', label: 'Data from it', numeric: true, cell: connFromCell },
	];

	/** Bytes to or from the address on one session; "—" when the record has no byte count. */
	function sessionBytes(c: DeviceConnection, way: 'to' | 'from'): string {
		// On a session a peer opened (in), the address is the destination: what the source sent went to it
		const side = (c.direction === 'in') === (way === 'to') ? 'source' : 'destination';
		const value = getField(c, `${side}.bytes`) ?? getField(c, `${side === 'source' ? 'client' : 'server'}.bytes`);
		// OLD CODE START — a value that isn't a number read as "0 B"
		// return value === undefined || value === null || value === '' ? '—' : formatBytes(Number(value) || 0);
		// OLD CODE END
		const n = value === undefined || value === null || value === '' ? NaN : Number(value);
		return Number.isFinite(n) ? formatBytes(n) : '—';
	}

	function duration(c: DeviceConnection): string {
		const ms = connectionDurationMs(c);
		if (ms === null) return '—';
		if (ms < 1000) return `${Math.round(ms)} ms`;
		const sec = ms / 1000;
		if (sec < 60) return `${sec.toFixed(1)} s`;
		const total = Math.round(sec);
		return `${Math.floor(total / 60)} min ${total % 60} s`;
	}

	const connPager = $derived(
		connTotal > 0
			? {
					page: connPage,
					pageCount: connPages,
					total: Math.min(connTotal, CONN_REACH),
					from: (connPage - 1) * CONN_PAGE_SIZE + 1,
					to: Math.min(connPage * CONN_PAGE_SIZE, connTotal, CONN_REACH),
					onpage: (p: number) => void loadConnections(p),
				}
			: undefined,
	);
	// OLD CODE: const tlsCertificates = (t: TlsName) => certificatesHref({ site: t.name, server: data?.ip ?? ip, ...span }); (slice 2a: span moves when a refresh starts)
	const tlsCertificates = (t: TlsName) => certificatesHref({ site: t.name, server: data?.ip ?? ip, ...(addressWindow ?? span) });
	/** The port's connections in Log Explorer: the count's own filters (no source), over its window; null for a row without a port or transport. */
	function portLogs(p: AddressPort): string | null {
		if (p.port === null || !p.transport || !data || !addressWindow) return null;
		const clauses = ['event.provider:zeek', 'event.dataset:conn', `destination.ip:"${data.ip}"`, `destination.port:${p.port}`, `network.transport:${p.transport}`];
		// OLD CODE: return logsHrefForQuery(clauses, addressWindow, shown.value); (section D: the link carries the row's figure)
		return withCount(logsHrefForQuery(clauses, addressWindow, shown.value), p.connections);
	}
	/**
	 * The alerts the Alerts card counts: over the card's own window once its figures land, carrying
	 * that figure (NET-160 section D); by range alone before, when there is no figure to carry.
	 */
	const alertsHref = $derived(
		addressWindow && data
			? withCount(`/alerts?ip=${encodeURIComponent(ip)}&${windowQuery(addressWindow, shown.value)}`, data.alerts)
			: `/alerts?ip=${encodeURIComponent(ip)}&range=${shown.value}`,
	);
</script>

{#snippet peerCell(p: AddressPeer)}
	{@const name = peerName(p)}
	{#if name}
		<span class="two"><a href={$ipHref(p.ip)}>{name}</a><span class="mono dim">{p.ip}</span></span>
	{:else}
		<IPAddress ip={p.ip} />
	{/if}
{/snippet}
{#snippet peerLanCell(p: AddressPeer)}{p.lan ? 'Your network' : 'Internet'}{/snippet}
{#snippet peerConnCell(p: AddressPeer)}{fmt(p.connections)}{/snippet}
<!-- OLD CODE START — a peer with no byte count read "at least 0 B"
{#snippet peerToCell(p: AddressPeer)}{p.bytes_partial ? 'at least ' : ''}{formatBytes(p.bytes_to)}{/snippet}
{#snippet peerFromCell(p: AddressPeer)}{p.bytes_partial ? 'at least ' : ''}{formatBytes(p.bytes_from)}{/snippet}
OLD CODE END -->
{#snippet peerToCell(p: AddressPeer)}{p.bytes_to === null ? 'Not measured' : `${p.bytes_partial ? 'at least ' : ''}${formatBytes(p.bytes_to)}`}{/snippet}
{#snippet peerFromCell(p: AddressPeer)}{p.bytes_from === null ? 'Not measured' : `${p.bytes_partial ? 'at least ' : ''}${formatBytes(p.bytes_from)}`}{/snippet}
{#snippet peerSeenCell(p: AddressPeer)}<span class="num">{formatWhen(p.last_seen)}</span>{/snippet}

<!-- OLD CODE START — port and transport can be null (a row keeps connections with no port recorded); toUpperCase threw on null
{#snippet portCell(p: AddressPort)}<span class="mono">{p.port}</span>{/snippet}
{#snippet transportCell(p: AddressPort)}<span class="tag">{p.transport.toUpperCase()}</span>{/snippet}
{#snippet serviceCell(p: AddressPort)}{#if p.service}<span class="mono">{p.service}</span>{:else}<span class="dim">Not identified</span>{/if}{/snippet}
OLD CODE END -->
<!-- OLD CODE START: {#snippet portCell(p: AddressPort)}{#if p.port === null}<span class="dim">Unknown port</span>{:else}<span class="mono">{p.port}</span>{/if}{/snippet} (slice 2a: not a link) OLD CODE END -->
{#snippet portCell(p: AddressPort)}
	{@const href = portLogs(p)}
	{#if p.port === null}<span class="dim">Unknown port</span>
	{:else if href}<a class="mono" {href}>{p.port}</a>
	{:else}<span class="mono">{p.port}</span>{/if}
{/snippet}
{#snippet transportCell(p: AddressPort)}{#if p.transport}<span class="tag">{p.transport.toUpperCase()}</span>{:else}<span class="dim">—</span>{/if}{/snippet}
<!-- OLD CODE START: {#snippet serviceCell(p: AddressPort)}{#if p.service}<span class="mono">{p.service}</span>{:else}<span class="dim">—</span>{/if}{/snippet} — a port now lists every service Zeek saw on it OLD CODE END -->
{#snippet servicesCell(p: AddressPort)}{#if p.services.length}<span class="mono">{p.services.join(', ')}</span>{:else}<span class="dim">—</span>{/if}{/snippet}
{#snippet portConnCell(p: AddressPort)}{fmt(p.connections)}{/snippet}

<!-- OLD CODE START — linked any name, so a value that isn't a host name opened a domain page that can only fail
{#snippet tlsNameCell(t: TlsName)}
	{#if t.name}<a class="mono" href={domainHref(t.name)}>{t.name}</a>{:else}<span class="dim">No name (SNI)</span>{/if}
{/snippet}
OLD CODE END -->
{#snippet tlsNameCell(t: TlsName)}
	{#if t.name === null}<span class="dim">No name (SNI)</span>
	{:else if isHostName(t.name)}<a class="mono" href={domainHref(t.name)}>{t.name}</a>
	{:else}<span class="mono" title="Not a host name, so there is no domain page for it">{t.name}</span>{/if}
{/snippet}
{#snippet tlsSessionsCell(t: TlsName)}{fmt(t.sessions)}{/snippet}
{#snippet tlsStatusCell(t: TlsName)}<span class="trunc" title={statusList(t.statuses)}>{statusList(t.statuses) || '—'}</span>{/snippet}
<!-- OLD CODE START — the no-name row's link dropped the site filter and opened every certificate on the server, and every link read the same
{#snippet tlsCertCell(t: TlsName)}<a class="link" href={tlsCertificates(t)}>Certificates seen<Icon name="back" class="chev" /></a>{/snippet}
OLD CODE END -->
{#snippet tlsCertCell(t: TlsName)}
	{#if t.name && isHostName(t.name)}<a class="link" href={tlsCertificates(t)} aria-label="Certificates seen for {t.name}">Certificates seen<Icon name="back" class="chev" /></a>{:else}<span class="dim">—</span>{/if}
{/snippet}

{#snippet connEnd(side: 'source' | 'destination', c: DeviceConnection)}
	{@const addr = asString(getField(c, `${side}.ip`))}
	<!-- OLD CODE START: {@const port = asString(getField(c, `${side}.port`))} — asString drops numbers, and ports are numbers OLD CODE END -->
	{@const rawPort = getField(c, `${side}.port`)}
	{@const port = typeof rawPort === 'number' ? String(rawPort) : asString(rawPort)}
	{#if !addr}<span class="dim">—</span>
	{:else if addr === data?.ip || addr === ip}<span class="mono dim">{addr}{port ? `:${port}` : ''}</span>
	{:else}<span class="mono"><IPAddress ip={addr} />{port ? `:${port}` : ''}</span>{/if}
{/snippet}
{#snippet connTimeCell({ c }: ConnRow)}<span class="num">{formatWhen(asString(getField(c, '@timestamp')))}</span>{/snippet}
{#snippet connDirectionCell({ c }: ConnRow)}{c.direction === 'out' ? 'This address' : 'The other side'}{/snippet}
{#snippet connSourceCell({ c }: ConnRow)}{@render connEnd('source', c)}{/snippet}
{#snippet connDestCell({ c }: ConnRow)}{@render connEnd('destination', c)}{/snippet}
{#snippet connProtoCell({ c }: ConnRow)}<span class="tag">{asString(getField(c, 'network.transport')).toUpperCase() || '—'}</span>{/snippet}
{#snippet connServiceCell({ c }: ConnRow)}<span class="mono">{asString(getField(c, 'network.protocol')) || '—'}</span>{/snippet}
{#snippet connDurationCell({ c }: ConnRow)}{duration(c)}{/snippet}
{#snippet connToCell({ c }: ConnRow)}{sessionBytes(c, 'to')}{/snippet}
{#snippet connFromCell({ c }: ConnRow)}{sessionBytes(c, 'from')}{/snippet}

{#snippet measuredFoot()}<span>{dataNotes.join(' · ')}</span>{/snippet}

{#snippet summaryState(what: string)}
	{#if !failure}
		<CardState state="loading" title="Loading {what}" />
	{:else}
		<CardState state="error" title={loadFailed(what)} message={failure || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
	{/if}
{/snippet}

<svelte:head>
	<title>{ip} | Address | NetTap</title>
</svelte:head>

<header class="page-head">
	<div>
		<h1 class="page-title mono">{ip}</h1>
		<p class="page-sub">Which of your devices talked to this address, on which ports, and what it served · {words}</p>
		{#if data}
			<div class="chips">
				{#if data.lan}<span class="chip"><Icon name="devices" />On your network</span>{/if}
				<!-- OLD CODE START — null meant "no indicators loaded"; the daemon now also checks the window's alerts
				{#if data.threat_intel === null}
					<span class="chip">Not checked: no threat indicators loaded yet</span>
				{:else if data.threat_intel.matched}
					<span class="chip is-bad"><Icon name="warn" />On a threat list: {data.threat_intel.feeds.map((f) => f.label).join(', ')}</span>
				{:else}
					<span class="chip is-ok" title="Checked against {fmt(data.threat_intel.indicators)} threat indicators"><Icon name="check" />Not on a threat list</span>
				{/if}
				OLD CODE END -->
				{#if data.threat_intel === null}
					<!-- only when nothing matched and some of the window's alerts couldn't be read -->
					<span class="chip">Not checked</span>
					<span class="chip-note">This window's alerts couldn't all be checked</span>
				{:else if data.threat_intel.matched}
					<span class="chip is-bad"><Icon name="warn" />On a threat list: {data.threat_intel.feeds.map((f) => f.label).join(', ')}</span>
					<!-- NET-228 (audit ALR-12): when it was listed, as far as NetTap knows -->
					{#if data.threat_intel.in_window === true}
						<span class="chip-note">A Suricata blocklist rule named it in this window</span>
					{:else if data.threat_intel.in_window === false}
						<span class="chip-note">Named on an earlier Threats scan; NetTap doesn't keep the date</span>
					{:else if data.threat_intel.in_window === null}
						<span class="chip-note">Named on an earlier Threats scan; this window's alerts couldn't all be checked</span>
					{/if}
				{:else}
					<span class="chip is-ok"><Icon name="check" />Not on a threat list</span>
					<span class="chip-note"
						>{data.threat_intel.indicators > 0
							? `Checked this window's alerts and ${fmt(data.threat_intel.indicators)} cached ${data.threat_intel.indicators === 1 ? 'indicator' : 'indicators'}`
							: "Checked this window's alerts"}</span
					>
				{/if}
			</div>
		{/if}
	</div>
	<div class="head-actions">
		<Pills options={DRILL_RANGES.map((r) => ({ value: r.value, label: r.label }))} bind:value={rangeValue} ariaLabel="Time range" />
	</div>
</header>

<div class="grid">
	{#if data?.lan}
		<p class="notice c-12" role="note">
			<Icon name="devices" /><span>This address is on your network. <a href="/devices/{encodeURIComponent(data.ip)}">Open its device page</a> for its traffic, alerts and risk.</span>
		</p>
	{/if}
	{#if failure && data}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" /><span>{loadFailed('this address', true)} {failure}</span></p>
	{/if}

	<KpiCard class="c-3" label="Connections" icon="connections" value={data ? fmt(data.connections) : '—'} sub={data?.last_seen ? `Last seen ${formatWhen(data.last_seen)}` : undefined} note={words} />
	<KpiCard
		class="c-3"
		label="Data to it"
		icon="bandwidth"
		value={data ? byteFigure(data.bytes_to) : '—'}
		sub={data ? `From it: ${byteFigure(data.bytes_from)}` : undefined}
		note={words}
		foot={dataNotes.length ? measuredFoot : undefined}
	/>
	<KpiCard
		class="c-3"
		label="Devices that talked to it"
		icon="devices"
		value={data && data.peers_complete ? fmt(lanPeers) : '—'}
		sub={data ? (data.peers_complete ? `on your network, of ${fmt(data.peers.length)} ${data.peers.length === 1 ? 'address' : 'addresses'} in all` : 'too many to count') : undefined}
		note={words}
	/>
	<KpiCard
		class="c-3"
		label="Alerts"
		icon="alerts"
		value={data ? fmt(data.alerts) : '—'}
		sub={data ? 'with this address on either side' : undefined}
		note={words}
		href={alertsHref}
	/>
	<!-- OLD CODE START: href="/alerts?ip={encodeURIComponent(ip)}&range={shown.value}" — section D: the list opened on a window anchored at click time, not the card's OLD CODE END -->
	<!-- OLD CODE START: href="/alerts?ip={encodeURIComponent(ip)}" — /alerts opened on its own 24 hours, so "40 · last 7 days" could list 5 OLD CODE END -->
</div>

<div class="grid">
	<!-- OLD CODE: sub="Connections per {shown.interval} · {words}" (NET-249: the bucket the reply says it used) -->
	<Card class="c-8" hero col title="Connections over time" sub="Connections per {slot} · {words}">
		{#if !data}
			{@render summaryState('connections over time')}
		{:else if data.connections === 0}
			<CardState state="empty" icon="connections" title="No connections in the {words}" message="This address didn't connect to or from your network in this window. Try a longer range." />
		{:else}
			<AreaChart
				series={[{ key: 'connections', label: 'Connections', colour: 1, points: timeline.map((p) => ({ t: p.t, v: p.n })) }]}
				formatX={chartTime}
				formatY={fmt}
				formatTip={(i) => `${chartTime(timeline[i].t)} · ${fmt(timeline[i].n)} connections`}
				highlightIndex={busiest}
				ariaLabel={chartLabel}
				onpick={chart ? (i, j) => pickSlots(chart!, i, j) : undefined}
			/>
			{#if chart}<p class="card-sub pick-hint">Click a point or drag across the chart to see that moment.</p>{/if}
		{/if}
	</Card>

	<Card class="c-4" title="Who it is" sub="Location, network and name · looked up now">
		<!-- OLD CODE START — reverse DNS ran on every visit, so the card waited on it and failed only when both lookups did
		{#if !geo && !geoFailed && !rdns}
			<CardState state="loading" title="Looking up this address" />
		{:else if geoFailed && !geo && rdns && rdnsFailed(rdns)}
			<CardState state="error" title={loadFailed('who this address is')} message={rdns.error || 'Check that NetTap is running on the System page, then try again.'} onaction={() => refresh.run()} />
		{:else}
		OLD CODE END -->
		<!-- A failed location lookup reads inline, so the name and WHOIS look-ups stay one click away -->
		{#if !geo && !geoFailed}
			<CardState state="loading" title="Looking up this address" />
		{:else}
			<dl class="facts">
				<dt>Location</dt>
				<dd>
					{#if geoFailed && !geo}<span class="dim">Couldn't look it up</span>
					{:else if geo?.is_private}Private address
					<!-- OLD CODE: {:else if geo}{[geo.city, geo.country].filter(Boolean).join(', ') || '—'}{#if geo.country_code}<span class="mono dim"> ({geo.country_code})</span>{/if} (NET-237: anycast) -->
					{:else if geo}{[geo.city, geo.country].filter(Boolean).join(', ') || '—'}{#if geo.country_code}<span class="mono dim"> ({geo.country_code})</span>{/if}{#if geo.anycast}<span class="dim"> · anycast, location varies</span>{/if}
					{:else}<span class="dim">Looking up…</span>{/if}
				</dd>
				<dt>Network</dt>
				<dd>
					{#if geo && (geo.asn !== null || geo.organization)}{#if geo.asn !== null}<span class="mono">AS{geo.asn}</span> {/if}{geo.organization ?? ''}
					{:else}<span class="dim">—</span>{/if}
				</dd>
				<dt>Name (reverse DNS)</dt>
				<dd>
					{#if rdns?.hostname}<span class="mono">{rdns.hostname}</span>
					{:else if rdns?.error}<span class="dim">{rdnsFailed(rdns) ? `Couldn't look it up: ${rdns.error}` : rdns.error}</span>
					<!-- NET-192 PR 3: the daemon gives the resolver 6 s, then answers with no name -->
					{:else if rdns?.timed_out}<span class="dim">Reverse DNS lookup timed out</span>
					<!-- OLD CODE START — looked up on every visit
					{:else}<span class="dim">{rdns ? 'None' : 'Looking up…'}</span>{/if}
					OLD CODE END -->
					{:else if rdns}<span class="dim">None</span>
					{:else}
						<button class="link-btn" type="button" disabled={rdnsFor === ip} onclick={lookUpName}>{rdnsFor === ip ? 'Looking up…' : 'Look up its name'}</button>
					{/if}
				</dd>
				<dt>WHOIS</dt>
				<dd>
					{#if whois && !whois.error}
						{whois.parsed.orgname ?? whois.parsed['org-name'] ?? whois.parsed.netname ?? 'No owner in the record'}{#if whois.parsed.cidr}<span class="mono dim"> {whois.parsed.cidr}</span>{/if}
					{:else if whois?.error}<span class="dim">Couldn't look it up: {whois.error}</span>
					{:else}
						<!-- OLD CODE START: <button class="link-btn" type="button" disabled={whoisLoading} onclick={lookUpWhois}>{whoisLoading ? 'Looking up…' : 'Look it up'}</button> OLD CODE END -->
						<button class="link-btn" type="button" disabled={whoisFor === ip} onclick={lookUpWhois}>{whoisFor === ip ? 'Looking up…' : 'Look it up'}</button>
					{/if}
				</dd>
			</dl>
			<p class="dim who-note">The name and WHOIS look-ups ask servers outside your network, and reverse DNS reaches whoever runs this address, so both run only when you click.</p>
			<div class="actions who-links">
				<a class="link" href="/geoip/{encodeURIComponent(ip)}">Location details<Icon name="back" class="chev" /></a>
				<a class="link" href="/lookup/whois/{encodeURIComponent(ip)}">Full WHOIS record<Icon name="back" class="chev" /></a>
			</div>
		{/if}
	</Card>
</div>

<div class="grid">
	<Card
		class="c-12"
		title="Devices that talked to it"
		sub={data
			? `${data.peers_complete ? '' : 'First '}${fmt(data.peers.length)} ${data.peers.length === 1 ? 'address' : 'addresses'} · your devices first · ${words}`
			: 'Your devices first'}
	>
		{#if !data}
			{@render summaryState('the devices that talked to it')}
		{:else if data.peers.length === 0}
			<CardState state="empty" icon="devices" title="Nothing talked to it in the {words}" message="Devices appear here once a connection to or from this address is recorded." />
		{:else}
			{#if !data.peers_complete}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Too many addresses to list them all: showing the first {fmt(data.peers.length)}.</span></p>
			{/if}
			<DataTable columns={peerColumns} rows={peerRows} ariaLabel="Devices that talked to it" rowKey={(p) => p.ip} />
		{/if}
	</Card>

	<Card class="c-6" title="Ports on this address" sub="Connections per port the network reached · {words}">
		{#if !data}
			{@render summaryState('its ports')}
		{:else if data.ports.length === 0}
			<CardState state="empty" icon="connections" title="No ports reached" message="No device connected to a port on this address in the {words}." />
		{:else}
			{#if !data.ports_complete}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Too many ports to list them all: showing the first {fmt(data.ports.length)}.</span></p>
			{/if}
			<!-- OLD CODE START: rowKey={(p) => `${p.port}/${p.transport}/${p.service ?? ''}`} — a null and an empty service collided OLD CODE END -->
			<DataTable columns={portColumns} rows={data.ports} ariaLabel="Ports on this address" rowKey={(p) => JSON.stringify([p.port, p.transport])} initialSort={{ key: 'connections', dir: 'desc' }} />
		{/if}
	</Card>

	<Card class="c-6" title="Names it served (TLS)" sub="TLS sessions per name the device asked for · {words}">
		{#if !data}
			{@render summaryState('the names it served')}
		{:else if data.tls_names.length === 0}
			<CardState state="empty" icon="certs" title="No TLS sessions" message="No device opened a TLS session to this address in the {words}." />
		{:else}
			{#if !data.tls_complete}
				<p class="notice is-warn" role="status"><Icon name="warn" /><span>Too many names to list them all: showing the first {fmt(data.tls_names.length)}.</span></p>
			{/if}
			<!-- OLD CODE START: rowKey={(t) => t.name ?? '(no name)'} — collided with a client that sends the literal name "(no name)" OLD CODE END -->
			<DataTable columns={tlsColumns} rows={data.tls_names} ariaLabel="Names it served" rowKey={(t) => JSON.stringify(t.name)} initialSort={{ key: 'sessions', dir: 'desc' }} />
			<p class="dim tls-note">Names are as each device sent them. Sessions count every TLS session. Certificates counts only the sessions that showed a certificate (TLS 1.3 hides it, and a resumed session doesn't send it again) and leaves out excluded addresses, so its figures can be lower.</p>
		{/if}
	</Card>

	<Card class="c-12" title="Connections" sub={connLoaded && !connFailed ? `${fmt(connTotal)} ${connTotal === 1 ? 'connection' : 'connections'} · either side · ${words}` : `Either side · ${words}`}>
		{#if !connLoaded}
			<CardState state="loading" title="Loading connections" />
		{:else if connFailed}
			<CardState state="error" title={loadFailed('connections')} message="Check that NetTap is running on the System page, then try again." onaction={() => loadConnections(connPage)} />
		{:else if connTotal === 0}
			<CardState state="empty" icon="connections" title="No connections in the {words}" message="Connections with this address on either side appear here." />
		{:else}
			{#if connTotal > CONN_REACH}
				<p class="notice is-warn" role="status">
					<Icon name="warn" /><span
						>{connSortKey === 'time' && connSortDir === 'desc'
							? `Showing the newest ${fmt(CONN_REACH)} of ${fmt(connTotal)}.`
							: `Showing the first ${fmt(CONN_REACH)} of ${fmt(connTotal)} in this order.`} Narrow the time range to reach older ones, or
						<!-- OLD CODE: <a href={logsHrefForIp(ip, shown.value)}>search them all in Log Explorer</a>.</span (slice 2a: the count's own window) -->
						<!-- OLD CODE: <a href={logsHrefForIp(ip, shown.value, connWindow ?? undefined)}> (section D: every log type, while connTotal counts conn records) -->
						<a href={withCount(logsHrefForIp(ip, shown.value, connWindow ?? undefined, 'zeek.conn'), connTotal)}>search them all in Log Explorer</a>.</span
					>
				</p>
			{/if}
			<DataTable
				columns={connColumns}
				rows={connRows}
				ariaLabel="Connections with this address"
				rowKey={(r) => r.key}
				initialSort={{ key: connSortKey, dir: connSortDir }}
				onsortchange={sortConnections}
				pager={connPager}
			/>
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.chips { margin-top: var(--sp-2); }
	.pick-hint { margin-top: var(--sp-2); }
	/* OLD CODE START: .two { display: inline-flex; flex-direction: column; line-height: 1.3; } — system.css defines .two OLD CODE END */
	.chip-note { align-self: center; color: var(--text-3); font-size: var(--text-sm); }
	.who-links { margin-top: var(--sp-3); }
	.who-note { margin: var(--sp-3) 0 0; font-size: var(--text-sm); }
	.tls-note { margin: var(--sp-3) 0 0; font-size: var(--text-sm); }
	.link-btn { background: none; border: 0; padding: 0; color: var(--accent-strong); cursor: pointer; font: inherit; text-decoration: underline; }
	.link-btn:hover { color: var(--text-1); }
	.link-btn:disabled { color: var(--text-3); cursor: default; text-decoration: none; }
	.link-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
</style>
