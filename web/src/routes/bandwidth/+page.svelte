<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	// OLD CODE START — F4 (NET-329): the month, the daily chart and the cap's figure come from the usage ledger, in the owner's month
	// import { getMonthlyUsage, getDailyUsage, getDeviceUsage, getHeatmap, utcMonthWindow } from '$lib/api/bandwidth';
	// import type { MonthlyUsage, DailyUsageEntry, DeviceUsage, HeatmapResponse } from '$lib/api/bandwidth';
	// OLD CODE END
	import { getBandwidthCap, getDeviceUsage, getHeatmap } from '$lib/api/bandwidth';
	import type { BandwidthCap, DeviceUsage, HeatmapResponse } from '$lib/api/bandwidth';
	import { getTimezone, getUsageMonth, hasFigures, setTimezone } from '$lib/api/usage';
	import type { OwnerTimezone, UsageDay, UsageMonth } from '$lib/api/usage';
	import { formatDate, monthNote, noRateReason, notFinalLine, sameAsUtc, STATUS_WORDS } from './usage-words';
	// OLD CODE START — replaced by the system's DeviceList (Top consumers) and DataTable, which sorts
	// import TopConsumers from '$lib/components/TopConsumers.svelte';
	// import { compareValues } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	import IPAddress from '$components/IPAddress.svelte';
	import { loadFailed } from '$lib/utils/load-failed';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import DeviceList, { type DeviceListItem } from '$lib/components/ui/DeviceList.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import AreaChart, { type AreaSeries } from '$lib/components/ui/charts/AreaChart.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import { ipHref } from '$lib/stores/lan';
	// OLD CODE: import { fmt } from '$lib/utils/drilldown'; (NET-249: a day opens its moment)
	// OLD CODE: import { fmt, momentHref, stepMs, type BandwidthChart } from '$lib/utils/drilldown'; (F4: ledger days carry their own bounds)
	import { fmt, momentHref, type BandwidthChart } from '$lib/utils/drilldown';
	// OLD CODE: import { recorded, upDownLocal } from '$lib/utils/up-down'; (F4: a ledger day's status says whether it has figures)
	import { upDownLocal } from '$lib/utils/up-down';
	import { ipv6ListNotes } from '$lib/utils/ipv6-coverage';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// OLD CODE START — F4 (NET-329): the daemon's UTC month and its raw daily sums
	// let monthly = $state<MonthlyUsage | null>(null);
	// let daily = $state<DailyUsageEntry[]>([]);
	// OLD CODE END
	/** The owner's month from the usage ledger: its bounds, totals and each day's status */
	let month = $state<UsageMonth | null>(null);
	/** The month's days up to today, from the month reply (future days have no figures and aren't drawn) */
	let daily = $state<UsageDay[]>([]);
	let cap = $state<BandwidthCap | null>(null);
	let capFailed = $state(false);
	/** The zone NetTap counts in, and whether the owner picked it */
	let ownerTz = $state<OwnerTimezone | null>(null);
	let tzSaving = $state(false);
	let tzError = $state('');
	/** The daily reply as a bandwidth chart, whole, when it echoes its window and its 1-day bucket (NET-249) */
	let dailyChart = $state<BandwidthChart | null>(null);
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
	/** The most rows the daemon's per-device endpoint returns. */
	const DEVICE_LIMIT = 200;

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-06 (NET-166): 1024-based under decimal labels (a 1,000 GB cap read 931.3 GB)
	// function formatBytes(bytes: number): string {
	// 	if (bytes < 1024) return `${bytes} B`;
	// 	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	// 	if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	// 	return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	// }
	//
	// function formatGB(bytes: number): string {
	// 	return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
	// }
	//
	// /** The GB figure alone, for a KPI whose unit sits beside it. */
	// const gb = (bytes: number) => (bytes / 1024 ** 3).toFixed(1);
	// OLD CODE END
	// Decimal units (1 GB = 10^9 bytes), as ISPs state caps; GB is the largest unit on this page
	function formatBytes(bytes: number): string {
		if (bytes < 1e3) return `${bytes} B`;
		if (bytes < 1e6) return `${(bytes / 1e3).toFixed(1)} KB`;
		if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
		return `${(bytes / 1e9).toFixed(1)} GB`;
	}

	function formatGB(bytes: number): string {
		return `${(bytes / 1e9).toFixed(1)} GB`;
	}

	/** The GB figure alone, for a KPI whose unit sits beside it. */
	const gb = (bytes: number) => (bytes / 1e9).toFixed(1);

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

	// formatDate and monthName moved to ./usage-words.ts (F4), beside the ledger wording that uses them

	// ---------------------------------------------------------------------------
	// The owner's month (F4, NET-329: the usage ledger, in the owner's time zone)
	// ---------------------------------------------------------------------------

	/** The browser's zone, offered while the owner hasn't picked one; UTC's other names are UTC, so it never offers "Etc/UTC" over UTC */
	const BROWSER_TZ = sameAsUtc(Intl.DateTimeFormat().resolvedOptions().timeZone || '');
	const DAY_MS = 86_400_000;

	const NO_FIGURES = { download_bytes: Number.NaN, upload_bytes: Number.NaN, local_bytes: Number.NaN };

	/** Ledger figures in the shape upDownLocal reads; a day without figures reads 0 */
	const upDown = (b: { download: number | null; upload: number | null; local: number | null }) => ({
		download_bytes: b.download ?? 0,
		upload_bytes: b.upload ?? 0,
		local_bytes: b.local ?? 0,
	});

	/** Count days in `zone` (this browser's, or keep the one in use), then reload so the page says it is switching */
	async function chooseZone(zone: string) {
		tzSaving = true;
		tzError = '';
		const result = await setTimezone(zone);
		tzSaving = false;
		if (!result.ok) {
			tzError = result.error;
			return;
		}
		ownerTz = result.data;
		void refresh.run();
	}

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

	// OLD CODE START — NET-226: download/upload were the responder's/originator's bytes, local traffic included
	// { key: 'download', label: 'Download', colour: 1, points: daily.map((d) => ({ t: d.date, v: d.resp_bytes })) },
	// { key: 'upload', label: 'Upload', colour: 2, points: daily.map((d) => ({ t: d.date, v: d.orig_bytes })) },
	// OLD CODE END
	// OLD CODE START — chart gaps: a day with no connection record drew as 0 B, and could be the busiest day
	// let dailySeries = $derived<AreaSeries[]>([
	// 	{ key: 'download', label: 'Download', colour: 1, points: daily.map((d) => ({ t: d.date, v: d.download_bytes })) },
	// 	{ key: 'upload', label: 'Upload', colour: 2, points: daily.map((d) => ({ t: d.date, v: d.upload_bytes })) },
	// 	{ key: 'local', label: 'Local', colour: 3, points: daily.map((d) => ({ t: d.date, v: d.local_bytes })) },
	// ]);
	//
	// let busiestDay = $derived(
	// 	daily.reduce((best, d, i) => (d.total_bytes > (daily[best]?.total_bytes ?? -1) ? i : best), -1),
	// );
	// const dailyTip = (i: number) => `${formatDate(daily[i].date)} · ${upDownLocal(daily[i], formatBytes, false)}`;
	// OLD CODE END
	// OLD CODE START — F4 (NET-329): raw daily sums, where a day with no connection record was the gap
	// /** A day's bytes, or NaN (a "No data" gap) when it has no connection record */
	// const bytesOf = (d: DailyUsageEntry, v: number) => (recorded(d) ? v : Number.NaN);
	// let dailySeries = $derived<AreaSeries[]>([
	// 	{ key: 'download', label: 'Download', colour: 1, points: daily.map((d) => ({ t: d.date, v: bytesOf(d, d.download_bytes) })) },
	// 	{ key: 'upload', label: 'Upload', colour: 2, points: daily.map((d) => ({ t: d.date, v: bytesOf(d, d.upload_bytes) })) },
	// 	{ key: 'local', label: 'Local', colour: 3, points: daily.map((d) => ({ t: d.date, v: bytesOf(d, d.local_bytes) })) },
	// ]);
	//
	// // a day with no record is never the busiest; a recorded 0 B day still beats it
	// let busiestDay = $derived(
	// 	daily.reduce((best, d, i) => (recorded(d) && d.total_bytes > (daily[best]?.total_bytes ?? -1) ? i : best), -1),
	// );
	//
	// // OLD CODE: `${formatDate(daily[i].date)} · ↓ ${formatBytes(daily[i].resp_bytes)} · ↑ ${formatBytes(daily[i].orig_bytes)}` (NET-226)
	// const dailyTip = (i: number) => `${formatDate(daily[i].date)} · ${recorded(daily[i]) ? upDownLocal(daily[i], formatBytes, false) : 'no data'}`;
	// OLD CODE END
	/** A day's bytes, or NaN (a "No data" gap) when the ledger has no figures for it */
	const bytesOf = (d: UsageDay, v: number | null) => (hasFigures(d) && v !== null ? v : Number.NaN);
	let dailySeries = $derived<AreaSeries[]>([
		{ key: 'download', label: 'Download', colour: 1, points: daily.map((d) => ({ t: d.date, v: bytesOf(d, d.download) })) },
		{ key: 'upload', label: 'Upload', colour: 2, points: daily.map((d) => ({ t: d.date, v: bytesOf(d, d.upload) })) },
		{ key: 'local', label: 'Local', colour: 3, points: daily.map((d) => ({ t: d.date, v: bytesOf(d, d.local) })) },
	]);

	// a day without figures is never the busiest; a counted 0 B day still beats it
	let busiestDay = $derived(
		daily.reduce((best, d, i) => (hasFigures(d) && (d.total ?? 0) > (daily[best]?.total ?? -1) ? i : best), -1),
	);

	const dailyTip = (i: number) => {
		const d = daily[i];
		return [formatDate(d.date), hasFigures(d) ? upDownLocal(upDown(d), formatBytes, false) : '', STATUS_WORDS[d.status]].filter(Boolean).join(' · ');
	};

	let notFinal = $derived(notFinalLine(daily));

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
		// OLD CODE START — NET-226: the originator's bytes, so a device's answers read as download
		// { key: 'orig_bytes', label: 'Upload', numeric: true, cell: uploadCell },
		// { key: 'resp_bytes', label: 'Download', numeric: true, cell: downloadCell },
		// OLD CODE END
		{ key: 'upload_bytes', label: 'Upload', numeric: true, cell: uploadCell },
		{ key: 'download_bytes', label: 'Download', numeric: true, cell: downloadCell },
		{ key: 'connection_count', label: 'Connections', numeric: true, cell: connectionsCell },
		{ key: 'percent_of_total', label: '% of total', numeric: true, cell: percentCell },
	];

	let maxDeviceBytes = $derived(Math.max(0, ...devices.map((d) => d.total_bytes)));
	// NET-226: IPv6 the daemon couldn't match to a device safely, said once per reason
	let ipv6Notes = $derived(ipv6ListNotes(devices));

	// The ten that TopConsumers showed, in the daemon's order
	let topConsumers = $derived<DeviceListItem[]>(
		devices.slice(0, 10).map((d) => ({
			key: d.ip,
			name: d.ip,
			ip: '',
			value: d.total_bytes,
			display: `${formatBytes(d.total_bytes)} · ${d.percent_of_total}%`,
			// OLD CODE START — NET-160: unencoded, and the device page for every address
			// href: '/devices/' + d.ip,
			// OLD CODE END
			href: $ipHref(d.ip),
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
		// OLD CODE START — 2026-11-06 (O5): the chart and table took the local month, the KPI the
		// daemon's UTC month, so east of UTC they counted hours of last month (west, missed hours)
		// const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
		// const from = monthStart.toISOString();
		// const to = now.toISOString();
		// OLD CODE END
		// OLD CODE START — F4 (NET-329): every card took the UTC month; now the ledger's month (the owner's
		// time zone) bounds the KPI row, the daily chart and the device card alike
		// const { year, month, from, to } = utcMonthWindow(now);
		//
		// const results = await Promise.allSettled([
		// 	// OLD CODE START — 2026-11-06 (O5): the daemon picked its own "now" for the month
		// 	// getMonthlyUsage(),
		// 	// OLD CODE END
		// 	getMonthlyUsage({ year, month }),
		// 	getDailyUsage({ from, to }),
		// 	// OLD CODE START — 2026-11-06 (O4): 50 rows were labelled as every device
		// 	// getDeviceUsage({ from, to, limit: 50 }),
		// 	// OLD CODE END
		// 	getDeviceUsage({ from, to, limit: DEVICE_LIMIT }),
		// 	getHeatmap({ from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString(), to: to }),
		// ]);
		// if (!guard.current(g)) return 'skipped';
		// const [monthlyRes, dailyRes, deviceRes, heatmapRes] = results;
		//
		// // A failed refresh keeps the last good section and says so
		// if (monthlyRes.status === 'fulfilled') monthly = monthlyRes.value;
		// // OLD CODE: if (dailyRes.status === 'fulfilled') daily = dailyRes.value.daily; (NET-249: the reply whole)
		// if (dailyRes.status === 'fulfilled') {
		// 	const reply = dailyRes.value;
		// 	const step = stepMs(reply.interval);
		// 	daily = reply.daily;
		// 	// a UTC day is [date, date + 1 d); the last one is clipped to the reply's `to` (now)
		// 	const windowed = Number.isFinite(Date.parse(reply.from)) && Number.isFinite(Date.parse(reply.to));
		// 	dailyChart = step && windowed ? { from: reply.from, to: reply.to, step, series: reply.daily.map((d) => ({ ...d, timestamp: d.date })) } : null;
		// }
		// if (deviceRes.status === 'fulfilled') devices = deviceRes.value.devices;
		// if (heatmapRes.status === 'fulfilled') heatmap = heatmapRes.value;
		// monthlyFailed = monthlyRes.status === 'rejected';
		// dailyFailed = dailyRes.status === 'rejected';
		// devicesFailed = deviceRes.status === 'rejected';
		// heatmapFailed = heatmapRes.status === 'rejected';
		// loading = false;
		//
		// // OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// // const failed = results.filter((r) => r.status === 'rejected').length;
		// // return failed === 0 ? 'ok' : failed === results.length ? 'failed' : 'partial';
		// // OLD CODE END
		// return outcome(results);
		// OLD CODE END
		const others = Promise.allSettled([
			getHeatmap({ from: new Date(now.getTime() - 7 * DAY_MS).toISOString(), to: now.toISOString() }),
			getBandwidthCap(),
			getTimezone(),
		]);
		// The month first: its local bounds are the device card's, and its days are the daily chart
		const [monthRes] = await Promise.allSettled([getUsageMonth()]);
		// a failed refresh keeps the last month on screen, so its table still refreshes
		const m = monthRes.status === 'fulfilled' ? monthRes.value : month;
		const [deviceRes] = await Promise.allSettled([
			m ? getDeviceUsage({ from: m.month_start, to: m.month_end, limit: DEVICE_LIMIT }) : Promise.reject(new Error("This month's bounds didn't load")),
		]);
		const [heatmapRes, capRes, tzRes] = await others;
		if (!guard.current(g)) return 'skipped';

		// A failed refresh keeps the last good section and says so
		if (monthRes.status === 'fulfilled') {
			month = monthRes.value;
			// the chart draws the month's own days, so its figures and the KPI's come from one answer
			daily = month.days.filter((d) => d.status !== 'future');
			const last = daily.at(-1);
			// each point is its local day [start, end) (23 or 25 h across a clock change); the window runs
			// from the month's start to what today's count reached, so today's pick ends where its figures do
			// today not counted yet reaches now; and never before its own start, so its pick is a valid window
			const reached = last && (last.cutoff ? Date.parse(last.cutoff) : Math.min(Date.now(), Date.parse(last.end) - 1));
			dailyChart = last
				? {
						from: daily[0].start,
						to: new Date(Math.max(reached || 0, Date.parse(last.start))).toISOString(),
						step: DAY_MS,
						// a day without figures is NaN, so a pick on it carries no figures to compare (momentHref)
						series: daily.map((d) => ({ timestamp: d.start, end: d.end, ...(hasFigures(d) ? upDown(d) : NO_FIGURES) })),
					}
				: null;
		}
		if (deviceRes.status === 'fulfilled') devices = deviceRes.value.devices;
		if (heatmapRes.status === 'fulfilled') heatmap = heatmapRes.value;
		if (capRes.status === 'fulfilled') cap = capRes.value;
		if (tzRes.status === 'fulfilled') ownerTz = tzRes.value;
		monthlyFailed = monthRes.status === 'rejected';
		// the chart's days come with the month
		dailyFailed = monthlyFailed;
		devicesFailed = deviceRes.status === 'rejected';
		heatmapFailed = heatmapRes.status === 'rejected';
		capFailed = capRes.status === 'rejected';
		loading = false;

		return outcome([monthRes, deviceRes, heatmapRes, capRes, tzRes]);
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
<!-- OLD CODE: uploadCell/downloadCell read d.orig_bytes / d.resp_bytes (NET-226) -->
{#snippet uploadCell(d: DeviceUsage)}{formatBytes(d.upload_bytes)}{/snippet}
{#snippet downloadCell(d: DeviceUsage)}{formatBytes(d.download_bytes)}{/snippet}
{#snippet connectionsCell(d: DeviceUsage)}{fmt(d.connection_count)}{/snippet}
{#snippet percentCell(d: DeviceUsage)}{d.percent_of_total}%{/snippet}

<div class="page-head">
	<div>
		<h1 class="page-title">Bandwidth</h1>
		<p class="page-sub">This month's usage, which devices use it, and when your network is busiest</p>
	</div>
</div>

<!-- OLD CODE: {#if monthlyFailed && monthly} (F4: the month comes from the usage ledger) -->
{#if monthlyFailed && month}
	<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed("this month's usage", true)}</span></p>
{/if}

<!-- F4: days are counted in the owner's zone; until one is picked, offer this browser's -->
{#if month?.pending_tz}
	<p class="notice page-note" role="status"><Icon name="refresh" /><span>Switching to {month.pending_tz}…</span></p>
{:else if ownerTz && !ownerTz.set && BROWSER_TZ && BROWSER_TZ !== sameAsUtc(ownerTz.tz)}
	<div class="notice page-note tz-offer" role="note">
		<Icon name="changelog" />
		<span>Days are counted in {ownerTz.tz}. Count them in {BROWSER_TZ}?</span>
		<button class="btn" type="button" onclick={() => chooseZone(BROWSER_TZ)} disabled={tzSaving}>{tzSaving ? 'Switching…' : `Count in ${BROWSER_TZ}`}</button>
		<!-- keeping the zone in use sets it, so the offer goes -->
		<button class="btn" type="button" onclick={() => chooseZone(ownerTz!.tz)} disabled={tzSaving}>Keep {ownerTz.tz}</button>
	</div>
{/if}
{#if tzError}
	<p class="notice is-error page-note" role="alert"><Icon name="warn" /><span>Couldn't change the time zone: {tzError}</span></p>
{/if}

<div class="grid">
	<!-- OLD CODE: {@const usedPercent = progressPercent(monthly.total_bytes, p.cap_bytes)} (NET-226 follow-up: local traffic never crosses the ISP link) -->
	<!-- OLD CODE: sub="↓ {formatGB(monthly.resp_bytes)} down · ↑ {formatGB(monthly.orig_bytes)} up" (NET-226: local traffic was counted as both) -->
	<!-- OLD CODE: label="This month" value={gb(monthly.total_bytes)} note="{monthName(monthly.year, monthly.month)} so far" (NET-226 follow-up: the cap counts internet traffic only) -->
	<!-- OLD CODE START — F4 (NET-329): the daemon's UTC month and its projection object; the KPI row reads the usage ledger now
	{#if monthly}
		{@const p = monthly.projection}
		{@const daysLeft = p.days_in_month - Math.floor(p.days_elapsed)}
		{@const usedPercent = progressPercent(p.current_bytes, p.cap_bytes)}
		<KpiCard class="c-3" label="Internet this month" icon="bandwidth" value={gb(p.current_bytes)} unit="GB"
			note="{monthName(monthly.year, monthly.month)} so far, without traffic between your devices" sub={upDownLocal(monthly, formatGB)}>
			{#snippet foot()}
				{#if p.cap_bytes > 0}
					<span class="cap">{p.usage_percent}% of your {formatGB(p.cap_bytes)} cap</span>
					<Meter value={usedPercent} label="{p.usage_percent}% of your monthly cap used" />
				{/if}
			{/snippet}
		</KpiCard>
		<KpiCard class="c-3" label="Projected" icon="up" value={gb(p.projected_bytes)} unit="GB"
			delta={p.exceeds_cap ? { text: 'Over your cap', direction: 'up', bad: true } : undefined} note="By the end of the month at this rate" />
		<KpiCard class="c-3" label="Daily rate" icon="download" value={gb(p.daily_rate_bytes)} unit="GB a day" note="Average so far this month" />
		<KpiCard class="c-3" label="Days remaining" icon="changelog" value={daysLeft} unit={daysLeft === 1 ? 'day' : 'days'} note="Of {p.days_in_month} this month" />
	OLD CODE END -->
	{#if month}
		<!-- the ledger's total is what crossed the ISP link (download + upload), without local traffic (NET-226 follow-up) -->
		{@const internet = month.bytes.total}
		{@const capBytes = cap?.monthly_cap_bytes ?? 0}
		{@const kpi = month.projected === null ? 'c-4' : 'c-3'}
		<!-- a null days_remaining (a stale or uncounted day) still has a calendar answer -->
		{@const daysLeft = Math.ceil(month.days_remaining ?? (Math.max(0, Date.parse(month.month_end) - Date.now()) / DAY_MS))}
		<KpiCard class={kpi} label="Internet this month" icon="bandwidth" value={gb(internet)} unit="GB" note={monthNote(month)} sub={upDownLocal(upDown(month.bytes), formatGB)}>
			{#snippet foot()}
				{#if capBytes > 0}
					{@const pct = Math.round((internet / capBytes) * 100)}
					<span class="cap">{pct}% of your {formatGB(capBytes)} cap</span>
					<Meter value={progressPercent(internet, capBytes)} label="{pct}% of your monthly cap used" />
				{:else if capFailed && !cap}
					<span class="cap">Couldn't load your cap</span>
				{/if}
			{/snippet}
		</KpiCard>
		{#if month.projected !== null}
			<KpiCard
				class={kpi}
				label="Projected"
				icon="up"
				value={gb(month.projected)}
				unit="GB"
				delta={capBytes > 0 && month.projected > capBytes ? { text: 'Over your cap', direction: 'up', bad: true } : undefined}
				note="By the end of the month at this rate"
			/>
		{/if}
		{#if month.daily_rate === null}
			<KpiCard class={kpi} label="Daily rate" icon="download" value="—" note={noRateReason(month)} />
		{:else}
			<KpiCard class={kpi} label="Daily rate" icon="download" value={gb(month.daily_rate)} unit="GB a day" note="Average so far this month" />
		{/if}
		<KpiCard class={kpi} label="Days remaining" icon="changelog" value={daysLeft} unit={daysLeft === 1 ? 'day' : 'days'} note="Of {month.days.length} this month" />
	{:else}
		<Card class="c-12" title="This month" sub="Data used, projection and cap">
			{#if monthlyFailed}
				<CardState state="error" title={loadFailed("this month's usage")} message={RETRY_HINT} onaction={() => refresh.run()} />
			{:else}
				<CardState state="loading" title="Loading this month's usage" />
			{/if}
		</Card>
	{/if}

	<!-- OLD CODE: sub="Data per day, download and upload · this month, UTC days" (NET-226: local is its own series) -->
	<!-- OLD CODE: sub="Data per day: download, upload and local · this month, UTC days" (F4: days in the owner's zone) -->
	<Card class="c-8" hero col title="Daily usage" sub="Data per day: download, upload and local · this month{month ? `, ${month.tz} days` : ''}">
		{#snippet actions()}
			<ul class="legend">
				<li><span class="sw c-d1"></span>Download</li>
				<li><span class="sw c-d2"></span>Upload</li>
				<li><span class="sw c-d3"></span>Local</li>
			</ul>
		{/snippet}
		<!-- OLD CODE: {#if daily.length > 0} (chart gaps: a month with no connection record is the empty state, not an all-hatched chart) -->
		<!-- OLD CODE: {#if daily.some(recorded)} (F4: a ledger day's status says whether it has figures) -->
		{#if daily.some(hasFigures)}
			<!-- OLD CODE: ariaLabel=… formatBytes(daily[busiestDay].total_bytes) (F4: the ledger's `total`) -->
			<AreaChart
				series={dailySeries}
				bytes
				gaps
				formatX={(t) => formatDate(String(t))}
				formatY={formatBytes}
				formatTip={dailyTip}
				highlightIndex={busiestDay}
				ariaLabel={busiestDay >= 0 ? `Busiest day ${formatDate(daily[busiestDay].date)}, with ${formatBytes(daily[busiestDay].total ?? 0)}` : 'Daily usage'}
				onpick={dailyChart ? (i, j) => dailyChart && goto(momentHref(dailyChart, i, j)) : undefined}
				flagged={(i) => !!STATUS_WORDS[daily[i]?.status]}
			/>
			{#if notFinal}
				<p class="notice is-warn load-note" role="note"><Icon name="warn" /><span>Not final yet. {notFinal}</span></p>
			{/if}
			{#if dailyChart}<p class="card-sub load-note">Click a point or drag across the chart to see that moment.</p>{/if}
			{#if dailyFailed}
				<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('daily usage', true)}</span></p>
			{/if}
		{:else if dailyFailed}
			<CardState state="error" title={loadFailed('daily usage')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else if loading}
			<CardState state="loading" title="Loading daily usage" />
		{:else if daily.some((d) => d.status === 'pending' || d.status === 'recount_pending')}
			<CardState state="empty" title="Still counting" message="Each day appears here once NetTap has counted it." />
		{:else}
			<CardState state="empty" title="No usage this month yet" message="Each day's usage appears here once NetTap sees traffic." />
		{/if}
	</Card>

	<Card class="c-4" title="Top consumers" sub="Data used this month, top 10 devices">
		{#if topConsumers.length > 0}
			<DeviceList items={topConsumers} />
			{#if devicesFailed}
				<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('per-device usage', true)}</span></p>
			{/if}
		{:else if devicesFailed}
			<CardState state="error" title={loadFailed('per-device usage')} message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else if loading}
			<CardState state="loading" title="Loading top consumers" />
		{:else}
			<CardState state="empty" title="No devices yet" message="Devices appear here once they use data this month." />
		{/if}
	</Card>

	<!-- OLD CODE START — 2026-11-06 (O4): a full page of rows read as every device
	<Card class="c-12" title="Per-device breakdown" sub="This month · {devices.length} {devices.length === 1 ? 'device' : 'devices'}">
	OLD CODE END -->
	<Card
		class="c-12"
		title="Per-device breakdown"
		sub="This month · {devices.length >= DEVICE_LIMIT ? `top ${DEVICE_LIMIT} devices` : `${devices.length} ${devices.length === 1 ? 'device' : 'devices'}`}"
	>
		{#if devices.length > 0}
			<DataTable columns={DEVICE_COLUMNS} rows={devices} ariaLabel="Per-device breakdown" rowKey={(d) => d.ip} initialSort={{ key: 'total_bytes', dir: 'desc' }} />
			{#each ipv6Notes as note (note)}
				<p class="notice is-warn load-note" role="note"><Icon name="warn" /><span>{note}</span></p>
			{/each}
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
				<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('the time-of-day heatmap', true)}</span></p>
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
	/* OLD CODE: .load-note { margin-top: var(--sp-3); font-size: var(--text-xs); color: var(--sev-medium); } (NET-192 PR 4: a stale note is the shared .notice.is-warn) */
	.load-note { margin-top: var(--sp-3); }
	.cap { font-size: var(--text-xs); color: var(--text-2); }
	/* F4: the time-zone notices sit above the grid; the offer's button follows its question */
	.page-note { margin-bottom: var(--sp-4); }
	.tz-offer { align-items: center; flex-wrap: wrap; }
	.heatmap-scroll { overflow-x: auto; }
	.heatmap { display: grid; grid-template-columns: var(--sp-8) repeat(24, minmax(16px, 1fr)); gap: 2px; min-width: 480px; }
	.hour, .day { font-size: var(--text-micro); color: var(--text-3); font-variant-numeric: tabular-nums; }
	.hour { text-align: center; }
	.day { display: flex; align-items: center; }
	.cell { aspect-ratio: 1; border-radius: var(--r-xs); }
</style>
