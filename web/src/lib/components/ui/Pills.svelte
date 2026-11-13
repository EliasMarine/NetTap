<!--
  Pills.svelte: the segmented control (nettap-design-system/components/Pills), in three modes.
  - toggle (default): buttons with aria-pressed in a role="group".
  - tabs: the WAI-ARIA tabs pattern. Arrow keys, Home and End move focus and select.
    The page renders each panel as
    <div role="tabpanel" id="{idPrefix}-panel-{value}" aria-labelledby="{idPrefix}-tab-{value}">.
    Values must be valid in an id (no spaces).
  - nav: links with aria-current="page" on the current route.
-->
<script module lang="ts">
	export interface PillOption<T extends string = string> {
		value: T;
		label: string;
		/** Required in nav mode. */
		href?: string;
	}
</script>

<script lang="ts" generics="T extends string">
	interface Props {
		options: PillOption<T>[];
		value: T;
		onchange?: (value: T) => void;
		/** Names what the pills choose: "Time range". */
		ariaLabel: string;
		mode?: 'toggle' | 'tabs' | 'nav';
		idPrefix?: string;
		/** Toggle and tabs: every pill off, e.g. while the page loads what the last one picked. */
		disabled?: boolean;
	}

	const uid = $props.id();
	let { options, value = $bindable(), onchange, ariaLabel, mode = 'toggle', idPrefix = uid, disabled = false }: Props = $props();

	let tablist = $state<HTMLElement>();
	// Roving tabindex: the selected tab, or the first when none is selected
	const focusIndex = $derived(Math.max(0, options.findIndex((o) => o.value === value)));

	function select(next: T) {
		if (next === value) return;
		value = next;
		onchange?.(next);
	}

	function onTabKey(event: KeyboardEvent, index: number) {
		const last = options.length - 1;
		const target =
			event.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
			: event.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
			: event.key === 'Home' ? 0
			: event.key === 'End' ? last
			: -1;
		if (target < 0) return;
		event.preventDefault();
		select(options[target].value);
		tablist?.querySelectorAll<HTMLElement>('[role="tab"]')[target]?.focus();
	}
</script>

{#if mode === 'tabs'}
	<div class="pills" role="tablist" aria-label={ariaLabel} bind:this={tablist}>
		{#each options as option, i (option.value)}
			<button
				class="pill"
				type="button"
				role="tab"
				id="{idPrefix}-tab-{option.value}"
				aria-selected={option.value === value}
				aria-controls="{idPrefix}-panel-{option.value}"
				tabindex={i === focusIndex ? 0 : -1}
				{disabled}
				onclick={() => select(option.value)}
				onkeydown={(e) => onTabKey(e, i)}>{option.label}</button
			>
		{/each}
	</div>
{:else if mode === 'nav'}
	<nav class="pills" aria-label={ariaLabel}>
		{#each options as option (option.value)}
			<a class="pill" href={option.href} aria-current={option.value === value ? 'page' : undefined}>{option.label}</a>
		{/each}
	</nav>
{:else}
	<div class="pills" role="group" aria-label={ariaLabel}>
		{#each options as option (option.value)}
			<button class="pill" type="button" aria-pressed={option.value === value} {disabled} onclick={() => select(option.value)}
				>{option.label}</button
			>
		{/each}
	</div>
{/if}
