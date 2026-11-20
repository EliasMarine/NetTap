<!--
  Settings › Network › Monthly data cap (F6, NET-339): the cap NetTap warns against at 80%, at 100%
  and when the month is on track to go over, with this month's use so far. Decimal GB, as ISPs state
  caps; blank or 0 is no cap. The use line never shows a figure higher than the real one
  (capUseLines). Saved on NetTap, so every browser sees the same cap.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import { getBandwidthCap, setBandwidthCap, type BandwidthCap } from '$lib/api/bandwidth';
	import { capUseLines } from '../bandwidth/usage-words';
	import Feedback from './Feedback.svelte';
	import { loadFailed } from '$lib/utils/load-failed';

	interface Props {
		/** The typed cap differs from the saved one. */
		dirty?: boolean;
		/** A save is running, so Settings holds a tab switch until it lands. */
		writing?: boolean;
	}

	let { dirty = $bindable(false), writing = $bindable(false) }: Props = $props();

	/** The daemon refuses more than 1 PB (its loader would turn such a cap off) */
	const MAX_GB = 1_000_000;
	const RANGE_ERROR = 'Enter a number of GB from 0 to 1,000,000 (1 PB), or leave it blank for no cap.';

	let phase = $state<'loading' | 'ready' | 'failed'>('loading');
	let cap = $state<BandwidthCap | null>(null);
	let typed = $state('');
	let savedTyped = $state('');
	let inputError = $state('');
	let saving = $state(false);
	let message = $state('');
	let isError = $state(false);

	const unsaved = $derived(phase === 'ready' && typed.trim() !== savedTyped);
	const lines = $derived(cap ? capUseLines(cap) : []);
	$effect(() => {
		dirty = unsaved;
		writing = saving;
	});

	/** The input's text for a cap in bytes: exact decimal GB, blank for no cap */
	const shown = (bytes: number) => (bytes > 0 ? String(bytes / 1e9) : '');

	async function load() {
		phase = 'loading';
		try {
			cap = await getBandwidthCap();
			savedTyped = shown(cap.monthly_cap_bytes);
			typed = savedTyped;
			phase = 'ready';
		} catch {
			phase = 'failed';
		}
	}

	async function save() {
		// OLD CODE: const text = typed.trim(); (review: Number() took "0x10" and "1e-400", refused "1,200")
		// digits with an optional decimal part; commas and spaces are thousands separators
		const text = typed.replace(/[,\s]/g, '');
		const gb = text === '' ? 0 : /^\d+(\.\d+)?$/.test(text) ? Number(text) : NaN;
		if (!Number.isFinite(gb) || gb < 0 || gb > MAX_GB) {
			inputError = RANGE_ERROR;
			return;
		}
		inputError = '';
		message = '';
		saving = true;
		try {
			const saved = await setBandwidthCap(gb);
			cap = cap && { ...cap, monthly_cap_bytes: saved.monthly_cap_bytes, monthly_cap_gb: saved.monthly_cap_gb, enabled: saved.monthly_cap_bytes > 0 };
			savedTyped = shown(saved.monthly_cap_bytes);
			typed = savedTyped;
			message = saved.monthly_cap_bytes > 0 ? 'Data cap saved.' : 'Data cap removed. NetTap sends no cap warnings.';
			isError = false;
		} catch (err) {
			// the typed value stays, so the owner can try again
			message = err instanceof Error && err.message ? err.message : "Couldn't save the cap.";
			isError = true;
		} finally {
			saving = false;
		}
	}

	onMount(load);
</script>

<Card title="Monthly data cap" sub="Decimal GB, as your ISP counts · warnings go to your notification channels" class="c-12">
	{#if phase === 'loading'}
		<CardState state="loading" title="Loading your data cap" />
	{:else if phase === 'failed'}
		<CardState state="error" title={loadFailed('your data cap')} message="Check that NetTap is running on the System page, then try again." onaction={load} />
	{:else}
		<div class="stack">
			<div>
				{#each lines as line, i (line)}
					<p class={i === 0 ? 'use-line' : 'field-help'}>{line}</p>
				{/each}
			</div>
			<Feedback {message} {isError} />
			<div class="field">
				<label class="label" for="data-cap-gb">Monthly cap in GB</label>
				<input
					class="input mono"
					id="data-cap-gb"
					type="text"
					inputmode="decimal"
					bind:value={typed}
					disabled={saving}
					oninput={() => (inputError = '')}
					placeholder="No cap"
					aria-invalid={inputError ? 'true' : undefined}
					aria-describedby={inputError ? 'data-cap-gb-error data-cap-gb-help' : 'data-cap-gb-help'}
				/>
				{#if inputError}<p class="field-error" id="data-cap-gb-error" role="alert">{inputError}</p>{/if}
				<p class="field-help" id="data-cap-gb-help">NetTap warns you at 80%, at 100%, and when the month is on track to go over. Leave it blank for no cap.</p>
			</div>
			<div class="form-actions">
				{#if unsaved}<span class="unsaved">Unsaved changes</span>{/if}
				<button class="btn primary" type="button" onclick={save} disabled={saving}>
					{saving ? 'Saving…' : 'Save data cap'}
				</button>
			</div>
		</div>
	{/if}
</Card>

<style>
	.use-line {
		margin: 0;
		font-size: var(--text-md);
		font-weight: 600;
		color: var(--text-1);
		font-variant-numeric: tabular-nums;
	}
</style>
