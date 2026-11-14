<!--
  Feedback.svelte: a Settings form's result line (NET-273: was the page's `feedback` snippet).
  Nothing renders without a message; an error is an alert, anything else a status.
-->
<script lang="ts">
	import Icon from '$lib/components/ui/Icon.svelte';

	let { message, isError }: { message: string; isError: boolean } = $props();
</script>

{#if message}
	<div class={['notice', isError ? 'is-error' : 'is-ok']} role={isError ? 'alert' : 'status'}>
		<Icon name={isError ? 'warn' : 'check'} />{message}
	</div>
{/if}
