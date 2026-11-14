<!--
  OwnerRulesCard.svelte: the "Your own rules" editor on Settings › Suricata rules (NET-191 slice 3).
  The page loads the file with the rest of the page (registerPageRefresh) and passes it in; this card
  owns the editor's text, the check and the save. `saving` is bound so the page can hold its other
  changes while Suricata tests and reloads the rules.
-->
<script lang="ts">
	import { tick, untrack } from 'svelte';
	import {
		checkOwnerRules,
		saveOwnerRules,
		type OwnerRules,
		type OwnerRuleError,
		type OwnerRulesReply,
	} from '$lib/api/suricata-rules';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { fmt } from '$lib/utils/drilldown';
	import { loadFailed } from '$lib/utils/load-failed';

	interface Props {
		/** The page's first load has landed. */
		loaded: boolean;
		/** The last owner rules file loaded; null until one lands. */
		owner: OwnerRules | null;
		/** The last refresh failed; the card keeps showing `owner`. */
		failed: boolean;
		/** Suricata can't read the owner rules folder yet (live owner_rules is null or missing), so saving is off. */
		unmounted: boolean;
		/** Another change is running: a rule update, an ET Pro change or the restart they cause. */
		busy: boolean;
		/** Reads the page again: Try again, and after every save. */
		reload: () => Promise<unknown>;
		/** True while a save runs. */
		saving?: boolean;
		/** NET-273: the editor's text differs from the file last loaded, so Settings can guard a tab switch. */
		dirty?: boolean;
	}

	let { loaded, owner, failed, unmounted, busy, reload, saving = $bindable(false), dirty = $bindable(false) }: Props = $props();

	type Result = { tone: 'is-ok' | 'is-warn' | 'is-error'; text: string; errors: OwnerRuleError[] };

	// The editor's text. A new file from a refresh replaces it only while it is unedited.
	let draft = $state('');
	// The file text `draft` was last taken from; null before the first file lands
	// OLD CODE: let base: string | null = null; (NET-273: state, so `dirty` follows it)
	let base = $state<string | null>(null);
	const unsaved = $derived(base !== null && draft !== base);
	$effect(() => {
		dirty = unsaved;
	});
	$effect.pre(() => {
		const content = owner?.content;
		if (content === undefined) return;
		untrack(() => {
			if (base === null || draft === base) draft = content;
			base = content;
		});
	});

	// "Write a rule" in the empty state opens the editor; a save keeps it open, even one that empties the file
	let writing = $state(false);
	let checking = $state(false);
	// The last check's or save's answer, shown until the next one or until the text changes
	let result = $state<Result | null>(null);
	let box = $state<HTMLTextAreaElement>();

	const ruleCount = (n: number) => `${fmt(n)} ${n === 1 ? 'rule' : 'rules'}`;
	// KB as 1,024 bytes, as the daemon's "over 256 KB" refusal counts it (formatBytes would say 262.1 KB)
	const maxKb = $derived(owner ? Math.round(owner.max_bytes / 1024) : 0);

	/** The daemon refuses more than max_bytes of text: say so without sending it. */
	function tooBig(): Result | null {
		if (!owner || new TextEncoder().encode(draft).length <= owner.max_bytes) return null;
		return { tone: 'is-error', text: `Your rules are over ${fmt(maxKb)} KB, so they weren't sent. Remove some rules and try again.`, errors: [] };
	}

	/** Focus moves to the box after a failure and back to the button after a success, unless the owner has moved it meanwhile. */
	async function refocus(r: Result, from: HTMLElement) {
		await tick();
		const active = document.activeElement;
		if (active !== null && active !== document.body && active !== from) return;
		(r.tone === 'is-ok' ? from : box)?.focus();
	}

	async function openEditor() {
		writing = true;
		await tick();
		box?.focus();
	}

	/** A refusal: the daemon's sentence, then its per-line reasons. */
	const refused = (r: OwnerRulesReply, tone: Result['tone'] = 'is-error', after = ''): Result => ({
		tone,
		text: `${r.error ?? ''}${after}`,
		errors: r.errors,
	});

	/** Validator only: fast, and changes nothing on the device. The box is read-only meanwhile, so the answer is about its text. */
	async function check(): Promise<Result> {
		checking = true;
		try {
			const r = await checkOwnerRules(draft);
			if (!r.ok) return refused(r);
			const counted = typeof r.rule_count === 'number' ? ` in ${ruleCount(r.rule_count)}` : '';
			return { tone: 'is-ok', text: `No problems found${counted}. Suricata tests them again when you save.`, errors: [] };
		} catch {
			return { tone: 'is-error', text: "Couldn't check the rules: the request failed.", errors: [] };
		} finally {
			checking = false;
		}
	}

	async function handleCheck(e: MouseEvent) {
		const from = e.currentTarget as HTMLElement;
		result = null;
		const next = tooBig() ?? (await check());
		result = next;
		await refocus(next, from);
	}

	// No answer reached the web server (a timeout or the daemon unreachable), or the browser lost the request:
	// the save may still have happened
	const UNCONFIRMED: Result = { tone: 'is-warn', text: "NetTap couldn't confirm the result. Check Rules active before saving again.", errors: [] };

	/** What a save answered: green when it loaded; amber when a rule update was in the way or the result is unknown; red when it was refused. */
	function saveOutcome(r: OwnerRulesReply): Result {
		if (r.ok) {
			const n = r.rule_count;
			const loadedLine = typeof r.engine?.loaded === 'number' ? ` Suricata has ${ruleCount(r.engine.loaded)} loaded.` : '';
			const text =
				typeof n !== 'number' ? 'Saved and loaded.' : n === 0 ? 'Saved. Your own rules are removed.' : `Saved and loaded ${ruleCount(n)} of your own.`;
			return { tone: 'is-ok', text: text + loadedLine, errors: [] };
		}
		if (r.daemonAvailable === false) return UNCONFIRMED;
		if (r.status === 409) return refused(r, 'is-warn');
		if (r.status === 422) return refused(r, 'is-error', ' Suricata keeps running the rules it had.');
		return refused(r);
	}

	async function save(): Promise<Result> {
		try {
			return saveOutcome(await saveOwnerRules(draft));
		} catch {
			return UNCONFIRMED;
		}
	}

	async function handleSave(e: MouseEvent) {
		const from = e.currentTarget as HTMLElement;
		writing = true;
		result = null;
		const big = tooBig();
		if (big) {
			result = big;
			await refocus(big, from);
			return;
		}
		saving = true;
		const next = await save();
		// shown at once; the buttons stay off until the page has read the counts again
		result = next;
		try {
			await reload();
		} finally {
			saving = false;
		}
		await refocus(next, from);
	}
