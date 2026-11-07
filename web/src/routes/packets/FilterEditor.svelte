<!--
  FilterEditor.svelte: a Wireshark display filter with field suggestions (NET-188, Start.dc
  "Write your own filter"). Suggestions come from TShark's own field list once the word being
  typed has 3 letters; each new word aborts the request before it. Once typing pauses, the whole
  filter is checked against the newest capture file, and an answer for older text is dropped.
-->
<script lang="ts">
	import { onDestroy } from 'svelte';
	import { checkFilter, suggestFields, type FieldSuggestion } from '$lib/api/packets';
	import { MAX_FILTER } from '$lib/utils/packet-query';
	import Icon from '$lib/components/ui/Icon.svelte';

	interface Props {
		value: string;
		/** Enter with no suggestion open */
		onsubmit?: () => void;
	}

	let { value = $bindable(), onsubmit }: Props = $props();

	const PAUSE_MS = 350;
	const uid = $props.id();

	let suggestions = $state<FieldSuggestion[]>([]);
	let more = $state(false);
	let active = $state(0);
	let open = $state(false);
	let check = $state<{ text: string; ok: boolean; message: string } | null>(null);
	let checking = $state(false);
	let input = $state<HTMLInputElement>();

	let suggestTimer: ReturnType<typeof setTimeout> | undefined;
	let checkTimer: ReturnType<typeof setTimeout> | undefined;
	let suggestAbort: AbortController | null = null;

	onDestroy(() => {
		clearTimeout(suggestTimer);
		clearTimeout(checkTimer);
		suggestAbort?.abort();
	});

	/** The field name being typed: the word that ends at the caret. */
	function wordAtCaret(): { word: string; start: number; end: number } {
		const end = input?.selectionStart ?? value.length;
		const start = end - (/[a-z0-9_.-]*$/i.exec(value.slice(0, end))?.[0].length ?? 0);
		return { word: value.slice(start, end), start, end };
	}

	function oninput() {
		open = false;
		suggestAbort?.abort();
		clearTimeout(suggestTimer);
		clearTimeout(checkTimer);
		const { word } = wordAtCaret();
		if (/^[a-z0-9_.-]{3,80}$/i.test(word)) suggestTimer = setTimeout(() => void suggest(word.toLowerCase()), PAUSE_MS);
		checkTimer = setTimeout(() => void runCheck(value), PAUSE_MS);
	}

	async function suggest(prefix: string) {
		const controller = new AbortController();
		suggestAbort = controller;
		try {
			const res = await suggestFields(prefix, controller.signal);
			if (controller.signal.aborted) return;
			suggestions = res.fields;
			more = res.more;
			active = 0;
			open = res.fields.length > 0;
		} catch {
			// Suggestions are a help only: a failed or aborted lookup leaves typing as it is
			if (!controller.signal.aborted) open = false;
		}
	}

	let checkSeq = 0;

	async function runCheck(text: string) {
		const seq = ++checkSeq;
		if (!text.trim()) {
			check = null;
			checking = false;
			return;
		}
		checking = true;
		try {
			await checkFilter(text);
			if (text === value) check = { text, ok: true, message: 'TShark accepts this filter.' };
		} catch (err) {
			if (text === value) check = { text, ok: false, message: err instanceof Error ? err.message : 'The check failed.' };
		} finally {
			if (seq === checkSeq) checking = false;
		}
	}

	function accept(s: FieldSuggestion) {
		const { start, end } = wordAtCaret();
		value = `${value.slice(0, start)}${s.field}${value.slice(end)}`;
		open = false;
		const caret = start + s.field.length;
		requestAnimationFrame(() => input?.setSelectionRange(caret, caret));
		clearTimeout(checkTimer);
		checkTimer = setTimeout(() => void runCheck(value), PAUSE_MS);
	}

	function onkeydown(event: KeyboardEvent) {
		if (open && suggestions.length) {
			if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
				event.preventDefault();
				active = (active + (event.key === 'ArrowDown' ? 1 : suggestions.length - 1)) % suggestions.length;
				return;
			}
			if (event.key === 'Enter' || event.key === 'Tab') {
				event.preventDefault();
				accept(suggestions[active]);
				return;
			}
			if (event.key === 'Escape') {
				event.preventDefault();
				open = false;
				return;
			}
		}
		if (event.key === 'Enter' && onsubmit) {
			event.preventDefault();
			onsubmit();
		}
	}

	const current = $derived(check && check.text === value ? check : null);
