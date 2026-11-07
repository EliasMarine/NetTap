<!--
  OwnerRulesCard.svelte: the "Your own rules" editor on Settings › Suricata rules (NET-191 slice 3).
  The page loads the file with the rest of the page (registerPageRefresh) and passes it in; this card
  owns the editor's text, the check and the save. `saving` is bound so the page can hold its other
  changes while Suricata tests and reloads the rules.
-->
<script lang="ts">
	import { untrack } from 'svelte';
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
		/** Suricata can't read the owner rules folder yet (live owner_rules is null), so saving is off. */
		unmounted: boolean;
		/** Another change is running: a rule update, an ET Pro change or the restart they cause. */
		busy: boolean;
		/** Reads the page again: Try again, and after every save. */
		reload: () => Promise<unknown>;
		/** True while a save runs. */
		saving?: boolean;
	}

	let { loaded, owner, failed, unmounted, busy, reload, saving = $bindable(false) }: Props = $props();

	type Result = { tone: 'is-ok' | 'is-warn' | 'is-error'; text: string; errors: OwnerRuleError[] };

	// The editor's text. A new file from a refresh replaces it only while it is unedited.
	let draft = $state('');
	// The file text `draft` was last taken from; null before the first file lands
	let base: string | null = null;
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
	// The last check's or save's answer, shown until the next one
	let result = $state<Result | null>(null);

	const ruleCount = (n: number) => `${fmt(n)} ${n === 1 ? 'rule' : 'rules'}`;

	/** A refusal: the daemon's sentence, then its per-line reasons. */
	const refused = (r: OwnerRulesReply, tone: Result['tone'] = 'is-error', after = ''): Result => ({
		tone,
		text: `${r.error ?? ''}${after}`,
		errors: r.errors,
	});

	/** Validator only: fast, and changes nothing on the device. */
	async function handleCheck() {
		result = null;
		checking = true;
		try {
			const r = await checkOwnerRules(draft);
			result = r.ok
				? { tone: 'is-ok', text: `No problems found in ${ruleCount(r.rule_count ?? 0)}. Suricata tests them again when you save.`, errors: [] }
				: refused(r);
		} catch {
			result = { tone: 'is-error', text: "Couldn't check the rules: the request failed.", errors: [] };
		} finally {
			checking = false;
		}
	}

	/** What a save answered: 409 is a rule update in the way (amber); every other failure left the old rules running. */
	function saveOutcome(r: OwnerRulesReply): Result {
		if (r.ok) {
			const n = r.rule_count ?? 0;
			const loadedLine = r.engine ? ` Suricata has ${ruleCount(r.engine.loaded)} loaded.` : '';
			const text = n === 0 ? 'Saved. Your own rules are removed.' : `Saved and loaded ${ruleCount(n)} of your own.`;
			return { tone: 'is-ok', text: text + loadedLine, errors: [] };
		}
		if (r.status === 409) return refused(r, 'is-warn');
		if (r.status === 422) return refused(r, 'is-error', ' Suricata keeps running the rules it had.');
		return refused(r);
	}

	async function handleSave() {
		writing = true;
		result = null;
		saving = true;
		try {
			result = saveOutcome(await saveOwnerRules(draft));
		} catch {
			result = { tone: 'is-error', text: "Couldn't save the rules: the request failed.", errors: [] };
		} finally {
			// Read the counts again either way; the buttons stay off until they land
			await reload();
			saving = false;
		}
	}
</script>

<Card title="Your own rules" sub="Suricata alert rules you write · checked and tested before they load" class="c-6">
	{#if !loaded}
		<CardState state="loading" title="Loading your own rules" />
	{:else if !owner}
		<CardState
			state="error"
			title="Couldn't load your own rules: the request failed."
			message="Try again in a moment. If it keeps failing, check the System page."
			onaction={() => void reload()}
		/>
	{:else if !writing && owner.content.trim() === ''}
		<CardState
			state="empty"
			icon="threats"
			title="No rules of your own yet"
			message="Write an alert rule for something only your network has, such as a device that should never reach the internet."
			actionLabel="Write a rule"
			onaction={() => (writing = true)}
		/>
	{:else}
		{#if failed}
			<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('your own rules', true)}</span></p>
		{/if}
		{#if unmounted}
			<p class="notice is-warn" role="status">
				<Icon name="warn" /><span>Suricata isn't connected to your rules folder yet, so saving is off: rules saved now wouldn't load. Updating NetTap connects it.</span>
			</p>
		{/if}
		<p class="card-text">
			One <span class="mono">alert</span> rule per line, each with a <span class="mono">sid</span> from 1000000 to 1999999. At most
			<!-- KB as 1,024 bytes, as the daemon's "over 256 KB" refusal counts it (formatBytes would say 262.1 KB) -->
			{fmt(owner.max_rules)} rules or {fmt(Math.round(owner.max_bytes / 1024))} KB. Lines starting with # are comments. Saving an empty box
			removes all your rules.
		</p>
		<div class="field">
			<label class="label" for="owner-rules">Rules</label>
			<textarea
				id="owner-rules"
				class="textarea mono owner-rules"
				bind:value={draft}
				readonly={saving}
				spellcheck="false"
				autocomplete="off"
				rows="10"
				placeholder={'alert tcp $HOME_NET any -> any 23 (msg:"Telnet out of my network"; sid:1000001; rev:1;)'}
				aria-invalid={result?.errors.length ? 'true' : undefined}
				aria-describedby={result?.errors.length ? 'owner-rules-errors' : undefined}
			></textarea>
		</div>
		{#if saving}
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
			<button class="btn" type="button" onclick={handleCheck} disabled={busy || checking || saving}>
				{checking ? 'Checking…' : 'Check rules'}
			</button>
			<button class="btn primary" type="button" onclick={handleSave} disabled={busy || checking || saving || unmounted}>
				{saving ? 'Saving and loading…' : 'Save and load'}
			</button>
		</div>
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