</script>

<Card title="Your own rules" sub="Suricata alert rules you write · checked and tested before they load" class="c-12">
	{#if !loaded}
		<CardState state="loading" title="Loading your own rules" />
	{:else if !owner}
		<CardState
			state="error"
			title="Couldn't load your own rules: the request failed."
			message="Try again in a moment. If it keeps failing, check the System page."
			onaction={() => void reload()}
		/>
	{:else}
		{#if failed}
			<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('your own rules', true)}</span></p>
		{/if}
		{#if !writing && owner.content.trim() === ''}
			<CardState
				state="empty"
				icon="threats"
				title="No rules of your own yet"
				message="Write an alert rule for something only your network has, such as a device that should never reach the internet."
				actionLabel="Write a rule"
				onaction={openEditor}
			/>
		{:else}
			{#if unmounted}
				<p class="notice is-warn" role="status">
					<Icon name="warn" /><span>Suricata isn't connected to your rules folder yet, so saving is off: rules saved now wouldn't load. Updating NetTap connects it.</span>
				</p>
			{/if}
			<p class="card-text">
				One <span class="mono">alert</span> rule per line, each with a <span class="mono">sid</span> from 1000000 to 1999999. At most
				{fmt(owner.max_rules)} rules or {fmt(maxKb)} KB. Lines starting with # are comments. Saving an empty box
				removes all your rules.
			</p>
			<div class="field">
				<label class="label" for="owner-rules">Rules</label>
				<textarea
					id="owner-rules"
					class="textarea mono owner-rules"
					bind:value={draft}
					bind:this={box}
					oninput={() => (result = null)}
					readonly={saving || checking}
					spellcheck="false"
					autocomplete="off"
					rows="10"
					placeholder={'alert tcp $HOME_NET any -> any 23 (msg:"Telnet out of my network"; sid:1000001; rev:1;)'}
					aria-invalid={result?.errors.length ? 'true' : undefined}
					aria-describedby={result?.errors.length ? 'owner-rules-errors' : undefined}
				></textarea>
			</div>
			{#if saving && !result}
				<p class="notice is-warn" role="status">
					<Icon name="warn" /><span>Suricata is testing and loading your rules. This can take up to 4 minutes.</span>
				</p>
			{:else if result}
				<p class={['notice', result.tone]} role={result.tone === 'is-ok' ? 'status' : 'alert'}>
					<Icon name={result.tone === 'is-ok' ? 'check' : 'warn'} /><span>{result.text}</span>
				</p>
				{#if result.errors.length}
					<ul class="line-errors" id="owner-rules-errors">
						{#each result.errors as e, i (i)}
							<li class="field-error">{e.line == null ? e.message : `Line ${e.line}: ${e.message}`}</li>
						{/each}
					</ul>
				{/if}
			{/if}
			<div class="form-actions">
				{#if unsaved}<span class="unsaved">Unsaved changes</span>{/if}
				<button class="btn" type="button" onclick={handleCheck} disabled={busy || checking || saving}>
					{checking ? 'Checking…' : 'Check rules'}
				</button>
				<button class="btn primary" type="button" onclick={handleSave} disabled={busy || checking || saving || unmounted}>
					{saving ? 'Saving and loading…' : 'Save and load'}
				</button>
			</div>
		{/if}
	{/if}
</Card>

<style>
	/* the page's own text and notice spacing */
	.card-text { color: var(--text-2); font-size: var(--text-sm); line-height: 1.5; margin-bottom: var(--sp-4); }
	.notice { margin-bottom: var(--sp-3); }
	/* one rule per visual line, so "Line 3" is the third line in the box */
	.owner-rules { white-space: pre; overflow-x: auto; }
	.line-errors { list-style: none; margin: 0 0 var(--sp-3); padding: 0; display: flex; flex-direction: column; gap: var(--sp-1); }
</style>
