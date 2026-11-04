<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getMonthlyUsage, getDailyUsage, getDeviceUsage, getHeatmap } from '$lib/api/bandwidth';
	import type { MonthlyUsage, DailyUsageEntry, DeviceUsage, HeatmapResponse } from '$lib/api/bandwidth';
	// OLD CODE START — replaced by the system's DeviceList (Top consumers) and DataTable, which sorts
	// import TopConsumers from '$lib/components/TopConsumers.svelte';
	// import { compareValues } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import IPAddress from '$components/IPAddress.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import DeviceList, { type DeviceListItem } from '$lib/components/ui/DeviceList.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import AreaChart, { type AreaSeries } from '$lib/components/ui/charts/AreaChart.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let monthly = $state<MonthlyUsage | null>(null);
	let daily = $state<DailyUsageEntry[]>([]);
	let devices = $state<DeviceUsage[]>([]);
	let heatmap = $state<HeatmapResponse | null>(null);
	let loading = $state(false);
	// OLD CODE START — never set since #96; each card shows its own error state
	// let error = $state('');
	// OLD CODE END
	// #96: each section says when its request failed instead of showing 0.0 GB or an empty heatmap
	let monthlyFailed = $state(false);
	let dailyFailed = $state(false);
	let devicesFailed = $state(false);
	let heatmapFailed = $state(false);

	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function formatBytes(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	}

	function formatGB(bytes: number): string {
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	}

	/** The GB figure alone, for a KPI whose unit sits beside it. */
	const gb = (bytes: number) => (bytes / 1024 ** 3).toFixed(1);

	function progressPercent(current: number, cap: number): number {
		if (cap <= 0) return 0;
		return Math.min(100, Math.round(current / cap * 100));
	}

	// OLD CODE START — legacy tokens (--red, --amber); the system's meter is one accent colour, and
	// a projection over the cap shows as a warning chip on the Projected KPI
	// function progressColor(percent: number): string {
	// 	if (percent >= 90) return 'var(--red)';
	// 	if (percent >= 75) return 'var(--amber)';
	// 	return 'var(--accent)';
	// }
	// OLD CODE END

	// OLD CODE START — the hand-drawn daily bars; the daily card is an AreaChart now
	// // Daily chart helpers
	// function maxDailyBytes(): number {
	// 	if (daily.length === 0) return 1;
	// 	return Math.max(...daily.map(d => d.total_bytes), 1);
	// }
	//
	// function barHeight(bytes: number): number {
	// 	return Math.max(2, (bytes / maxDailyBytes()) * 200);
	// }
	// OLD CODE END

	function formatDate(dateStr: string): string {
		try {
			const d = new Date(dateStr);
			// OLD CODE START — 2026-11-01: local time shifted each UTC-midnight bucket back a day west of UTC
			// return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
			// OLD CODE END
			// Daily buckets are UTC days (as is "this month"), so label them as such
			return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
		} catch {
			return dateStr;
		}
	}

	/** "November 2026" for the daemon's year and 1-based month. */
	const monthName = (year: number, month: number) =>
		new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });

	// Heatmap helpers
	const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
	const HOURS = Array.from({ length: 24 }, (_, i) => i);

	function heatmapColor(value: number, maxVal: number): string {
		// OLD CODE START: if (maxVal <= 0 || value <= 0) return 'var(--bg-tertiary)'; (legacy token) OLD CODE END
		if (maxVal <= 0 || value <= 0) return 'var(--surface-2)';
		const intensity = Math.min(1, value / maxVal);
		const alpha = 0.1 + intensity * 0.9;
		return `color-mix(in srgb, var(--accent) ${Math.round(alpha * 100)}%, transparent)`;
	}

	function heatmapMax(): number {
		if (!heatmap?.matrix) return 1;
		let max = 0;
		for (const row of heatmap.matrix) {
			for (const val of row) {
				if (val > max) max = val;
			}
		}
		return max || 1;
	}

	/** The heatmap's headline for its aria-label: the busiest hour of the week. */
	let busiestHour = $derived.by(() => {
		let best = { day: 0, hour: 0, value: 0 };
		heatmap?.matrix?.forEach((row, day) => row.forEach((value, hour) => {
			if (value > best.value) best = { day, hour, value };
		}));
		return best;
	});

	// ---------------------------------------------------------------------------
	// Daily usage chart
	// ---------------------------------------------------------------------------

	let dailySeries = $derived<AreaSeries[]>([
		{ key: 'download', label: 'Download', colour: 1, points: daily.map((d) => ({ t: d.date, v: d.resp_bytes })) },
		{ key: 'upload', label: 'Upload', colour: 2, points: daily.map((d) => ({ t: d.date, v: d.orig_bytes })) },
	]);

	let busiestDay = $derived(
		daily.reduce((best, d, i) => (d.total_bytes > (daily[best]?.total_bytes ?? -1) ? i : best), -1),
	);

	const dailyTip = (i: number) =>
		`${formatDate(daily[i].date)} · ↓ ${formatBytes(daily[i].resp_bytes)} · ↑ ${formatBytes(daily[i].orig_bytes)}`;

	// ---------------------------------------------------------------------------
	// Per-device table (the DataTable sorts; every column both ways)
	// ---------------------------------------------------------------------------

	// OLD CODE START — the page's own sort state and comparator; the DataTable does both now. Its
	// rule is the same for every column: a new column starts descending (the Device column started
	// ascending here)
	// type DeviceSortColumn = 'ip' | 'total_bytes' | 'orig_bytes' | 'resp_bytes' | 'connection_count' | 'percent_of_total';
	//
	// let sortColumn = $state<DeviceSortColumn>('total_bytes');
	// let sortDirection = $state<'asc' | 'desc'>('desc');
	//
	// const deviceColumnDefs: { key: DeviceSortColumn; label: string }[] = [
	// 	{ key: 'ip', label: 'Device' },
	// 	{ key: 'total_bytes', label: 'Total' },
	// 	{ key: 'orig_bytes', label: 'Upload' },
	// 	{ key: 'resp_bytes', label: 'Download' },
	// 	{ key: 'connection_count', label: 'Connections' },
	// 	{ key: 'percent_of_total', label: '% of Total' },
	// ];
	//
	// function handleSort(column: DeviceSortColumn) {
	// 	if (sortColumn === column) {
	// 		sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		sortColumn = column;
	// 		sortDirection = column === 'ip' ? 'asc' : 'desc';
	// 	}
	// }
	//
	// function getSortIndicator(column: DeviceSortColumn): string {
	// 	if (sortColumn !== column) return '';
	// 	return sortDirection === 'asc' ? ' ↑' : ' ↓';
	// }
	//
	// let sortedDevices = $derived.by(() => {
	// 	if (devices.length === 0) return [];
	// 	return [...devices].sort((a, b) => {
	// 		const aVal = a[sortColumn];
	// 		const bVal = b[sortColumn];
	//
	// 		if (aVal == null && bVal == null) return 0;
	// 		if (aVal == null) return 1;
	// 		if (bVal == null) return -1;
	//
	// 		let cmp = 0;
	// 		if (typeof aVal === 'number' && typeof bVal === 'number') {
	// 			cmp = aVal - bVal;
	// 		} else {
	// 			// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 			// cmp = String(aVal).localeCompare(String(bVal));
	// 			// OLD CODE END
	// 			cmp = compareValues(aVal, bVal);
	// 		}
	//
	// 		return sortDirection === 'asc' ? cmp : -cmp;
	// 	});
	// });
	// OLD CODE END

	const DEVICE_COLUMNS: Column<DeviceUsage>[] = [
		{ key: 'ip', label: 'Device', cell: deviceCell },
		{ key: 'total_bytes', label: 'Total', numeric: true, cell: totalCell },
		{ key: 'orig_bytes', label: 'Upload', numeric: true, cell: uploadCell },
		{ key: 'resp_bytes', label: 'Download', numeric: true, cell: downloadCell },
		{ key: 'connection_count', label: 'Connections', numeric: true, cell: connectionsCell },
		{ key: 'percent_of_total', label: '% of total', numeric: true, cell: percentCell },
	];

	let maxDeviceBytes = $derived(Math.max(0, ...devices.map((d) => d.total_bytes)));

	// The ten that TopConsumers showed, in the daemon's order
	let topConsumers = $derived<DeviceListItem[]>(
		devices.slice(0, 10).map((d) => ({
			key: d.ip,
			name: d.ip,
			ip: '',
			value: d.total_bytes,
			display: `${formatBytes(d.total_bytes)} · ${d.percent_of_total}%`,
			href: '/devices/' + d.ip,
		})),
	);

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN.md §5.5: loads now go through the page refresh contract (the top bar's
	// Refresh and "Updated"), report what happened, and an older load can't overwrite a newer one
	// async function fetchAll() {
	// 	loading = true;
	// 	error = '';
	// 	// OLD CODE START — #96: the getters faked zeros on failure (0.0 GB, an empty heatmap); now that
	// 	// they throw, Promise.all let one failure hide every section behind a single banner
	// 	// try {
	// 	// 	const now = new Date();
	// 	// 	const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
	// 	// 	const from = monthStart.toISOString();
	// 	// 	const to = now.toISOString();
	// 	//
	// 	// 	const [monthlyData, dailyData, deviceData, heatmapData] = await Promise.all([
	// 	// 		getMonthlyUsage(),
	// 	// 		getDailyUsage({ from, to }),
	// 	// 		getDeviceUsage({ from, to, limit: 50 }),
	// 	// 		getHeatmap({ from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString(), to: to }),
	// 	// 	]);
	// 	//
	// 	// 	monthly = monthlyData;
	// 	// 	daily = dailyData.daily;
	// 	// 	devices = deviceData.devices;
	// 	// 	heatmap = heatmapData;
	// 	// } catch (e) {
	// 	// 	error = e instanceof Error ? e.message : 'Failed to fetch bandwidth data';
	// 	// } finally {
	// 	// 	loading = false;
	// 	// }
	// 	// OLD CODE END
	// 	const now = new Date();
	// 	const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
	// 	const from = monthStart.toISOString();
	// 	const to = now.toISOString();
	//
	// 	const [monthlyRes, dailyRes, deviceRes, heatmapRes] = await Promise.allSettled([
	// 		getMonthlyUsage(),
	// 		getDailyUsage({ from, to }),
	// 		getDeviceUsage({ from, to, limit: 50 }),
	// 		getHeatmap({ from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString(), to: to }),
	// 	]);
	//
	// 	// A failed refresh keeps the last good section and says so
	// 	if (monthlyRes.status === 'fulfilled') monthly = monthlyRes.value;
	// 	if (dailyRes.status === 'fulfilled') daily = dailyRes.value.daily;
	// 	if (deviceRes.status === 'fulfilled') devices = deviceRes.value.devices;
	// 	if (heatmapRes.status === 'fulfilled') heatmap = heatmapRes.value;
	// 	monthlyFailed = monthlyRes.status === 'rejected';
	// 	dailyFailed = dailyRes.status === 'rejected';
	// 	devicesFailed = deviceRes.status === 'rejected';
	// 	heatmapFailed = heatmapRes.status === 'rejected';
	// 	loading = false;
	// }
	//
	// $effect(() => {
	// 	fetchAll();
	// });
	// OLD CODE END
	async function fetchAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		loading = true;
		const now = new Date();
		const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
		const from = monthStart.toISOString();
		const to = now.toISOString();

		const results = await Promise.allSettled([
			getMonthlyUsage(),
			getDailyUsage({ from, to }),
			getDeviceUsage({ from, to, limit: 50 }),
			getHeatmap({ from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString(), to: to }),
		]);
		if (!guard.current(g)) return 'skipped';
		const [monthlyRes, dailyRes, deviceRes, heatmapRes] = results;

		// A failed refresh keeps the last good section and says so
		if (monthlyRes.status === 'fulfilled') monthly = monthlyRes.value;
		if (dailyRes.status === 'fulfilled') daily = dailyRes.value.daily;
		if (deviceRes.status === 'fulfilled') devices = deviceRes.value.devices;
		if (heatmapRes.status === 'fulfilled') heatmap = heatmapRes.value;
		monthlyFailed = monthlyRes.status === 'rejected';
		dailyFailed = dailyRes.status === 'rejected';
		devicesFailed = deviceRes.status === 'rejected';
		heatmapFailed = heatmapRes.status === 'rejected';
		loading = false;

		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const failed = results.filter((r) => r.status === 'rejected').length;
		// return failed === 0 ? 'ok' : failed === results.length ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(results);
	}

	const refresh = registerPageRefresh(fetchAll);
	onMount(() => void refresh.run());
	onDestroy(() => refresh.unregister());
