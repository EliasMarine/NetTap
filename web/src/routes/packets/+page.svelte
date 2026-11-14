<script lang="ts">
	/**
	 * Packet analysis (NET-188): what crossed the network, packet by packet, from NetTap's saved
	 * captures. With no search in the URL it starts from a question (who, what, when, how many);
	 * with one (`readUrlState`) it shows the daemon's answer. Every figure comes from the rows or
	 * the daemon's reply and says what it covers.
	 */
	// OLD CODE: import { onDestroy, tick, untrack } from 'svelte'; (NET-276: afterNavigate replaced the URL effect)
	import { onDestroy, tick } from 'svelte';
	// OLD CODE: import { goto } from '$app/navigation'; (NET-276)
	import { afterNavigate, goto } from '$app/navigation';
	import { page as pageStore } from '$app/stores';
	import { getCaptures, searchPackets, type CaptureFile, type CapturesResponse, type PacketSearchResult } from '$lib/api/packets';
	import { fetchCaptureStatus, type CaptureStatus } from '$lib/api/capture';
	import { getTSharkStatus, type TSharkStatus } from '$lib/api/tshark';
	import { getRegistryDevices } from '$lib/api/devices-registry';
	import { outcome, registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { lanPolicy } from '$lib/stores/lan';
	import { namesByIp } from '$lib/utils/device-names';
	import type { CommonQuestion } from '$lib/utils/packet-library';
	import { packetsUrl, readUrlState, type PacketQuestion, type PacketUrlState } from '$lib/utils/packet-query';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import FilterEditor from './FilterEditor.svelte';
	import FilterLibrary from './FilterLibrary.svelte';
	import QuestionBuilder, { type DeviceOption } from './QuestionBuilder.svelte';
	import ResultsView from './ResultsView.svelte';
	import SavedCaptures from './SavedCaptures.svelte';
	import StartKpis from './StartKpis.svelte';
	import { fileSpanWindow, isIp, searchProblem, writtenFilter, type SearchProblem } from './packets-view';

	const message = (err: unknown) => (err instanceof Error && err.message ? err.message : 'The request failed.');

	// ---- The URL ----
	const urlState = $derived(readUrlState($pageStore.url.searchParams));
	const urlKey = $derived(urlState ? packetsUrl(urlState) : null);
	/** A link with search parameters that don't make a valid search: say so, never guess. */
	const badLink = $derived(!urlState && $pageStore.url.searchParams.size > 0);

	// ---- What the page loads ----
	let captures = $state<CapturesResponse | null>(null);
	let capturesError = $state<string | null>(null);
	let capture = $state<CaptureStatus | null>(null);
	let captureFailed = $state(false);
	let reader = $state<TSharkStatus | null | undefined>(undefined);
	let devices = $state<ReadonlyMap<string, string>>(new Map());
	let deviceOptions = $state<DeviceOption[]>([]);
	let nowMs = $state(Date.now());

	let result = $state<{ key: string; data: PacketSearchResult } | null>(null);
	let problem = $state<{ key: string; problem: SearchProblem } | null>(null);
	let started = $state<number | null>(null);
	let elapsed = $state<number | null>(null);
	let ticker: ReturnType<typeof setInterval> | undefined;
	/**
	 * NET-276: the URL's search waits for Run. A search holds one of the daemon's two packet-reader slots for
	 * up to ~45 s, and a link from another site makes this page ask for it from the same origin, so only a
	 * navigation inside NetTap runs it straight away. True until one says so: nothing searches by default.
	 */
	let held = $state(true);

	// ---- The question (first visit) ----
	let question = $state<PacketQuestion>({
		device: null,
		other: { kind: 'anyone' },
		port: null,
		kinds: ['all'],
		when: { kind: 'last', seconds: 900 },
		limit: 100,
	});
	let override = $state<string | null>(null);
	/** The router's address, for "Lookups that skip your router" */
	let router = $state('');
	let showEditor = $state(false);
	let builder = $state<{ search: () => void }>();
	const written = $derived(writtenFilter(question, $lanPolicy, router));

	const refresh = registerPageRefresh(load);
	onDestroy(() => {
		refresh.unregister();
		clearInterval(ticker);
	});

	let appliedUrl: string | null = null;
	// OLD CODE START — NET-276: loaded on any URL change, so a full load from another site's link searched at once
	// $effect(() => {
	// 	const key = $pageStore.url.search;
	// 	untrack(() => {
	// 		if (key === appliedUrl) return;
	// 		appliedUrl = key;
	// 		void refresh.run();
	// 	});
	// });
	// OLD CODE END
	// Runs on mount and after every navigation to a URL; 'enter' is a full load (a bookmark, a pasted link,
	// another site, a new tab), every other type is a navigation inside NetTap (a link, goto, Back or Forward)
	afterNavigate(({ type }) => {
		const key = $pageStore.url.search;
		if (key === appliedUrl) return;
		appliedUrl = key;
		held = type === 'enter';
		void refresh.run();
	});

	function startTicker() {
		clearInterval(ticker);
		started = Date.now();
		elapsed = 0;
		ticker = setInterval(() => (elapsed = started === null ? null : Math.floor((Date.now() - started) / 1000)), 1000);
	}

	function stopTicker() {
		clearInterval(ticker);
		started = null;
		elapsed = null;
	}

	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const wanted = urlState;
		const key = urlKey;
		const live = () => guard.current(g);
		nowMs = Date.now();

		const tasks: Promise<unknown>[] = [
			getCaptures().then(
				(c) => {
					if (live()) [captures, capturesError] = [c, null];
				},
				(err) => {
					if (live()) capturesError = message(err);
					throw err;
				},
			),
			// Without the registry, devices show by address
			getRegistryDevices({ limit: 200 }).then((r) => {
				if (!live()) return;
				devices = namesByIp(r.devices);
				deviceOptions = r.devices
					.flatMap((d) => d.ips.filter((ip) => isIp(ip)).map((ip) => ({ ip, label: `${devices.get(ip) ?? d.display_name ?? ip} · ${ip}` })))
					.sort((a, b) => a.label.localeCompare(b.label, 'en-GB'));
			}),
		];

		if (wanted && key && held) {
			// NET-276: opened from outside NetTap; the search waits for Run, the captures and names still load
			stopTicker();
		} else if (wanted && key) {
			// The same search again keeps its packets on screen until the new answer lands
			if (result?.key !== key) result = null;
			problem = null;
			startTicker();
			tasks.push(
				searchPackets({ filter: wanted.filter, from: wanted.from, to: wanted.to, limit: wanted.limit }).then(
					(data) => {
						if (!live()) return;
						result = { key, data };
						problem = null;
						stopTicker();
					},
					(err) => {
						if (live()) {
							problem = { key, problem: searchProblem(err) };
							stopTicker();
						}
						throw err;
					},
				),
			);
		} else {
			stopTicker();
			tasks.push(
				fetchCaptureStatus().then(
					(c) => {
						if (live()) [capture, captureFailed] = [c, false];
					},
					(err) => {
						if (live()) captureFailed = true;
						throw err;
					},
				),
				getTSharkStatus().then(
					(r) => {
						if (live()) reader = r;
					},
					(err) => {
						if (live()) reader = null;
						throw err;
					},
				),
			);
		}

		const settled = await Promise.allSettled(tasks);
		if (!live()) return 'skipped';
		// The registry only adds names; the page's figures don't depend on it
		return outcome(settled.filter((_, i) => i !== 1));
	}

	function search(state: PacketUrlState) {
		const href = packetsUrl(state);
		if (href === `${$pageStore.url.pathname}${$pageStore.url.search}`) {
			rerun();
			return;
		}
		void goto(href);
	}

	/** The same search again from scratch: its captures changed, the reader was busy, or it waited for Run. */
	function rerun() {
		held = false;
		result = null;
		void refresh.run();
	}

	async function scrollTo(id: string) {
		await tick();
		document.getElementById(id)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
	}

	function ask(q: CommonQuestion) {
		question = { ...q.question, device: question.device, limit: question.limit };
		override = null;
		void scrollTo('packet-question');
	}

	function useFilter(id: string) {
		question = { ...question, kinds: [id] };
		override = null;
		void scrollTo('packet-question');
	}

	function writeOwn() {
		showEditor = true;
		void scrollTo('packet-editor');
	}

	/** "Search this file's time span": the question's filter over the file's own packet times. */
	function spanHref(file: CaptureFile): string | null {
		const span = fileSpanWindow(file);
		const filter = override ?? written.filter;
		if (!span || (override === null && written.problem)) return null;
		return packetsUrl({ filter, from: span.from, to: span.to, limit: question.limit, device: question.device, conn: null });
	}