</script>

<div class="editor">
	<label class="label" for="{uid}-filter">Display filter</label>
	<div class="combo">
		<input
			bind:this={input}
			bind:value
			id="{uid}-filter"
			class="input mono"
			type="text"
			role="combobox"
			autocomplete="off"
			spellcheck="false"
			maxlength={MAX_FILTER}
			placeholder="ip.addr == 192.168.1.20 && tls"
			aria-autocomplete="list"
			aria-expanded={open}
			aria-controls="{uid}-fields"
			aria-activedescendant={open ? `${uid}-field-${active}` : undefined}
			aria-invalid={current && !current.ok ? 'true' : undefined}
			aria-describedby="{uid}-status {uid}-help"
			{oninput}
			{onkeydown}
			onblur={() => setTimeout(() => (open = false), 150)}
		/>
		{#if open}
			<ul class="fields" role="listbox" id="{uid}-fields" aria-label="Fields">
				{#each suggestions as s, i (s.field)}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- The keyboard path is the input's arrow keys and Enter (combobox pattern) -->
					<li
						role="option"
						id="{uid}-field-{i}"
						aria-selected={i === active}
						onmousedown={(e) => e.preventDefault()}
						onclick={() => accept(s)}
					>
						<code>{s.field}</code><span>{s.name} · {s.type}</span>
					</li>
				{/each}
				{#if more}<li class="more" role="presentation">More fields start with this; keep typing to narrow them.</li>{/if}
			</ul>
		{/if}
	</div>
	<p class="status" id="{uid}-status" role="status">
		{#if checking && !current}
			Checking…
		{:else if current?.ok}
			<span class="ok"><Icon name="check" />{current.message}</span>
		{:else if current}
			<span class="bad"><Icon name="warn" />{current.message}</span>
		{/if}
	</p>
	<p class="field-help" id="{uid}-help">
		Wireshark display filter syntax, up to {MAX_FILTER} characters. Checked against the newest capture file when you pause typing; suggestions come from TShark's own field list.
	</p>
</div>

<style>
	/* Layout glue: the suggestion list hangs under the input */
	.editor { display: flex; flex-direction: column; gap: var(--sp-1); min-width: 0; }
	.combo { position: relative; }
	.fields {
		position: absolute; z-index: 5; top: calc(100% + var(--sp-1)); left: 0; right: 0;
		list-style: none; margin: 0; padding: var(--sp-1); max-height: calc(var(--sp-8) * 8); overflow-y: auto;
		background: var(--surface-1); border: 1px solid var(--line-strong); border-radius: var(--r-md); box-shadow: var(--shadow-pop);
	}
	.fields li { display: flex; justify-content: space-between; gap: var(--sp-3); padding: var(--sp-2) var(--sp-3); border-radius: var(--r-sm); cursor: pointer; font-size: var(--text-sm); color: var(--text-1); }
	.fields li span { color: var(--text-3); font-size: var(--text-xs); text-align: right; }
	.fields li[aria-selected='true'] { background: var(--surface-3); }
	.fields li.more { cursor: default; color: var(--text-3); font-size: var(--text-xs); }
	code { font-family: var(--font-mono); overflow-wrap: anywhere; }
	.status { min-height: 1.5em; font-size: var(--text-sm); color: var(--text-2); margin: 0; }
	.ok, .bad { display: inline-flex; align-items: flex-start; gap: var(--sp-1); }
	.ok { color: var(--ok); }
	.bad { color: var(--sev-critical); }
	.ok :global(.ic), .bad :global(.ic) { width: 16px; height: 16px; flex: none; margin-top: 2px; }
</style>
