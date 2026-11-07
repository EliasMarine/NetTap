<!--
  FilterLibrary.svelte: the common questions and the 37 ready-made filters (NET-188, Start.dc).
  "Use" puts a filter in the question builder; the device and time come from its choices.
  Filter text is the library's own data, shown as text.
-->
<script lang="ts">
	import Card from '$lib/components/ui/Card.svelte';
	import Pills from '$lib/components/ui/Pills.svelte';
	import SearchField from '$lib/components/ui/SearchField.svelte';
	import { COMMON_QUESTIONS, LIBRARY, type CommonQuestion } from '$lib/utils/packet-library';
	import { filterFor } from '$lib/utils/packet-query';
	import { CONVERSATION_FILTER, ROUTER_EXAMPLE_ADDRESS, ROUTER_FILTER } from './packets-view';

	interface Props {
		onask: (q: CommonQuestion) => void;
		onuse: (id: string) => void;
	}

	let { onask, onuse }: Props = $props();

	const uid = $props.id();
	const TOTAL = LIBRARY.reduce((n, g) => n + g.filters.length, 0);

	let query = $state('');
	let group = $state('all');

	const groupOptions = [
		{ value: 'all', label: `All ${TOTAL}` },
		...LIBRARY.map((g) => ({ value: g.id, label: `${g.label} ${g.filters.length}` })),
	];

	const shown = $derived.by(() => {
		const q = query.trim().toLowerCase();
		return LIBRARY.filter((g) => group === 'all' || g.id === group)
			.map((g) => ({
				...g,
				filters: g.filters.filter((f) => !q || `${f.label} ${f.explain} ${f.filter}`.toLowerCase().includes(q)),
			}))
			.filter((g) => g.filters.length > 0);
	});

	/** A common question's filter exactly as it runs before a device is picked (empty for every packet). */
	const questionFilter = (q: CommonQuestion) => filterFor({ device: null, ...q.question }, null);
</script>

<Card class="c-4" title="Common questions" sub="One click fills in the search · pick the device after">
	<ul class="questions">
		{#each COMMON_QUESTIONS as q (q.id)}
			<li>
				<button class="question" type="button" onclick={() => onask(q)}>
					<b>{q.label}</b>
					<span>{q.explain}</span>
					{#if questionFilter(q)}<code>{questionFilter(q)}</code>{/if}
				</button>
			</li>
		{/each}
	</ul>
	<a class="all-link" href="#{uid}-library">All {TOTAL} in the filter library</a>
</Card>

<section class="card c-12" id="{uid}-library" aria-labelledby="{uid}-library-title">
	<div class="card-head">
		<div>
			<h2 class="card-title" id="{uid}-library-title">Filter library</h2>
			<p class="card-sub">{TOTAL} ready-made filters · Use puts it in the search; the device and time come from the choices above</p>
		</div>
	</div>
	<div class="toolbar">
		<SearchField id="{uid}-search" label="Search the library" placeholder="Search {TOTAL} filters…" size="toolbar" bind:value={query} />
		<div class="track"><Pills options={groupOptions} bind:value={group} ariaLabel="Filter group" /></div>
	</div>
	<p class="field-help note">
		NetTap only sees traffic that crosses its own link. Two devices talking through the same switch or Wi-Fi never cross it, so no filter can show that traffic.
	</p>
	{#if shown.length === 0}
		<p class="empty">No filter matches “{query}”.</p>
	{:else}
		<div class="groups">
			{#each shown as g (g.id)}
				<section aria-labelledby="{uid}-g-{g.id}">
					<h3 id="{uid}-g-{g.id}">{g.label}<span>{g.filters.length}</span></h3>
					<ul>
						{#each g.filters as f (f.id)}
							<li>
								<div>
									<b>{f.label}</b>
									<span>{f.explain}</span>
									{#if f.id === ROUTER_FILTER}
										<!-- The example address is a slot the user fills in, never a value to run -->
										{@const [before, after] = f.filter.split(ROUTER_EXAMPLE_ADDRESS)}
										<code>{before}<span class="slot">router address</span>{after}</code>
									{:else}
										<code>{f.filter}</code>
									{/if}
								</div>
								{#if f.id === CONVERSATION_FILTER}
									<!-- A stream number means something only inside one search: the packet's drawer offers it -->
									<span class="needs">Open a packet, then choose Show its whole conversation</span>
								{:else}
									<button class="btn" type="button" aria-label="Use {f.label}" onclick={() => onuse(f.id)}>Use</button>
								{/if}
							</li>
						{/each}
					</ul>
				</section>
			{/each}
		</div>
	{/if}
</section>

<style>
	/* Layout glue: question buttons, and the library in up to three columns */
	.questions { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-2); }
	.question {
		all: unset; box-sizing: border-box; width: 100%; display: flex; flex-direction: column; gap: 2px; cursor: pointer;
		padding: var(--sp-2) var(--sp-3); border-radius: var(--r-md); border: 1px solid var(--line); color: var(--text-1); font-size: var(--text-sm);
	}
	.question:hover { background: var(--row-hover); }
	.question:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.question span { color: var(--text-2); font-size: var(--text-xs); }
	code { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--text-3); overflow-wrap: anywhere; }
	.all-link { display: inline-block; margin-top: var(--sp-3); font-size: var(--text-sm); }
	.toolbar { display: flex; flex-wrap: wrap; gap: var(--sp-3); align-items: center; margin-bottom: var(--sp-3); }
	.note { margin: 0 0 var(--sp-4); }
	/* Seven group pills scroll inside their track, as a11y.css correction 5 does on phones */
	.track { min-width: 0; max-width: 100%; overflow-x: auto; scrollbar-width: none; }
	.empty { color: var(--text-2); font-size: var(--text-sm); }
	.groups { columns: 3 calc(var(--sp-8) * 9); column-gap: var(--sp-6); }
	.groups section { break-inside: avoid; margin-bottom: var(--sp-5); }
	h3 { display: flex; gap: var(--sp-2); align-items: baseline; font: 500 var(--text-base)/1.3 var(--font-display); margin: 0 0 var(--sp-2); }
	h3 span { color: var(--text-3); font-size: var(--text-xs); }
	ul { list-style: none; margin: 0; padding: 0; }
	.groups li { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--sp-3); padding: var(--sp-2) 0; border-top: 1px solid var(--line); }
	.groups li div { display: flex; flex-direction: column; gap: 2px; min-width: 0; font-size: var(--text-sm); }
	.groups li span { color: var(--text-2); font-size: var(--text-xs); }
	.slot { padding: 0 var(--sp-1); border: 1px dashed var(--line); border-radius: var(--r-xs); color: var(--text-2); font-style: italic; }
	.groups li .needs { flex: 0 1 calc(var(--sp-8) * 5); color: var(--text-3); text-align: right; }
</style>
