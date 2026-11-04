<!-- Who.svelte: a device table cell, icon + name over the mono IP (DataTable README: .who). -->
<script lang="ts">
	import Icon from './Icon.svelte';
	import { deviceIcon } from './device-icon';

	let { name, ip, category }: { name: string; ip?: string; category?: string } = $props();
</script>

<span class="who">
	<Icon name={deviceIcon(category)} />
	<span class="two">
		<span class="who-name trunc" title={name}>{name}</span>
		{#if ip}<span class="mono">{ip}</span>{/if}
	</span>
</span>
