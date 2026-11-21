<!--
  QuestionBuilder.svelte: "What do you want to see?" (NET-188, Start.dc). Who, what, when and how
  many write the filter; before anything runs it shows that filter, the files the search will
  read and their size, by the daemon's own file rule (packets-view planFiles). A filter typed in
  "Write your own filter" (`override`) replaces the written one until a choice changes.
-->
<script module lang="ts">
	export interface DeviceOption {
		ip: string;
		label: string;
	}
</script>

<script lang="ts">
	import { untrack } from 'svelte';
	import type { CapturesResponse, PacketRowLimit } from '$lib/api/packets';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import { KINDS, LIBRARY } from '$lib/utils/packet-library';
	import { formatBytes } from '$lib/api/logs';
	import { MAX_WINDOW_SECONDS, windowFor, type PacketQuestion, type PacketUrlState, type WhenPreset } from '$lib/utils/packet-query';
	// OLD CODE: import { clockTime, LIMIT_OPTIONS, planFiles, plural, ROUTER_FILTER } from './packets-view'; (NET-349: the limit check moved to plan-check)
	import { clockTime, LIMIT_OPTIONS, plural, ROUTER_FILTER } from './packets-view';
	import { planCheck } from './plan-check';

	interface Props {
		question: PacketQuestion;
		override: string | null;
		/** The router's address, which "Lookups that skip your router" needs */
		router: string;
		/** The filter the choices write (packets-view writtenFilter) */
		written: { filter: string; problem: string };
		devices: readonly DeviceOption[];
		captures: CapturesResponse | null;
		/** NET-349: epoch ms when `captures` arrived, the "now" of a "last N minutes" window */
		capturesAt: number | null;
		/** NET-349: loads the capture list again; Find packets calls it when the list is over a minute old */
		reloadCaptures: () => Promise<unknown>;
		onsearch: (state: PacketUrlState) => void;
		onwriteown: () => void;
	}

	// OLD CODE: let { question = $bindable(), override = $bindable(), router = $bindable(), written, devices, captures, onsearch, onwriteown }: Props = $props(); (NET-349: + capturesAt, reloadCaptures)
	let { question = $bindable(), override = $bindable(), router = $bindable(), written, devices, captures, capturesAt, reloadCaptures, onsearch, onwriteown }: Props = $props();

	const uid = $props.id();
	let rangeFrom = $state('');
	let rangeTo = $state('');
	let portText = $state(untrack(() => (question.port === null ? '' : String(question.port))));
	let error = $state('');
	/** NET-349: the last Find packets was refused for size; shown only while the search is still over */
	let refusedForSize = $state(false);

	// A common question or a library filter sets the port from outside: show it
	$effect(() => {
		const port = question.port;
		untrack(() => {
			const text = port === null ? '' : String(port);
			if (!Number.isNaN(port) && text !== portText.trim()) portText = text;
		});
	});

	const WHEN_OPTIONS = [
		{ value: '300', label: 'Last 5 min' },
		{ value: '900', label: 'Last 15 min' },
		{ value: '1800', label: 'Last 30 min' },
		{ value: 'range', label: 'From… to…' },
	];
	const LIBRARY_LABELS = new Map(LIBRARY.flatMap((g) => g.filters).map((f) => [f.id, f.label] as const));

	/** Every change to a choice writes the filter again, so a typed filter never hides one. */
	function change(next: Partial<PacketQuestion>) {
		question = { ...question, ...next };
		override = null;
		error = '';
		refusedForSize = false;
	}

	function toggleKind(id: string) {
		if (id === 'all') return change({ kinds: ['all'] });
		const rest = question.kinds.filter((k) => k !== 'all');
		const kinds = rest.includes(id) ? rest.filter((k) => k !== id) : [...rest, id];
		change({ kinds: kinds.length ? kinds : ['all'] });
	}

	const extraKinds = $derived(question.kinds.filter((k) => !KINDS.some((kind) => kind.id === k)));

	/** datetime-local text → whole epoch seconds, or null. */
	function epochOf(text: string): string | null {
		const ms = new Date(text).getTime();
		return text && Number.isFinite(ms) ? String(Math.floor(ms / 1000)) : null;
	}

	function changeWhen(value: string) {
		if (value === 'range') {
			const to = new Date();
			const from = new Date(to.getTime() - 15 * 60_000);
			const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 19);
			rangeFrom ||= local(from);
			rangeTo ||= local(to);
			return setRange();
		}
		change({ when: { kind: 'last', seconds: Number(value) as WhenPreset } });
	}

	function setRange() {
		const from = epochOf(rangeFrom);
		const to = epochOf(rangeTo);
		change({ when: { kind: 'range', from: from ?? '', to: to ?? '' } });
	}

	const filter = $derived(override ?? written.filter);
	const problem = $derived(override === null ? written.problem : '');

	const windowProblem = $derived.by(() => {
		if (question.when.kind !== 'range') return '';
		const { from, to } = question.when;
		if (!from || !to) return 'Pick a start and an end time.';
		const seconds = Number(to) - Number(from);
		if (seconds <= 0) return 'The end has to be after the start.';
		if (seconds > MAX_WINDOW_SECONDS) return 'A search covers at most 30 minutes. Pick a shorter stretch.';
		return '';
	});

	// OLD CODE START — NET-349: the preview took "now" from the clock but the files from an older capture list, and the search took a later "now" again
	// // The window as it stands now; a "last 15 minutes" search takes its own "now" when it runs
	// const preview = $derived(windowProblem ? null : windowFor(question.when, Date.now()));
	// const plan = $derived(preview && captures ? planFiles(captures.files, preview.from, preview.to) : null);
	// const overLimit = $derived(
	// 	plan && captures ? plan.read.length > captures.limits.max_files || plan.bytes > captures.limits.max_bytes : false,
	// );
	// OLD CODE END
	// A "last N minutes" window ends when the capture list arrived, so the files shown, the limit
	// check and the search all describe that one moment; with no list yet, it ends now
	const preview = $derived(windowProblem ? null : windowFor(question.when, capturesAt ?? Date.now()));
	const checked = $derived(preview && captures ? planCheck(captures, preview.from, preview.to) : null);
	const plan = $derived(checked?.plan ?? null);
	const overLimit = $derived(checked?.overLimit ?? false);
	const limitWarning = $derived(
		captures
			? `That's more than one search reads (${captures.limits.max_files} files or ${formatBytes(captures.limits.max_bytes)}). Pick a shorter stretch of time. This estimate is from when the page last loaded its list of capture files.`
			: '',
	);
	// OLD CODE START — NET-349 review: a list up to a minute old ended the window before what you just did
	// const STALE_MS = 60_000;
	// const stale = () => capturesAt === null || Date.now() - capturesAt > STALE_MS;
	// OLD CODE END

	/** The over-limit warning while the search is over the limit, for the editor card's own button. */
	export const blockedBy = (): string => (overLimit ? limitWarning : '');

	/** Says why the question can't run as it stands (and returns true), or clears the last reason. */
	function refuse(): boolean {
		error = problem || windowProblem;
		refusedForSize = !error && overLimit;
		return error !== '' || refusedForSize;
	}

	// OLD CODE START — NET-349: ran a search over the limit, and took a later "now" than the preview showed
	// /** Run the search with the choices as they stand; "Write your own filter" calls it too. */
	// export function search() {
	// 	if (problem || windowProblem) {
	// 		error = problem || windowProblem;
	// 		return;
	// 	}
	// 	const { from, to } = windowFor(question.when, Date.now());
	// 	onsearch({ filter, from, to, limit: question.limit, device: question.device, conn: null });
	// }
	// OLD CODE END
	/**
	 * Run the search with the choices as they stand, over exactly the window shown; "Write your own
	 * filter" calls it too. A "last N minutes" window loads the list first, so it ends at the press.
	 */
	// OLD CODE START — NET-349 review: each press compared against its own "before", so a second press after
	// the list landed (the rest of the page still loading) read the new list as "didn't arrive"
	// let reloading: Promise<unknown> | null = null;
	// … const before = capturesAt; reloading ??= reloadCaptures().finally(() => (reloading = null)); await reloading;
	// … if (capturesAt === null || capturesAt === before) { error = …; return; }
	// OLD CODE END
	/** The list reload in flight: every press and Check again shares it, and its answer */
	let reloading: Promise<boolean> | null = null;

	/** Loads the capture list again; true when a new one arrived (a failed load leaves the old time). */
	function reloadList(): Promise<boolean> {
		if (!reloading) {
			const before = capturesAt;
			reloading = reloadCaptures()
				.then(() => capturesAt !== null && capturesAt !== before)
				.finally(() => (reloading = null));
		}
		return reloading;
	}

	export async function search() {
		if (refuse()) return;
		if (question.when.kind === 'last') {
			if (!(await reloadList())) {
				error = "NetTap couldn't load its list of capture files again, so nothing was searched. Try again in a moment.";
				return;
			}
			if (refuse()) return;
		}
		if (!preview) return;
		onsearch({ filter, from: preview.from, to: preview.to, limit: question.limit, device: question.device, conn: null });
	}
