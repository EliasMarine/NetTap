<!--
  KpiCard.svelte: a headline number with its label, change and a small supporting visual
  (nettap-design-system/components/KpiCard). With `href` the whole card is one link, so
  the `foot` snippet must not hold links or buttons then.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons';

	interface Props {
		label: string;
		icon: IconName;
		value: string | number;
		unit?: string;
		/** `bad` marks the chip is-warn (alerts up, trackers up). */
		delta?: { text: string; direction: 'up' | 'down'; bad?: boolean };
		/** The comparison window beside the delta: "vs previous 24 h". */
		comparison?: string;
		/** A source note when there is no comparison: "from Changelog". */
		note?: string;
		/** One line of breakdown: "↓ 31.8 GB down · ↑ 7.4 GB up". */
		sub?: string;
		href?: string;
		class?: string;
		foot?: Snippet;
	}

	let { label, icon, value, unit, delta, comparison, note, sub, href, class: cls = '', foot }: Props = $props();
	const meta = $derived(comparison ?? note);
</script>

<svelte:element this={href ? 'a' : 'article'} {href} class={['card', 'kpi', cls]}>
	<div class="kpi-top"><span>{label}</span><Icon name={icon} /></div>
	<div class="kpi-num">{value}{#if unit}<span class="kpi-unit">{unit}</span>{/if}</div>
	{#if delta || meta}
		<div class="kpi-meta">
			{#if delta}<span class={['chip', delta.bad && 'is-warn']}><Icon name={delta.direction} />{delta.text}</span>{/if}
			{#if meta}<span>{meta}</span>{/if}
		</div>
	{/if}
	{#if sub}<div class="kpi-sub">{sub}</div>{/if}
	{#if foot}<div class="kpi-foot">{@render foot()}</div>{/if}
</svelte:element>

<style>
	a.kpi { text-decoration: none; }
</style>
