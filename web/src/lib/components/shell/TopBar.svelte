<!--
  TopBar.svelte: global search, the page's "Updated" time and Refresh, notifications,
  and the daemon-offline warning (PLAN.md §5.5).
  Search is a WAI-ARIA 1.2 combobox over the daemon's suggestions; choosing a query opens
  it in Log Explorer, which already reads ?ip= and ?query= on load.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { getSearchSuggestions } from '$api/search';
	import Icon from '$lib/components/ui/Icon.svelte';
	import NotificationBell from '$components/NotificationBell.svelte';
	import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
	import { searchTarget, updatedText } from './topbar';

	let { offline }: { offline: boolean } = $props();

	const LIST_ID = 'global-search-list';
	const SUGGEST_DELAY_MS = 200;

	let input = $state<HTMLInputElement>();
	let query = $state('');
	let suggestions = $state<string[]>([]);
	let open = $state(false);
	let active = $state(-1);
	let status = $state<'idle' | 'ok' | 'error'>('idle');
	let timer: ReturnType<typeof setTimeout> | undefined;
	let requestId = 0;

	let announcement = $derived(
		!open || status === 'idle'
			? ''
			: status === 'error'
				? "Couldn't load suggestions."
				: suggestions.length === 0
					? `No matches for "${query}".`
					: `${suggestions.length} suggestion${suggestions.length === 1 ? '' : 's'}.`,
	);

	function onInput() {
		clearTimeout(timer);
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
			const res = await getSearchSuggestions(q);
			if (id !== requestId) return; // a newer keystroke owns the list
			suggestions = res.suggestions.map((s) => s.text);
			status = 'ok';
		} catch {
			if (id !== requestId) return;
			suggestions = [];
			status = 'error';
		}
		open = true;
	}

	function submit(text: string) {
		const target = searchTarget(text);
		if (!target) return;
		open = false;
		active = -1;
		goto(target);
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
			submit(active >= 0 && open ? suggestions[active] : query);
		} else if (e.key === 'Escape') {
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
				oninput={onInput}
				onkeydown={onKeydown}
				onblur={() => setTimeout(() => (open = false), 150)}
			/>
			<kbd aria-hidden="true">⌘K</kbd>
		</label>
		<ul class="search-list" id={LIST_ID} role="listbox" aria-label="Search suggestions" hidden={!open || suggestions.length === 0}>
			{#each suggestions as s, i (s)}
				<li
					id="{LIST_ID}-{i}"
					role="option"
					aria-selected={i === active}
					class:active={i === active}
					onmousedown={(e) => {
						e.preventDefault();
						submit(s);
					}}
				>
					{s}
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
	}
	.search-list li {
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
</style>
