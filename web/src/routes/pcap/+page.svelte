<script lang="ts">
	import { onDestroy, onMount, untrack } from 'svelte';
	import {
		getPcapFiles,
		searchPcaps,
		checkPcapFilter,
		PcapRequestError,
		previewPcap,
		getDownloadUrl,
		getFileDownloadUrl,
		formatBytes,
		formatRelativeTime,
		QUICK_FILTERS,
		PROTO_FILTER_MAP,
		DOWNLOAD_ERROR_MESSAGE,
	} from '$lib/api/pcap';
	import type {
		PcapFile,
		PcapSearchResult,
		PcapPacket,
	} from '$lib/api/pcap';
	import type { PcapReadOutcome } from '$lib/api/pcap';
	import { formatDuration } from '$lib/utils/tshark-helpers';
	// OLD CODE START — DataTable sorts every table (utils/table-sort)
	// import { TableSort, compareValues } from '$lib/utils/table-sort.svelte';
	// OLD CODE END
	// OLD CODE START — getCaptureStatus fakes enabled: true when the request fails
	// import { getCaptureStatus, toggleCapture, captureState } from '$lib/api/capture';
	// OLD CODE END
	import { fetchCaptureStatus, toggleCapture, captureState } from '$lib/api/capture';
	import type { CaptureStatus } from '$lib/api/capture';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import AreaChart from '$lib/components/ui/charts/AreaChart.svelte';
	import BarList from '$lib/components/ui/BarList.svelte';
	import Bytes from '$lib/components/ui/Bytes.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import KpiCard from '$lib/components/ui/KpiCard.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	// OLD CODE: import { chartTime, DRILL_RANGES, fmt, type DrillRangeValue } from '$lib/utils/drilldown'; (NET-249: the table's buckets and window words)
	import { chartTime, DRILL_RANGES, fmt, windowWords } from '$lib/utils/drilldown';
	import { formatTime } from '$lib/utils/time';

	// ---------------------------------------------------------------------------
	// Constants
	// ---------------------------------------------------------------------------

	// One range set across the app (NET-192 PR 4): 1h 6h 24h 7d 30d, as on Home
	// OLD CODE START — NET-196: the app's one list (DRILL_RANGES), with this page's ms and capture-timeline bucket beside it
	// const TIME_RANGES = [
	// 	{ label: '1h', value: '1h', ms: 60 * 60 * 1000, words: 'last hour', bucket: '5 minutes' },
	// 	// OLD CODE: { label: '4h', value: '4h', ms: 4 * 60 * 60 * 1000, words: 'last 4 hours', bucket: '20 minutes' }, (NET-192 PR 4)
	// 	{ label: '6h', value: '6h', ms: 6 * 60 * 60 * 1000, words: 'last 6 hours', bucket: '30 minutes' },
	// 	{ label: '24h', value: '24h', ms: 24 * 60 * 60 * 1000, words: 'last 24 hours', bucket: 'hour' },
	// 	{ label: '7d', value: '7d', ms: 7 * 24 * 60 * 60 * 1000, words: 'last 7 days', bucket: '6 hours' },
	// 	{ label: '30d', value: '30d', ms: 30 * 24 * 60 * 60 * 1000, words: 'last 30 days', bucket: 'day' },
	// ];
	// OLD CODE END
	// OLD CODE START — NET-249 slice 2: the timeline's buckets come from the owner's table (DRILL_RANGES' bucketMs and bucketWords)
	// // The timeline's bar per range: its words for the subtitle and its width, kept together so they can't drift
	// const BUCKET: Record<DrillRangeValue, { words: string; minutes: number }> = {
	// 	'1h': { words: '5 minutes', minutes: 5 },
	// 	'6h': { words: '30 minutes', minutes: 30 },
	// 	'24h': { words: 'hour', minutes: 60 },
	// 	'7d': { words: '6 hours', minutes: 360 },
	// 	'30d': { words: 'day', minutes: 1440 },
	// };
	// const TIME_RANGES = DRILL_RANGES.map((r) => ({ ...r, ms: r.hours * 3_600_000, bucket: BUCKET[r.value].words, bucketMs: BUCKET[r.value].minutes * 60_000 }));
	// OLD CODE END
	const TIME_RANGES = DRILL_RANGES.map((r) => ({ ...r, ms: r.hours * 3_600_000 }));

	const SEARCH_POLL_MS = 3000;

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	// OLD CODE START — #137: a whole day is ~185 GB on a busy network, hours to search
	// let selectedTimeRange = $state('24h');
	// OLD CODE END
	let selectedTimeRange = $state('1h');
	// OLD CODE START — PLAN §5.5: a range change during the first load now starts a new, guarded load
	// let initialized = $state(false);
	// OLD CODE END

	// Filter
	let bpfFilter = $state('');
	// NET-189: the download's own window (datetime-local text); both empty = the page's range
	let downloadFrom = $state('');
	let downloadTo = $state('');
	/** NET-373: why the last download didn't start, shown beside its dates */
	let downloadProblem = $state('');
	/** The tab the current download opened: only it may report a refusal (NET-373) */
	let downloadTab: Window | null = null;
	/** A download whose tab the browser blocked, offered as a plain link */
	let blockedUrl = $state('');
	let loading = $state(false);
	let error = $state('');

	// Files
	let files = $state<PcapFile[]>([]);
	/** The window the files on screen were listed for, and the timeline's bucket for it (NET-249: set when they land) */
	let filesWindow = $state<{ from: string; to: string; step: number } | null>(null);
	/** The timeline slots picked (NET-249): the files written in [from, to), ms. The list shows only those; null shows every file */
	let fileWindow = $state<{ from: number; to: number } | null>(null);
	let filesLoading = $state(true);
	let filesFailed = $state(false); // #96: a failed listing is not "No PCAP files"

	// Search
	let searchResults = $state<PcapSearchResult[]>([]);
	let searchDone = $state(false);
	let searchProgress = $state<{
		checked: number;
		total: number;
		timedOut: number;
		failed: number;
		error: string;
		bytesChecked: number;
		bytesTotal: number;
		secondsElapsed: number;
		/** NET-347: files read to the end, and files that ended mid-packet */
		full: number;
		truncated: number;
	} | null>(null);
	/** NET-347: the search on screen (filter and window as sent); results and their previews follow it, not the input */
	type Submitted = { filter: string; from: string; to: string };
	let submitted = $state<Submitted | null>(null);
	/** A search that failed to start for a reason other than the filter: "Try again" resends it as it was */
	// OLD CODE: let retrySearch = $state<Submitted | null>(null); (review: the button showed beside later, unrelated errors)
	let retrySearch = $state<{ search: Submitted; message: string } | null>(null);
	/** TShark's refusal of a submitted filter, shown under the field while it still holds that text */
	let filterError = $state<{ text: string; message: string } | null>(null);
	/** NET-347: the check that enables Download filtered, for the text it checked */
	let filterCheck = $state<{ text: string; state: 'checking' | 'ok' | 'invalid' | 'unknown'; message?: string } | null>(null);
	let checkRun = 0;
	/** Bumped on every new search and on destroy so a stale poll loop exits. */
	let searchRun = 0;
	/** The scroll-to-preview timer; cleared on destroy, when `document` may be gone. */
	let scrollTimer: ReturnType<typeof setTimeout> | undefined;

	// Preview
	let previewPackets = $state<PcapPacket[]>([]);
	let previewTimedOut = $state(false);
	let previewFile = $state('');
	/** NET-347: the filter the preview was asked with, and its request number (a late answer for an older pick is dropped) */
	let previewFilter = $state('');
	let previewRun = 0;
	let previewLoading = $state(false);
	// A failed preview is not "No packets to display"
	let previewFailed = $state(false);

	// OLD CODE START — DataTable sorts the file and result tables (every column, utils/table-sort)
	// // Sorting — Files
	// type FileSortKey = 'name' | 'size_bytes' | 'modified';
	// let fileSortKey = $state<FileSortKey>('modified');
	// let fileSortDir = $state<'asc' | 'desc'>('desc');
	//
	// // Sorting — Search Results
	// type ResultSortKey = 'name' | 'matching_packets' | 'size_bytes' | 'modified';
	// let resultSortKey = $state<ResultSortKey>('matching_packets');
	// let resultSortDir = $state<'asc' | 'desc'>('desc');
	// OLD CODE END

	// Capture control
	// OLD CODE START — assumed on, so an unread state showed the toggle on and a click turned capture off
	// let captureEnabled = $state(true);
	// OLD CODE END
	let captureEnabled = $state<boolean | null>(null); // null until the daemon says
	let captureLoading = $state(false);
	let captureStatus = $state<CaptureStatus | null>(null);
	let captureView = $derived(captureState(captureStatus));
	// OLD CODE START — sentence case (design system voice)
	// const CAPTURE_LABELS = { active: 'Capture Active', stopped: 'Capture Stopped', unknown: 'Capture Status Unknown' };
	// OLD CODE END
	const CAPTURE_LABELS = { active: 'Capture active', stopped: 'Capture stopped', unknown: 'Capture status unknown' };

	// OLD CODE START — the hand-drawn timeline's hover and width; AreaChart handles both
	// // Timeline
	// let hoveredBarIndex = $state<number | null>(null);
	// let chartWidth = $state(800);
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Derived — Stats
	// ---------------------------------------------------------------------------

	let totalFileCount = $derived(files.length);
	let totalBytes = $derived(files.reduce((s, f) => s + f.size_bytes, 0));
	let newestCapture = $derived(files.length ? files.reduce((a, b) => a.modified > b.modified ? a : b).modified : '');
	let oldestCapture = $derived(files.length ? files.reduce((a, b) => a.modified < b.modified ? a : b).modified : '');
	let maxFileSize = $derived(Math.max(1, ...files.map((f) => f.size_bytes)));

	// OLD CODE: ?? TIME_RANGES[0] (NET-192 PR 4: the default by value, not by position)
	const range = $derived(TIME_RANGES.find((r) => r.value === selectedTimeRange) ?? TIME_RANGES.find((r) => r.value === '1h')!);
	// The file counts read as unknown, not 0, until the first listing arrives
	const filesUnknown = $derived(filesFailed || (filesLoading && files.length === 0));

	// ---------------------------------------------------------------------------
	// Derived — Capture Timeline
	// ---------------------------------------------------------------------------

	interface TimelineBucket {
		label: string;
		count: number;
		bytes: number;
	}

	/* OLD CODE START — NET-249: the buckets started at Date.now() when derived, so they shifted on every re-derive and
	   no slot had an exact window; they are epoch-aligned slots over the files' own window now
	function buildCaptureTimeline(fileList: PcapFile[], range: string): TimelineBucket[] {
		if (!fileList.length) return [];
		const now = Date.now();
		const rangeMs = TIME_RANGES.find((r) => r.value === range)?.ms ?? 86400000;
		// OLD CODE: const bucketMs = range === '1h' ? 5 * 60000 : range === '4h' ? 20 * 60000 : … (NET-192 PR 4: 6h, not 4h)
		// OLD CODE: const bucketMs = range === '1h' ? 5 * 60000 : range === '6h' ? 30 * 60000 : range === '24h' ? 3600000 : range === '7d' ? 6 * 3600000 : 86400000; (NET-196: BUCKET holds the width beside its words)
		const bucketMs = TIME_RANGES.find((r) => r.value === range)?.bucketMs ?? 86400000;
		const bucketCount = Math.ceil(rangeMs / bucketMs);
		const startMs = now - rangeMs;
		const buckets: TimelineBucket[] = Array.from({ length: bucketCount }, (_, i) => ({
			label: new Date(startMs + i * bucketMs).toISOString(),
			count: 0,
			bytes: 0,
		}));
		for (const file of fileList) {
			const fileMs = new Date(file.modified).getTime();
			const idx = Math.floor((fileMs - startMs) / bucketMs);
			if (idx >= 0 && idx < bucketCount) {
				buckets[idx].count++;
				buckets[idx].bytes += file.size_bytes;
			}
		}
		return buckets;
	}
	OLD CODE END */
	/** A time's slot: epoch-aligned, `step` ms wide. The chart and the file filter both use it, so a slot's figure is its files. */
	const slotOf = (ms: number, step: number) => Math.floor(ms / step);

	/** Files written per slot, every slot from the window's start to its end, by each file's `modified` time. */
	function buildCaptureTimeline(fileList: PcapFile[], win: { from: string; to: string; step: number } | null): TimelineBucket[] {
		if (!fileList.length || !win) return [];
		const first = slotOf(Date.parse(win.from), win.step);
		const count = slotOf(Date.parse(win.to), win.step) - first + 1;
		const buckets: TimelineBucket[] = Array.from({ length: count }, (_, i) => ({ label: new Date((first + i) * win.step).toISOString(), count: 0, bytes: 0 }));
		for (const file of fileList) {
			const idx = slotOf(Date.parse(file.modified), win.step) - first;
			if (idx >= 0 && idx < count) {
				buckets[idx].count++;
				buckets[idx].bytes += file.size_bytes;
			}
		}
		return buckets;
	}

	// OLD CODE: let captureTimeline = $derived(buildCaptureTimeline(files, selectedTimeRange)); (NET-249)
	let captureTimeline = $derived(buildCaptureTimeline(files, filesWindow));
	/** The list under the chart: every file, or only those written in the picked slots (the chart's own rule) */
	const shownFiles = $derived.by(() => {
		const w = fileWindow;
		if (!w) return files;
		return files.filter((f) => {
			const ms = Date.parse(f.modified);
			return ms >= w.from && ms < w.to;
		});
	});

	/** A pick on the timeline (NET-249) narrows the file list to the files written in those slots, and brings it into view. */
	function pickFiles(i: number, j: number) {
		const step = filesWindow?.step;
		const a = captureTimeline[Math.min(i, j)];
		const b = captureTimeline[Math.max(i, j)];
		if (!step || !a || !b) return;
		fileWindow = { from: Date.parse(a.label), to: Date.parse(b.label) + step };
		document.getElementById('files-section')?.scrollIntoView?.({ behavior: 'smooth' });
	}
	const fileWord = (n: number) => `${fmt(n)} ${n === 1 ? 'file' : 'files'}`;
	// OLD CODE START — the hand-drawn timeline's scale; AreaChart fits its own axis
	// let maxTimelineCount = $derived(Math.max(1, ...captureTimeline.map((b) => b.count)));
	// OLD CODE END
	const busiestBucket = $derived(
		captureTimeline.reduce((best, b, i) => (b.count > (captureTimeline[best]?.count ?? 0) ? i : best), -1),
	);

	// ---------------------------------------------------------------------------
	// Derived — Protocol Breakdown
	// ---------------------------------------------------------------------------

	interface ProtoEntry {
		protocol: string;
		count: number;
	}

	/** Wireshark's Protocol column as given (#141); an old frame.protocols chain shows its last entry. */
	function protocolLabel(protocol: string): string {
		return protocol.includes(':') ? (protocol.split(':').at(-1) ?? protocol).toUpperCase() : protocol;
	}

	function buildProtocolBreakdown(packets: PcapPacket[]): ProtoEntry[] {
		const counts = new Map<string, number>();
		for (const pkt of packets) {
			// OLD CODE START — #141: the daemon now sends Wireshark's column, and TLSv1.3 isn't TLSV1.3
			// const parts = pkt.protocol.split(':');
			// const proto = (parts[parts.length - 1] || pkt.protocol).toUpperCase();
			// OLD CODE END
			const proto = protocolLabel(pkt.protocol);
			counts.set(proto, (counts.get(proto) ?? 0) + 1);
		}
		return [...counts.entries()]
			.map(([protocol, count]) => ({ protocol, count }))
			.sort((a, b) => b.count - a.count)
			.slice(0, 10);
	}

	let protocolBreakdown = $derived(buildProtocolBreakdown(previewPackets));

	// ---------------------------------------------------------------------------
	// Derived — Sorted tables
	// ---------------------------------------------------------------------------

	// OLD CODE START — DataTable sorts these (utils/table-sort compareValues, blanks last)
	// let sortedFiles = $derived(
	// 	[...files].sort((a, b) => {
	// 		// OLD CODE START — never returned 0 for equal values, and compared names as plain text
	// 		// const cmp = fileSortKey === 'name' ? a.name.localeCompare(b.name) : (a[fileSortKey] as number | string) < (b[fileSortKey] as number | string) ? -1 : 1;
	// 		// OLD CODE END
	// 		const cmp = compareValues(a[fileSortKey], b[fileSortKey]);
	// 		return fileSortDir === 'asc' ? cmp : -cmp;
	// 	})
	// );
	//
	// let sortedResults = $derived(
	// 	[...searchResults].sort((a, b) => {
	// 		// OLD CODE START — never returned 0 for equal values, and compared names as plain text
	// 		// const cmp = resultSortKey === 'name' ? a.name.localeCompare(b.name) : (a[resultSortKey] as number | string) < (b[resultSortKey] as number | string) ? -1 : 1;
	// 		// OLD CODE END
	// 		const cmp = compareValues(a[resultSortKey], b[resultSortKey]);
	// 		return resultSortDir === 'asc' ? cmp : -cmp;
	// 	})
	// );
	//
	// type PacketSortKey = 'frame_number' | 'timestamp' | 'source' | 'destination' | 'protocol' | 'length' | 'info';
	// const PACKET_COLUMNS: [PacketSortKey, string][] = [
	// 	['frame_number', '#'], ['timestamp', 'Time'], ['source', 'Source'], ['destination', 'Destination'],
	// 	['protocol', 'Protocol'], ['length', 'Length'], ['info', 'Info'],
	// ];
	// // capture order first; every field is text, compareValues orders "10" after "9"
	// const packetSort = new TableSort<PacketSortKey>('frame_number', 'asc');
	// OLD CODE END

	function packetProtocol(pkt: PcapPacket): string {
		// OLD CODE START — #141: upper-cased the last frame.protocols entry
		// return pkt.protocol.split(':').at(-1)?.toUpperCase() ?? pkt.protocol;
		// OLD CODE END
		return protocolLabel(pkt.protocol);
	}

	// OLD CODE START — DataTable sorts the packets; capture order first (initialSort below)
	// let sortedPreviewPackets = $derived(
	// 	packetSort.apply(previewPackets, (pkt, key) => (key === 'protocol' ? packetProtocol(pkt) : pkt[key]))
	// );
	//
	// let maxMatchingPackets = $derived(Math.max(1, ...searchResults.map((r) => r.matching_packets)));
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	function getTimeRange(): { from: string; to: string } {
		const now = new Date();
		const range = TIME_RANGES.find((r) => r.value === selectedTimeRange);
		const ms = range?.ms ?? 24 * 60 * 60 * 1000;
		return { from: new Date(now.getTime() - ms).toISOString(), to: now.toISOString() };
	}

	// OLD CODE START — unused; counts read in full
	// function formatNumber(n: number): string {
	// 	if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
	// 	if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
	// 	return n.toString();
	// }
	// OLD CODE END

	// OLD CODE START — the browser's locale ("07:00 PM"), and only the time of day at 7 d and 30 d (NET-192 PR 4: chartTime)
	// function formatTimestamp(ts: string): string {
	// 	try {
	// 		return new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	// 	} catch { return ts; }
	// }
	// OLD CODE END
	const formatTimestamp = (ts: string) => chartTime(ts, range.ms / 3_600_000);

	// OLD CODE START — #137: a shorter range doesn't make a large file any faster
	// function timedOutNote(n: number): string {
	// 	return n === 1
	// 		? '1 large file took longer than 5 minutes and was skipped — pick a shorter time range to search it.'
	// 		: `${n} large files took longer than 5 minutes each and were skipped — pick a shorter time range to search them.`;
	// }
	// OLD CODE END
	function timedOutNote(n: number): string {
		return n === 1
			? "1 file took longer than 5 minutes and wasn't searched: any matches in it aren't counted."
			: `${n} files took longer than 5 minutes each and weren't searched: any matches in them aren't counted.`;
	}

	/** Time left at this box's own pace so far (#137); none before the first file is done. */
	function searchEta(p: { bytesChecked: number; bytesTotal: number; secondsElapsed: number }): string {
		if (p.bytesChecked <= 0 || p.secondsElapsed <= 0) return '';
		const left = (p.secondsElapsed * (p.bytesTotal - p.bytesChecked)) / p.bytesChecked;
		return `, about ${formatDuration(Math.round(left))} left`;
	}

	// OLD CODE START — DataTable draws the sort chevrons
	// function sortIndicator(active: boolean, dir: 'asc' | 'desc'): string {
	// 	return active ? (dir === 'asc' ? ' ↑' : ' ↓') : '';
	// }
	// OLD CODE END

	// ---------------------------------------------------------------------------
	// Data fetching
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN §5.5: the guarded page loader below lists the files and reads the capture state
	// async function loadFiles() {
	// 	filesLoading = true;
	// 	filesFailed = false;
	// 	try {
	// 		const { from, to } = getTimeRange();
	// 		const response = await getPcapFiles({ from, to });
	// 		files = response.files;
	// 	} catch {
	// 		files = [];
	// 		filesFailed = true;
	// 	} finally {
	// 		filesLoading = false;
	// 	}
	// }
	// OLD CODE END
	const refresh = registerPageRefresh(loadPage);
	onDestroy(refresh.unregister);

	/** The file list for the range and the capture state: the first load, Refresh and every range change. */
	async function loadPage(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const { from, to } = getTimeRange();
		const step = range.bucketMs;
		filesLoading = true;
		filesFailed = false;
		const [filesRes, captureRes] = await Promise.allSettled([getPcapFiles({ from, to }), fetchCaptureStatus()]);
		if (!guard.current(g)) return 'skipped';
		files = filesRes.status === 'fulfilled' ? filesRes.value.files : [];
		// NET-249: the timeline's slots follow the window these files were listed for, with the table's bucket
		filesWindow = filesRes.status === 'fulfilled' ? { from, to, step } : null;
		filesFailed = filesRes.status === 'rejected';
		filesLoading = false;
		// A failed read leaves the state unknown: the label says so and the toggle stays disabled
		if (captureRes.status === 'fulfilled') {
			captureStatus = captureRes.value;
			captureEnabled = captureRes.value.enabled;
		}
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const ok = [filesRes, captureRes].filter((r) => r.status === 'fulfilled').length;
		// return ok === 2 ? 'ok' : ok === 0 ? 'failed' : 'partial';
		// OLD CODE END
		return outcome([filesRes, captureRes]);
	}

	// OLD CODE START — 2026-11-02: one request that waited for the daemon to tshark every file,
	// which could never finish inside the 10 s web proxy timeout on a 24 h range
	// async function runSearch() {
	// 	if (!bpfFilter.trim()) {
	// 		error = 'Enter a display filter to search';
	// 		return;
	// 	}
	// 	loading = true;
	// 	error = '';
	// 	searchDone = false;
	// 	searchResults = [];
	// 	try {
	// 		const { from, to } = getTimeRange();
	// 		const response = await searchPcaps(bpfFilter, { from, to });
	// 		searchResults = response.results;
	// 		searchDone = true;
	// 	} catch (e) {
	// 		error = e instanceof Error ? e.message : 'Search failed';
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// OLD CODE END

	// OLD CODE START — NET-347: a refused filter read as a failed search, results followed the input box, and
	// a retry recomputed the window (a new background job)
	// async function runSearch() {
	// 	if (!bpfFilter.trim()) {
	// 		error = 'Enter a display filter to search';
	// 		return;
	// 	}
	// 	const run = ++searchRun;
	// 	// Filter and range are captured once: the daemon keys its background job on the exact
	// 	// (filter, from, to), so changing any of them mid-poll would cancel and restart it.
	// 	const filter = bpfFilter;
	// 	const { from, to } = getTimeRange();
	// 	loading = true;
	// 	error = '';
	// 	searchDone = false;
	// 	searchResults = [];
	// 	searchProgress = null;
	// 	try {
	// 		while (run === searchRun) {
	// 			const response = await searchPcaps(filter, { from, to });
	// 			if (run !== searchRun) return;
	// 			searchResults = response.results;
	// 			searchProgress = {
	// 				checked: response.files_checked,
	// 				total: response.files_total,
	// 				timedOut: response.timed_out,
	// 				// #96: files tshark couldn't read are not "no match"
	// 				failed: response.failed ?? 0,
	// 				error: response.error ?? '',
	// 				bytesChecked: response.bytes_checked ?? 0,
	// 				bytesTotal: response.bytes_total ?? 0,
	// 				secondsElapsed: response.seconds_elapsed ?? 0,
	// 			};
	// 			if (response.complete) {
	// 				searchDone = true;
	// 				return;
	// 			}
	// 			await new Promise((resolve) => setTimeout(resolve, SEARCH_POLL_MS));
	// 		}
	// 	} catch (e) {
	// 		if (run === searchRun) error = e instanceof Error ? e.message : 'Search failed';
	// 	} finally {
	// 		if (run === searchRun) loading = false;
	// 	}
	// }
	// OLD CODE END
	async function runSearch(again?: Submitted) {
		if (!again && !bpfFilter.trim()) {
			error = 'Enter a display filter to search';
			return;
		}
		const run = ++searchRun;
		// Filter and range are captured once: the daemon keys its background job on the exact
		// (filter, from, to), so changing any of them mid-poll would cancel and restart it.
		const search: Submitted = again ?? { filter: bpfFilter, ...getTimeRange() };
		submitted = search;
		retrySearch = null;
		filterError = null;
		loading = true;
		error = '';
		searchDone = false;
		searchResults = [];
		searchProgress = null;
		try {
			while (run === searchRun) {
				const response = await searchPcaps(search.filter, { from: search.from, to: search.to });
				if (run !== searchRun) return;
				searchResults = response.results;
				searchProgress = {
					checked: response.files_checked,
					total: response.files_total,
					timedOut: response.timed_out,
					// #96: files tshark couldn't read are not "no match"
					failed: response.failed ?? 0,
					error: response.error ?? '',
					bytesChecked: response.bytes_checked ?? 0,
					bytesTotal: response.bytes_total ?? 0,
					secondsElapsed: response.seconds_elapsed ?? 0,
					full: response.files_full ?? 0,
					truncated: response.files_truncated ?? 0,
				};
				if (response.complete) {
					searchDone = true;
					return;
				}
				await new Promise((resolve) => setTimeout(resolve, SEARCH_POLL_MS));
			}
		} catch (e) {
			if (run !== searchRun) return;
			if (e instanceof PcapRequestError && e.status === 400) {
				// TShark refused the filter: nothing was searched, so there is no result card or count
				submitted = null;
				if (bpfFilter === search.filter) filterError = { text: search.filter, message: e.message };
				else error = `The filter "${search.filter}" was refused: ${e.message}`;
			} else {
				error = e instanceof Error ? e.message : 'Search failed';
				retrySearch = { search, message: error };
			}
		} finally {
			if (run === searchRun) loading = false;
		}
	}

	const trimmedFilter = $derived(bpfFilter.trim());
	/** NET-347: Download filtered stays off until TShark accepts the text in the box (checked 500 ms after typing stops). */
	$effect(() => {
		const text = trimmedFilter;
		const run = ++checkRun;
		if (!text) {
			filterCheck = null;
			return;
		}
		filterCheck = { text, state: 'checking' };
		const timer = setTimeout(async () => {
			try {
				await checkPcapFilter(text);
				if (run === checkRun) filterCheck = { text, state: 'ok' };
			} catch (e) {
				if (run !== checkRun) return;
				// Busy or unavailable is not "invalid": the download checks the filter again on the daemon
				filterCheck =
					e instanceof PcapRequestError && e.status === 400
						? { text, state: 'invalid', message: e.message }
						: { text, state: 'unknown' };
			}
		}, 500);
		return () => clearTimeout(timer);
	});

	/** TShark's message for the text in the box: from the search that was refused, or from the check. */
	const fieldError = $derived(
		filterError?.text === bpfFilter
			? filterError.message
			: filterCheck?.state === 'invalid' && filterCheck.text === trimmedFilter
				? (filterCheck.message ?? '')
				: '',
	);
	const checkUnknown = $derived(filterCheck?.state === 'unknown' && filterCheck.text === trimmedFilter);
	const downloadReady = $derived(
		filterCheck !== null && filterCheck.text === trimmedFilter && (filterCheck.state === 'ok' || filterCheck.state === 'unknown'),
	);

	/** Rows whose read stopped before the end of the file: their counts are a minimum */
	const stoppedEarly = (o: PcapReadOutcome | undefined) => o === 'failed' || o === 'timed_out';

	/** NET-347: what the finished search covered, so a count never reads as more than it is */
	const coverage = $derived.by(() => {
		const p = searchProgress;
		if (!p || loading) return null;
		const early = searchResults.filter((r) => stoppedEarly(r.outcome));
		const earlyFailed = early.filter((r) => r.outcome === 'failed').length;
		const earlyTimedOut = early.length - earlyFailed;
		return {
			incomplete: p.failed + p.timedOut > 0,
			full: p.full,
			total: p.total,
			early: early.length,
			earlyFailed,
			unreadFailed: Math.max(0, p.failed - earlyFailed),
			unreadTimedOut: Math.max(0, p.timedOut - earlyTimedOut),
			truncated: p.truncated,
		};
	});
	const plural = (n: number, one: string, many: string) => (n === 1 ? `1 ${one}` : `${n} ${many}`);

	// OLD CODE START — NET-347: a late answer for an earlier pick could land under the newer file's name,
	// and the preview always took the filter in the box
	// async function showPreview(file: string) {
	// 	previewLoading = true;
	// 	previewFile = file;
	// 	previewPackets = [];
	// 	previewTimedOut = false;
	// 	previewFailed = false;
	// 	error = '';
	// 	try {
	// 		const response = await previewPcap(file, {
	// 			filter: bpfFilter || undefined,
	// 			limit: 100,
	// 		});
	// 		previewPackets = response.packets;
	// 		previewTimedOut = response.timed_out ?? false;
	// 	} catch (e) {
	// 		error = e instanceof Error ? e.message : 'Preview failed';
	// 		previewFailed = true;
	// 	} finally {
	// 		previewLoading = false;
	// 		scrollTimer = setTimeout(() => {
	// 			document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	// 		}, 50);
	// 	}
	// }
	// OLD CODE END
	async function showPreview(file: string, filter: string = bpfFilter) {
		const run = ++previewRun;
		previewLoading = true;
		previewFile = file;
		previewFilter = filter;
		previewPackets = [];
		previewTimedOut = false;
		previewFailed = false;
		error = '';
		try {
			const response = await previewPcap(file, {
				filter: filter || undefined,
				limit: 100,
			});
			if (run !== previewRun) return;
			previewPackets = response.packets;
			previewTimedOut = response.timed_out ?? false;
		} catch (e) {
			if (run !== previewRun) return;
			error = e instanceof Error ? e.message : 'Preview failed';
			previewFailed = true;
		} finally {
			if (run === previewRun) {
				previewLoading = false;
				scrollTimer = setTimeout(() => {
					document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
				}, 50);
			}
		}
	}

	function closePreview() {
		previewRun++; // a preview still loading for this file is dropped
		previewFile = '';
		previewPackets = [];
		previewTimedOut = false;
		previewFailed = false;
	}

	// ---------------------------------------------------------------------------
	// Interaction handlers
	// ---------------------------------------------------------------------------

	// OLD CODE START — DataTable owns the header toggles
	// function toggleFileSort(key: FileSortKey) {
	// 	if (fileSortKey === key) { fileSortDir = fileSortDir === 'asc' ? 'desc' : 'asc'; }
	// 	else { fileSortKey = key; fileSortDir = key === 'name' ? 'asc' : 'desc'; }
	// }
	//
	// function toggleResultSort(key: ResultSortKey) {
	// 	if (resultSortKey === key) { resultSortDir = resultSortDir === 'asc' ? 'desc' : 'asc'; }
	// 	else { resultSortKey = key; resultSortDir = key === 'name' ? 'asc' : 'desc'; }
	// }
	// OLD CODE END

	function applyQuickFilter(filter: string) {
		bpfFilter = filter;
	}

	function applyProtocolFilter(proto: string) {
		bpfFilter = PROTO_FILTER_MAP[proto] ?? proto.toLowerCase();
	}

	// OLD CODE START — NET-189: the download could only take the page's range (1 hour at least),
	// far more than one download can read at busy times
	// function downloadFiltered() {
	// 	if (!bpfFilter.trim()) return;
	// 	const { from, to } = getTimeRange();
	// 	window.open(getDownloadUrl(bpfFilter, { from, to }), '_blank');
	// }
	// OLD CODE END

	/** The download's window: its own start and end when both are set, else the page's range; a string says what's wrong. */
	function downloadWindow(): { from: string; to: string } | string {
		if (!downloadFrom && !downloadTo) return getTimeRange();
		const from = new Date(downloadFrom).getTime();
		const to = new Date(downloadTo).getTime();
		if (!Number.isFinite(from) || !Number.isFinite(to)) return 'Set both a start and an end for the download, or clear both.';
		if (to <= from) return 'The download’s end has to be after its start.';
		return { from: new Date(from).toISOString(), to: new Date(to).toISOString() };
	}

	// OLD CODE START — NET-373: a refused download's JSON opened in the new tab, away from the dates
	// function downloadFiltered() {
	// 	// OLD CODE: if (!bpfFilter.trim()) return; (NET-347: only a filter TShark accepted, or couldn't check)
	// 	if (!bpfFilter.trim() || !downloadReady) return;
	// 	const span = downloadWindow();
	// 	if (typeof span === 'string') {
	// 		error = span;
	// 		return;
	// 	}
	// 	error = '';
	// 	window.open(getDownloadUrl(bpfFilter, span), '_blank');
	// }
	// OLD CODE END
	function downloadFiltered() {
		if (!bpfFilter.trim() || !downloadReady) return;
		const span = downloadWindow();
		if (typeof span === 'string') {
			downloadProblem = span;
			return;
		}
		// a retry with the same filter and dates must not keep the last refusal on screen
		downloadProblem = '';
		blockedUrl = '';
		const url = getDownloadUrl(bpfFilter, { ...span, reply: 'page' });
		downloadTab = window.open(url, '_blank');
		if (!downloadTab) {
			downloadProblem = 'Your browser blocked the download tab.';
			blockedUrl = url;
		}
	}

	/** A refusal from the download's tab (lib/server/download-error-page.ts): say it here and close the tab */
	function onDownloadMessage(e: MessageEvent) {
		const data: unknown = e.data;
		if (e.origin !== window.location.origin || !downloadTab || e.source !== downloadTab) return;
		if (!data || typeof data !== 'object' || !('type' in data) || data.type !== DOWNLOAD_ERROR_MESSAGE) return;
		if (!('message' in data) || typeof data.message !== 'string') return;
		downloadProblem = data.message;
		downloadTab.close();
		downloadTab = null;
	}

	// Another filter, window or range: the last download's answer no longer belongs beside these fields.
	// Its tab, if it is still open, keeps its own readable page.
	$effect(() => {
		void [bpfFilter, downloadFrom, downloadTo, selectedTimeRange];
		untrack(() => {
			downloadTab = null;
			downloadProblem = '';
			blockedUrl = '';
		});
	});

	function downloadFile(file: string) {
		window.open(getFileDownloadUrl(file), '_blank');
	}

	function copyText(text: string) {
		navigator.clipboard.writeText(text);
	}

	function handleTimeRangeChange(value: string) {
		selectedTimeRange = value;
		fileWindow = null; // the picked slots were the last range's
		// OLD CODE START — PLAN §5.5: the guard drops the older range's load, so always reload
		// if (initialized) loadFiles();
		// OLD CODE END
		refresh.run();
	}

	// ---------------------------------------------------------------------------
	// Capture control
	// ---------------------------------------------------------------------------

	// OLD CODE START — PLAN §5.5: the capture state is read by the page loader with the file list
	// async function loadCaptureStatus() {
	// 	// OLD CODE START — a failed read came back as enabled: true and set the toggle on
	// 	// try {
	// 	// 	captureStatus = await getCaptureStatus();
	// 	// 	captureEnabled = captureStatus.enabled;
	// 	// } catch {
	// 	// 	// Default to enabled if API unreachable
	// 	// }
	// 	// OLD CODE END
	// 	try {
	// 		captureStatus = await fetchCaptureStatus();
	// 		captureEnabled = captureStatus.enabled;
	// 	} catch {
	// 		// state unknown: the label says so and the toggle stays disabled
	// 	}
	// }
	// OLD CODE END

	async function handleCaptureToggle() {
		if (captureEnabled === null) return;
		captureLoading = true;
		try {
			const result = await toggleCapture(!captureEnabled);
			captureEnabled = result.enabled;
			if (captureStatus) {
				captureStatus.enabled = result.enabled;
				captureStatus.containerRunning = result.containerRunning;
				captureStatus.containerStatus = result.containerStatus;
			}
		} catch (err) {
			// OLD CODE START — showed the bare daemon/HTTP message
			// error = err instanceof Error ? err.message : 'Toggle failed';
			// OLD CODE END
			error = `Couldn't turn capture ${captureEnabled ? 'off' : 'on'}: ${err instanceof Error ? err.message : 'the request failed'}`;
		} finally {
			captureLoading = false;
		}
	}

	/** The switch shows the daemon's state, never the click: put it back until the daemon answers. */
	function onCaptureSwitch(event: Event & { currentTarget: HTMLInputElement }) {
		event.currentTarget.checked = captureEnabled === true;
		handleCaptureToggle();
	}

	// ---------------------------------------------------------------------------
	// Tables
	// ---------------------------------------------------------------------------

	const fileColumns: Column<PcapFile>[] = [
		{ key: 'name', label: 'File', class: 'mono' },
		{ key: 'size_bytes', label: 'Size', numeric: true, cell: fileSizeCell },
		{ key: 'modified', label: 'Modified', cell: modifiedCell },
		// Every column sorts (repo rule); this one by file name
		{ key: 'actions', label: 'Actions', sortValue: (f) => f.name, cell: fileActionsCell },
	];

	const resultColumns: Column<PcapSearchResult>[] = [
		{ key: 'name', label: 'File', class: 'mono' },
		{ key: 'matching_packets', label: 'Matching', numeric: true, cell: matchingCell },
		{ key: 'size_bytes', label: 'Size', numeric: true, cell: sizeCell },
		{ key: 'modified', label: 'Modified', cell: modifiedCell },
		{ key: 'actions', label: 'Actions', sortValue: (r) => r.name, cell: downloadCell },
	];

	// Capture order first; every field is text, and the sort orders "10" after "9"
	const packetColumns: Column<PcapPacket>[] = [
		{ key: 'frame_number', label: '#', numeric: true, class: 'mono' },
		{ key: 'timestamp', label: 'Time', class: 'mono' },
		{ key: 'source', label: 'Source', class: 'mono' },
		{ key: 'destination', label: 'Destination', class: 'mono' },
		{ key: 'protocol', label: 'Protocol', class: 'mono', sortValue: packetProtocol, cell: protocolCell },
		{ key: 'length', label: 'Length', numeric: true, class: 'mono' },
		{ key: 'info', label: 'Info', class: 'info' },
	];

	const previewName = $derived(files.find((f) => f.file === previewFile)?.name ?? previewFile.split('/').at(-1) ?? '');

	// ---------------------------------------------------------------------------
	// Lifecycle
	// ---------------------------------------------------------------------------

	onMount(() => {
		// OLD CODE START — PLAN §5.5: one guarded loader reads the files and the capture state
		// loadCaptureStatus();
		// loadFiles().then(() => { initialized = true; });
		// OLD CODE END
		refresh.run();
		// OLD CODE: return () => { searchRun++; clearTimeout(scrollTimer); }; (review: a late preview set a timer after teardown)
		return () => { searchRun++; previewRun++; checkRun++; clearTimeout(scrollTimer); };
	});
