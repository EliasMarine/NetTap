<!--
  TopBar.svelte: global search, the page's "Updated" time and Refresh, notifications,
  and the daemon-offline warning (PLAN.md §5.5).
  Search is a WAI-ARIA 1.2 combobox (NET-202). The suggestions are the registry's devices whose
  name, hostname, IP or MAC contains the text, each opening its device page. Enter opens an IP's
  own page (device page on the LAN, address page otherwise), the device a name or MAC belongs to,
  a domain's page, or else Log Explorer with the text.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	// OLD CODE: import { getSearchSuggestions } from '$api/search'; (NET-202: canned sentences with a placeholder 192.168.1.1)
	import { getRegistryDevices, type RegistryDevice } from '$api/devices-registry';
	import Icon from '$lib/components/ui/Icon.svelte';
	import NotificationBell from '$components/NotificationBell.svelte';
	import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
	import { ipHref } from '$lib/stores/lan';
	// OLD CODE: import { searchTarget, updatedText } from './topbar'; (NET-202)
	import { deviceSuggestions, isSearchIp, searchTarget, toSuggestion, updatedText, type Suggestion } from './topbar';

	let { offline }: { offline: boolean } = $props();

	const LIST_ID = 'global-search-list';
	const SUGGEST_DELAY_MS = 200;
	const DEVICES_TTL_MS = 60_000;

	let input = $state<HTMLInputElement>();
	let query = $state('');
	// OLD CODE: let suggestions = $state<string[]>([]); (NET-202: devices, each with its own page)
	let suggestions = $state<Suggestion[]>([]);
	/** The typed name several devices share, while the list shows just them. */
	let matchesFor = $state<string | null>(null);
	let open = $state(false);
	let active = $state(-1);
	let status = $state<'idle' | 'ok' | 'error'>('idle');
	let timer: ReturnType<typeof setTimeout> | undefined;
	let requestId = 0;
	let devicesLoad: { at: number; promise: Promise<RegistryDevice[]> } | null = null;
	// OLD CODE: void $ipHref; read at mount (NET-202 review: every page, sign-in and setup included, then asked for the LAN policy, a 401 before sign-in)
	/** A store subscribes when first read: reading it as search takes focus loads the LAN policy before the first IP search. */
	const loadLanPolicy = () => void $ipHref;

	let announcement = $derived(
		!open || status === 'idle'
			? ''
			: status === 'error'
				? "Couldn't load suggestions."
				: matchesFor !== null
					? `${suggestions.length} devices are called "${matchesFor}". Pick one.`
					: suggestions.length === 0
						? `No matches for "${query}".`
						: `${suggestions.length} suggestion${suggestions.length === 1 ? '' : 's'}.`,
	);

	/** The registry for search, asked for at most once a minute and shared by every keystroke and submit. */
	// shortcut: the daemon lists at most 500 registry devices, so search matches those only; search on the daemon if a network outgrows that
	function searchDevices(): Promise<RegistryDevice[]> {
		if (!devicesLoad || Date.now() - devicesLoad.at > DEVICES_TTL_MS) {
			const promise = getRegistryDevices({ limit: 500 }).then((r) => r.devices);
			devicesLoad = { at: Date.now(), promise };
			// a failure is forgotten, so the next keystroke asks again
			promise.catch(() => {
				if (devicesLoad?.promise === promise) devicesLoad = null;
			});
		}
		return devicesLoad.promise;
	}

	// A debounce timer or a request still in flight would reopen the list after it was meant to close.
	function cancelPending() {
		clearTimeout(timer);
		requestId++;
	}

	function onInput() {
		cancelPending();
		active = -1;
		const q = query.trim();
		if (q.length < 2) {
			open = false;
			suggestions = [];
			status = 'idle';
			return;
		}
		timer = setTimeout(() => loadSuggestions(q), SUGGEST_DELAY_MS);
	}

	async function loadSuggestions(q: string) {
		const id = ++requestId;
		try {
			// OLD CODE START — NET-202: the daemon's canned sentences, not the network's devices
			// const res = await getSearchSuggestions(q);
			// if (id !== requestId) return; // a newer keystroke owns the list
			// // OLD CODE START — the daemon sends strings, so .text was undefined and every option was blank
			// // suggestions = res.suggestions.map((s) => s.text);
			// // OLD CODE END
			// suggestions = res.suggestions;
			// OLD CODE END
			const devices = await searchDevices();
			if (id !== requestId) return; // a newer keystroke owns the list
			suggestions = deviceSuggestions(devices, q);
			status = 'ok';
		} catch {
			if (id !== requestId) return;
			suggestions = [];
			status = 'error';
		}
		matchesFor = null;
		open = true;
	}

	// OLD CODE START — NET-202: one synchronous hand-off, every query to Log Explorer
	// function submit(text: string) {
	// 	const target = searchTarget(text);
	// 	if (!target) return;
	// 	cancelPending();
	// 	open = false;
	// 	active = -1;
	// 	goto(target);
	// }
	// OLD CODE END
	function go(href: string) {
		cancelPending();
		open = false;
		active = -1;
		goto(href);
	}

	/**
	 * An IP opens its page at once; other text first waits for the registry (the shared request),
	 * so an exact name finds its device whether or not the suggestions had loaded. A newer keystroke
	 * or Escape cancels the wait; a failed registry still searches (domain page or Log Explorer).
	 */
	async function submit(text: string) {
		const q = text.trim();
		if (!q) return;
		if (isSearchIp(q)) return go($ipHref(q));
		cancelPending();
		const id = ++requestId;
		const devices = await searchDevices().catch((): RegistryDevice[] => []);
		if (id !== requestId) return;
		const target = searchTarget(q, $ipHref, devices);
		if (!target) return;
		if ('href' in target) return go(target.href);
		// several devices share the name: list just them to pick from
		suggestions = target.matches.map(toSuggestion);
		matchesFor = q;
		status = 'ok';
		active = -1;
		open = true;
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'ArrowDown' && suggestions.length > 0) {
			e.preventDefault();
			open = true;
			active = (active + 1) % suggestions.length;
		} else if (e.key === 'ArrowUp' && suggestions.length > 0) {
			e.preventDefault();
			open = true;
			active = active <= 0 ? suggestions.length - 1 : active - 1;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			// OLD CODE: submit(active >= 0 && open ? suggestions[active] : query); (NET-202: a suggestion opens its own page)
			if (active >= 0 && open) go(suggestions[active].href);
			else void submit(query);
		} else if (e.key === 'Escape') {
			cancelPending();
			if (open) {
				open = false;
				active = -1;
			} else {
				query = '';
				suggestions = [];
				status = 'idle';
			}
		}
	}

	// ⌘K / Ctrl-K focuses search from anywhere.
	function onWindowKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			input?.focus();
		}
	}

	// "Updated N s ago" ticks while a page with a loader is showing.
	let now = $state(Date.now());
	$effect(() => {
		if (!$pageRefresh.available) return;
		const t = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(t);
	});
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="topbar">
	<div class="search-box">
		<label class="search">
			<span class="sr-only">Search IPs, domains and devices</span>
			<Icon name="search" />
			<input
				bind:this={input}
				bind:value={query}
				id="global-search"
				type="search"
				placeholder="Search IPs, domains, devices…"
				autocomplete="off"
				role="combobox"
				aria-expanded={open && suggestions.length > 0}
				aria-controls={LIST_ID}
				aria-autocomplete="list"
				aria-activedescendant={open && active >= 0 ? `${LIST_ID}-${active}` : undefined}
				onfocus={loadLanPolicy}
				oninput={onInput}
				onkeydown={onKeydown}
				onblur={() => setTimeout(() => (open = false), 150)}
			/>
			<kbd aria-hidden="true">⌘K</kbd>
		</label>
		<ul class="search-list" id={LIST_ID} role="listbox" aria-label="Search suggestions" hidden={!open || suggestions.length === 0}>
			<!-- OLD CODE: {#each suggestions as s, i (s)} … submit(s); … {s} (NET-202: a device, opened by its stored MAC) -->
			{#each suggestions as s, i (s.href)}
				<li
					id="{LIST_ID}-{i}"
					role="option"
					aria-selected={i === active}
					class:active={i === active}
					onmousedown={(e) => {
						e.preventDefault();
						go(s.href);
					}}
				>
					<span>{s.label}</span> <span class="mono s-detail">{s.detail}</span>
				</li>
			{/each}
		</ul>
		<span class="sr-only" role="status" aria-live="polite">{announcement}</span>
	</div>

	<div class="top-right">
		{#if offline}
			<span class="chip is-warn" role="status"><Icon name="warn" />Can't reach NetTap</span>
		{/if}
		{#if $pageRefresh.available}
			{#if $pageRefresh.status === 'partial'}
				<span class="chip is-warn">Some data failed to refresh</span>
			{/if}
			<span>{updatedText($pageRefresh.updatedAt, now)}</span>
			<button
				class="icon-btn"
				type="button"
				aria-label="Refresh this page"
				disabled={$pageRefresh.running}
				onclick={() => refreshPage()}
			>
				<Icon name="refresh" />
			</button>
		{/if}
		<NotificationBell />
	</div>
</div>

<style>
	.search-box {
		position: relative;
		flex: 1 1 auto;
		max-width: 480px;
	}
	.search-box .search {
		max-width: none;
	}
	.search-list {
		position: absolute;
		z-index: 40;
		top: calc(100% + var(--sp-1));
		left: 0;
		right: 0;
		margin: 0;
		padding: var(--sp-1);
		list-style: none;
		background: var(--surface-1);
		border: 1px solid var(--line-strong);
		border-radius: var(--r-md);
		box-shadow: var(--shadow-pop);
		/* NET-202: several devices can share a typed name, so a long list scrolls */
		max-height: 60vh;
		overflow-y: auto;
	}
	.search-list li {
		display: flex;
		flex-direction: column;
		padding: var(--sp-2) var(--sp-3);
		border-radius: var(--r-sm);
		font-size: var(--text-sm);
		color: var(--text-2);
		cursor: pointer;
	}
	.search-list li.active,
	.search-list li:hover {
		background: var(--surface-3);
		color: var(--text-1);
	}
	.s-detail {
		font-size: var(--text-xs);
		color: var(--text-3);
	}
</style>