</script>

<svelte:head>
	<title>Bandwidth | NetTap</title>
</svelte:head>

{#snippet deviceCell(d: DeviceUsage)}<IPAddress ip={d.ip} />{/snippet}
{#snippet totalCell(d: DeviceUsage)}<Bytes value={d.total_bytes} max={maxDeviceBytes} display={formatBytes(d.total_bytes)} />{/snippet}
{#snippet uploadCell(d: DeviceUsage)}{formatBytes(d.orig_bytes)}{/snippet}
{#snippet downloadCell(d: DeviceUsage)}{formatBytes(d.resp_bytes)}{/snippet}
{#snippet connectionsCell(d: DeviceUsage)}{d.connection_count.toLocaleString()}{/snippet}
{#snippet percentCell(d: DeviceUsage)}{d.percent_of_total}%{/snippet}

<div class="page-head">
	<div>
		<h1 class="page-title">Bandwidth</h1>
		<p class="page-sub">This month's usage, which devices use it, and when your network is busiest</p>
	</div>
</div>

{#if monthlyFailed && monthly}
	<p class="notice is-warn" role="status">{loadFailed("this month's usage", true)}</p>
{/if}

<div class="grid">
	{#if monthly}
		{@const p = monthly.projection}
		{@const daysLeft = p.days_in_month - Math.floor(p.days_elapsed)}
		{@const usedPercent = progressPercent(monthly.total_bytes, p.cap_bytes)}
		<KpiCard
			class="c-3"
			label="This month"
			icon="bandwidth"
			value={gb(monthly.total_bytes)}
			unit="GB"
			note="{monthName(monthly.year, monthly.month)} so far"
			sub="↓ {formatGB(monthly.resp_bytes)} down · ↑ {formatGB(monthly.orig_bytes)} up"
		>
			{#snippet foot()}
				{#if p.cap_bytes > 0}
					<span class="cap">{p.usage_percent}% of your {formatGB(p.cap_bytes)} cap</span>
					<Meter value={usedPercent} label="{p.usage_percent}% of your monthly cap used" />
				{/if}
			{/snippet}
		</KpiCard>
		<KpiCard
			class="c-3"
			label="Projected"
			icon="up"
			value={gb(p.projected_bytes)}
			unit="GB"
			delta={p.exceeds_cap ? { text: 'Over your cap', direction: 'up', bad: true } : undefined}
			note="By the end of the month at this rate"
		/>
		<KpiCard class="c-3" label="Daily rate" icon="download" value={gb(p.daily_rate_bytes)} unit="GB a day" note="Average so far this month" />
		<KpiCard class="c-3" label="Days remaining" icon="changelog" value={daysLeft} unit={daysLeft === 1 ? 'day' : 'days'} note="Of {p.days_in_month} this month" />
	{:else}
		<Card class="c-12" title="This month" sub="Data used, projection and cap">
			{#if monthlyFailed}
				<CardState state="error" title={loadFailed("this month's usage")} message={RETRY_HINT} onaction={() => refresh.run()} />
			{:else}
				<CardState state="loading" title="Loading this month's usage" />
			{/if}
		</Card>
	{/if}

	<Card class="c-8" hero title="Daily usage" sub="Data per day, download and upload · this month, UTC days">
		{#snippet actions()}
			<ul class="legend">
				<li><span class="sw c-d1"></span>Download</li>
				<li><span class="sw c-d2"></span>Upload</li>
			</ul>
		{/snippet}
		{#if daily.length > 0}
			<AreaChart
				series={dailySeries}
				formatX={(t) => formatDate(String(t))}
				formatY={formatBytes}
				formatTip={dailyTip}
				highlightIndex={busiestDay}
				ariaLabel={busiestDay >= 0 ? `Busiest day ${formatDate(daily[busiestDay].date)}, with ${formatBytes(daily[busiestDay].total_bytes)}` : 'Daily usage'}
			/>
			{#if dailyFailed}
				<p class="load-note">{loadFailed('daily usage', true)}</p>
			{/if}
		{:else if dailyFailed}
			<CardState state="error" title={loadFailed('daily usage')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else if loading}
			<CardState state="loading" title="Loading daily usage" />
		{:else}
			<CardState state="empty" title="No usage this month yet" message="Each day's usage appears here once NetTap sees traffic." />
		{/if}
	</Card>

	<Card class="c-4" title="Top consumers" sub="Data used this month, top 10 devices">
		{#if topConsumers.length > 0}
			<DeviceList items={topConsumers} />
			{#if devicesFailed}
				<p class="load-note">{loadFailed('per-device usage', true)}</p>
			{/if}
		{:else if devicesFailed}
			<CardState state="error" title={loadFailed('per-device usage')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else if loading}
			<CardState state="loading" title="Loading top consumers" />
		{:else}
			<CardState state="empty" title="No devices yet" message="Devices appear here once they use data this month." />
		{/if}
	</Card>

	<Card class="c-12" title="Per-device breakdown" sub="This month · {devices.length} {devices.length === 1 ? 'device' : 'devices'}">
		{#if devices.length > 0}
			<DataTable columns={DEVICE_COLUMNS} rows={devices} ariaLabel="Per-device breakdown" rowKey={(d) => d.ip} initialSort={{ key: 'total_bytes', dir: 'desc' }} />
		{:else if devicesFailed}
			<CardState state="error" title={loadFailed('the per-device breakdown')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else if loading}
			<CardState state="loading" title="Loading the per-device breakdown" />
		{:else}
			<CardState state="empty" title="No devices yet" message="Devices appear here once they use data this month." />
		{/if}
	</Card>

	<Card class="c-12" title="When your network is busiest" sub="Data per hour · last 7 days">
		{#snippet actions()}
			<!-- a daemon that doesn't echo tz ignored it and bucketed in UTC -->
			{#if heatmap}<span class="card-sub">Hours in {heatmap.tz || 'UTC'}</span>{/if}
		{/snippet}
		{#if heatmap && heatmap.matrix}
			{#if heatmapFailed}
				<p class="load-note">{loadFailed('the time-of-day heatmap', true)}</p>
			{/if}
			<div class="heatmap-scroll">
				<div
					class="heatmap"
					role="img"
					aria-label={busiestHour.value > 0
						? `Busiest hour ${DAYS[busiestHour.day]} ${busiestHour.hour}:00, with ${formatBytes(busiestHour.value)}`
						: 'No traffic in the last 7 days'}
				>
					<span></span>
					{#each HOURS as hour (hour)}
						<span class="hour">{hour}</span>
					{/each}
					{#each DAYS as day, dayIdx (day)}
						<span class="day">{day}</span>
						{#each HOURS as hour (hour)}
							<span
								class="cell"
								style:background-color={heatmapColor(heatmap.matrix[dayIdx]?.[hour] ?? 0, heatmapMax())}
								title="{day} {hour}:00 - {formatBytes(heatmap.matrix[dayIdx]?.[hour] ?? 0)}"
							></span>
						{/each}
					{/each}
				</div>
			</div>
		{:else if heatmapFailed}
			<CardState state="error" title={loadFailed('the time-of-day heatmap')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else}
			<CardState state="loading" title="Loading the time-of-day heatmap" />
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	.load-note { margin-top: var(--sp-3); font-size: var(--text-xs); color: var(--sev-medium); }
	.cap { font-size: var(--text-xs); color: var(--text-2); }
	.heatmap-scroll { overflow-x: auto; }
	.heatmap { display: grid; grid-template-columns: var(--sp-8) repeat(24, minmax(16px, 1fr)); gap: 2px; min-width: 480px; }
	.hour, .day { font-size: var(--text-micro); color: var(--text-3); font-variant-numeric: tabular-nums; }
	.hour { text-align: center; }
	.day { display: flex; align-items: center; }
	.cell { aspect-ratio: 1; border-radius: var(--r-xs); }
</style>
