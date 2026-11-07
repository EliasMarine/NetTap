<!-- AutoRefreshButton.svelte: Home's "Auto" / "Paused" toggle, one look and one wording on every page (NET-192 PR 4). -->
<script lang="ts">
	import Icon from './Icon.svelte';

	interface Props {
		/** Whether the page refreshes on its own. */
		on: boolean;
		/** How often it refreshes, for the hover text. */
		seconds: number;
		ontoggle: () => void;
	}

	let { on, seconds, ontoggle }: Props = $props();
</script>

<button class="btn" type="button" onclick={ontoggle} title={on ? `Refreshes every ${seconds} s` : 'Auto-refresh is paused'}>
	<Icon name={on ? 'refresh' : 'pause'} />{on ? 'Auto' : 'Paused'}
</button>
