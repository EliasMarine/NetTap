<script lang="ts">
	import { onDestroy, onMount, type Snippet } from 'svelte';
	import {
		getDnsStats,
		getTopDomains,
		getNxdomains,
		getQueryTypes,
		getDnsTimeline,
		getSuspiciousDns,
		getDeviceDns,
		ENCRYPTED_DNS_NOTE,
	} from '$lib/api/dns';
	import { page } from '$app/stores';
	import { captureMode, initCaptureMode } from '$lib/stores/captureMode';
	import { partOfWhole } from '$lib/utils/part-of-whole';
	import { loadFailed } from '$lib/utils/load-failed';
	// OLD CODE START — replaced by the design system's BarList
	// import HorizontalBarList from '$components/HorizontalBarList.svelte';
	// OLD CODE END
	import type {
		DnsStats,
		TopDomain,
		NxdomainEntry,
		QueryTypeEntry,
		TimelineEntry,
		SuspiciousEntry,
		DeviceDnsEntry,
	} from '$lib/api/dns';
	import { compareValues } from '$lib/utils/table-sort.svelte';
	import type { SortDir } from '$lib/utils/table-sort.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import type { SeverityLevel } from '$lib/utils/severity';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import { domainHref } from '$lib/stores/lan';
	// OLD CODE: import { chartTime, DRILL_RANGES, fmt, rangeWindow, startRange } from '$lib/utils/drilldown'; (NET-238: SCAN_CAP)
	import { chartTime, DRILL_RANGES, fmt, rangeWindow, SCAN_CAP, startRange } from '$lib/utils/drilldown';
	import { formatCompactNumber as formatNumber } from '$lib/api/logs';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	// One range set across the app (NET-192 PR 4): 1h 6h 24h 7d 30d, as on Home. Live is the real-time page.
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES), with this page's ms beside it
	// const TIME_RANGES = [
	// 	// OLD CODE: { label: '15m', value: '15m', ms: 15 * 60 * 1000, words: 'last 15 minutes' }, (NET-192 PR 4)
	// 	{ label: '1h', value: '1h', ms: 60 * 60 * 1000, words: 'last hour' },
	// 	// OLD CODE: { label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000, words: 'last 4 hours' }, (NET-192 PR 4)
	// 	{ label: '6h', value: '6h', ms: 6 * 60 * 60 * 1000, words: 'last 6 hours' },
	// 	{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000, words: 'last 24 hours' },
	// 	{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000, words: 'last 7 days' },
	// 	{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000, words: 'last 30 days' },
	// ];
	// OLD CODE END
	const TIME_RANGES = [...DRILL_RANGES]; // a copy: Pills takes a mutable list

	// OLD CODE START — severity is now the system's SeverityPill (colour, shape and word)
	// const SEVERITY_COLORS: Record<string, string> = {
	// 	critical: 'var(--sev-critical)',
	// 	high: 'var(--sev-high)',
	// 	medium: 'var(--sev-medium)',
	// 	low: 'var(--sev-low)',
	// 	info: 'var(--sev-info)',
	// };
	// OLD CODE END
	const LEVELS = new Set<string>(['critical', 'high', 'medium', 'low', 'info']);
	const isLevel = (s: string): s is SeverityLevel => LEVELS.has(s);

	/** The timeline's bucket per range, and how the chart names it. */
	const INTERVALS: Record<string, { interval: string; words: string }> = {
		// OLD CODE: '15m': { interval: '1m', words: 'minute' }, (NET-192 PR 4)
		'1h': { interval: '5m', words: '5 minutes' },
		// OLD CODE: '4h': { interval: '10m', words: '10 minutes' }, (NET-192 PR 4)
		'6h': { interval: '10m', words: '10 minutes' },
		'24h': { interval: '15m', words: '15 minutes' },
		'7d': { interval: '1h', words: 'hour' },
		// 120 buckets, near 7 d's 168; not yet timed on the G11 (NET-192 PR 4)
		'30d': { interval: '6h', words: '6 hours' },
	};

	const RETRY_HINT = 'Check that NetTap is running on the System page, then try again.';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// OLD CODE: let selectedTimeRange = $state('24h'); (NET-195: Settings › Display's default, read where the range starts)
	let selectedTimeRange = $state<string>(startRange('24h'));
	let loading = $state(true);
	// OLD CODE START — PLAN §5.5: a range change during the first load now starts a new, guarded load
	// let initialized = $state(false);
	// OLD CODE END

	// Data
	// OLD CODE START — #96: zeros before (or without) a successful load read as "0 queries"
	// let stats = $state<DnsStats>({ total_queries: 0, unique_domains: 0, nxdomain_count: 0, avg_resolution_ms: 0 });
	// OLD CODE END
	let stats = $state<DnsStats | null>(null);
	// #96: a failed section keeps its last good data and says so; it never reads as "none"
	let statsFailed = $state(false);
	let domainsFailed = $state(false);
	let nxFailed = $state(false);
	let typesFailed = $state(false);
	let timelineFailed = $state(false);
	let deviceDnsFailed = $state(false);
	let topDomains = $state<TopDomain[]>([]);
	let nxdomains = $state<NxdomainEntry[]>([]);
	let queryTypes = $state<QueryTypeEntry[]>([]);
	let timeline = $state<TimelineEntry[]>([]);
	let suspicious = $state<SuspiciousEntry[]>([]);
	// #96: a failed check must not read as "none detected"; a long list shows its first rows
	let suspiciousFailed = $state(false);
	// NET-238: false when the name scan stopped at its cap, so the list may be missing some
	let suspiciousComplete = $state(true);
	let showAllSuspicious = $state(false);
	const SUSPICIOUS_SHOWN = 50;

	// Per-device
	let deviceIpInput = $state('');
	let selectedDeviceIp = $state('');
	let deviceDns = $state<DeviceDnsEntry[]>([]);
	let deviceLoading = $state(false);
	// Only the newest lookup writes the table, so a slower answer for the last range never wins (I13)
	let deviceLookupSeq = 0;
	/** The daemon lists at most this many domains per device (its terms size). */
	const DEVICE_DOMAIN_CAP = 200;

	// Interaction state
	let selectedDomain = $state<string | null>(null);
	let domainSearch = $state('');
	// OLD CODE START — the hand-drawn bar chart's hover; AreaChart handles its own
	// let hoveredBarIndex = $state<number | null>(null);
	// OLD CODE END

	// OLD CODE START — DataTable sorts Top Domains and NXDOMAIN (every column, utils/table-sort)
	// // Sorting — Top Domains
	// type DomainSortKey = 'domain' | 'count' | 'unique_clients';
	// let domainSortKey = $state<DomainSortKey>('count');
	// let domainSortDir = $state<'asc' | 'desc'>('desc');
	//
	// // Sorting — NXDOMAIN
	// // OLD CODE START — Clients and Types couldn't be sorted (design system: every column sorts)
	// // type NxSortKey = 'domain' | 'count';
	// // type DeviceSortKey = 'domain' | 'count';
	// // OLD CODE END
	// type NxSortKey = 'domain' | 'count' | 'clients';
	// let nxSortKey = $state<NxSortKey>('count');
	// let nxSortDir = $state<'asc' | 'desc'>('desc');
	// OLD CODE END

	// Sorting — Device DNS (sorted here, then cut to its first 50, so DataTable reports the sort)
	type DeviceSortKey = 'domain' | 'count' | 'types';
	let deviceSortKey = $state<DeviceSortKey>('count');
	let deviceSortDir = $state<'asc' | 'desc'>('desc');

	// OLD CODE START — AreaChart measures its own width
	// // Chart dimensions
	// let chartWidth = $state(800);
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	// OLD CODE START — DataTable sorts the rows; the page only filters them now
	// let filteredDomains = $derived(
	// 	(() => {
	// 		let list = [...topDomains];
	// 		if (domainSearch) {
	// 			const q = domainSearch.toLowerCase();
	// 			list = list.filter((d) => d.domain.toLowerCase().includes(q));
	// 		}
	// 		const key = domainSortKey;
	// 		list.sort((a, b) => {
	// 			const cmp = key === 'domain'
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// ? a.domain.localeCompare(b.domain)
	// 				// OLD CODE END
	// 				? compareValues(a.domain, b.domain)
	// 				: (a[key] as number) - (b[key] as number);
	// 			return domainSortDir === 'asc' ? cmp : -cmp;
	// 		});
	// 		return list;
	// 	})()
	// );
	//
	// let sortedNxdomains = $derived(
	// 	(() => {
	// 		const list = [...nxdomains];
	// 		list.sort((a, b) => {
	// 			const cmp = nxSortKey === 'domain'
	// 				// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
	// 				// ? a.domain.localeCompare(b.domain)
	// 				// OLD CODE END
	// 				? compareValues(a.domain, b.domain)
	// 				: nxSortKey === 'clients'
	// 					? a.clients.length - b.clients.length
	// 					: a.count - b.count;
	// 			return nxSortDir === 'asc' ? cmp : -cmp;
	// 		});
	// 		return list;
	// 	})()
	// );
	// OLD CODE END
	let filteredDomains = $derived(
		domainSearch ? topDomains.filter((d) => d.domain.toLowerCase().includes(domainSearch.toLowerCase())) : topDomains
	);

	function typesOf(entry: { query_types: { type: string }[] }): string {
		return entry.query_types.map((t) => t.type).join(', ');
	}

	let sortedDeviceDns = $derived(
		(() => {
			const list = [...deviceDns];
			list.sort((a, b) => {
				const cmp = deviceSortKey === 'domain'
					// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
					// ? a.domain.localeCompare(b.domain)
					// OLD CODE END
					? compareValues(a.domain, b.domain)
					: deviceSortKey === 'types'
						? compareValues(typesOf(a), typesOf(b))
						: a.count - b.count;
				return deviceSortDir === 'asc' ? cmp : -cmp;
			});
			return list;
		})()
	);

	// OLD CODE START — the hand-drawn bar chart's scale; AreaChart fits its own axis
	// let maxTimelineCount = $derived(Math.max(1, ...timeline.map((t) => t.count)));
	// OLD CODE END

	let totalQueryTypeCount = $derived(queryTypes.reduce((sum, qt) => sum + qt.count, 0));

	const rangeWords = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange)?.words ?? 'last 24 hours');
	const busiest = $derived(timeline.reduce((best, t, i) => (t.count > (timeline[best]?.count ?? -1) ? i : best), -1));

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(rangeValue: string = selectedTimeRange): { from: string; to: string } {
		// OLD CODE START — NET-196: the shared list's hours and rangeWindow, not milliseconds
		// const now = new Date();
		// const range = TIME_RANGES.find((r) => r.value === rangeValue);
		// const ms = range?.ms ?? 24 * 60 * 60 * 1000;
		// return {
		// 	from: new Date(now.getTime() - ms).toISOString(),
		// 	to: now.toISOString(),
		// };
		// OLD CODE END
		return rangeWindow(TIME_RANGES.find((r) => r.value === rangeValue)?.hours ?? 24);
	}

	// OLD CODE START — one compact format for the app (NET-192 PR 4): formatCompactNumber in $lib/api/logs
	// function formatNumber(n: number): string {
	// 	if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
	// 	if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
	// 	return n.toString();
	// }
	// OLD CODE END

	// OLD CODE START — the browser's locale ("07:00 PM"), and only the time of day at 7 d (NET-192 PR 4: chartTime)
	// function formatTimestamp(ts: string): string {
	// 	try {
	// 		const d = new Date(ts);
	// 		return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	// 	} catch {
	// 		return ts;
	// 	}
	// }
	// OLD CODE END
	// OLD CODE: const rangeHours = $derived((TIME_RANGES.find((r) => r.value === selectedTimeRange)?.ms ?? 86_400_000) / 3_600_000); (NET-196: the list has hours)
	const rangeHours = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange)?.hours ?? 24);
	const formatTimestamp = (ts: string) => chartTime(ts, rangeHours);

	// OLD CODE START — DataTable draws the sort chevrons
	// function sortIndicator(active: boolean, dir: 'asc' | 'desc'): string {
	// 	return active ? (dir === 'asc' ? ' ↑' : ' ↓') : '';
	// }
	// OLD CODE END

	function typeLabel(type: string): string {
		const words = type.replace(/_/g, ' ');
		return words.charAt(0).toUpperCase() + words.slice(1);
	}

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN §5.5: the page refresh contract (load guard and a result for the top bar)
	// async function fetchAll() {
	// 	loading = true;
	// 	const { from, to } = getTimeRange();
	// 	const interval = selectedTimeRange === '15m' ? '1m' : selectedTimeRange === '1h' ? '5m' : selectedTimeRange === '4h' ? '10m' : selectedTimeRange === '7d' ? '1h' : '15m';
	//
	// 	const results = await Promise.allSettled([
	// 		getDnsStats({ from, to }),
	// 		getTopDomains({ from, to, limit: 50 }),
	// 		getNxdomains({ from, to }),
	// 		getQueryTypes({ from, to }),
	// 		getDnsTimeline({ from, to, interval }),
	// 		getSuspiciousDns({ from, to }),
	// 	]);
	//
	// 	if (results[0].status === 'fulfilled') stats = results[0].value;
	// 	if (results[1].status === 'fulfilled') topDomains = results[1].value.domains;
	// 	if (results[2].status === 'fulfilled') nxdomains = results[2].value.nxdomains;
	// 	if (results[3].status === 'fulfilled') queryTypes = results[3].value.types;
	// 	if (results[4].status === 'fulfilled') timeline = results[4].value.series;
	// 	if (results[5].status === 'fulfilled') suspicious = results[5].value.suspicious;
	// 	suspiciousFailed = results[5].status === 'rejected';
	// 	statsFailed = results[0].status === 'rejected';
	// 	domainsFailed = results[1].status === 'rejected';
	// 	nxFailed = results[2].status === 'rejected';
	// 	typesFailed = results[3].status === 'rejected';
	// 	timelineFailed = results[4].status === 'rejected';
	//
	// 	loading = false;
	// }
	// OLD CODE END
	/** NET-225 (DNS-1): post-NAT, the router's address is every IPv4 lookup's source */
	const BRIDGE_DNS =
		"In inline bridge mode, lookups over IPv4 carry your router's address, so they can't be tied to a device, and lookups your router answers from its own cache never reach NetTap.";

	const refresh = registerPageRefresh(fetchAll);
	onDestroy(refresh.unregister);

	async function fetchAll(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// NET-225: the bridge-mode notice; asks again if the startup request failed, never blocks the figures
		void initCaptureMode();
		const range = selectedTimeRange;
		const { from, to } = getTimeRange(range);
		const interval = INTERVALS[range]?.interval ?? '15m';
		loading = true;

		const results = await Promise.allSettled([
			getDnsStats({ from, to }),
			getTopDomains({ from, to, limit: 50 }),
			getNxdomains({ from, to }),
			getQueryTypes({ from, to }),
			getDnsTimeline({ from, to, interval }),
			getSuspiciousDns({ from, to }),
		]);
		if (!guard.current(g)) return 'skipped';

		if (results[0].status === 'fulfilled') stats = results[0].value;
		if (results[1].status === 'fulfilled') topDomains = results[1].value.domains;
		if (results[2].status === 'fulfilled') nxdomains = results[2].value.nxdomains;
		if (results[3].status === 'fulfilled') queryTypes = results[3].value.types;
		if (results[4].status === 'fulfilled') timeline = results[4].value.series;
		// OLD CODE: if (results[5].status === 'fulfilled') suspicious = results[5].value.suspicious; (NET-238: and complete)
		if (results[5].status === 'fulfilled') {
			suspicious = results[5].value.suspicious;
			suspiciousComplete = results[5].value.complete;
		}
		suspiciousFailed = results[5].status === 'rejected';
		statsFailed = results[0].status === 'rejected';
		domainsFailed = results[1].status === 'rejected';
		nxFailed = results[2].status === 'rejected';
		typesFailed = results[3].status === 'rejected';
		timelineFailed = results[4].status === 'rejected';

		loading = false;
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const ok = results.filter((r) => r.status === 'fulfilled').length;
		// return ok === results.length ? 'ok' : ok === 0 ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(results);
	}

	// OLD CODE START — I13: no guard, so the last range's slower answer could overwrite this range's
	// async function lookupDevice() {
	// 	const ip = deviceIpInput.trim() || selectedDeviceIp;
	// 	if (!ip) return;
	//
	// 	deviceLoading = true;
	// 	selectedDeviceIp = ip;
	// 	const { from, to } = getTimeRange();
	//
	// 	try {
	// 		const result = await getDeviceDns(ip, { from, to });
	// 		deviceDns = result.domains;
	// 		deviceDnsFailed = false;
	// 	} catch {
	// 		deviceDns = [];
	// 		deviceDnsFailed = true;
	// 	} finally {
	// 		deviceLoading = false;
	// 	}
	// }
	// OLD CODE END
	async function lookupDevice() {
		const ip = deviceIpInput.trim() || selectedDeviceIp;
		if (!ip) return;

		const seq = ++deviceLookupSeq;
		deviceLoading = true;
		selectedDeviceIp = ip;
		const { from, to } = getTimeRange();

		try {
			const result = await getDeviceDns(ip, { from, to });
			if (seq !== deviceLookupSeq) return;
			deviceDns = result.domains;
			deviceDnsFailed = false;
		} catch {
			if (seq !== deviceLookupSeq) return;
			deviceDns = [];
			deviceDnsFailed = true;
		} finally {
			if (seq === deviceLookupSeq) deviceLoading = false;
		}
	}

	// ---------------------------------------------------------------------------
	// Interaction handlers
	// ---------------------------------------------------------------------------

	function selectDomain(domain: string) {
		selectedDomain = selectedDomain === domain ? null : domain;
	}

	function selectDeviceIp(ip: string) {
		deviceIpInput = ip;
		selectedDeviceIp = ip;
		lookupDevice();
		setTimeout(() => {
			document.getElementById('device-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}, 50);
	}

	// OLD CODE START — DataTable owns the header toggles; the device table reports its sort below
	// function toggleDomainSort(key: DomainSortKey) {
	// 	if (domainSortKey === key) {
	// 		domainSortDir = domainSortDir === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		domainSortKey = key;
	// 		domainSortDir = key === 'domain' ? 'asc' : 'desc';
	// 	}
	// }
	//
	// function toggleNxSort(key: NxSortKey) {
	// 	if (nxSortKey === key) {
	// 		nxSortDir = nxSortDir === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		nxSortKey = key;
	// 		nxSortDir = key === 'domain' ? 'asc' : 'desc';
	// 	}
	// }
	//
	// function toggleDeviceSort(key: DeviceSortKey) {
	// 	if (deviceSortKey === key) {
	// 		deviceSortDir = deviceSortDir === 'asc' ? 'desc' : 'asc';
	// 	} else {
	// 		deviceSortKey = key;
	// 		deviceSortDir = key === 'domain' ? 'asc' : 'desc';
	// 	}
	// }
	// OLD CODE END
	function setDeviceSort(key: string, dir: SortDir) {
		deviceSortKey = key as DeviceSortKey;
		deviceSortDir = dir;
	}

	function handleTimeRangeChange(value: string) {
		selectedTimeRange = value;
		// #96: the last range's figures must not stand in for this range if its load fails
		stats = null;
		topDomains = [];
		nxdomains = [];
		queryTypes = [];
		timeline = [];
		suspicious = [];
		suspiciousComplete = true;
		// I13: the device table kept the last range's domains under this range's label
		deviceDns = [];
		if (selectedDeviceIp) lookupDevice();
		// OLD CODE START — PLAN §5.5: the guard drops the older range's load, so always reload
		// if (initialized) fetchAll();
		// OLD CODE END
		refresh.run();
	}

	function copyDomain(domain: string) {
		navigator.clipboard.writeText(domain);
	}

	// ---------------------------------------------------------------------------
	// Tables
	// ---------------------------------------------------------------------------

	const domainColumns: Column<TopDomain>[] = [
		{ key: 'domain', label: 'Domain', class: 'mono' },
		{ key: 'count', label: 'Queries', numeric: true, cell: countCell },
		{ key: 'unique_clients', label: 'Clients', numeric: true },
		// Every column sorts (repo rule); this one by domain
		{ key: 'copy', label: 'Actions', sortValue: (d) => d.domain, cell: copyCell },
	];

	const nxColumns: Column<NxdomainEntry>[] = [
		{ key: 'domain', label: 'Domain', class: 'mono' },
		{ key: 'count', label: 'Count', numeric: true, cell: countCell },
		{ key: 'clients', label: 'Clients', sortValue: (nx) => nx.clients.length, cell: clientsCell },
	];

	const deviceColumns: Column<DeviceDnsEntry>[] = [
		{ key: 'domain', label: 'Domain', class: 'mono' },
		{ key: 'count', label: 'Queries', numeric: true, cell: countCell },
		{ key: 'types', label: 'Types', class: 'mono', cell: typesCell },
	];

	interface Section {
		/** What the request loads, as loadFailed() words it. */
		what: string;
		failed: boolean;
		has: boolean;
		emptyTitle: string;
		emptyMessage?: string;
	}

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		// Apply query params from URL
		const urlDomain = $page.url.searchParams.get('domain') || '';
		const urlType = $page.url.searchParams.get('type') || '';
		if (urlDomain) {
			domainSearch = urlDomain;
		}
		if (urlType) {
			// urlType can pre-filter; stored for potential future use
			domainSearch = domainSearch || urlType;
		}

		// OLD CODE START — PLAN §5.5: every load goes through the page refresh contract
		// fetchAll().then(() => {
		// 	initialized = true;
		// });
		// OLD CODE END
		refresh.run();
	});
</script>

{#snippet countCell(row: { count: number })}{fmt(row.count)}{/snippet}
{#snippet typesCell(entry: DeviceDnsEntry)}{typesOf(entry)}{/snippet}
{#snippet copyCell(d: TopDomain)}
	<button class="link" type="button" aria-label="Copy {d.domain}" onclick={() => copyDomain(d.domain)}>Copy</button>
{/snippet}
{#snippet clientsCell(nx: NxdomainEntry)}
	{#each nx.clients.slice(0, 3) as ip, j (ip)}
		{#if j > 0}<span class="dim">, </span>{/if}
		<button class="link mono" type="button" onclick={() => selectDeviceIp(ip)}>{ip}</button>
	{/each}
	{#if nx.clients.length > 3}
		<span class="dim"> +{nx.clients.length - 3}</span>
	{/if}
{/snippet}

{#snippet timelineBody()}
	<AreaChart
		series={[{ key: 'queries', label: 'Queries', colour: 1, points: timeline.map((t) => ({ t: t.timestamp, v: t.count })) }]}
		formatX={(t) => formatTimestamp(String(t))}
		formatY={formatNumber}
		formatTip={(i) => `${formatTimestamp(timeline[i]?.timestamp ?? '')} · ${fmt(timeline[i]?.count ?? 0)} queries`}
		highlightIndex={busiest}
		ariaLabel={busiest >= 0
			? `Busiest at ${formatTimestamp(timeline[busiest].timestamp)}, with ${fmt(timeline[busiest].count)} queries`
			: 'DNS queries over time'}
	/>
{/snippet}
{#snippet topBody()}
	<BarList
		items={topDomains.slice(0, 10).map((d) => ({
			key: d.domain,
			label: d.domain,
			value: d.count,
			display: fmt(d.count),
			detail: `${d.unique_clients} clients`,
			onclick: () => selectDomain(d.domain),
		}))}
	/>
{/snippet}
{#snippet domainsBody()}
	<div class="toolbar">
		<SearchField id="dns-domain-filter" label="Filter domains" placeholder="Filter domains…" size="toolbar" bind:value={domainSearch} />
	</div>
	<DataTable
		columns={domainColumns}
		rows={filteredDomains}
		ariaLabel="Domains"
		rowKey={(d) => d.domain}
		initialSort={{ key: 'count', dir: 'desc' }}
		onrowactivate={(d) => selectDomain(d.domain)}
		rowLabel={(d) => `Select ${d.domain}`}
		selectedKey={selectedDomain ?? undefined}
	>
		{#snippet empty()}<p class="dim">No domains match “{domainSearch}”.</p>{/snippet}
	</DataTable>
{/snippet}
{#snippet typesBody()}
	<BarList
		items={queryTypes.map((qt) => ({
			key: qt.type,
			label: qt.type,
			value: qt.count,
			display: fmt(qt.count),
			detail: `${(totalQueryTypeCount > 0 ? (qt.count / totalQueryTypeCount) * 100 : 0).toFixed(1)}%`,
		}))}
	/>
{/snippet}
{#snippet nxBody()}
	<DataTable
		columns={nxColumns}
		rows={nxdomains}
		ariaLabel="NXDOMAIN errors"
		rowKey={(nx) => nx.domain}
		initialSort={{ key: 'count', dir: 'desc' }}
		onrowactivate={(nx) => selectDomain(nx.domain)}
		rowLabel={(nx) => `Select ${nx.domain}`}
		selectedKey={selectedDomain ?? undefined}
	/>
{/snippet}

<!-- One card body: its data (with a note when a refresh failed), or its loading, error or empty state -->
{#snippet section(s: Section, body: Snippet)}
	{#if s.has}
		{#if s.failed && !loading}
			<p class="notice is-warn stale" role="status"><Icon name="warn" />{loadFailed(s.what, true)}</p>
		{/if}
		{@render body()}
	{:else if loading}
		<CardState state="loading" title="Loading {s.what}" />
	{:else if s.failed}
		<CardState state="error" title={loadFailed(s.what)} message={RETRY_HINT} onaction={() => refresh.run()} />
	{:else}
		<CardState state="empty" icon="dns" title={s.emptyTitle} message={s.emptyMessage} />
	{/if}
{/snippet}

<svelte:head>
	<title>DNS Analytics - NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">DNS analytics</h1>
		<p class="page-sub">Domain queries, NXDOMAIN errors, and suspicious patterns</p>
	</div>
	<div class="head-actions">
		<Pills
			options={TIME_RANGES}
			value={selectedTimeRange}
			onchange={handleTimeRangeChange}
			ariaLabel="Time range"
		/>
	</div>
</div>

<p class="notice" role="note"><Icon name="dns" /><span>{ENCRYPTED_DNS_NOTE}{$captureMode === 'bridge' ? ` ${BRIDGE_DNS}` : ''}</span></p>

<div class="grid">
	{#if statsFailed}
		<p class="notice is-warn c-12" role="status"><Icon name="warn" />{loadFailed('DNS totals', stats !== null)}</p>
	{/if}
	<!-- OLD CODE START — #96: stats now start null (not loaded) instead of zeros
	<span class="stat-value">{formatNumber(stats.total_queries)}</span>
	<span class="stat-value">{formatNumber(stats.unique_domains)}</span>
	<span class="stat-value" class:text-warning={stats.nxdomain_count > 0}>{formatNumber(stats.nxdomain_count)}</span>
	<span class="stat-value">{stats.avg_resolution_ms.toFixed(1)}<span class="stat-unit">ms</span></span>
	OLD CODE END -->
	<KpiCard class="c-3" label="Total queries" icon="dns" value={stats ? formatNumber(stats.total_queries) : '—'} note={rangeWords} />
	<KpiCard class="c-3" label="Unique domains" icon="dns" value={stats ? formatNumber(stats.unique_domains) : '—'} note={rangeWords} />
	<KpiCard
		class="c-3"
		label="NXDOMAIN errors"
		icon="warn"
		value={stats ? formatNumber(stats.nxdomain_count) : '—'}
		note="Lookups for names that don't exist"
		href="#nxdomain-section"
	/>
	<!-- OLD CODE START — NET-225 (DNS-3): the mean, which a few 20 s retries skew (G11: mean 19.6 ms, median 6.3 ms)
	<KpiCard
		class="c-3"
		label="Average resolution"
		icon="changelog"
		value={stats ? stats.avg_resolution_ms.toFixed(1) : '—'}
		unit={stats ? 'ms' : undefined}
		note={rangeWords}
	/>
	OLD CODE END -->
	<KpiCard
		class="c-3"
		label="Median resolution"
		icon="changelog"
		value={stats?.median_resolution_ms != null ? stats.median_resolution_ms.toFixed(1) : '—'}
		unit={stats?.median_resolution_ms != null ? 'ms' : undefined}
		note={rangeWords}
		sub={!stats
			? undefined
			: stats.median_resolution_ms == null
				? 'No answered lookups to time'
				: stats.avg_resolution_ms != null
					? `Mean ${stats.avg_resolution_ms.toFixed(1)} ms`
					: undefined}
	/>

	<Card
		title="Queries over time"
		sub="Queries per {INTERVALS[selectedTimeRange]?.words ?? '15 minutes'} · {rangeWords}"
		hero
		col
		class="c-8"
	>
		{@render section(
			{ what: 'the query timeline', failed: timelineFailed, has: timeline.length > 0, emptyTitle: 'No timeline data available for this time range.', emptyMessage: 'Queries appear here once Zeek sees DNS traffic.' },
			timelineBody,
		)}
	</Card>

	<Card title="Most looked-up domains" sub="Queries per domain · {rangeWords}" class="c-4">
		{@render section(
			{ what: 'the most looked-up domains', failed: domainsFailed, has: topDomains.length > 0, emptyTitle: 'No domains recorded.', emptyMessage: 'Check that Zeek is capturing DNS traffic.' },
			topBody,
		)}
	</Card>

	<Card title="Domains" sub="Queries and clients per domain · {rangeWords} · top 50" class="c-8">
		{@render section(
			{ what: 'top domains', failed: domainsFailed, has: topDomains.length > 0, emptyTitle: 'No domains recorded.', emptyMessage: 'Check that Zeek is capturing DNS traffic.' },
			domainsBody,
		)}
	</Card>

	<Card title="Query types" sub="Share of queries by record type · {rangeWords}" class="c-4">
		{@render section(
			{ what: 'query types', failed: typesFailed, has: queryTypes.length > 0, emptyTitle: 'No query type data available.', emptyMessage: 'Record types appear once Zeek sees DNS traffic.' },
			typesBody,
		)}
	</Card>

	<Card title="DNS by device" sub="Domains one device looked up · {rangeWords}" class="c-12">
		<span id="device-section" class="anchor"></span>
		{#if selectedDomain}
			<div class="chips selected">
				<span class="chip">Selected domain: <span class="mono">{selectedDomain}</span></span>
				<!-- NET-160: the domain tables open this selection on their row, so the domain page link lives here -->
				<a class="link" href={domainHref(selectedDomain)}>Open domain page</a>
				<button class="link" type="button" onclick={() => copyDomain(selectedDomain ?? '')}>Copy</button>
				<button class="link" type="button" onclick={() => (selectedDomain = null)}>Clear</button>
			</div>
		{/if}
		<div class="toolbar">
			<label class="sr-only" for="dns-device-ip">Device IP</label>
			<input
				id="dns-device-ip"
				type="text"
				class="input mono device-ip"
				placeholder="Enter device IP (e.g. 192.168.1.100)"
				bind:value={deviceIpInput}
				onkeydown={(e) => e.key === 'Enter' && lookupDevice()}
			/>
			<button class="btn primary" type="button" onclick={lookupDevice} disabled={deviceLoading}>
				{deviceLoading ? 'Looking up…' : 'Lookup'}
			</button>
		</div>
		{#if !selectedDeviceIp}
			<CardState state="empty" icon="devices" title="No device chosen" message="Enter a device IP, or pick a client from the NXDOMAIN errors, to see the domains it looked up." />
		{:else if deviceLoading}
			<CardState state="loading" title="Loading DNS data for {selectedDeviceIp}" />
		{:else if deviceDnsFailed}
			<CardState state="error" title={loadFailed(`DNS records for ${selectedDeviceIp}`)} message={RETRY_HINT} onaction={lookupDevice} />
		{:else if deviceDns.length === 0}
			<!-- OLD CODE: message="This device made no DNS queries in this time range." (NET-225: DoH, DoT and, in bridge mode, NAT hide lookups) -->
			<CardState
				state="empty"
				icon="dns"
				title="No DNS records for {selectedDeviceIp}"
				message="NetTap saw no plain DNS lookups from this address in this time range. Lookups over DoH or DoT are encrypted and never show here.{$captureMode === 'bridge' ? ` ${BRIDGE_DNS}` : ''}"
			/>
		{:else}
			<DataTable
				columns={deviceColumns}
				rows={sortedDeviceDns.slice(0, 50)}
				ariaLabel="DNS queries from {selectedDeviceIp}"
				rowKey={(e) => e.domain}
				initialSort={{ key: deviceSortKey, dir: deviceSortDir }}
				onsortchange={setDeviceSort}
				onrowactivate={(e) => selectDomain(e.domain)}
				rowLabel={(e) => `Select ${e.domain}`}
				selectedKey={selectedDomain ?? undefined}
			/>
			<!-- OLD CODE START — I13: at the daemon's 200 cap, "of 200" read as the device's total
			{#if deviceDns.length > 50}
				<p class="tbl-foot">Showing 50 of {deviceDns.length} domains</p>
			{/if}
			OLD CODE END -->
			{#if deviceDns.length > 50}
				<p class="tbl-foot">
					{deviceDns.length >= DEVICE_DOMAIN_CAP
						? `Showing 50 of the ${DEVICE_DOMAIN_CAP} most looked-up domains`
						: `Showing 50 of ${deviceDns.length} domains`}
				</p>
			{/if}
		{/if}
	</Card>

	<Card title="NXDOMAIN errors" sub="Lookups for names that don't exist · {rangeWords}" class="c-6">
		<span id="nxdomain-section" class="anchor"></span>
		<!-- OLD CODE: emptyMessage: "That's a good sign." (NET-225: encrypted lookups aren't checked at all) -->
		{@render section(
			{ what: 'NXDOMAIN errors', failed: nxFailed, has: nxdomains.length > 0, emptyTitle: 'No NXDOMAIN errors detected.', emptyMessage: 'Only plain DNS lookups are checked.' },
			nxBody,
		)}
	</Card>

	<Card title="Suspicious DNS patterns" sub="Possible beaconing, tunnelling and generated names · {rangeWords}" class="c-6">
		<!-- OLD CODE START — #96: a failed check showed "No suspicious DNS patterns detected"
		{#if suspicious.length === 0 && !loading}
		OLD CODE END -->
		{#if !suspiciousComplete && !suspiciousFailed}
			<p class="notice is-warn capped" role="status">
				<Icon name="warn" /><span
					>Stopped after checking the first {fmt(SCAN_CAP)} query names, in name order, not the busiest; more exist, so this list may be missing some.</span
				>
			</p>
		{/if}
		{#if suspiciousFailed && !loading}
			<CardState state="error" title="Couldn't check for suspicious DNS patterns: the request failed." message={RETRY_HINT} onaction={() => refresh.run()} />
		{:else if suspicious.length === 0 && loading}
			<CardState state="loading" title="Loading suspicious DNS patterns" />
		{:else if suspicious.length === 0}
			<CardState state="empty" icon="check" title="No suspicious DNS patterns detected." message="NetTap checks for beaconing, very long names and heavy TXT use." />
		{:else}
			<ul class="findings">
				{#each showAllSuspicious ? suspicious : suspicious.slice(0, SUSPICIOUS_SHOWN) as s}
					<li class="finding">
						<div class="finding-top">
							{#if isLevel(s.severity)}<SeverityPill level={s.severity} />{:else}<span class="chip">{s.severity}</span>{/if}
							<b>{typeLabel(s.type)}</b>
						</div>
						<button class="link mono finding-domain" type="button" onclick={() => selectDomain(s.domain)}>{s.domain}</button>
						<p class="finding-desc">{s.description}</p>
						<p class="dim num finding-meta">
							{fmt(s.count)} queries{#if s.unique_clients} · {s.unique_clients} client(s){/if}{#if s.length} · {s.length} chars{/if}
						</p>
					</li>
				{/each}
			</ul>
			{#if suspicious.length > SUSPICIOUS_SHOWN}
				<div class="tbl-foot">
					<span>Showing {partOfWhole(showAllSuspicious ? suspicious.length : SUSPICIOUS_SHOWN, suspicious.length)}</span>
					<button class="btn" type="button" onclick={() => (showAllSuspicious = !showAllSuspicious)}>
						{showAllSuspicious ? 'Show fewer' : `Show all ${suspicious.length.toLocaleString('en-US')}`}
					</button>
				</div>
			{/if}
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	/* An in-card anchor for the KPI links; the margin keeps the card head in view */
	.anchor { display: block; scroll-margin-top: calc(var(--sp-8) * 3); }
	/* OLD CODE: .stale { margin-bottom: var(--sp-3); } (NET-238: the capped-scan notice too) */
	.stale, .capped { margin-bottom: var(--sp-3); }
	.selected { align-items: center; margin-bottom: var(--sp-3); }
	.device-ip { flex: 0 1 20rem; }
	.findings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
	.finding { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-1); padding: var(--sp-3) 0; min-width: 0; }
	.finding + .finding { border-top: 1px solid var(--line); }
	.finding-top { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--text-sm); }
	.finding-domain { white-space: normal; overflow-wrap: anywhere; text-align: left; }
	.finding-desc { color: var(--text-2); font-size: var(--text-sm); }
	.finding-meta { font-size: var(--text-xs); }
	button.link { background: none; border: 0; padding: 0; cursor: pointer; }
</style>
