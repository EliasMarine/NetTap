<!--
  CardState.svelte: a card body while loading, when empty, or when its request failed
  (nettap-design-system/components/CardStates). Goes inside a Card, which keeps its head.
  Loading reads `title` as its accessible text ("Loading bandwidth"), default "Loading".
  The 230 px minimum height comes from the system's .state and .skel-wrap.
-->
<script lang="ts">
	import Icon from './Icon.svelte';
	import type { IconName } from './icons';

	interface Props {
		state: 'loading' | 'empty' | 'error';
		/** Empty/error heading: names what is missing or what failed. */
		title?: string;
		/** One sentence: when it will appear, or the likely cause and fix. */
		message?: string;
		actionLabel?: string;
		onaction?: () => void;
		/** Empty-state icon; error always shows the warn icon. */
		icon?: IconName;
		/** Empty-state action as a link to the place that fixes it. */
		href?: string;
	}

	let { state, title, message, actionLabel, onaction, icon = 'empty', href }: Props = $props();
</script>

{#if state === 'loading'}
	<div class="skel-wrap" role="status" aria-busy="true">
		<span class="sr-only">{title ?? 'Loading'}</span>
		<div class="skel skel-head"></div>
		<div class="skel skel-body"></div>
		<div class="skel skel-line"></div>
	</div>
{:else if state === 'empty'}
	<div class="state">
		<span class="state-ic"><Icon name={icon} /></span>
		<h3>{title ?? 'Nothing to show yet'}</h3>
		{#if message}<p>{message}</p>{/if}
		{#if href && actionLabel}
			<a class="btn" {href}>{actionLabel}</a>
		{:else if onaction && actionLabel}
			<button class="btn" type="button" onclick={onaction}>{actionLabel}</button>
		{/if}
	</div>
{:else}
	<div class="state is-error" role="alert">
		<span class="state-ic"><Icon name="warn" /></span>
		<h3>{title ?? "Couldn't load this: the request failed."}</h3>
		{#if message}<p>{message}</p>{/if}
		{#if onaction}
			<button class="btn" type="button" onclick={onaction}><Icon name="refresh" />{actionLabel ?? 'Try again'}</button>
		{/if}
	</div>
{/if}

<style>
	/* Skeleton shapes from the CardStates preview (a headline, a chart, a caption line) */
	.skel-head { height: var(--sp-8); width: 46%; }
	.skel-body { height: calc(var(--sp-8) * 4); }
	.skel-line { height: var(--sp-3); width: 70%; }
</style>
