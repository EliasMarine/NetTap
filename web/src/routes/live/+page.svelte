<!--
  Live Network Monitor: what is talking to the world right now, refreshed every 3 s.
  Stat strip, the destination dot map beside the top talkers, the protocol split and the live feed.
  Three filters narrow the feed and the side cards together: a country (map hotspots), a protocol
  (pills above the feed) and a device (top-talker rows).
-->
<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getLiveDashboard, getLiveConnectionDetail } from '$lib/api/live';
	import { loadFailed } from '$lib/utils/load-failed';
	import { prefersReducedMotion } from '$lib/utils/tokens';
	import type {
		LiveConnection,
		LiveDashboardResponse,
		ConnectionDetailResponse,
		// OLD CODE START — GeoMap's input type; DotMap takes hotspots
		// GeoArc,
		// OLD CODE END
		TopTalker,
	} from '$lib/api/live';
	import DetailDrawer from '$components/DetailDrawer.svelte';
	import type { DrawerTab } from '$components/DetailDrawer.svelte';
	// OLD CODE START — replaced by the system's StatStrip, DataTable, Donut, DeviceList and DotMap
	// (PLAN.md §5.3); GeoMap and Leaflet are deleted in step C
	// import LiveStatsRibbon from '$components/live/LiveStatsRibbon.svelte';
	// import LiveConnectionTable from '$components/live/LiveConnectionTable.svelte';
	// import ProtocolDonut from '$components/live/ProtocolDonut.svelte';
	// import TopTalkersChart from '$components/live/TopTalkersChart.svelte';
	// import GeoMap from '$components/live/GeoMap.svelte';
	// OLD CODE END
	import LiveConnectionDrawerContent from '$components/drawer/content/LiveConnectionDrawerContent.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import StatStrip, { type Stat } from '$lib/components/ui/StatStrip.svelte';
	import LiveChip from '$lib/components/ui/LiveChip.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import DeviceList, { type DeviceListItem } from '$lib/components/ui/DeviceList.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Donut from '$lib/components/ui/charts/Donut.svelte';
	import DotMap, { type Hotspot } from '$lib/components/ui/charts/DotMap.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { compareValues } from '$lib/utils/table-sort.svelte';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	const REFRESH_INTERVAL_MS = 3000;
	const PAGE_SIZE = 200;
	/** Polls of history behind each top talker's sparkline. */
	const SPARK_SAMPLES = 20;

	// OLD CODE START — a made-up centre of the continental US, drawn as "Your network" (PLAN.md §5.4):
	// DotMap gets home = null, so it shows destinations only. Auto-detecting home is a follow-up.
	// // Default home location (center of continental US).
	// // TODO: auto-detect from appliance WAN IP GeoIP or user settings.
	// const DEFAULT_HOME = { lat: 39.8, lng: -98.6 };
	// OLD CODE END

	/** A feed row with an id that stays the same across polls (the drawer and new-row flash use it). */
	type FeedRow = LiveConnection & { key: string };

	// ---------------------------------------------------------------------------
	// State — raw data
	// ---------------------------------------------------------------------------

	let dashboard = $state<LiveDashboardResponse | null>(null);
	let loading = $state(false);
	let error = $state('');
	let paused = $state(false);
	/** Rows that arrived with the latest poll; they flash in (tr.new). */
	let newKeys = $state.raw<Set<string>>(new Set());
	let seenKeys = new Set<string>();
	/** Bytes per top talker at each poll, oldest first: the rows' sparklines. */
	let talkerHistory = $state.raw<Map<string, number[]>>(new Map());

	// ---------------------------------------------------------------------------
	// State — cross-filtering
	// ---------------------------------------------------------------------------

	let countryFilter = $state<string | null>(null);
	let protocolFilter = $state<string | null>(null);
	let deviceFilter = $state<string | null>(null);

	// ---------------------------------------------------------------------------
	// State — drawer
	// ---------------------------------------------------------------------------

	let drawerConn = $state<FeedRow | null>(null);
	let drawerTab = $state('details');
	let drawerDetail = $state<ConnectionDetailResponse | null>(null);
	let drawerDetailLoading = $state(false);
	// #96: a failed detail must not read as "No alerts for this connection"
	let drawerDetailFailed = $state(false);

	// ---------------------------------------------------------------------------
	// Derived — filtered connections
	// ---------------------------------------------------------------------------

	/** Same connection, same key, poll after poll; repeats get #2, #3 so keys stay unique. */
	function withKeys(connections: LiveConnection[]): FeedRow[] {
		const seen = new Map<string, number>();
		return connections.map((c) => {
			const base = `${c.timestamp}|${c.source_ip}|${c.source_port}|${c.dest_ip}|${c.dest_port}`;
			const n = (seen.get(base) ?? 0) + 1;
			seen.set(base, n);
			return { ...c, key: n === 1 ? base : `${base}#${n}` };
		});
	}

	let feedRows = $derived(withKeys(dashboard?.connections ?? []));

	let filteredConnections = $derived.by(() => {
		if (!dashboard) return [];
		// OLD CODE START: let result = dashboard.connections; (rows now carry a stable key) OLD CODE END
		let result = feedRows;
		if (countryFilter) {
			result = result.filter(
				(c) => c.country?.toUpperCase() === countryFilter!.toUpperCase()
			);
		}
		if (protocolFilter) {
			result = result.filter(
				(c) => c.protocol?.toLowerCase() === protocolFilter!.toLowerCase()
			);
		}
		if (deviceFilter) {
			result = result.filter(
				(c) => c.source_ip === deviceFilter || c.dest_ip === deviceFilter
			);
		}
		return result;
	});

	let hasActiveFilter = $derived(
		countryFilter !== null || protocolFilter !== null || deviceFilter !== null
	);

	// OLD CODE START — GeoMap coloured countries with an alerting connection red; DotMap has no such
	// state (dropped on purpose, listed in the PR body). Alerts stay marked in the feed.
	// let alertCountrySet = $derived.by(() => {
	// 	if (!dashboard) return new Set<string>();
	// 	const s = new Set<string>();
	// 	for (const conn of dashboard.connections) {
	// 		if (conn.has_alert && conn.country) s.add(conn.country.toUpperCase());
	// 	}
	// 	return s;
	// });
	// OLD CODE END

	// Derive protocol distribution from filtered connections for cross-filter feedback
	let filteredProtocols = $derived.by(() => {
		const map: Record<string, number> = {};
		for (const c of filteredConnections) {
			const p = (c.protocol || 'other').toLowerCase();
			map[p] = (map[p] || 0) + 1;
		}
		return map;
	});

	// Derive top talkers from filtered connections
	let filteredTopTalkers = $derived.by((): TopTalker[] => {
		const map = new Map<string, { bytes: number; connections: number }>();
		for (const c of filteredConnections) {
			const existing = map.get(c.source_ip) || { bytes: 0, connections: 0 };
			existing.bytes += c.bytes;
			existing.connections += 1;
			map.set(c.source_ip, existing);
		}
		return [...map.entries()]
			.sort((a, b) => b[1].bytes - a[1].bytes)
			.slice(0, 10)
			.map(([ip, data]) => ({ ip, bytes: data.bytes, connections: data.connections }));
	});

	// OLD CODE START — never matched LiveConnectionTable's row ids, so no row ever showed as open
	// // Connection ID for drawer highlight
	// let selectedConnId = $derived(
	// 	drawerConn ? `${drawerConn.timestamp}${drawerConn.source_ip}${drawerConn.dest_ip}` : null
	// );
	// OLD CODE END

	/** The household's name for each source IP, where the feed has one. */
	let deviceNames = $derived(
		new Map((dashboard?.connections ?? []).filter((c) => c.device_name).map((c) => [c.source_ip, c.device_name])),
	);

	let talkerItems = $derived<DeviceListItem[]>(
		(hasActiveFilter ? filteredTopTalkers : (dashboard?.top_talkers ?? [])).map((t) => ({
			key: t.ip,
			name: deviceNames.get(t.ip) || t.ip,
			ip: deviceNames.has(t.ip) ? t.ip : '',
			value: t.bytes,
			display: `${formatBytes(t.bytes)} · ${t.connections.toLocaleString('en-GB')} conn`,
			// The history is of the unfiltered figures, so a filtered list shows bars instead
			spark: hasActiveFilter ? undefined : talkerHistory.get(t.ip),
		})),
	);

	let protocolCounts = $derived(hasActiveFilter ? filteredProtocols : (dashboard?.protocols ?? {}));
	let protocolItems = $derived(
		Object.entries(protocolCounts).map(([key, value]) => ({ key, label: key.toUpperCase(), value })),
	);
	let protocolTotal = $derived(hasActiveFilter ? filteredConnections.length : dashboard?.stats.connections_in_window);

	// Every protocol the window saw, so another can be picked while one is filtered
	let protocolPills = $derived([
		{ value: 'all', label: 'All' },
		...[...new Set([...Object.keys(dashboard?.protocols ?? {}), ...(protocolFilter ? [protocolFilter] : [])])].map((p) => ({
			value: p,
			label: p.toUpperCase(),
		})),
	]);

	let hotspots = $derived<Hotspot[]>(
		(dashboard?.geo_arcs ?? []).map((a) => ({
			country: a.country || a.country_code,
			code: a.country_code,
			lat: a.lat,
			lng: a.lon,
			count: a.count,
		})),
	);

	let liveStats = $derived<Stat[]>(
		dashboard
			? [
					{ key: 'rate', label: 'Connections per second', value: dashboard.stats.connections_per_second.toFixed(1) },
					{ key: 'bandwidth', label: 'Bandwidth', value: formatBandwidth(dashboard.stats.bandwidth_bytes_per_second) },
					{ key: 'devices', label: 'Active devices', value: String(dashboard.stats.active_devices) },
					{ key: 'country', label: 'Top country', value: dashboard.stats.top_country || '—' },
				]
			: [],
	);

	// No count until a dashboard has loaded: a failed first load must not read as 0
	let feedSub = $derived(
		dashboard
			? `${filteredConnections.length.toLocaleString('en-GB')}${hasActiveFilter ? ` of ${dashboard.count.toLocaleString('en-GB')}, filtered` : ''} connections · newest first`
			: 'Newest first',
	);

	let maxFeedBytes = $derived(Math.max(0, ...filteredConnections.map((c) => c.bytes)));

	// ---------------------------------------------------------------------------
	// Format helpers (from LiveStatsRibbon, LiveConnectionTable and TopTalkersChart)
	// ---------------------------------------------------------------------------

	function formatBandwidth(bytesPerSec: number): string {
		if (bytesPerSec >= 1_000_000) return `${(bytesPerSec / 1_000_000).toFixed(1)} MB/s`;
		if (bytesPerSec >= 1_000) return `${(bytesPerSec / 1_000).toFixed(1)} KB/s`;
		return `${Math.round(bytesPerSec)} B/s`;
	}

	function formatBytes(bytes: number): string {
		if (bytes >= 1_000_000_000) return (bytes / 1_000_000_000).toFixed(1) + ' GB';
		if (bytes >= 1_000_000) return (bytes / 1_000_000).toFixed(1) + ' MB';
		if (bytes >= 1_000) return (bytes / 1_000).toFixed(1) + ' KB';
		return bytes + ' B';
	}

	function formatTime(ts: string): string {
		try {
			return new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
		} catch {
			return ts;
		}
	}

	function formatDuration(seconds: number): string {
		if (seconds < 0.001) return '<1ms';
		if (seconds < 1) return (seconds * 1000).toFixed(0) + 'ms';
		if (seconds < 60) return seconds.toFixed(1) + 's';
		const total = Math.round(seconds);
		if (total < 3600) return `${Math.floor(total / 60)}m ${total % 60}s`;
		const totalMin = Math.round(seconds / 60);
		return `${Math.floor(totalMin / 60)}h ${totalMin % 60}m`;
	}

	/**
	 * Heuristic for direction: if dest_port is a well-known service port (<1024)
	 * the connection is outbound (our device talking to a server). Otherwise,
	 * inbound (remote initiated or P2P).
	 */
	function getDirection(conn: LiveConnection): 'OUT' | 'IN' {
		return conn.dest_port < 1024 ? 'OUT' : 'IN';
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN.md §5.5: the loop and the Resume button now go through the page refresh
	// contract, which reports what happened and drops a response a newer load has overtaken
	// async function fetchData() {
	// 	if (paused) return;
	// 	loading = true;
	// 	error = '';
	// 	try {
	// 		dashboard = await getLiveDashboard({ limit: PAGE_SIZE });
	// 		if (dashboard._error) {
	// 			error = dashboard._error;
	// 		}
	// 	} catch {
	// 		// OLD CODE START — #96: the getter now throws instead of returning a zero dashboard
	// 		// error = e instanceof Error ? e.message : 'Failed to fetch live data';
	// 		// OLD CODE END
	// 		// The last good dashboard stays on screen; the status bar says it is stale
	// 		error = loadFailed('live data', dashboard !== null);
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// OLD CODE END
	async function fetchData(guard: LoadGuard): Promise<LoadResult> {
		if (paused) return 'skipped';
		const g = guard.begin();
		loading = true;
		try {
			const next = await getLiveDashboard({ limit: PAGE_SIZE });
			if (!guard.current(g)) return 'skipped';
			markNewRows(withKeys(next.connections));
			recordTalkers(next.top_talkers);
			dashboard = next;
			error = next._error ?? '';
			loading = false;
			return next._error ? 'partial' : 'ok';
		} catch {
			if (!guard.current(g)) return 'skipped';
			// The last good dashboard stays on screen; the status line says it is stale
			error = loadFailed('live data', dashboard !== null);
			loading = false;
			return 'failed';
		}
	}

	/** Rows not in the previous poll flash in; the first poll's rows don't. */
	function markNewRows(rows: FeedRow[]) {
		const keys = rows.map((r) => r.key);
		newKeys = seenKeys.size ? new Set(keys.filter((k) => !seenKeys.has(k))) : new Set();
		seenKeys = new Set(keys);
	}

	function recordTalkers(talkers: TopTalker[]) {
		talkerHistory = new Map(talkers.map((t) => [t.ip, [...(talkerHistory.get(t.ip) ?? []), t.bytes].slice(-SPARK_SAMPLES)]));
	}

	const refresh = registerPageRefresh(fetchData);

	function togglePause() {
		paused = !paused;
		// OLD CODE START: if (!paused) fetchData(); OLD CODE END
		if (!paused) void refresh.run();
	}

	// ---------------------------------------------------------------------------
	// Cross-filter handlers (toggle behavior)
	// ---------------------------------------------------------------------------

	function setCountryFilter(code: string) {
		countryFilter = countryFilter === code ? null : code;
	}

	function setProtocolFilter(proto: string) {
		protocolFilter = protocolFilter === proto ? null : proto;
	}

	function setDeviceFilter(ip: string) {
		deviceFilter = deviceFilter === ip ? null : ip;
	}

	function clearAllFilters() {
		countryFilter = null;
		protocolFilter = null;
		deviceFilter = null;
	}

	/** The feed's protocol pills: "All" clears the filter, the rest go through setProtocolFilter. */
	function pickProtocol(value: string) {
		if (value === 'all') protocolFilter = null;
		else setProtocolFilter(value);
	}

	// ---------------------------------------------------------------------------
	// Drawer
	// ---------------------------------------------------------------------------

	function openDrawer(conn: FeedRow) {
		drawerConn = conn;
		drawerTab = 'details';
		drawerDetail = null;
		drawerDetailLoading = true;
		drawerDetailFailed = false;
		getLiveConnectionDetail(conn.source_ip, conn.dest_ip, conn.dest_port)
			.then((d) => { drawerDetail = d; })
			.catch(() => { drawerDetail = null; drawerDetailFailed = true; })
			.finally(() => { drawerDetailLoading = false; });
	}

	function closeDrawer() {
		drawerConn = null;
		drawerDetail = null;
	}

	// Update drawer alert badge
	let drawerTabs = $derived.by((): DrawerTab[] => {
		const alertCount = drawerDetail?.alert_count ?? 0;
		return [
			{ id: 'details', label: 'Details' },
			{ id: 'alerts', label: 'Alerts', badge: alertCount > 0 ? alertCount : undefined },
		];
	});

	// ---------------------------------------------------------------------------
	// Feed table
	// ---------------------------------------------------------------------------

	// The columns, labels and sort values of LiveConnectionTable
	const COLUMNS: Column<FeedRow>[] = [
		{ key: 'timestamp', label: 'Time', cell: timeCell },
		{ key: 'source_ip', label: 'Source', cell: sourceCell },
		{ key: 'direction', label: 'Dir', sortValue: getDirection, cell: directionCell },
		{ key: 'dest_ip', label: 'Destination', cell: destinationCell },
		{ key: 'protocol', label: 'Protocol', sortValue: (c) => c.service || c.protocol, cell: protocolCell },
		{ key: 'dest_port', label: 'Port', numeric: true, cell: portCell },
		{ key: 'bytes', label: 'Bytes', numeric: true, cell: bytesCell },
		{ key: 'duration', label: 'Duration', numeric: true, cell: durationCell },
		{ key: 'has_alert', label: 'Alert', sortValue: (c) => (c.has_alert ? 1 : 0), cell: alertCell },
	];

	const rowLabel = (c: FeedRow) => `Open connection from ${c.device_name || c.source_ip} to ${c.dest_ip}`;

	// ---------------------------------------------------------------------------
	// Auto-refresh lifecycle
	// ---------------------------------------------------------------------------

	// OLD CODE START — through the refresh contract; a tick waits while a load is running, since
	// starting another would make the guard drop the slow one and a slow daemon would never update
	// onMount(() => {
	// 	fetchData();
	// 	const timer = setInterval(fetchData, REFRESH_INTERVAL_MS);
	// 	return () => clearInterval(timer);
	// });
	// OLD CODE END
	onMount(() => {
		void refresh.run();
		// The first load has already checked `paused` (before its first await). Under reduced
		// motion the feed then starts paused (PLAN.md §4.5): no new rows until Resume.
		if (prefersReducedMotion()) paused = true;
		const timer = setInterval(() => {
			if (!loading) void refresh.run();
		}, REFRESH_INTERVAL_MS);
		return () => clearInterval(timer);
	});

	onDestroy(() => refresh.unregister());
</script>

<svelte:head>
	<title>Live Monitor | NetTap</title>
</svelte:head>

{#snippet timeCell(c: FeedRow)}<span class={['mono', newKeys.has(c.key) && 'row-new']}>{formatTime(c.timestamp)}</span>{/snippet}

{#snippet sourceCell(c: FeedRow)}
	<span class="who">
		<Icon name="devices" />
		{#if c.device_name}
			<span class="two"><span class="who-name trunc" title={c.device_name}>{c.device_name}</span><IPAddress ip={c.source_ip} /></span>
		{:else}
			<IPAddress ip={c.source_ip} />
		{/if}
	</span>
{/snippet}

{#snippet directionCell(c: FeedRow)}<span class="tag">{getDirection(c)}</span>{/snippet}

{#snippet destinationCell(c: FeedRow)}
	<span class="dest">
		<IPAddress ip={c.dest_ip} />
		{#if c.country}<span class="mono country" title={c.country_name || c.country}>{c.country}</span>{/if}
	</span>
{/snippet}

{#snippet protocolCell(c: FeedRow)}<span class="tag">{String(c.service || c.protocol || '').toUpperCase() || '—'}</span>{/snippet}

{#snippet portCell(c: FeedRow)}<span class="mono">{c.dest_port}</span>{/snippet}

{#snippet bytesCell(c: FeedRow)}<Bytes value={c.bytes} max={maxFeedBytes} display={formatBytes(c.bytes)} />{/snippet}

{#snippet durationCell(c: FeedRow)}{formatDuration(c.duration)}{/snippet}

{#snippet alertCell(c: FeedRow)}
	{#if c.has_alert}<span class="chip is-warn"><Icon name="warn" />Alert</span>{/if}
{/snippet}

<div class="page-head">
	<div>
		<h1 class="page-title">Live monitor</h1>
		<p class="page-sub">
			Connections from your network to the world · {paused ? 'paused' : `refreshing every ${REFRESH_INTERVAL_MS / 1000} s`}
		</p>
	</div>
	<div class="head-actions">
		<LiveChip {paused} />
		<button class={['btn', paused && 'primary']} type="button" onclick={togglePause}>
			<Icon name={paused ? 'play' : 'pause'} />{paused ? 'Resume' : 'Pause'}
		</button>
	</div>
</div>

{#if error && dashboard}
	<p class="notice is-warn" role="status"><Icon name="warn" />{error}</p>
{/if}

<div class="grid">
	<Card class="c-12" title="Right now" sub="Connections, throughput and devices · last 5 minutes">
		{#if dashboard}
			<StatStrip stats={liveStats} />
		{:else if error}
			<CardState state="error" title={error} message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			<CardState state="loading" title="Loading live data" />
		{/if}
	</Card>

	<Card class="c-8 map-card" hero title="Where your traffic goes" sub="Connections by destination country · last 5 minutes">
		{#if hotspots.length > 0}
			<DotMap
				{hotspots}
				home={null}
				selected={countryFilter ?? undefined}
				onselect={setCountryFilter}
				ariaLabel="Connections by destination country{dashboard?.stats.top_country ? `, most to ${dashboard.stats.top_country}` : ''}. Choose a country to filter the feed."
			/>
		{:else if dashboard}
			<CardState state="empty" title="No destinations yet" message="Countries appear here once your devices connect to the internet." />
		{:else if error}
			<CardState state="error" title={error} message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			<CardState state="loading" title="Loading the map" />
		{/if}
	</Card>

	<Card class="c-4" title="Top talkers" sub="Bytes and connections per device · last 5 minutes">
		{#if talkerItems.length > 0}
			<DeviceList items={talkerItems} mode="select" selectedKey={deviceFilter ?? undefined} onselect={(item) => setDeviceFilter(item.key)} />
		{:else if dashboard}
			<CardState state="empty" title={hasActiveFilter ? 'No devices match these filters' : 'No devices talking yet'} message="Devices appear here once they send traffic." />
		{:else if error}
			<CardState state="error" title={error} message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			<CardState state="loading" title="Loading top talkers" />
		{/if}
	</Card>

	<Card class="c-4" title="Protocols" sub="Share of connections · last 5 minutes">
		{#if protocolItems.some((p) => p.value > 0)}
			<Donut
				items={protocolItems}
				total={protocolTotal}
				centreLabel="connections"
				formatValue={(v) => v.toLocaleString('en-GB')}
				ariaLabel="Protocols across {protocolTotal?.toLocaleString('en-GB') ?? 'the'} connections"
			/>
		{:else if dashboard}
			<CardState state="empty" title="No protocols yet" message="The protocol split appears here once connections arrive." />
		{:else if error}
			<CardState state="error" title={error} message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			<CardState state="loading" title="Loading protocols" />
		{/if}
	</Card>

	<Card class="c-8 live-feed" title="Live connections" sub={feedSub}>
		{#if dashboard}
			<div class="toolbar">
				<Pills options={protocolPills} value={protocolFilter ?? 'all'} onchange={pickProtocol} ariaLabel="Protocol" />
			</div>
			{#if hasActiveFilter}
				<div class="chips filters" role="group" aria-label="Active filters">
					{#if countryFilter}
						<button class="chip" type="button" aria-label="Remove the country filter {countryFilter}" onclick={() => { countryFilter = null; }}
							>Country: {countryFilter}<Icon name="close" /></button
						>
					{/if}
					{#if protocolFilter}
						<button class="chip" type="button" aria-label="Remove the protocol filter {protocolFilter.toUpperCase()}" onclick={() => { protocolFilter = null; }}
							>Protocol: {protocolFilter.toUpperCase()}<Icon name="close" /></button
						>
					{/if}
					{#if deviceFilter}
						<button class="chip" type="button" aria-label="Remove the device filter {deviceFilter}" onclick={() => { deviceFilter = null; }}
							>Device: <span class="mono">{deviceFilter}</span><Icon name="close" /></button
						>
					{/if}
					<button class="link" type="button" onclick={clearAllFilters}>Clear filters</button>
				</div>
			{/if}
			<DataTable
				columns={COLUMNS}
				rows={filteredConnections}
				ariaLabel="Live connections"
				rowKey={(c) => c.key}
				initialSort={{ key: 'timestamp', dir: 'desc' }}
				onrowactivate={openDrawer}
				{rowLabel}
				selectedKey={drawerConn?.key}
			>
				{#snippet empty()}
					<CardState state="empty" title={hasActiveFilter ? 'No connections match these filters' : 'No connections right now'} message={hasActiveFilter ? 'Remove a filter to see more of the feed.' : 'New connections appear here within a few seconds.'} />
				{/snippet}
			</DataTable>
		{:else if error}
			<CardState state="error" title={error} message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else}
			<CardState state="loading" title="Loading live connections" />
		{/if}
	</Card>
</div>

<!-- Detail Drawer -->
<DetailDrawer
	open={drawerConn !== null}
	title={drawerConn ? `${drawerConn.source_ip} → ${drawerConn.dest_ip}` : ''}
	subtitle={drawerConn ? `${(drawerConn.protocol || '').toUpperCase()} : ${drawerConn.dest_port}` : ''}
	tabs={drawerTabs}
	activeTab={drawerTab}
	onclose={closeDrawer}
	ontabchange={(t) => { drawerTab = t; }}
>
	{#snippet children()}
		{#if drawerConn}
			<LiveConnectionDrawerContent
				connection={drawerConn}
				detail={drawerDetail}
				detailLoading={drawerDetailLoading}
				detailFailed={drawerDetailFailed}
				activeTab={drawerTab}
			/>
		{/if}
	{/snippet}
	{#snippet actions()}
		{#if drawerConn}
			<button class="btn" type="button" onclick={() => { if (drawerConn) setDeviceFilter(drawerConn.source_ip); closeDrawer(); }}>
				Filter by source
			</button>
			<button class="btn" type="button" onclick={() => { if (drawerConn) setCountryFilter(drawerConn.country?.toUpperCase()); closeDrawer(); }}>
				Filter by country
			</button>
		{/if}
	{/snippet}
</DetailDrawer>

<style>
	/* Layout glue the system lacks */
	.dest { display: inline-flex; align-items: center; gap: var(--sp-2); }
	.country { color: var(--text-3); font-size: var(--text-xs); }
	.filters { margin-bottom: var(--sp-4); align-items: center; }
	button.chip { border: 0; font-family: inherit; cursor: pointer; }
	button.link { border: 0; background: none; padding: 0; cursor: pointer; }
	/* The system's new-row flash (tr.new, bundle.css:310) on a row the DataTable renders; the system
	   CSS stops it under reduced motion */
	:global(.live-feed tr:has(.row-new) td) { animation: rowin 900ms var(--ease); }
</style>
