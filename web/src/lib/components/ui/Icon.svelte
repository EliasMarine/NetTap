<!--
  Icon.svelte: one icon from the NetTap outline set (nettap-design-system/assets/Icons).
  Takes its colour from the surrounding text. Decorative unless given a label.
-->
<script lang="ts">
	import { ICONS, type IconName } from './icons';

	let { name, label, class: cls = '' }: { name: IconName; label?: string; class?: string } = $props();
</script>

<svg
	class="ic {cls}"
	viewBox="0 0 24 24"
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : 'true'}
	focusable="false"
	><!-- ICONS holds static markup copied from the design system's own files, never user data -->{@html ICONS[name]}</svg
>
