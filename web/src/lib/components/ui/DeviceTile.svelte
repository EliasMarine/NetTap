<!--
  DeviceTile.svelte: the device-type icon in its surface-3 tile (DeviceList README: .tile).
  md is the 36 px list tile; lg is the 72 px accent tile of a device page.
-->
<script lang="ts">
	import Icon from './Icon.svelte';
	import { deviceIcon } from './device-icon';

	let { category, size = 'md' }: { category?: string; size?: 'md' | 'lg' } = $props();
</script>

<span class={['tile', size === 'lg' && 'lg']}><Icon name={deviceIcon(category)} /></span>

<style>
	/* The large tile outside .ident: the same values as bundle.css:380-381 (.ident .tile) */
	.tile.lg { width: 72px; height: 72px; border-radius: 22px; color: var(--accent); }
	.tile.lg :global(.ic) { width: 32px; height: 32px; stroke-width: 1.5; }
</style>
