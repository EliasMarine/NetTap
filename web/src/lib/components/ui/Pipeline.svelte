<!--
  Pipeline.svelte: the capture pipeline, one item per stage (StatStrip README: .pipe).
  Each stage's state is colour, icon and word: the icon carries "Healthy", "Failing" or
  "Unknown" as its accessible name, and `detail` says what is happening.
-->
<script module lang="ts">
	export type StageStatus = 'ok' | 'failing' | 'unknown';

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
		failing: { icon: 'warn', word: 'Failing' },
		unknown: { icon: 'changelog', word: 'Unknown' },
	};
</script>

<div class="pipe">
	{#each stages as stage (stage.key)}
		<div class="pipe-item">
			<span class={['pipe-k', stage.status === 'failing' && 'is-failing', stage.status === 'unknown' && 'is-unknown']}
				><Icon name={LOOK[stage.status].icon} label={LOOK[stage.status].word} />{stage.label}</span
			>
			<span class="pipe-v">{stage.detail}</span>
		</div>
	{/each}
</div>

<style>
	/* bundle.css:290 colours every stage icon ok. A failing stage is sev-high, an unknown one neutral. */
	.pipe-k.is-failing :global(.ic) { color: var(--sev-high); }
	.pipe-k.is-unknown :global(.ic) { color: var(--text-3); }
</style>
