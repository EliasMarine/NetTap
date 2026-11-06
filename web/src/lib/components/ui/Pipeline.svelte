<!--
  Pipeline.svelte: the capture pipeline, one item per stage (StatStrip README: .pipe).
  Each stage's state is colour, icon and word: the icon carries "Healthy", "Warning", "Failing"
  or "Unknown" as its accessible name, and `detail` says what is happening.
-->
<script module lang="ts">
	// OLD CODE: export type StageStatus = 'ok' | 'failing' | 'unknown'; (NET-168: no amber state,
	// so a health check that only partly ran read as grey "Unknown")
	/** `warn` is amber: NetTap checked, and something needs a look (a check that couldn't run). */
	export type StageStatus = 'ok' | 'warn' | 'failing' | 'unknown';

	export interface PipelineStage {
		key: string;
		label: string;
		status: StageStatus;
		/** One line of status: "Writing logs · last one 2 s ago". */
		detail: string;
	}
</script>

<script lang="ts">
	import Icon from './Icon.svelte';
	import type { IconName } from './icons';

	let { stages }: { stages: PipelineStage[] } = $props();

	const LOOK: Record<StageStatus, { icon: IconName; word: string }> = {
		ok: { icon: 'check', word: 'Healthy' },
		warn: { icon: 'warn', word: 'Warning' },
		failing: { icon: 'warn', word: 'Failing' },
		unknown: { icon: 'changelog', word: 'Unknown' },
	};
</script>

<div class="pipe">
	{#each stages as stage (stage.key)}
		<div class="pipe-item">
			<span
				class={[
					'pipe-k',
					stage.status === 'warn' && 'is-warn',
					stage.status === 'failing' && 'is-failing',
					stage.status === 'unknown' && 'is-unknown',
				]}
				><Icon name={LOOK[stage.status].icon} label={LOOK[stage.status].word} />{stage.label}</span
			>
			<span class="pipe-v">{stage.detail}</span>
		</div>
	{/each}
</div>

<style>
	/* bundle.css:290 colours every stage icon ok. A warning stage is sev-medium (amber), a failing
	   one sev-high, an unknown one neutral. */
	.pipe-k.is-warn :global(.ic) { color: var(--sev-medium); }
	.pipe-k.is-failing :global(.ic) { color: var(--sev-high); }
	.pipe-k.is-unknown :global(.ic) { color: var(--text-3); }
</style>