</script>

<Card hero title="What do you want to see?" sub="Pick a device, the kind of traffic and when · each choice narrows the search">
	<div class="rows">
		<div class="row">
			<span class="k">Who</span>
			<div class="v">
				<label class="sr-only" for="{uid}-device">Device</label>
				<select
					id="{uid}-device"
					class="select"
					value={question.device ?? ''}
					onchange={(e) => change({ device: e.currentTarget.value || null })}
				>
					<option value="">Any device</option>
					{#each devices as d (d.ip)}<option value={d.ip}>{d.label}</option>{/each}
				</select>
				<span class="word">talking to</span>
				<label class="sr-only" for="{uid}-other">Other side</label>
				<select
					id="{uid}-other"
					class="select"
					value={question.other.kind}
					onchange={(e) => {
						const kind = e.currentTarget.value;
						change({ other: kind === 'address' ? { kind, value: '' } : kind === 'internet' ? { kind } : { kind: 'anyone' } });
					}}
				>
					<option value="anyone">anyone</option>
					<option value="address">an address or site…</option>
					<option value="internet">the internet</option>
				</select>
				{#if question.other.kind === 'address'}
					<label class="sr-only" for="{uid}-address">Address or site</label>
					<input
						id="{uid}-address"
						class="input mono addr"
						type="text"
						placeholder="203.0.113.5 or example.com"
						value={question.other.value}
						oninput={(e) => change({ other: { kind: 'address', value: e.currentTarget.value } })}
						aria-describedby="{uid}-address-help"
					/>
				{/if}
				<span class="word">on port</span>
				<label class="sr-only" for="{uid}-port">Port</label>
				<input
					id="{uid}-port"
					class="input mono port"
					type="text"
					inputmode="numeric"
					placeholder="any"
					bind:value={portText}
					oninput={() => {
						const text = portText.trim();
						change({ port: text === '' ? null : /^\d+$/.test(text) ? Number(text) : Number.NaN });
					}}
				/>
				{#if question.other.kind === 'address'}<span class="field-help" id="{uid}-address-help">A site name matches exactly; www.example.com is a different name</span>{/if}
			</div>
		</div>

		<div class="row">
			<span class="k">What</span>
			<div class="v">
				<div class="pills kinds" role="group" aria-label="Kind of traffic">
					{#each KINDS as kind (kind.id)}
						<button class="pill" type="button" aria-pressed={question.kinds.includes(kind.id)} onclick={() => toggleKind(kind.id)}>{kind.label}</button>
					{/each}
				</div>
				{#each extraKinds as id (id)}
					<span class="chip">
						{LIBRARY_LABELS.get(id) ?? id}
						<button class="chip-x" type="button" aria-label="Remove {LIBRARY_LABELS.get(id) ?? id}" onclick={() => toggleKind(id)}><Icon name="close" /></button>
					</span>
				{/each}
				{#if question.kinds.includes(ROUTER_FILTER)}
					<label class="word" for="{uid}-router">Your router's address</label>
					<input
						id="{uid}-router"
						class="input mono addr"
						type="text"
						placeholder="its IP address"
						bind:value={router}
						oninput={() => change({})}
						aria-describedby="{uid}-router-help"
					/>
					<span class="field-help" id="{uid}-router-help">NetTap can't tell which device is your router; its settings page shows the address</span>
				{/if}
			</div>
		</div>

		<div class="row">
			<span class="k">When</span>
			<div class="v">
				<Pills
					options={WHEN_OPTIONS}
					value={question.when.kind === 'range' ? 'range' : String(question.when.seconds)}
					onchange={changeWhen}
					ariaLabel="When"
				/>
				{#if question.when.kind === 'range'}
					<label class="word" for="{uid}-from">from</label>
					<input id="{uid}-from" class="input when" type="datetime-local" step="1" bind:value={rangeFrom} onchange={setRange} />
					<label class="word" for="{uid}-to">to</label>
					<input id="{uid}-to" class="input when" type="datetime-local" step="1" bind:value={rangeTo} onchange={setRange} />
					<span class="field-help">At most 30 minutes, the longest stretch one search reads</span>
				{/if}
			</div>
		</div>

		<div class="row">
			<span class="k">How many</span>
			<div class="v">
				<Pills
					options={LIMIT_OPTIONS}
					value={String(question.limit)}
					onchange={(v) => change({ limit: Number(v) as PacketRowLimit })}
					ariaLabel="Packets to show"
				/>
				<span class="word">the first ones that match, oldest first</span>
			</div>
		</div>
	</div>

	<div class="plan" aria-live="polite">
		{#if problem || windowProblem}
			<p class="notice is-warn"><Icon name="warn" />{problem || windowProblem}</p>
		{:else if preview}
			<p>
				NetTap will read
				{#if plan}<b>{plural(plan.read.length, 'capture file')}</b> ({clockTime(preview.from, false)} to {clockTime(preview.to, false)}, {formatBytes(plan.bytes)}){:else}the capture files from {clockTime(preview.from, false)} to {clockTime(preview.to, false)}{/if}
				{#if plan?.unindexed}and up to {plan.unindexed.toLocaleString('en-GB')} more not indexed yet, if {plan.unindexed === 1 ? 'it holds' : 'they hold'} packets from this window,{/if}
				<!-- OLD CODE: with {filter ? 'this filter:' : 'no filter, so every packet:'} (NET-283: with no filter nothing follows, so a colon left the line hanging) -->
				with {filter ? 'this filter:' : 'no filter, so every packet.'}
			</p>
			{#if filter}<code class="filter">{filter}</code>{/if}
			{#if override !== null}<p class="field-help">You wrote this filter. Changing a choice above writes it again.</p>{/if}
			{#if plan?.failed.length}
				<p class="notice is-warn"><Icon name="warn" />{plural(plan.failed.length, 'capture file')} can't be read, so any search is incomplete: it may hold packets from this window.</p>
			{/if}
			<!-- OLD CODE START — NET-349: the warning didn't say how old its estimate was, and nothing pointed at it
			{#if overLimit && captures}
				<p class="notice is-warn"><Icon name="warn" />That's more than one search reads ({captures.limits.max_files} files or {formatBytes(captures.limits.max_bytes)}). Pick a shorter stretch of time.</p>
			{/if}
			OLD CODE END -->
			<!-- OLD CODE: <p class="notice is-warn" id="{uid}-limit"><Icon name="warn" />{limitWarning}</p> (NET-349 review: a disabled Find packets left no way to refresh the estimate here) -->
			{#if overLimit}
				<p class="notice is-warn" id="{uid}-limit"><Icon name="warn" />{limitWarning}</p>
				<button class="btn check-again" type="button" onclick={() => reloadList()}><Icon name="refresh" />Check again</button>
			{/if}
		{/if}
		<!-- OLD CODE: {#if error && !(problem || windowProblem)}<p class="field-error" role="alert">{error}</p>{/if} (NET-349: + a refusal for size, until a choice or a new capture list fits) -->
		{#if error && !(problem || windowProblem)}<p class="field-error" role="alert">{error}</p>
		{:else if refusedForSize && overLimit}<p class="field-error" role="alert">{limitWarning}</p>{/if}
	</div>

	<div class="form-actions">
		<button class="btn" type="button" onclick={onwriteown}>Write my own filter</button>
		<!-- OLD CODE: <button class="btn primary" type="button" onclick={search}><Icon name="search" />Find packets</button> (NET-349: offered a search the daemon refuses) -->
		<button class="btn primary" type="button" disabled={overLimit} aria-describedby={overLimit ? `${uid}-limit` : undefined} onclick={search}><Icon name="search" />Find packets</button>
	</div>
</Card>

<style>
	/* Layout glue: label column and wrapping controls */
	.rows { display: flex; flex-direction: column; gap: var(--sp-4); }
	.row { display: grid; grid-template-columns: calc(var(--sp-8) * 3) minmax(0, 1fr); gap: var(--sp-3); align-items: start; }
	.k { font-size: var(--text-sm); font-weight: 600; color: var(--text-2); padding-top: var(--sp-2); }
	.v { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); min-width: 0; }
	.v .select { width: auto; max-width: 100%; }
	.word { font-size: var(--text-sm); color: var(--text-3); }
	/* A hint takes its own line under the controls it explains */
	.v .field-help { flex-basis: 100%; margin: 0; }
	.check-again { margin-top: var(--sp-2); }
	/* Nine kinds: the track wraps instead of running past the card (bundle.css:42 makes it flex: none) */
	.kinds { flex: 0 1 auto; flex-wrap: wrap; max-width: 100%; border-radius: var(--r-lg); }
	.addr { width: calc(var(--sp-8) * 8); max-width: 100%; }
	.port { width: calc(var(--sp-8) * 2.5); }
	.when { width: auto; }
	.plan { display: flex; flex-direction: column; gap: var(--sp-2); margin-top: var(--sp-5); padding-top: var(--sp-4); border-top: 1px solid var(--line); font-size: var(--text-sm); color: var(--text-2); }
	.plan p { margin: 0; }
	.filter { display: block; font-family: var(--font-mono); font-size: var(--text-sm); color: var(--text-1); background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-md); padding: var(--sp-2) var(--sp-3); overflow-wrap: anywhere; }
	.chip-x { all: unset; display: inline-grid; place-items: center; cursor: pointer; color: var(--text-2); }
	.chip-x:focus-visible { outline: 2px solid var(--focus); border-radius: var(--r-xs); }
	@container app (max-width: 760px) {
		.row { grid-template-columns: minmax(0, 1fr); gap: var(--sp-1); }
		.k { padding-top: 0; }
	}
</style>
