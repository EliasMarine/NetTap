<!--
  AlertRow.svelte: one alert in a list (nettap-design-system/components/AlertRow): severity,
  plain title over the raw signature, device, count, last seen and a chevron, as one button.
  aria-current="true" while its details are open. Device, count and time hide on phones.
-->
<script lang="ts">
	import type { SeverityLevel } from '$lib/utils/severity';
	import Icon from './Icon.svelte';
	import SeverityPill from './SeverityPill.svelte';
	import { deviceIcon } from './device-icon';

	interface Props {
		severity: SeverityLevel;
		/** The plain description: "Kitchen iPad looked up a .su website". */
		title: string;
		/** The Suricata signature, shown as received. */
		signature: string;
		device?: { name: string; category?: string };
		count: number;
		/** Formatted last-seen time: "21:05". */
		lastSeen: string;
		selected?: boolean;
		onselect: () => void;
	}

	let { severity, title, signature, device, count, lastSeen, selected = false, onselect }: Props = $props();
</script>

<button type="button" class="alert-row" aria-current={selected ? 'true' : 'false'} onclick={onselect}>
	<SeverityPill level={severity} />
	<span class="alert-main">
		<span class="alert-title" {title}>{title}</span>
		<span class="sig" title={signature}>{signature}</span>
	</span>
	{#if device}
		<span class="who hide-sm"><Icon name={deviceIcon(device.category)} /><span class="trunc">{device.name}</span></span>
	{:else}
		<span class="hide-sm"></span>
	{/if}
	<span class="num dim hide-sm">×{count.toLocaleString('en-GB')}</span>
	<span class="num dim hide-sm">{lastSeen}</span>
	<Icon name="back" class="chev" />
</button>
