<!--
  DeviceTile.svelte: the device-type icon in its surface-3 tile (DeviceList README: .tile).
  md is the 36 px list tile; lg is the 72 px accent tile of a device page.
  NET-200: the owner's photo fills the tile when there is one (back to the icon if it fails to
  load), and an icon the owner picked replaces the category's.
-->
<script lang="ts">
	import Icon from './Icon.svelte';
	import { deviceIcon } from './device-icon';

	// OLD CODE: let { category, size = 'md' }: { category?: string; size?: 'md' | 'lg' } = $props(); (NET-200: picture and icon)
	let {
		category,
		size = 'md',
		picture = null,
		icon = null,
	}: { category?: string; size?: 'md' | 'lg'; picture?: string | null; icon?: string | null } = $props();

	/** The photo URL that failed to load; another URL gets its own try. */
	let failed = $state<string | null>(null);
	const showPhoto = $derived(!!picture && failed !== picture);
	const px = $derived(size === 'lg' ? 72 : 36);
</script>

<!-- OLD CODE: <span class={['tile', size === 'lg' && 'lg']}><Icon name={deviceIcon(category)} /></span> (NET-200) -->
<span class={['tile', size === 'lg' && 'lg', showPhoto && 'has-photo']}>
	{#if showPhoto}
		<!-- decorative: the device's name is always beside the tile -->
		<img src={picture} alt="" width={px} height={px} loading="lazy" onerror={() => (failed = picture)} />
	{:else}
		<Icon name={deviceIcon(icon ?? category)} />
	{/if}
</span>

<style>
	/* The large tile outside .ident: the same values as bundle.css:380-381 (.ident .tile) */
	.tile.lg { width: 72px; height: 72px; border-radius: 22px; color: var(--accent); }
	.tile.lg :global(.ic) { width: 32px; height: 32px; stroke-width: 1.5; }
	/* A photo fills the tile edge to edge, clipped to its rounded corners */
	.tile.has-photo { overflow: hidden; }
	.tile img { width: 100%; height: 100%; object-fit: cover; display: block; }
</style>
