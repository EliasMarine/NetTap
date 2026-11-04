<!--
  SeverityPill.svelte: severity as colour, shape and word together
  (nettap-design-system/components/SeverityPill). With `count` it renders the .sev-count tile.
-->
<script lang="ts">
	import type { SeverityLevel } from '$lib/utils/severity';

	let { level, count }: { level: SeverityLevel; count?: number } = $props();

	const WORD: Record<SeverityLevel, string> = {
		critical: 'Critical',
		high: 'High',
		medium: 'Medium',
		low: 'Low',
		info: 'Info',
	};
</script>

{#snippet pill()}
	<!-- .sev is inline-flex, so the whitespace between the shape and the word is not rendered -->
	<span class="sev sev-{level}">
		<svg viewBox="0 0 10 10" aria-hidden="true">
			{#if level === 'critical'}
				<path d="M5 .5 9.5 5 5 9.5.5 5z" />
			{:else if level === 'high'}
				<path d="M5 1 9.4 9H.6z" />
			{:else if level === 'medium'}
				<rect x="1" y="1" width="8" height="8" rx="1.5" />
			{:else if level === 'low'}
				<circle cx="5" cy="5" r="4" />
			{:else}
				<circle cx="5" cy="5" r="3.4" class="hollow" />
			{/if}
		</svg>
		{WORD[level]}
	</span>
{/snippet}

{#if count === undefined}
	{@render pill()}
{:else}
	<div class="sev-count">{@render pill()}<b>{count.toLocaleString('en-GB')}</b></div>
{/if}
