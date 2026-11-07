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
		/** The title links here (a raw Suricata category's page, NET-160 slice 2b-2); the count stays plain. */
		href?: string;
		children: Snippet;
	}

	let { title, count, plain, href, children }: Props = $props();
</script>

<section class="alert-group">
	<div class="group-head">
		<!-- OLD CODE: <h3 class="group-title">{title}</h3> (slice 2b-2: the title can link) -->
		<h3 class="group-title">{#if href}<a {href} title="Every alert in this Suricata category over the list's window">{title}</a>{:else}{title}{/if}</h3>
		<span class="dim num">{count.toLocaleString('en-GB')} {count === 1 ? 'alert' : 'alerts'}</span>
	</div>
	{#if plain}<p class="group-plain">{plain}</p>{/if}
	<div class="alert-rows">{@render children()}</div>
</section>
