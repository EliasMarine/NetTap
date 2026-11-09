<!--
  Sidebar.svelte: the floating navigation panel (nettap-design-system/components/Sidebar).
  Brand, capture-mode chip, grouped links with the open-alert count, storage and the user.
-->
<script lang="ts">
	import Icon from '$lib/components/ui/Icon.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import BrandMark from './BrandMark.svelte';
	import { NAV_GROUPS, isActive } from './nav';
	import type { CaptureChip, StorageFoot } from './status';
	import { fitCount } from '$lib/utils/drilldown';

	interface Props {
		path: string;
		capture: CaptureChip;
		/** Alerts in the last 24 hours (the same snapshot Home and Alerts show); null hides the badge. */
		alertCount: number | null;
		/** NET-228 (audit HON-49): the count couldn't be loaded, which must not read as zero (no badge) */
		alertCountFailed?: boolean;
		storage: StorageFoot | null;
		username: string | null;
		/** Called when a link is chosen, so the phone drawer can close. */
		onnavigate?: () => void;
		sidebarEl?: HTMLElement;
	}

	// OLD CODE: let { path, capture, alertCount, storage, username, onnavigate, sidebarEl = $bindable() }: Props = $props(); (NET-228: + alertCountFailed)
	let { path, capture, alertCount, alertCountFailed = false, storage, username, onnavigate, sidebarEl = $bindable() }: Props = $props();
</script>

<nav class="sidebar" id="app-sidebar" aria-label="Main" bind:this={sidebarEl}>
	<a class="brand" href="/" aria-label="NetTap home" onclick={onnavigate}>
		<BrandMark />
		<span>NetTap</span>
	</a>

	<div class="mode-chip" role="status">
		{#if capture.pulse}
			<span class="live-dot" aria-hidden="true"></span>
		{:else}
			<span class="mode-dot tone-{capture.tone}" aria-hidden="true"></span>
		{/if}
		<span>{capture.text}</span>
	</div>

	{#each NAV_GROUPS as group (group.label)}
		<div class="nav-label" id="nav-{group.label.toLowerCase()}">{group.label}</div>
		<div class="nav" role="group" aria-labelledby="nav-{group.label.toLowerCase()}">
			{#each group.items as item (item.href)}
				<a
					href={item.href}
					aria-current={isActive(item.href, path) ? 'page' : undefined}
					onclick={onnavigate}
				>
					<Icon name={item.icon} />
					<span>{item.label}</span>
					{#if item.href === '/alerts' && alertCountFailed}
						<span class="count unknown" aria-hidden="true">?</span>
						<span class="sr-only">Couldn't load the alert count</span>
					{:else if item.href === '/alerts' && alertCount !== null && alertCount > 0}
						<!-- OLD CODE: {alertCount} (NET-192: printed "214000"; the sr-only line keeps the exact figure) -->
						<span class="count" aria-hidden="true">{fitCount(alertCount)}</span>
						<span class="sr-only">{alertCount} alerts in the last 24 hours</span>
					{/if}
				</a>
			{/each}
		</div>
	{/each}

	<div class="side-foot">
		{#if storage}
			<div class="foot-row"><span class="dim">Storage</span><span>{storage.used}</span></div>
			<Meter value={storage.percent} label="Disk used" />
			{#if storage.detail}<div class="dim">{storage.detail}</div>{/if}
		{/if}
		<div class="user">
			{#if username}
				<span class="avatar"><Icon name="user" /></span>
				<span><b>{username}</b></span>
			{/if}
			<form method="POST" action="/api/auth/logout">
				<button class="icon-btn ghost" type="submit" aria-label="Sign out">
					<Icon name="logout" />
				</button>
			</form>
		</div>
	</div>
</nav>

<style>
	/* The system shows only the healthy pulsing dot; the other capture states reuse its size, static. */
	.mode-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex: none;
	}
	.tone-medium { background: var(--sev-medium); }
	.tone-high { background: var(--sev-high); }
	.tone-muted { background: var(--text-3); }
	/* a count that couldn't be loaded: muted, so it doesn't read as alerts */
	.count.unknown { color: var(--text-2); background: var(--surface-3); }

	.user form {
		margin-left: auto;
	}
</style>
