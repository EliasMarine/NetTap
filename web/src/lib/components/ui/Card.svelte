<!--
  Card.svelte: the system's basic container (nettap-design-system/components/Card).
  `class` carries the grid span (c-3 … c-12). `actions` sits right of the head (legend, link,
  pills); `foot` renders in a .card-foot, which sits at the bottom when `col` is set.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		/** States the unit and window: "GB per hour · busiest at 21:00". */
		sub?: string;
		hero?: boolean;
		col?: boolean;
		headingLevel?: 2 | 3 | 4;
		class?: string;
		actions?: Snippet;
		children?: Snippet;
		foot?: Snippet;
	}

	let {
		title,
		sub,
		hero = false,
		col = false,
		headingLevel = 2,
		class: cls = '',
		actions,
		children,
		foot,
	}: Props = $props();
</script>

<article class={['card', hero && 'hero', col && 'col', cls]}>
	<div class="card-head">
		<div>
			<svelte:element this={`h${headingLevel}`} class="card-title">{title}</svelte:element>
			{#if sub}<p class="card-sub">{sub}</p>{/if}
		</div>
		{@render actions?.()}
	</div>
	{@render children?.()}
	{#if foot}<div class="card-foot">{@render foot()}</div>{/if}
</article>
