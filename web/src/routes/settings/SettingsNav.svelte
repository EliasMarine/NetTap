<!--
  SettingsNav.svelte: the Settings page's section menu (NET-273), a WAI-ARIA tablist.
  - A left rail with group labels on wider screens; one row that scrolls on its own on a phone.
  - Each tab controls `settings-panel-{id}`, which the page renders for every tab.
  - The arrow keys, Home and End move focus and select, as Pills tabs mode does. Up/Down and
    Left/Right both work, so the keys are the same in the rail and in the phone row.
  - Group labels are aria-hidden (a tablist may only own tabs); each panel's intro names its group.
-->
<script lang="ts">
	import { SETTINGS_GROUPS, SETTINGS_TABS, type TabId } from './settings-helpers';

	interface Props {
		active: TabId;
		/** Called with a tab the owner picked; the page navigates to `?tab=`. */
		onselect: (id: TabId) => void;
	}

	let { active, onselect }: Props = $props();

	let list = $state<HTMLElement>();
	// The rail is a column; the phone row is a row. Read from the CSS so the two can't disagree.
	let vertical = $state(true);
	$effect(() => {
		const el = list;
		if (!el || typeof ResizeObserver === 'undefined') return;
		const observer = new ResizeObserver(() => (vertical = getComputedStyle(el).flexDirection !== 'row'));
		observer.observe(el);
		return () => observer.disconnect();
	});

	function select(id: TabId) {
		if (id !== active) onselect(id);
	}

	const KEY_STEP: Record<string, number> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };

	function onKey(event: KeyboardEvent, index: number) {
		const last = SETTINGS_TABS.length - 1;
		const step = KEY_STEP[event.key];
		const target =
			step !== undefined ? (index + step + SETTINGS_TABS.length) % SETTINGS_TABS.length
			: event.key === 'Home' ? 0
			: event.key === 'End' ? last
			: -1;
		if (target < 0) return;
		event.preventDefault();
		select(SETTINGS_TABS[target].id);
		list?.querySelectorAll<HTMLElement>('[role="tab"]')[target]?.focus();
	}

	const indexOf = (id: TabId) => SETTINGS_TABS.findIndex((t) => t.id === id);
</script>

<div
	class="settings-nav"
	role="tablist"
	aria-label="Settings sections"
	aria-orientation={vertical ? 'vertical' : 'horizontal'}
	bind:this={list}
>
	{#each SETTINGS_GROUPS as group (group.label)}
		<span class="eyebrow nav-group" aria-hidden="true">{group.label}</span>
		{#each group.tabs as tab (tab.id)}
			<button
				class="nav-tab"
				type="button"
				role="tab"
				id="settings-tab-{tab.id}"
				aria-selected={tab.id === active}
				aria-controls="settings-panel-{tab.id}"
				tabindex={tab.id === active ? 0 : -1}
				onclick={() => select(tab.id)}
				onkeydown={(e) => onKey(e, indexOf(tab.id))}>{tab.label}</button
			>
		{/each}
	{/each}
</div>

<style>
	.settings-nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
		position: sticky;
		top: var(--sp-4);
	}

	.nav-group {
		padding: var(--sp-4) var(--sp-3) var(--sp-1);
	}

	.nav-group:first-child {
		padding-top: 0;
	}

	.nav-tab {
		display: flex;
		align-items: center;
		min-height: 36px;
		padding: var(--sp-2) var(--sp-3);
		border: 0;
		border-radius: var(--r-md);
		background: transparent;
		color: var(--text-2);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: 600;
		text-align: left;
		white-space: nowrap;
		cursor: pointer;
		transition: background var(--dur-fast), color var(--dur-fast);
	}

	.nav-tab:hover {
		background: var(--surface-2);
		color: var(--text-1);
	}

	.nav-tab[aria-selected='true'] {
		background: var(--pill-active-bg);
		color: var(--on-light);
	}

	.nav-tab:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}

	/* The phone row: the tabs scroll inside the row, never the page; the group labels go */
	@container app (max-width: 760px) {
		.settings-nav {
			flex-direction: row;
			position: static;
			overflow-x: auto;
			scrollbar-width: none;
			padding: var(--sp-1);
			margin: calc(var(--sp-1) * -1);
		}

		.nav-group {
			display: none;
		}

		.nav-tab {
			border-radius: var(--r-pill);
		}
	}
</style>