</script>

<svelte:head>
	<title>Packet analysis | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Packet analysis</h1>
		<p class="page-sub">
			See exactly what crossed your network, packet by packet, from NetTap's saved captures.
			{urlState
				? 'Encrypted traffic shows its size, timing and the site it went to, not its content.'
				: 'Start with a question; NetTap picks the files and writes the filter.'}
		</p>
	</div>
</div>

{#if badLink}
	<p class="notice is-warn" role="status">
		<Icon name="warn" />This link's search couldn't be read (a time, the window of at most 30 minutes, or the number of packets isn't valid), so nothing was searched. Start a new search below.
	</p>
{/if}

{#if urlState}
	{#key urlKey}
		<ResultsView
			query={urlState}
			result={result?.key === urlKey ? result.data : null}
			problem={problem?.key === urlKey ? problem.problem : null}
			{elapsed}
			{held}
			{captures}
			{devices}
			onsearch={search}
			onrerun={rerun}
		/>
	{/key}
{:else}
	<div class="grid">
		<StartKpis {captures} {capture} {reader} {nowMs} failed={{ captures: !!capturesError, capture: captureFailed, reader: reader === null }} />
		<div class="c-8 anchor" id="packet-question">
			<QuestionBuilder
				bind:this={builder}
				bind:question
				bind:override
				bind:router
				{written}
				devices={deviceOptions}
				{captures}
				onsearch={search}
				onwriteown={writeOwn}
			/>
		</div>
		<FilterLibrary onask={ask} onuse={useFilter} />
		{#if showEditor}
			<div class="c-12 anchor" id="packet-editor">
				<Card title="Write your own filter" sub="Wireshark display filter syntax · suggestions come from TShark's own field list">
					{#snippet actions()}<button class="btn" type="button" onclick={() => (showEditor = false)}>Hide</button>{/snippet}
					<FilterEditor bind:value={() => override ?? written.filter, (v) => (override = v)} onsubmit={() => builder?.search()} />
					<div class="form-actions">
						<button class="btn primary" type="button" onclick={() => builder?.search()}><Icon name="search" />Find packets</button>
					</div>
				</Card>
			</div>
		{/if}
		<SavedCaptures {captures} error={capturesError} onretry={() => void refresh.run()} {spanHref} />
	</div>
{/if}

<style>
	/* Layout glue: a card wrapped for its scroll anchor keeps the grid span */
	.anchor { display: flex; flex-direction: column; min-width: 0; scroll-margin-top: var(--sp-4); }
	.anchor > :global(.card) { flex: 1; }
</style>
