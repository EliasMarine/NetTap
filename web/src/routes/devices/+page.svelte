<script lang="ts">
	/**
	 * Devices: every device NetTap sees on the network.
	 *
	 * - By type: Home's device cards (moved here, PLAN.md §3): the registry, one card per MAC,
	 *   with each card's traffic from the device list, grouped by device type. Mirror mode only,
	 *   as on Home.
	 * - All devices: the IP-keyed device list as a sortable table, with type filter and search.
	 *
	 * NET-160 slice 2b-3: the page reads its window from the URL (`range`, or an exact `from`/`to`
	 * shown as Custom), so Home's Devices card opens the devices it counted. One list reply answers
	 * the table, Total devices and Online now.
	 */

	import { onDestroy, onMount, untrack } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	// OLD CODE START — NET-160 slice 2b-3: Total devices and Online now came from separate count requests
	// import { getDevices, getDeviceCount } from '$api/devices';
	// OLD CODE END
	import { getDevices } from '$api/devices';
	import type { Device, DeviceListResponse } from '$api/devices';
	import { countDifference, customRange, DRILL_RANGES, fmt, linkedCount, rangeWindow, startRange, type LinkedCount } from '$lib/utils/drilldown';
	import { getNewDeviceCount, getRegistryDevices, isNewDevice } from '$api/devices-registry';
	import type { RegistryDevice, RegistryListResponse } from '$api/devices-registry';
	import { BRIDGE_NO_DEVICES, getCaptureMode } from '$api/capture';
	import type { CaptureMode } from '$api/capture';
	import { loadFailed } from '$lib/utils/load-failed';
	import { formatBytes, formatCompactNumber as formatNumber } from '$lib/api/logs';
	import { withTraffic } from '$lib/utils/registry-traffic';
	import { likelyType, osBasis, typeBasis } from '$lib/utils/device-guess';
	import { ipv6ListNotes } from '$lib/utils/ipv6-coverage';
	import { registerPageRefresh, outcome, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import NewDeviceBanner from '$components/NewDeviceBanner.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	// OLD CODE: import DeviceTile from '$lib/components/ui/DeviceTile.svelte'; (NET-201: only the Cards layout used it)
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import AutoRefreshButton from '$lib/components/ui/AutoRefreshButton.svelte';
	import { deviceIcon } from '$lib/components/ui/device-icon';
	import { groupByType } from './device-types';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let loading = $state(true);
	// OLD CODE START — NET-160 slice 2b-3: the list, its total and the online count were separate
	// states from separate requests, so a list and a total from different readings could show together
	// let devices = $state<Device[]>([]);
	// // the list's range start, once it has loaded (Home's deviceListFrom, for the card merge)
	// let listFrom = $state<string | null>(null);
	// // the list stops at LIST_LIMIT rows; Total Devices is the exact count, '—' until one loads
	// let deviceCount = $state<number | null>(null);
	// let deviceCountFailed = $state(false);
	// // exact counts, not filters of the busiest-N list: '—' until loaded, a note if they fail
	// let onlineCount = $state<number | null>(null);
	// let onlineFailed = $state(false);
	// OLD CODE END
	/**
	 * One reading of the device list: its rows, the devices before the cut, the online count and
	 * the daemon clock it was counted by, with the window it answers and that window's words.
	 * Replaced whole on success; a failed refresh of the same window keeps it; a window change clears it.
	 */
	interface Reading {
		devices: Device[];
		total: number;
		online_total: number;
		online_since: string;
		as_of: string;
		from: string;
		to: string;
		words: string;
	}
	let loaded = $state.raw<Reading | null>(null);
	/** The window of the reading on screen (not reactive: only the loader reads it) */
	let loadedWindow = '';
	const devices = $derived(loaded?.devices ?? []);
	// the list stops at LIST_LIMIT rows; Total devices is the reading's total, '—' until one loads
	const deviceCount = $derived(loaded?.total ?? null);
	// #96: a failed load keeps the last list and says so; it never reads as "No devices seen yet"
	let devicesFailed = $state(false);
	// exact counts, not filters of the busiest-N list: '—' until loaded, a note if they fail
	let newCount = $state<number | null>(null);
	let newFailed = $state(false);
	const LIST_LIMIT = 500; // the daemon's largest device list
	const HOUR = 60 * 60 * 1000;
	const DAY = 24 * HOUR;
	// OLD CODE START — NET-160 slice 2b-3: the table's status now reads the reading's online_since and as_of
	// // the table's Online rule and the "Online now" count's (NET-158)
	// const ONLINE_MS = 5 * 60 * 1000;
	// OLD CODE END

	// The window: Home's five ranges (anything else is the saved default, else 24 hours), or the exact from/to a link brought (Custom)
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES)
	// const RANGES = [
	// 	{ value: '1h', label: '1h', hours: 1, words: 'last hour' },
	// 	{ value: '6h', label: '6h', hours: 6, words: 'last 6 hours' },
	// 	{ value: '24h', label: '24h', hours: 24, words: 'last 24 hours' },
	// 	{ value: '7d', label: '7d', hours: 168, words: 'last 7 days' },
	// 	{ value: '30d', label: '30d', hours: 720, words: 'last 30 days' },
	// ] as const;
	// OLD CODE END
	const RANGES = DRILL_RANGES;
	const params = $derived($page.url.searchParams);
	const custom = $derived(customRange(params.get('from'), params.get('to')));
	// OLD CODE: ?? RANGES[2] (NET-192 PR 4: the default by value, not by position)
	// OLD CODE: … ?? RANGES.find((r) => r.value === '24h')!); (NET-195: a link's window or range, else Settings › Display's default)
	const range = $derived(custom ?? RANGES.find((r) => r.value === params.get('range')) ?? RANGES.find((r) => r.value === startRange('24h'))!);
	const windowKey = $derived(custom ? `${custom.from}|${custom.to}` : range.value);
	/**
	 * NET-160 section D: the Total devices figure the link was clicked at (Home's Devices card).
	 * Its own key beside windowKey, never inside it: a count-only change keeps the loaded reading.
	 */
	const appliedCount = $derived(linkedCount(params.get('count')));
	/** The one comparison a counted hand-off's load makes; any other load ends it (null). */
	let linked = $state.raw<LinkedCount | null>(null);
	// compared with Total devices (loaded.total): the local search, type pills and sort never change it
	const linkedLine = $derived(
		linked?.observed == null ? null : countDifference(linked.expected, linked.observed, { lead: 'This window now has', one: 'device', many: 'devices' }),
	);
	const rangeOptions = $derived([...RANGES, ...(custom ? [custom] : [])].map(({ value, label }) => ({ value, label })));
	// the loaded figures' words, not the URL's: a slow reply can't show under another window's words
	const words = $derived(loaded?.words ?? range.words);
	const windowNote = $derived(words.charAt(0).toUpperCase() + words.slice(1));
	/** A Custom window that ended before the reading's last 5 minutes: its online count isn't "now". */
	const windowEnded = $derived(loaded !== null && Date.parse(loaded.to) < Date.parse(loaded.online_since));
	let searchQuery = $state('');
	let categoryFilter = $state('all');
	let autoRefresh = $state(false);

	// By type: Home's registry cards (mirror mode only)
	let captureMode = $state<CaptureMode | null>(null);
	let modeFailed = $state(false);
	let registryDevices = $state<RegistryDevice[]>([]);
	let registryFailed = $state(false);
	const isMirrorMode = $derived(captureMode?.mode === 'mirror');
	// NET-225: post-NAT, every device's IPv4 traffic carries the router's address
	const isBridgeMode = $derived(captureMode?.mode === 'bridge');

	// The tab the user picked; until then the URL's `view`; else By type in mirror mode, All devices otherwise
	let pickedView = $state<'type' | 'all' | null>(null);
	// OLD CODE START — NET-160 slice 2b-3: no URL view, so Home's card couldn't open All devices
	// const view = $derived(pickedView ?? (isMirrorMode ? 'type' : 'all'));
	// OLD CODE END
	const VIEWS = [
		{ value: 'type' as const, label: 'By type' },
		{ value: 'all' as const, label: 'All devices' },
	];
	const urlView = $derived(VIEWS.find((v) => v.value === params.get('view'))?.value ?? null);
	const view = $derived(pickedView ?? urlView ?? (isMirrorMode ? 'type' : 'all'));

	// OLD CODE START — NET-201: By type is the list only (the owner asked to drop the cards), so there is no layout to pick
	// // NET-180: By type as cards or compact rows, remembered per browser (a convenience, not data)
	// type Layout = 'cards' | 'list';
	// const LAYOUT_KEY = 'nettap-devices-layout';
	// const LAYOUTS = [
	// 	{ value: 'cards' as const, label: 'Cards' },
	// 	{ value: 'list' as const, label: 'List' },
	// ];
	// let layout = $state<Layout>('cards');
	//
	// /** A missing or unknown value is Cards. */
	// function readLayout(): Layout {
	// 	try {
	// 		return localStorage.getItem(LAYOUT_KEY) === 'list' ? 'list' : 'cards';
	// 	} catch {
	// 		return 'cards'; // storage blocked: the default
	// 	}
	// }
	//
	// function pickLayout(next: Layout) {
	// 	layout = next;
	// 	try {
	// 		localStorage.setItem(LAYOUT_KEY, next);
	// 	} catch {
	// 		// storage blocked: the choice lasts until the page reloads
	// 	}
	// }
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Category config
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 UI redesign: emoji icons and legacy colours; device types use the system icons
	// const CATEGORIES = [
	// 	{ key: 'all', label: 'All', icon: '' },
	// 	{ key: 'computer', label: 'Computers', icon: '\u{1F4BB}' },
	// 	{ key: 'phone', label: 'Phones', icon: '\u{1F4F1}' },
	// 	{ key: 'media', label: 'Media', icon: '\u{1F4FA}' },
	// 	{ key: 'iot', label: 'IoT', icon: '\u{1F4E1}' },
	// 	{ key: 'infrastructure', label: 'Infra', icon: '\u{1F5A7}' },
	// 	{ key: 'unknown', label: 'Unknown', icon: '\u{2753}' },
	// ];
	// const CATEGORY_COLORS: Record<string, string> = {
	// 	computer: 'var(--cyan)', phone: 'var(--green)', media: 'var(--purple)',
	// 	iot: 'var(--orange)', infrastructure: 'var(--blue)', unknown: 'var(--text-dim)',
	// };
	// const CATEGORY_ICONS: Record<string, string> = {
	// 	computer: '\u{1F4BB}', phone: '\u{1F4F1}', media: '\u{1F4FA}',
	// 	iot: '\u{1F4E1}', infrastructure: '\u{1F5A7}', unknown: '\u{2753}',
	// };
	// OLD CODE END
	const CATEGORIES = [
		{ key: 'all', label: 'All' },
		{ key: 'computer', label: 'Computers' },
		{ key: 'phone', label: 'Phones' },
		{ key: 'media', label: 'Media' },
		{ key: 'iot', label: 'IoT' },
		{ key: 'infrastructure', label: 'Infrastructure' },
		{ key: 'unknown', label: 'Unknown' },
	];
	const CATEGORY_LABELS: Record<string, string> = {
		computer: 'Computer', phone: 'Phone', media: 'Media', iot: 'IoT', infrastructure: 'Infrastructure', unknown: 'Unknown',
	};

	// ---------------------------------------------------------------------------
	// Fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-03 UI redesign: the loader goes through the page refresh contract
	// (PLAN.md §5.5) with a load guard, and also loads Home's registry cards for By type
	// async function fetchDevices() {
	// 	loading = true;
	// 	const now = Date.now();
	// 	const iso = (ms: number) => new Date(ms).toISOString();
	// 	const [listRes, countRes, onlineRes, newRes] = await Promise.allSettled([
	// 		getDevices({ sort: 'bytes', order: 'desc', limit: LIST_LIMIT }),
	// 		getDeviceCount(),
	// 		getDeviceCount({ from: iso(now - 5 * 60 * 1000), to: iso(now) }),
	// 		getNewDeviceCount(iso(now - 24 * 60 * 60 * 1000)),
	// 	]);
	// 	if (onlineRes.status === 'fulfilled') onlineCount = onlineRes.value.count;
	// 	onlineFailed = onlineRes.status === 'rejected';
	// 	if (newRes.status === 'fulfilled') newCount = newRes.value.count;
	// 	newFailed = newRes.status === 'rejected';
	// 	if (listRes.status === 'fulfilled') {
	// 		devices = listRes.value.devices;
	// 		lastUpdated = new Date().toLocaleTimeString();
	// 	}
	// 	devicesFailed = listRes.status === 'rejected';
	// 	if (countRes.status === 'fulfilled') deviceCount = countRes.value.count;
	// 	deviceCountFailed = countRes.status === 'rejected';
	// 	loading = false;
	// }
	// $effect(() => { fetchDevices(); });
	// $effect(() => {
	// 	if (autoRefreshTimer) clearInterval(autoRefreshTimer);
	// 	if (autoRefresh) {
	// 		autoRefreshTimer = setInterval(() => fetchDevices(), 30_000);
	// 	}
	// 	return () => { if (autoRefreshTimer) clearInterval(autoRefreshTimer); };
	// });
	// onDestroy(() => { if (autoRefreshTimer) clearInterval(autoRefreshTimer); });
	// OLD CODE END

	/** Home's order (routes/+page.svelte fetchAllData): the capture mode first, the registry only in mirror mode. */
	async function loadRegistry(): Promise<{
		mode: PromiseSettledResult<CaptureMode>;
		registry: PromiseSettledResult<RegistryListResponse> | null;
	}> {
		const [mode] = await Promise.allSettled([getCaptureMode()]);
		if (mode.status === 'rejected' || mode.value.mode !== 'mirror') return { mode, registry: null };
		const [registry] = await Promise.allSettled([getRegistryDevices({ limit: 200 })]);
		return { mode, registry };
	}

	// OLD CODE START — NET-160 slice 2b-3: a fixed 24 h list plus two count requests, each a separate
	// reading, written to separate states
	// async function load(guard: LoadGuard): Promise<LoadResult> {
	// 	const g = guard.begin();
	// 	// same (default 24 h) range for the list and the total: the page sends no from/to
	// 	const now = Date.now();
	// 	const iso = (ms: number) => new Date(ms).toISOString();
	// 	const [[listRes, countRes, onlineRes, newRes], { mode: modeRes, registry: registryRes }] = await Promise.all([
	// 		Promise.allSettled([
	// 			// OLD CODE START — a 200-row list; Online Now and the category pills counted only it
	// 			// getDevices({ sort: 'bytes', order: 'desc', limit: 200 }),
	// 			// OLD CODE END
	// 			getDevices({ sort: 'bytes', order: 'desc', limit: LIST_LIMIT }),
	// 			getDeviceCount(),
	// 			// OLD CODE START — NET-158: a 5-minute range needs 3 records in it, but the table
	// 			// calls a listed device Online on its newest record alone
	// 			// // devices with traffic in the last 5 minutes, by the list's own device rules
	// 			// getDeviceCount({ from: iso(now - 5 * 60 * 1000), to: iso(now) }),
	// 			// OLD CODE END
	// 			// the listed devices (same 24 h range) the table shows as Online
	// 			getDeviceCount({ active_since: iso(now - ONLINE_MS) }),
	// 			getNewDeviceCount(iso(now - DAY)),
	// 		]),
	// 		loadRegistry(),
	// 	]);
	// 	if (!guard.current(g)) return 'skipped';
	//
	// 	if (onlineRes.status === 'fulfilled') onlineCount = onlineRes.value.count;
	// 	onlineFailed = onlineRes.status === 'rejected';
	// 	if (newRes.status === 'fulfilled') newCount = newRes.value.count;
	// 	newFailed = newRes.status === 'rejected';
	// 	if (listRes.status === 'fulfilled') {
	// 		devices = listRes.value.devices;
	// 		listFrom = listRes.value.from;
	// 	}
	// 	devicesFailed = listRes.status === 'rejected';
	// 	if (countRes.status === 'fulfilled') deviceCount = countRes.value.count;
	// 	deviceCountFailed = countRes.status === 'rejected';
	// 	...the capture mode and registry, as below
	// 	return outcome([listRes, countRes, onlineRes, newRes, modeRes, ...(registryRes ? [registryRes] : [])]);
	// }
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// Section D: the hand-off's own load takes the comparison it set up (gen null); any other load ends it
		linked = linked?.gen === null ? { ...linked, gen: g } : null;
		// the window, fixed before the first await: the link's exact one (Custom), else the range ending now
		const key = windowKey;
		const shownWords = range.words;
		const win = custom ? { from: custom.from, to: custom.to } : rangeWindow(range.hours);
		// A refresh of the same window keeps its last reading; another window must not show it
		if (key !== loadedWindow) {
			loaded = null;
			devicesFailed = false;
			loading = true;
			// else Back to the last good window after a failed one skips this reset (PR #190 review)
			loadedWindow = '';
		}
		const [[listRes, newRes], { mode: modeRes, registry: registryRes }] = await Promise.all([
			Promise.allSettled([
				getDevices({ ...win, sort: 'bytes', order: 'desc', limit: LIST_LIMIT }).then(checkedReading),
				getNewDeviceCount(new Date(Date.now() - DAY).toISOString()),
			]),
			loadRegistry(),
		]);
		if (!guard.current(g)) return 'skipped';

		if (newRes.status === 'fulfilled') newCount = newRes.value.count;
		newFailed = newRes.status === 'rejected';
		if (listRes.status === 'fulfilled') {
			const { devices, total, online_total, online_since, as_of, from, to } = listRes.value;
			loaded = { devices, total, online_total, online_since, as_of, from, to, words: shownWords };
			loadedWindow = key;
			if (linked?.gen === g) linked = { ...linked, observed: total };
		}
		devicesFailed = listRes.status === 'rejected';
		// a failed mode keeps the last one; with none, By type says so instead of guessing bridge
		if (modeRes.status === 'fulfilled') captureMode = modeRes.value;
		modeFailed = modeRes.status === 'rejected';
		// #96: a failed registry keeps the last cards; it never reads as "No devices detected yet"
		if (registryRes?.status === 'fulfilled') registryDevices = registryRes.value.devices;
		registryFailed = registryRes?.status === 'rejected';
		loading = false;

		return outcome([listRes, newRes, modeRes, ...(registryRes ? [registryRes] : [])]);
	}

	/** A range pill: a rolling window ending now, so the link's exact window (Custom) goes; the URL's tab stays. */
	function pickRange(value: string) {
		if (value === 'custom') return;
		const q = new URLSearchParams({ range: value });
		if (urlView) q.set('view', urlView);
		void goto(`${$page.url.pathname}?${q}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	const refresh = registerPageRefresh(load);
	onMount(() => {
		// OLD CODE: layout = readLayout(); (NET-201: no layout to pick)
		// OLD CODE START — NET-160 slice 2b-3: one load on mount; the effect below also loads on a new URL window
		// refresh.run();
		// OLD CODE END
	});
	onDestroy(() => refresh.unregister());

	// OLD CODE START — NET-160 section D: only the window started a load; a new `count` (a hand-off
	// over the same window) now starts one too, keeping the loaded reading
	// // The first load, and a new one whenever the URL's window changes (a range pill, Back, a link)
	// $effect(() => {
	// 	void windowKey;
	// 	untrack(() => refresh.run());
	// });
	// OLD CODE END
	// The first load, and a new one whenever the URL's window or count changes (a range pill, Back, a
	// link). A valid count starts a comparison, which the load this starts claims.
	$effect(() => {
		void windowKey;
		const expected = appliedCount;
		untrack(() => {
			linked = expected === null ? null : { expected, gen: null, observed: null };
			void refresh.run();
		});
	});

	// The page's own 30 s auto refresh, through the same contract so "Updated" stays honest
	const AUTO_REFRESH_MS = 30_000;
	$effect(() => {
		if (!autoRefresh) return;
		const timer = setInterval(() => refresh.runIfIdle(), AUTO_REFRESH_MS);
		return () => clearInterval(timer);
	});

	// ---------------------------------------------------------------------------
	// Derived
	// ---------------------------------------------------------------------------

	// Home's device cards: the range's traffic per IP; a list shorter than its limit holds every device
	// OLD CODE: const deviceCards = $derived(withTraffic(registryDevices, listFrom ? devices : null, devices.length < LIST_LIMIT, listFrom ?? '')); (slice 2b-3: one reading)
	// OLD CODE: const deviceCards = $derived(withTraffic(registryDevices, loaded ? devices : null, devices.length < LIST_LIMIT, loaded?.from ?? '')); (slice 2b-3 review: exactly LIST_LIMIT devices read as cut off)
	// the list holds every device when it holds the reading's `total`
	const deviceCards = $derived(withTraffic(registryDevices, loaded ? devices : null, loaded !== null && devices.length >= loaded.total, loaded?.from ?? ''));
	const typeGroups = $derived(groupByType(deviceCards));

	let filteredDevices = $derived.by(() => {
		let list = [...devices];

		// Category filter
		if (categoryFilter !== 'all') {
			list = list.filter((d) => (d.category ?? 'unknown') === categoryFilter);
		}

		// Search filter
		if (searchQuery.trim()) {
			const q = searchQuery.trim().toLowerCase();
			list = list.filter((d) =>
				d.ip.toLowerCase().includes(q) ||
				(d.hostname && d.hostname.toLowerCase().includes(q)) ||
				(d.manufacturer && d.manufacturer.toLowerCase().includes(q)) ||
				(d.unifi_name && d.unifi_name.toLowerCase().includes(q)) ||
				// NET-200
				(d.custom_name && d.custom_name.toLowerCase().includes(q)),
			);
		}

		return list;
	});

	// Category counts
	let categoryCounts = $derived.by(() => {
		const counts: Record<string, number> = { all: devices.length };
		for (const d of devices) {
			const cat = d.category ?? 'unknown';
			counts[cat] = (counts[cat] ?? 0) + 1;
		}
		return counts;
	});
	const categoryOptions = $derived(CATEGORIES.map((c) => ({ value: c.key, label: `${c.label} ${categoryCounts[c.key] ?? 0}` })));

	// OLD CODE START — counted inside the busiest-200 list; and first_seen is the first record in
	// the page's 24 h window, so "New (24h)" was every device (54 of 54 on the G11)
	// let onlineCount = $derived(devices.filter((d) => d.last_seen && (Date.now() - new Date(d.last_seen).getTime()) < 5 * 60 * 1000).length);
	// let newCount = $derived(devices.filter((d) => d.first_seen && (Date.now() - new Date(d.first_seen).getTime()) < 24 * 60 * 60 * 1000).length);
	// OLD CODE END
	// the list holds only the busiest LIST_LIMIT devices on a bigger network
	let listIsPartial = $derived(deviceCount !== null && devices.length < deviceCount);
	let topConsumer = $derived(devices.length > 0 ? devices[0] : null);

	// Max bytes for bar widths
	let maxBytes = $derived(devices.length > 0 ? Math.max(...devices.map((d) => d.total_bytes), 1) : 1);

	// OLD CODE START — 2026-11-03 UI redesign: the hand-built table's sort; DataTable sorts every column
	// let sortedDevices = $derived.by(() => {
	// 	return [...filteredDevices].sort((a, b) => {
	// 		const av = (a as any)[sortField] ?? 0;
	// 		const bv = (b as any)[sortField] ?? 0;
	// 		const cmp = compareValues(av, bv);
	// 		return sortDir === 'asc' ? cmp : -cmp;
	// 	});
	// });
	// OLD CODE END

	const subtitle = $derived.by(() => {
		if (devicesFailed) return devices.length > 0 ? loadFailed('devices', true) : 'Every device NetTap sees on the network';
		if (deviceCount === null && devices.length === 0) return 'Every device NetTap sees on the network';
		const total = deviceCount !== null ? `${deviceCount} devices seen on the network` : `Showing ${devices.length} devices`;
		return listIsPartial ? `${total} · showing the ${devices.length} busiest` : total;
	});

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — 2026-11-06 (NET-166): a copy of formatBytes in $lib/api/logs, 1024-based under decimal labels; the shared one is decimal
	// function formatBytes(bytes: number): string {
	// 	if (bytes === 0) return '0 B';
	// 	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	// 	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	// 	return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
	// }
	// OLD CODE END

	/** A registry card's traffic: undefined is unknown (the list didn't cover it), 0 is a real zero. */
	function cardBytes(bytes: number | undefined): string {
		return bytes === undefined || bytes < 0 ? '—' : formatBytes(bytes);
	}

	// NET-180: the card and its List row read these, so both show the same figures
	const cardName = (d: RegistryDevice) => d.display_name || d.mac;
	/** NET-200: List-row photo URLs that failed to load; those rows show the icon instead. */
	let failedPhotos = $state(new Set<string>());
	const photoFailed = (url: string | null | undefined) => {
		if (url) failedPhotos = new Set([...failedPhotos, url]);
	};
	const cardAddress = (d: RegistryDevice) => d.ips[0] ?? d.mac;
	const cardConnections = (d: RegistryDevice) => (d.connection_count != null ? fmt(d.connection_count) : '—');
	/** Some of the device's addresses weren't in the device list, so its traffic is theirs only. */
	const partlyListed = (d: RegistryDevice) => !!d.ips_listed && d.ips_listed < d.ips.length;
	const openCard = (d: RegistryDevice) => goto(`/devices/mac/${encodeURIComponent(d.mac)}`);
	/** A List row's address suffix: " +2 · 2 of 3 listed" (the card's addresses note, shortened). */
	const addressMore = (d: RegistryDevice) =>
		(d.ips.length > 1 ? ` +${d.ips.length - 1}` : '') + (partlyListed(d) ? ` · ${d.ips_listed} of ${d.ips.length} listed` : '');

	// OLD CODE START — one compact format for the app (NET-192 PR 4): formatCompactNumber in $lib/api/logs
	// function formatNumber(n: number): string {
	// 	if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
	// 	if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
	// 	return n.toLocaleString();
	// }
	// OLD CODE END

	// OLD CODE START — NET-160 slice 2b-3: the browser's clock at render time, a request's time
	// after the count's cutoff, and a strict < where the count uses >=
	// function ageMs(d: Device): number | null {
	// 	return d.last_seen ? Date.now() - new Date(d.last_seen).getTime() : null;
	// }
	//
	// /** Traffic in the last 5 minutes is online; in the last hour, idle. */
	// function status(d: Device): { rank: number; label: string } {
	// 	const age = ageMs(d);
	// 	if (age !== null && age < ONLINE_MS) return { rank: 2, label: 'Online' };
	// 	if (age !== null && age < 60 * 60 * 1000) return { rank: 1, label: 'Idle' };
	// 	return { rank: 0, label: 'Offline' };
	// }
	// OLD CODE END
	// The reading's own clock: online_total counted last_seen >= online_since, so the table does too
	const onlineFrom = $derived(loaded ? Date.parse(loaded.online_since) : Infinity);
	const idleFrom = $derived(loaded ? Date.parse(loaded.as_of) - HOUR : Infinity);

	/**
	 * A list reply without the reading's fields (an older daemon) is a failed load: read as it is,
	 * every row would say Offline and the figures "—" with no error (PR #191 review).
	 */
	function checkedReading(r: DeviceListResponse): DeviceListResponse {
		const times = [r.as_of, r.online_since].map((t) => Date.parse(t));
		if (!Number.isFinite(r.total) || !Number.isFinite(r.online_total) || times.some(Number.isNaN)) {
			throw new Error('The device list reply has no reading');
		}
		return r;
	}

	/**
	 * Seen at or after the reading's online_since is online; within the hour before its as_of, idle.
	 * A window that ended before the last 5 minutes can't say what is online now (PR #191 review).
	 */
	function status(d: Device): { rank: number; label: string } {
		if (windowEnded) return { rank: -1, label: '—' };
		const seen = d.last_seen ? Date.parse(d.last_seen) : NaN;
		if (seen >= onlineFrom) return { rank: 2, label: 'Online' };
		if (seen >= idleFrom) return { rank: 1, label: 'Idle' };
		return { rank: 0, label: 'Offline' };
	}

	function timeAgo(dateStr: string): string {
		if (!dateStr) return '—';
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	// OLD CODE: const deviceName = (d: Device) => d.unifi_name ?? d.hostname ?? d.ip; (NET-200: the owner's name first)
	const deviceName = (d: Device) => d.custom_name ?? d.unifi_name ?? d.hostname ?? d.ip;
	const openDevice = (d: Device) => goto(`/devices/${encodeURIComponent(d.ip)}`);
	// "1.2 GB" as the KPI's value and unit
	const topBytes = $derived(topConsumer ? formatBytes(topConsumer.total_bytes).split(' ') : null);

	// Every column sorts (design system); the snippets are at the top of the markup
	const columns: Column<Device>[] = [
		{ key: 'ip', label: 'IP address', cell: ipCell },
		// OLD CODE: { key: 'name', label: 'Name', cell: nameCell, sortValue: (d) => d.unifi_name ?? d.hostname }, (NET-200)
		{ key: 'name', label: 'Name', cell: nameCell, sortValue: (d) => d.custom_name ?? d.unifi_name ?? d.hostname },
		// OLD CODE: { key: 'status', label: 'Status', cell: statusCell, sortValue: (d) => status(d).rank }, (PR #191 review: a past window has no status)
		{ key: 'status', label: 'Status', cell: statusCell, sortValue: (d) => (windowEnded ? null : status(d).rank) },
		{ key: 'category', label: 'Type', cell: typeCell, sortValue: (d) => d.category ?? 'unknown' },
		{ key: 'os_hint', label: 'OS', cell: osCell },
		{ key: 'manufacturer', label: 'Manufacturer', cell: vendorCell },
		{ key: 'total_bytes', label: 'Bandwidth', numeric: true, cell: bytesCell },
		{ key: 'connection_count', label: 'Connections', numeric: true, cell: connCell },
		{ key: 'alert_count', label: 'Alerts', numeric: true, cell: alertCell },
		{ key: 'last_seen', label: 'Last seen', cell: seenCell, sortValue: (d) => (d.last_seen ? Date.parse(d.last_seen) : null) },
	];

	// NET-180: By type's List layout. Unknown figures sort as missing (last both ways), never as 0;
	// Last seen descending is the cards' order (device-types.ts)
	const listColumns: Column<RegistryDevice>[] = [
		{ key: 'name', label: 'Device', cell: listDeviceCell, sortValue: cardName },
		{ key: 'address', label: 'Address', cell: listAddressCell, sortValue: cardAddress },
		{ key: 'manufacturer', label: 'Maker', cell: listMakerCell, sortValue: (d) => d.manufacturer || null },
		{
			key: 'total_bytes', label: 'Traffic', numeric: true, cell: listBytesCell,
			sortValue: (d) => (d.total_bytes === undefined || d.total_bytes < 0 ? null : d.total_bytes),
		},
		{ key: 'connection_count', label: 'Connections', numeric: true, cell: listConnCell, sortValue: (d) => d.connection_count ?? null },
		{ key: 'last_seen', label: 'Last seen', cell: listSeenCell, sortValue: (d) => Date.parse(d.last_seen) },
	];

	function resetFilters() {
		searchQuery = '';
		categoryFilter = 'all';
	}
</script>

{#snippet ipCell(d: Device)}<span class="mono">{d.ip}</span>{/snippet}
{#snippet nameCell(d: Device)}
	<!-- NET-200: the owner's name is in hostname already; the UniFi tag only when the UniFi name is the one shown -->
	{#if d.custom_name}
		{d.custom_name}
	{:else if d.unifi_name}
		<span class="two"><span>{d.unifi_name} <span class="tag">UniFi</span></span><span class="mono">{d.hostname ?? '—'}</span></span>
	{:else}
		{d.hostname ?? '—'}
	{/if}
{/snippet}
{#snippet statusCell(d: Device)}
	{@const s = status(d)}
	<span class={['res', s.rank === 2 && 'is-live']}>{s.label}</span>
{/snippet}
<!-- OLD CODE START — NET-226 (DEV-7/8): the guessed type and OS read as fact
{#snippet typeCell(d: Device)}
	<span class="type"><Icon name={deviceIcon(d.category)} />{CATEGORY_LABELS[d.category ?? 'unknown'] ?? d.category}</span>
{/snippet}
{#snippet osCell(d: Device)}{d.os_hint ?? '—'}{/snippet}
OLD CODE END -->
{#snippet typeCell(d: Device)}
	{@const basis = typeBasis(d.category, d.category_basis)}
	<span class="type"><Icon name={deviceIcon(d.category)} /><span class="two"><span>{likelyType(CATEGORY_LABELS[d.category ?? 'unknown'] ?? d.category ?? 'Unknown', d.category)}</span>{#if basis}<span class="basis">{basis}</span>{/if}</span></span>
{/snippet}
{#snippet osCell(d: Device)}
	{#if d.os_hint}
		{@const basis = osBasis(d.os_basis)}
		<span class="two"><span>Likely {d.os_hint}</span>{#if basis}<span class="basis">{basis}</span>{/if}</span>
	{:else}—{/if}
{/snippet}
{#snippet vendorCell(d: Device)}{d.manufacturer ?? '—'}{/snippet}
{#snippet bytesCell(d: Device)}<Bytes value={d.total_bytes} max={maxBytes} display={formatBytes(d.total_bytes)} />{/snippet}
{#snippet connCell(d: Device)}{formatNumber(d.connection_count)}{/snippet}
{#snippet alertCell(d: Device)}{formatNumber(d.alert_count)}{/snippet}
{#snippet seenCell(d: Device)}{timeAgo(d.last_seen)}{/snippet}

<!-- NET-180: By type's List rows. The Device cell sits inside the row's button: no links or buttons in it -->
{#snippet listDeviceCell(d: RegistryDevice)}
	<!-- OLD CODE: <span class="who"><Icon name={deviceIcon(d.category)} /> … (NET-200: the owner's photo or picked icon) -->
	<!-- PR #214 review: a photo that fails to load falls back to the icon, as DeviceTile does (it hid the image and left a gap) -->
	<span class="who">{#if d.picture && !failedPhotos.has(d.picture)}<img class="who-photo" src={d.picture} alt="" width="20" height="20" loading="lazy" onerror={() => photoFailed(d.picture)} />{:else}<Icon name={deviceIcon(d.icon ?? d.category)} />{/if}<span class="who-name">{cardName(d)}</span>{#if isNewDevice(d)}<span class="chip is-ok">New</span>{/if}</span>
{/snippet}
{#snippet listAddressCell(d: RegistryDevice)}
	<span class="mono">{cardAddress(d)}</span>{#if addressMore(d)}<span class="dim">{addressMore(d)}</span>{/if}
{/snippet}
{#snippet listMakerCell(d: RegistryDevice)}
	{#if d.manufacturer}{d.manufacturer}{:else}<span class="dim">Maker unknown</span>{/if}
{/snippet}
{#snippet listBytesCell(d: RegistryDevice)}{cardBytes(d.total_bytes)}{/snippet}
{#snippet listConnCell(d: RegistryDevice)}{cardConnections(d)}{/snippet}
{#snippet listSeenCell(d: RegistryDevice)}{timeAgo(d.last_seen)}{/snippet}

<svelte:head>
	<title>Devices | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Devices</h1>
		<!-- OLD CODE START — 2026-11-01: devices come from observed traffic, not DHCP leases ("DHCP-leased devices") -->
		<!-- OLD CODE END -->
		<p class="page-sub">{subtitle}</p>
	</div>
	<div class="head-actions">
		<Pills options={rangeOptions} value={range.value} onchange={pickRange} ariaLabel="Seen in the last" />
		<!-- OLD CODE START — NET-192 PR 4: Home's Auto / Paused button on every page
		<button class="btn" type="button" aria-pressed={autoRefresh} onclick={() => (autoRefresh = !autoRefresh)}>
			<Icon name="refresh" />{autoRefresh ? 'Auto refresh on' : 'Auto refresh off'}
		</button>
		OLD CODE END -->
		<AutoRefreshButton on={autoRefresh} seconds={AUTO_REFRESH_MS / 1000} ontoggle={() => (autoRefresh = !autoRefresh)} />
	</div>
</div>

{#if isBridgeMode}
	<p class="notice" role="note"><Icon name="infra" /><span>{BRIDGE_NO_DEVICES}</span></p>
{/if}

<!-- New device detection banner (mirror mode), fed from the registry as on Home -->
{#if isMirrorMode && registryDevices.length > 0}
	<NewDeviceBanner devices={registryDevices} />
{/if}

<!-- OLD CODE START — NET-160 slice 2b-3: Total devices and Online now came from their own count requests,
     and the notes said "Last 24 hours" whatever the window
<KpiCard class="c-3" label="Total devices" icon="devices" value={deviceCount ?? '—'}
	sub={deviceCountFailed ? loadFailed('the device count', deviceCount !== null) : 'Seen on the network'} note="Last 24 hours" />
<KpiCard class="c-3" label="Online now" icon="live" value={onlineCount ?? '—'}
	sub={onlineFailed ? loadFailed('the online count', onlineCount !== null) : 'Traffic in the last 5 minutes'} />
…Top consumer: note="Last 24 hours"
OLD CODE END -->
<div class="grid">
	<KpiCard
		class="c-3"
		label="Total devices"
		icon="devices"
		value={deviceCount ?? '—'}
		sub={devicesFailed ? loadFailed('the device count', loaded !== null) : 'Seen on the network'}
		note={windowNote}
	/>
	<KpiCard
		class="c-3"
		label="Online now"
		icon="live"
		value={windowEnded ? '—' : (loaded?.online_total ?? '—')}
		sub={devicesFailed
			? loadFailed('the online count', loaded !== null)
			: windowEnded
				? 'This window ended before the last 5 minutes'
				: 'Traffic in the last 5 minutes'}
	/>
	<KpiCard
		class="c-3"
		label="New in 24 h"
		icon="up"
		value={newCount ?? '—'}
		sub={newFailed ? loadFailed('the new-device count', newCount !== null) : 'First seen by NetTap'}
		note="Last 24 hours"
	/>
	<KpiCard
		class="c-3"
		label="Top consumer"
		icon="bandwidth"
		value={topBytes?.[0] ?? '—'}
		unit={topBytes?.[1]}
		sub={topConsumer ? deviceName(topConsumer) : undefined}
		note={windowNote}
	/>
	<!-- NET-160 section D: a full row under the KPIs, starting under Total devices, the figure it compares -->
	{#if linkedLine}
		<p class="notice c-12" role="status">{linkedLine}</p>
	{/if}
</div>

<div>
	<Pills mode="tabs" idPrefix="devices" ariaLabel="Device view" options={VIEWS} value={view} onchange={(v) => (pickedView = v)} />
</div>

<!-- OLD CODE START — NET-160 slice 2b-3: By type's and All devices' subtitles and note said "the last 24 hours"
     whatever the window: sub="Grouped by device type · traffic in the last 24 hours",
     sub="Busiest first · traffic in the last 24 hours" and "Traffic in the last 24 hours from the listed addresses…"
OLD CODE END -->
<div role="tabpanel" id="devices-panel-type" aria-labelledby="devices-tab-type" hidden={view !== 'type'}>
	{#if view === 'type'}
		{#if loading && !captureMode}
			<Card title="Devices by type" sub="Grouped by device type · traffic in the {words}">
				<CardState state="loading" title="Loading devices" />
			</Card>
		{:else if !captureMode}
			<Card title="Devices by type" sub="Grouped by device type · traffic in the {words}">
				<CardState state="error" title={loadFailed('the capture mode')} message="By type needs the capture mode. Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
			</Card>
		{:else if !isMirrorMode}
			<Card title="Devices by type" sub="Grouped by device type">
				<!-- OLD CODE: message="All devices lists every device NetTap sees in this capture mode." (NET-225: in bridge mode it sees none) -->
				<CardState
					state="empty"
					icon="devices"
					title="Device cards by type show in mirror mode"
					message={isBridgeMode
						? "In inline bridge mode your devices share the router's IPv4 address, so they can't be listed by type."
						: 'All devices lists every device NetTap sees in this capture mode.'}
					actionLabel="Show all devices"
					onaction={() => (pickedView = 'all')}
				/>
			</Card>
		{:else if registryFailed && registryDevices.length === 0}
			<Card title="Devices by type" sub="Grouped by device type · traffic in the {words}">
				<CardState state="error" title={loadFailed('devices')} onaction={() => refresh.run()} />
			</Card>
		{:else if registryDevices.length === 0}
			<Card title="Devices by type" sub="Grouped by device type · traffic in the {words}">
				<CardState state="empty" icon="devices" title="No devices yet" message="Devices appear here once NetTap sees their traffic." />
			</Card>
		{:else}
			{#if registryFailed}
				<!-- OLD CODE: <p class="note">{loadFailed('devices', true)}</p> (NET-192 PR 4: a stale note is the shared amber notice) -->
				<p class="notice is-warn load-note" role="status"><Icon name="warn" /><span>{loadFailed('devices', true)}</span></p>
			{/if}
			<!-- NET-158: a card adds up the device list's rows for its addresses; an address another device took since counts on both -->
			<!-- OLD CODE START — NET-180: the note stood alone; the Cards / List switch now sits beside it -->
			<!-- <p class="note">Traffic in the last 24 hours from the listed addresses each device has used.</p> -->
			<!-- OLD CODE END -->
			<div class="type-head">
				<p class="note">Traffic in the {words} from the listed addresses each device has used.</p>
				<!-- OLD CODE: <Pills ariaLabel="Layout" options={LAYOUTS} value={layout} onchange={pickLayout} /> (NET-201: the list only) -->
			</div>
			<div class="type-groups">
				{#each typeGroups as group (group.key)}
					<section class="type-group" aria-labelledby="type-{group.key}">
						<div class="group-head">
							<h2 class="card-title" id="type-{group.key}">{group.label}</h2>
							<span class="chip">{group.devices.length}</span>
						</div>
						<!-- OLD CODE: {#if layout === 'list'} (NET-201: By type is the list only; the Cards markup is kept below) -->
							<div class="card dev-list">
								<DataTable
									ariaLabel="{group.label}, as a list"
									rows={group.devices}
									rowKey={(d) => d.mac}
									initialSort={{ key: 'last_seen', dir: 'desc' }}
									onrowactivate={openCard}
									rowLabel={(d) => `Open ${cardName(d)}`}
									columns={listColumns}
								/>
							</div>
						<!-- OLD CODE START — NET-201: the Cards layout (NET-180), dropped at the owner's request. Its own
						     comments are written <! - - … - - > so this one stays whole.
						{:else}
							<div class="grid">
								{#each group.devices as device (device.mac)}
									<a class="card dev-card c-4" href="/devices/mac/{encodeURIComponent(device.mac)}">
										<span class="dev-card-top">
											<! - - OLD CODE: <DeviceTile category={device.category} /> (NET-200) - - >
											<DeviceTile category={device.category} picture={device.picture} icon={device.icon} />
											<span class="two">
												<span class="dev-name">{cardName(device)}</span>
												<span class="mono">{cardAddress(device)}</span>
											</span>
											<! - - OLD CODE START — NET-158: is_new clears on the device's next update, so the chip rarely showed - - >
											<! - - {#if device.is_new}<span class="chip is-ok">New</span>{/if} - - >
											<! - - OLD CODE END - - >
											{#if isNewDevice(device)}<span class="chip is-ok">New</span>{/if}
										</span>
										<! - - OLD CODE START — NET-180: a card with no maker was a line shorter, so its stats sat higher
										     than its neighbours', and the addresses note came after the stats - - >
										<! - - {#if device.manufacturer}<span class="dim vendor">{device.manufacturer}</span>{/if} - - >
										<! - - …the stats… - - >
										<! - - {#if device.ips_listed && device.ips_listed < device.ips.length}
											<span class="dim vendor">({device.ips_listed} of {device.ips.length} addresses listed)</span>
										{/if} - - >
										<! - - OLD CODE END - - >
										<! - - NET-180: every card has the same three rows (top, maker, stats), each as tall as the band's tallest - - >
										<span class="dim vendor dev-card-about">
											<span>{device.manufacturer || 'Maker unknown'}</span>
											{#if partlyListed(device)}<span>({device.ips_listed} of {device.ips.length} addresses listed)</span>{/if}
										</span>
										<span class="dev-card-stats">
											<span><span class="meta-k">Traffic</span><span class="meta-v num">{cardBytes(device.total_bytes)}</span></span>
											<span><span class="meta-k">Connections</span><span class="meta-v num">{cardConnections(device)}</span></span>
											<span><span class="meta-k">Last seen</span><span class="meta-v">{timeAgo(device.last_seen)}</span></span>
										</span>
									</a>
								{/each}
							</div>
						{/if}
						OLD CODE END -->
					</section>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<div role="tabpanel" id="devices-panel-all" aria-labelledby="devices-tab-all" hidden={view !== 'all'}>
	{#if view === 'all'}
		<Card title="All devices" sub="Busiest first · traffic in the {words}">
			{#if loading && devices.length === 0}
				<CardState state="loading" title="Loading devices" />
			{:else if devicesFailed && devices.length === 0}
				<CardState state="error" title={loadFailed('devices')} onaction={() => refresh.run()} />
			{:else if devices.length === 0}
				<!-- OLD CODE START — 2026-11-01: "No DHCP-leased devices found." / "...obtain an IP from the network's DHCP server." -->
				<!-- OLD CODE END -->
				<!-- OLD CODE: the empty state below in every mode; in bridge mode it promised devices that never appear (NET-225) -->
				{#if isBridgeMode}
					<CardState state="empty" icon="devices" title="No devices to show in inline bridge mode" message={BRIDGE_NO_DEVICES} />
				{:else}
					<CardState
						state="empty"
						icon="devices"
						title="No devices seen yet."
						message="Devices appear once they make a few connections through the monitored link."
					/>
				{/if}
			{:else}
				<div class="toolbar">
					<Pills ariaLabel="Device type" options={categoryOptions} bind:value={categoryFilter} />
					{#if listIsPartial}
						<span class="dim">counts for the {devices.length} busiest devices</span>
					{/if}
					<SearchField id="device-search" label="Search devices" placeholder="Search by IP, hostname or vendor" size="toolbar" bind:value={searchQuery} />
				</div>
				{#if filteredDevices.length === 0}
					<CardState state="empty" icon="filter" title="No devices match these filters" actionLabel="Reset filters" onaction={resetFilters} />
				{:else}
					<DataTable
						ariaLabel="All devices"
						rows={filteredDevices}
						rowKey={(d) => d.ip}
						initialSort={{ key: 'total_bytes', dir: 'desc' }}
						onrowactivate={openDevice}
						rowLabel={(d) => `Open ${deviceName(d)}`}
						{columns}
					/>
				{/if}
				<p class="note table-note">Traffic and connections count both directions and include IPv6, matched to each device by its MAC address.</p>
				{#each ipv6ListNotes(devices) as note (note)}
					<p class="notice is-warn table-note" role="note"><Icon name="warn" /><span>{note}</span></p>
				{/each}
			{/if}
		</Card>
	{/if}
</div>

<style>
	/* OLD CODE: Layout glue the system lacks: the By type groups and their device cards (NET-201: no cards) */
	/* Layout glue the system lacks: the By type groups and their lists */
	.type-groups { display: flex; flex-direction: column; gap: var(--sp-6); }
	.type-group { display: flex; flex-direction: column; gap: var(--sp-3); }
	.group-head { display: flex; align-items: center; gap: var(--sp-2); }
	/* OLD CODE START — NET-201: the Cards layout's styles (its own comments written (* … *))
	.dev-card { display: flex; flex-direction: column; gap: var(--sp-3); text-decoration: none; color: var(--text-1); }
	.dev-card:hover { border-color: var(--line-strong); }
	(* NET-180: without subgrid, equal-height cards at least end level *)
	.dev-card-stats { margin-top: auto; }
	(* NET-180: each card spans three rows of its group's grid and shares their heights, so every
	   card's stats start at the same height in a band, whatever wraps above or inside them *)
	@supports (grid-template-rows: subgrid) {
		.dev-card { display: grid; grid-row: span 3; grid-template-rows: subgrid; grid-template-columns: minmax(0, 1fr); row-gap: var(--sp-3); }
		.dev-card-stats { margin-top: 0; }
	}
	.dev-card-about { display: flex; flex-direction: column; }
	OLD CODE END */
	.type-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: var(--sp-3); margin-bottom: var(--sp-3); }
	.type-head .note { margin-bottom: 0; }
	/* compact rows: one line each */
	.dev-list :global(tbody td) { padding-top: var(--sp-2); padding-bottom: var(--sp-2); }
	/* OLD CODE START — NET-201: the Cards layout's styles
	.dev-card-top { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: var(--sp-3); align-items: center; }
	.dev-name { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.vendor { font-size: var(--text-xs); }
	.dev-card-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--sp-3); padding-top: var(--sp-3); border-top: 1px solid var(--line); }
	.dev-card-stats > span { display: flex; flex-direction: column; min-width: 0; }
	OLD CODE END */
	.type { display: inline-flex; align-items: center; gap: var(--sp-2); }
	.type :global(.ic) { color: var(--text-3); width: 16px; height: 16px; }
	.note { color: var(--text-2); font-size: var(--text-sm); margin-bottom: var(--sp-3); }
	/* NET-226: what the table's figures count, under it */
	.table-note { margin-top: var(--sp-3); margin-bottom: 0; }
	.basis { color: var(--text-3); font-size: var(--text-xs); }
	.load-note { margin-bottom: var(--sp-3); }
	/* NET-200: the owner's photo in a List row, the size of the row's icon slot */
	.who-photo { width: 20px; height: 20px; flex: none; border-radius: var(--r-xs); object-fit: cover; }
</style>
