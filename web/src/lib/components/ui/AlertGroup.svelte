<!--
  AlertGroup.svelte: a category heading with its count and one plain sentence, over its
  AlertRows (AlertRow README: .alert-group).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		count: number;
		/** What the category means, in one sentence. */
		plain?: string;
		children: Snippet;
	}

	let { title, count, plain, children }: Props = $props();
</script>

<section class="alert-group">
	<div class="group-head">
		<h3 class="group-title">{title}</h3>
		<span class="dim num">{count.toLocaleString('en-GB')} {count === 1 ? 'alert' : 'alerts'}</span>
	</div>
	{#if plain}<p class="group-plain">{plain}</p>{/if}
	<div class="alert-rows">{@render children()}</div>
</section>