</script>

{#snippet fileSizeCell(f: PcapFile)}<Bytes value={f.size_bytes} max={maxFileSize} display={formatBytes(f.size_bytes)} />{/snippet}
{#snippet sizeCell(r: PcapSearchResult)}{formatBytes(r.size_bytes)}{/snippet}
<!-- OLD CODE: {#snippet matchingCell(r: PcapSearchResult)}{fmt(r.matching_packets)}{/snippet} (NET-347: a stopped read's count is a minimum) -->
{#snippet matchingCell(r: PcapSearchResult)}{stoppedEarly(r.outcome) ? `at least ${fmt(r.matching_packets)}` : r.outcome === 'truncated' ? `${fmt(r.matching_packets)} (file ends mid-packet)` : fmt(r.matching_packets)}{/snippet}
{#snippet modifiedCell(f: { modified: string })}<span class="num">{formatTime(f.modified)}</span>{/snippet}
{#snippet protocolCell(pkt: PcapPacket)}{packetProtocol(pkt)}{/snippet}
{#snippet downloadCell(r: { file: string; name: string })}
	<button class="btn" type="button" aria-label="Download {r.name}" onclick={() => downloadFile(r.file)}><Icon name="download" />Download</button>
{/snippet}
{#snippet fileActionsCell(f: PcapFile)}
	<div class="row-actions">
		<button class="btn" type="button" aria-label="Copy the name {f.name}" onclick={() => copyText(f.name)}>Copy name</button>
		{@render downloadCell(f)}
	</div>
{/snippet}

<svelte:window onmessage={onDownloadMessage} />

<svelte:head>
	<title>PCAP Search - NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">PCAP search</h1>
		<p class="page-sub">Search and analyze captured network traffic</p>
	</div>
	<div class="head-actions">
		<!-- OLD CODE START — showed "Active" whenever capture was enabled, even with the
		     container down or the status request failed (DEFAULT_STATUS has enabled: true)
		<span class="capture-status-dot" class:active={captureEnabled}></span>
		<span class="capture-status-label">
			{captureEnabled ? 'Capture Active' : 'Capture Stopped'}
		</span>
		OLD CODE END -->
		<span class={['chip', captureView === 'active' && 'is-ok', captureView === 'stopped' && 'is-bad']}>
			{#if captureView === 'active'}<span class="live-dot"></span>{/if}{CAPTURE_LABELS[captureView]}
		</span>
		<label class="check-row">
			<input
				type="checkbox"
				role="switch"
				class="switch"
				checked={captureEnabled === true}
				disabled={captureLoading || captureEnabled === null}
				aria-label={captureEnabled === null ? "PCAP capture state unknown: can't change it" : undefined}
				onchange={onCaptureSwitch}
			/>
			PCAP capture
		</label>
		<Pills options={TIME_RANGES} value={selectedTimeRange} onchange={handleTimeRangeChange} ariaLabel="Time range" />
	</div>
</div>

<div class="grid">
	<KpiCard class="c-3" label="PCAP files" icon="pcap" value={filesUnknown ? '—' : totalFileCount} note={range.words} href="#files-section" />
	<KpiCard class="c-3" label="Total captured" icon="download" value={filesUnknown ? '—' : formatBytes(totalBytes)} note={range.words} />
	<KpiCard
		class="c-3"
		label="Newest capture"
		icon="changelog"
		value={newestCapture ? formatRelativeTime(newestCapture) : '—'}
		note={oldestCapture ? `Oldest ${formatRelativeTime(oldestCapture)}` : undefined}
	/>
	<!-- #63: it only counts the previewed packets, so the label says so -->
	<KpiCard
		class="c-3"
		label="Top protocol in preview"
		icon="connections"
		value={protocolBreakdown.length > 0 ? protocolBreakdown[0].protocol : '—'}
		note="Among the packets in the preview below"
	/>

	<!-- OLD CODE: sub="Files written per {range.bucket} · {range.words}" (NET-249: the table's bucket) -->
	<Card title="Capture timeline" sub="Files written per {range.bucketWords} · {range.words}" hero col class="c-8">
		{#if filesFailed && !filesLoading}
			<CardState state="error" title="Couldn't load the PCAP file list: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else if captureTimeline.length === 0 && filesLoading}
			<CardState state="loading" title="Loading the PCAP file list" />
		{:else if captureTimeline.length === 0}
			<CardState state="empty" icon="pcap" title="No PCAP files in this time range." message="Files appear here while capture is on. Pick a longer range to see older ones." />
		{:else}
			<AreaChart
				series={[{ key: 'files', label: 'Files', colour: 1, points: captureTimeline.map((b) => ({ t: b.label, v: b.count })) }]}
				formatX={(t) => formatTimestamp(String(t))}
				formatY={(v) => String(Math.round(v))}
				formatTip={(i) => `${formatTimestamp(captureTimeline[i]?.label ?? '')} · ${captureTimeline[i]?.count ?? 0} file(s), ${formatBytes(captureTimeline[i]?.bytes ?? 0)}`}
				highlightIndex={busiestBucket >= 0 ? busiestBucket : undefined}
				ariaLabel={busiestBucket >= 0
					? `Most files at ${formatTimestamp(captureTimeline[busiestBucket].label)}, with ${captureTimeline[busiestBucket].count} written`
					: 'No files written in this range'}
				onpick={pickFiles}
			/>
			<p class="card-sub pick-hint">Click a point or drag across the chart to list the files written then.</p>
		{/if}
	</Card>

	<Card title="Selected file" sub="The file in the packet preview" class="c-4">
		{#snippet actions()}
			{#if previewFile}
				<button class="icon-btn" type="button" aria-label="Close the preview" onclick={closePreview}><Icon name="close" /></button>
			{/if}
		{/snippet}
		{#if previewFile}
			{@const selectedFileObj = files.find((f) => f.file === previewFile)}
			<dl class="facts">
				<dt>Name</dt><dd class="mono">{selectedFileObj?.name ?? previewName}</dd>
				{#if selectedFileObj}
					<dt>Size</dt><dd class="num">{formatBytes(selectedFileObj.size_bytes)}</dd>
					<dt>Modified</dt><dd class="num">{formatTime(selectedFileObj.modified)}</dd>
					<dt>Path</dt><dd class="mono">{selectedFileObj.relative_path}</dd>
				{/if}
			</dl>
		{:else}
			<CardState state="empty" icon="pcap" title="No file selected" message="Click a file to inspect it." />
		{/if}
	</Card>

	<Card title="Search captures" sub="Wireshark display filter · {range.words}, newest files first" class="c-12">
		<div class="toolbar">
			<div class="filter-field">
				<SearchField
					id="pcap-filter"
					label="Wireshark display filter"
					placeholder="Wireshark display filter (e.g., tcp.port == 80, ip.addr == 192.168.1.1, dns)"
					size="toolbar"
					class="mono"
					bind:value={bpfFilter}
					onkeydown={(e) => e.key === 'Enter' && runSearch()}
					aria-invalid={fieldError ? 'true' : undefined}
					aria-describedby={fieldError ? 'pcap-filter-error' : checkUnknown ? 'pcap-filter-help' : undefined}
				/>
			</div>
			<!-- 2026-11-02: never disabled; a background search can take many minutes, so a new
			     filter or range must be able to replace it -->
			<button class="btn primary" type="button" onclick={() => runSearch()}>
				<Icon name="search" />{loading ? 'Searching…' : 'Search'}
			</button>
			<!-- OLD CODE: disabled={!bpfFilter.trim()} (NET-347: a filter TShark refuses could be downloaded) -->
			<button class="btn" type="button" onclick={downloadFiltered} disabled={!downloadReady}>
				<Icon name="download" />Download filtered
			</button>
		</div>
		{#if fieldError}
			<p id="pcap-filter-error" class="field-error filter-error" role="alert">{fieldError}</p>
		{:else if checkUnknown}
			<p id="pcap-filter-help" class="field-help">Couldn't check the filter just now. Download filtered checks it again before it starts.</p>
		{/if}
		<div class="toolbar">
			<label class="word" for="pcap-download-from">Download from</label>
			<!-- OLD CODE: the date inputs had no aria-describedby (NET-373: a refusal is shown beside them) -->
			<input id="pcap-download-from" class="input when" type="datetime-local" step="1" bind:value={downloadFrom} aria-describedby={downloadProblem ? 'pcap-download-error' : undefined} />
			<label class="word" for="pcap-download-to">to</label>
			<input id="pcap-download-to" class="input when" type="datetime-local" step="1" bind:value={downloadTo} aria-describedby={downloadProblem ? 'pcap-download-error' : undefined} />
		</div>
		{#if downloadProblem}
			<p id="pcap-download-error" class="field-error download-error" role="alert">
				{downloadProblem}
				{#if blockedUrl}
					<a class="link" href={blockedUrl} target="_blank" rel="noopener" onclick={() => { downloadProblem = ''; blockedUrl = ''; }}>Start the download</a>
				{/if}
			</p>
		{/if}
		<!-- OLD CODE START — NET-373: a refusal now arrives here, not in a new tab
		<p class="field-help download-help">
			Download filtered saves the {range.words} unless you set a start and an end here. One download reads a limited
			number of packets, so keep the window short; a window that holds too many opens a message saying how many.
		</p>
		OLD CODE END -->
		<p class="field-help download-help">
			Download filtered saves the {range.words} unless you set a start and an end here. One download reads a limited
			number of packets, so keep the window short; a window that holds too many says how many here.
		</p>
		<div class="toolbar">
			<Pills
				options={QUICK_FILTERS.map((qf) => ({ value: qf.filter as string, label: qf.label as string }))}
				value={bpfFilter}
				onchange={applyQuickFilter}
				ariaLabel="Quick filters"
			/>
		</div>
		<p class="field-help">
			Display filter syntax:
			<code class="tag">ip.addr == 1.2.3.4</code>
			<code class="tag">tcp.port == 443</code>
			<code class="tag">http.request</code>
			<code class="tag">dns</code>
		</p>
	</Card>

	{#if error}
		<!-- OLD CODE: <p class="notice is-error c-12" role="alert"><Icon name="warn" />{error}</p> (NET-347: a search that failed to start can be resent as it was) -->
		<p class="notice is-error c-12" role="alert">
			<Icon name="warn" /><span>{error}</span>
			{#if retrySearch?.message === error}
				<button class="btn" type="button" onclick={() => retrySearch && runSearch(retrySearch.search)}>Try again</button>
			{/if}
		</p>
	{/if}

	<!-- OLD CODE START — NET-347: the card said "N files match" for whatever was in the filter box
	{#if searchDone || loading}
		<Card
			title="Search results"
			sub={searchResults.length === 1 ? '1 file matches' : `${searchResults.length} files match`}
			class="c-12"
		>
	OLD CODE END -->
	{#if submitted && (searchDone || loading)}
		<Card
			title="Search results"
			sub="{searchResults.length === 1 ? '1 file matches' : `${searchResults.length} files match`} {submitted.filter}{coverage?.incomplete ? ' · incomplete' : ''}"
			class="c-12"
		>
			{#if loading}
				<p class="search-progress num" role="status">
					{#if searchProgress}
						<!-- OLD CODE START — #137: no sizes or estimate
						Checked {searchProgress.checked} of {searchProgress.total} files, newest first&hellip;
						OLD CODE END -->
						Checked {searchProgress.checked} of {searchProgress.total} files ({formatBytes(searchProgress.bytesChecked)} of {formatBytes(searchProgress.bytesTotal)}), newest first{searchEta(searchProgress)}&hellip;
					{:else}
						Starting search&hellip;
					{/if}
				</p>
			<!-- OLD CODE START — NET-347: failure counts alone, which didn't say how much was searched
			{:else if searchProgress && searchProgress.timedOut > 0}
				<p class="notice is-warn note"><Icon name="warn" />{timedOutNote(searchProgress.timedOut)}</p>
			{/if}
			{#if !loading && searchProgress && searchProgress.failed > 0}
				<p class="notice is-warn note">
					<Icon name="warn" />{searchProgress.failed === 1 ? "1 file couldn't be searched" : `${searchProgress.failed} files couldn't be searched`}{searchProgress.error ? `: ${searchProgress.error}` : '.'}
				</p>
			{/if}
			OLD CODE END -->
			{/if}
			{#if coverage && (coverage.incomplete || coverage.truncated > 0)}
				<div class="notice is-warn note coverage" role="status">
					<Icon name="warn" />
					<div>
						<!-- OLD CODE: <p>Fully searched {coverage.full} of {plural(coverage.total, 'file', 'files')}.{coverage.incomplete ? ' Results are incomplete.' : ''}</p> (the file being written read as missed on every recent search) -->
						{#if coverage.incomplete}
							<p>Fully searched {coverage.full + coverage.truncated} of {plural(coverage.total, 'file', 'files')}. Results are incomplete.</p>
						{/if}
						{#if coverage.early > 0}
							<p>Reading stopped early in {plural(coverage.early, 'file', 'files')}: {coverage.early === 1 ? 'its count is' : 'their counts are'} a minimum.</p>
						{/if}
						{#if coverage.unreadFailed > 0}
							<p>{coverage.unreadFailed === 1 ? "1 file couldn't be searched" : `${coverage.unreadFailed} files couldn't be searched`}{searchProgress?.error ? `: ${searchProgress.error}` : '.'}</p>
						{/if}
						{#if coverage.unreadFailed === 0 && coverage.earlyFailed > 0 && searchProgress?.error}
							<p>The first read error: {searchProgress.error}</p>
						{/if}
						{#if coverage.unreadTimedOut > 0}
							<p>{timedOutNote(coverage.unreadTimedOut)}</p>
						{/if}
						{#if coverage.truncated > 0}
							<p>{plural(coverage.truncated, 'file ends', 'files end')} mid-packet (still being written, or cut short): {coverage.truncated === 1 ? 'its count covers' : 'their counts cover'} the packets {coverage.truncated === 1 ? 'it holds' : 'they hold'}.</p>
						{/if}
					</div>
				</div>
			{/if}
			{#if searchResults.length === 0}
				<!-- OLD CODE: {#if searchDone && searchProgress && searchProgress.failed > 0} (NET-347: timed-out files weren't searched either) -->
				{#if searchDone && coverage?.incomplete}
					<CardState state="empty" icon="search" title="No matching packets in the files that could be searched." message="Try another filter, or a range without the unreadable files." />
				{:else if searchDone}
					<CardState state="empty" icon="search" title="No matching packets found in any PCAP file." message="Try another filter or a longer time range." />
				{/if}
			{:else}
				<DataTable
					columns={resultColumns}
					rows={searchResults}
					ariaLabel="Files matching the filter"
					rowKey={(r) => r.file}
					initialSort={{ key: 'matching_packets', dir: 'desc' }}
					onrowactivate={(r) => showPreview(r.file, submitted?.filter ?? bpfFilter)}
					rowLabel={(r) => `Preview ${r.name}`}
					selectedKey={previewFile || undefined}
				/>
			{/if}
		</Card>
	{/if}

	<Card
		title="Packet preview"
		sub={previewFile ? `${previewName} · first 100 packets${previewFilter ? ` matching ${previewFilter}` : ''}` : 'The first 100 packets of a file'}
		class="c-12"
	>
		{#snippet actions()}
			{#if previewFile}
				<div class="head-actions">
					<button class="btn" type="button" onclick={() => downloadFile(previewFile)}><Icon name="download" />Download</button>
					<button class="btn" type="button" onclick={closePreview}><Icon name="close" />Close</button>
				</div>
			{/if}
		{/snippet}
		<span id="preview-panel" class="anchor"></span>
		{#if !previewFile}
			<CardState state="empty" icon="pcap" title="No file selected" message="Select a file below or run a search to preview packets." />
		{:else if previewLoading}
			<CardState state="loading" title="Loading packets from {previewName}" />
		{:else if previewPackets.length > 0}
			<div class="packets">
				<DataTable
					columns={packetColumns}
					rows={previewPackets}
					ariaLabel="Packets in {previewName}"
					rowKey={(pkt) => pkt.frame_number}
					initialSort={{ key: 'frame_number', dir: 'asc' }}
				/>
			</div>
			<p class="tbl-foot">Showing {previewPackets.length} packets</p>
			{#if previewTimedOut}
				<p class="notice is-warn note"><Icon name="warn" />Stopped after 45 seconds: this file is large, so only its first part was read.</p>
			{/if}
		{:else if previewFailed}
			<CardState state="error" title="Couldn't preview {previewName}: the request failed." message={error || undefined} onaction={() => showPreview(previewFile, previewFilter)} />
		{:else if previewTimedOut}
			<p class="notice is-warn"><Icon name="warn" />No matching packets in the part of this file read within 45 seconds. The file is large; try a smaller file or a narrower time range.</p>
		{:else}
			<CardState state="empty" icon="pcap" title="No packets to display{previewFilter ? ` matching filter "${previewFilter}"` : ''}." message="Try another file, or clear the display filter." />
		{/if}
	</Card>

	<Card title="Available files" sub="{filesUnknown ? 'Capture files' : `${files.length} files`} · {range.words}" class="c-8 fit">
		<!-- NET-249: a timeline pick narrows this list; the notice says to what, and Show all clears it -->
		<span id="files-section" class="anchor"></span>
		{#if filesFailed && !filesLoading}
			<CardState state="error" title="Couldn't load the PCAP file list: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={() => refresh.run()} />
		{:else if files.length === 0 && filesLoading}
			<CardState state="loading" title="Loading PCAP files" />
		{:else if files.length === 0}
			<CardState state="empty" icon="pcap" title="No PCAP files found in the selected time range." message="Files appear here while capture is on." />
		{:else}
			{#if fileWindow}
				<p class="notice" role="status">
					<span>Showing the {fileWord(shownFiles.length)} written {windowWords(new Date(fileWindow.from).toISOString(), new Date(fileWindow.to - 1).toISOString())}, of the {fileWord(files.length)} listed.</span>
					<button class="btn" type="button" onclick={() => (fileWindow = null)}>Show all</button>
				</p>
			{/if}
			{#if shownFiles.length === 0}
				<CardState state="empty" icon="pcap" title="No file was written then." message="Pick another part of the timeline, or show all the files." />
			{:else}
			<!-- OLD CODE: rows={files} (NET-249: a timeline pick narrows the list) -->
			<DataTable
				columns={fileColumns}
				rows={shownFiles}
				ariaLabel="PCAP files"
				rowKey={(f) => f.file}
				initialSort={{ key: 'modified', dir: 'desc' }}
				onrowactivate={(f) => showPreview(f.file)}
				rowLabel={(f) => `Preview ${f.name}`}
				selectedKey={previewFile || undefined}
			/>
			{/if}
		{/if}
	</Card>

	<Card title="Protocols in preview" sub="Packets per protocol · share of the preview" class="c-4 fit">
		{#if protocolBreakdown.length === 0}
			<CardState state="empty" icon="connections" title="No preview loaded" message="Load a file preview to see protocol distribution." />
		{:else}
			<BarList
				items={protocolBreakdown.map((proto) => ({
					key: proto.protocol,
					label: proto.protocol,
					value: proto.count,
					display: fmt(proto.count),
					detail: `${(previewPackets.length > 0 ? (proto.count / previewPackets.length) * 100 : 0).toFixed(1)}%`,
					onclick: () => applyProtocolFilter(proto.protocol),
				}))}
			/>
		{/if}
	</Card>
</div>

<style>
	/* Layout glue the system lacks */
	/* In-card anchors for the KPI link and the preview scroll; the margin keeps the card head in view */
	.anchor { display: block; scroll-margin-top: calc(var(--sp-8) * 3); }
	/* The display filter takes the toolbar's free width (the system caps a toolbar search at 360px) */
	.filter-field { display: flex; flex: 1 1 28rem; min-width: 0; }
	.filter-field :global(.search) { max-width: none; }
	.search-progress { color: var(--text-2); font-size: var(--text-sm); margin-bottom: var(--sp-3); }
	/* NET-189: the download window's labels and inputs, as on Packet analysis */
	.word { font-size: var(--text-sm); color: var(--text-3); }
	.when { width: auto; }
	.download-help { margin-top: calc(var(--sp-2) * -1); margin-bottom: var(--sp-4); }
	.download-error { margin-top: calc(var(--sp-2) * -1); margin-bottom: var(--sp-3); }
	.note { margin-bottom: var(--sp-3); }
	.pick-hint { margin-top: var(--sp-2); }
	/* NET-347: TShark's refusal keeps its own line breaks (the caret under the bad token) */
	.filter-error { margin-top: var(--sp-2); white-space: pre-wrap; font-family: var(--font-mono); }
	.coverage p { margin: 0; }
	.coverage p + p { margin-top: var(--sp-1); }
	.notice .btn { margin-left: auto; }
	.row-actions { display: flex; gap: var(--sp-2); justify-content: flex-end; }
	/* A long preview scrolls inside the card */
	.packets { max-height: 32rem; overflow-y: auto; }
	.packets :global(td.info) { white-space: normal; overflow-wrap: anywhere; min-width: 16rem; }
</style>
