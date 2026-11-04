<!--
  ConnResult.svelte: a connection result as colour, shape and word (system README
  "Connection results"): Completed grey dot, Ongoing ok dot, No reply square, Reset triangle.
-->
<script module lang="ts">
	export type ConnResultKind = 'completed' | 'ongoing' | 'no-reply' | 'reset';
</script>

<script lang="ts">
	let { result }: { result: ConnResultKind } = $props();

	const LOOK: Record<ConnResultKind, { cls: string; word: string }> = {
		completed: { cls: '', word: 'Completed' },
		ongoing: { cls: 'is-live', word: 'Ongoing' },
		'no-reply': { cls: 'is-medium', word: 'No reply' },
		reset: { cls: 'is-high', word: 'Reset' },
	};
</script>

<span class={['res', LOOK[result].cls]}>{LOOK[result].word}</span>
