<!--
  Settings (NET-273): one page, a grouped section menu and one panel per section. The Suricata rules,
  notification channels and backup pages are tabs here now; their old addresses redirect.
  - The open tab comes from the URL (`?tab=`), so a link, Back and Forward all switch it.
  - Only the open tab's component is mounted: it loads fresh each time, and registers the top bar's
    Refresh itself when it has read-only figures.
  - A tab with unsaved edits holds navigation behind a Keep editing / Discard bar; a tab sending a
    change holds it until the change lands.
-->
<script lang="ts">
	import { beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { NavigationType } from '@sveltejs/kit';
	import Icon from '$lib/components/ui/Icon.svelte';
	import SettingsNav from './SettingsNav.svelte';
	import { SETTINGS_TABS, tabFrom, type TabId } from './settings-helpers';
	import './settings.css';
	import NotificationsTab from './tabs/NotificationsTab.svelte';
	import SuricataRulesTab from './tabs/SuricataRulesTab.svelte';
	import RetentionTab from './tabs/RetentionTab.svelte';
	import CaptureTab from './tabs/CaptureTab.svelte';
	import BackupTab from './tabs/BackupTab.svelte';
	import NetworkTab from './tabs/NetworkTab.svelte';
	import IntegrationsTab from './tabs/IntegrationsTab.svelte';
	import ApiKeysTab from './tabs/ApiKeysTab.svelte';
	import DisplayTab from './tabs/DisplayTab.svelte';
	import AboutTab from './tabs/AboutTab.svelte';

	// OLD CODE START — NET-273: the tab was page state set once on mount, so a ?tab= link inside the
	// page, Back and Forward left the panel where it was; the URL is the source now
	// type TabId = 'notifications' | 'retention' | 'capture' | 'api-keys' | 'network' | 'integrations' | 'display' | 'about';
	//
	// let activeTab = $state<TabId>('notifications');
	//
	// // Values are id-safe: Pills builds settings-tab-{value} / settings-panel-{value} from them
	// const TABS: PillOption<TabId>[] = [
	// 	{ value: 'notifications', label: 'Notifications' },
	// 	{ value: 'retention', label: 'Retention' },
	// 	{ value: 'capture', label: 'Capture' },
	// 	{ value: 'api-keys', label: 'API keys' },
	// 	{ value: 'network', label: 'Network' },
	// 	{ value: 'integrations', label: 'Integrations' },
	// 	{ value: 'display', label: 'Display' },
	// 	{ value: 'about', label: 'About' },
	// ];
	// OLD CODE END
	const activeTab = $derived(tabFrom(page.url));
	const active = $derived(SETTINGS_TABS.find((t) => t.id === activeTab) ?? SETTINGS_TABS[0]);

	// OLD CODE START — NET-273: the page read Retention health and About for the top bar's Refresh and
	// loaded every tab's form on mount; each tab now loads its own form and registers its own loader
	// // OLD CODE START — NET-192 PR 4: the top bar's Refresh did nothing here; the reads go through the page loader
	// // onMount(() => {
	// // 	loadNotificationConfig();
	// // 	loadRetention();
	// // 	loadDiskUsage();
	// // 	loadExcludedIps();
	// // 	loadApiKeys();
	// // 	loadAbout();
	// // 	loadDisplaySettings();
	// // 	loadCaptureSettings();
	// // 	loadUnifiStatus();
	// // });
	// // OLD CODE END
	// /**
	//  * The top bar's Refresh: the read-only status sections only (Retention health, About), never a
	//  * form, so an unsaved edit survives it. Capture and UniFi status share their loaders with their
	//  * forms, so they stay read once, with the forms.
	//  */
	// async function load(guard: LoadGuard): Promise<LoadResult> {
	// 	const g = guard.begin();
	// 	// shortcut: each read writes its own section unguarded; neither takes a range or filter, so an
	// 	// older reply answers the same question. Copy the query into locals if a section gains one.
	// 	const [, aboutOk] = await Promise.all([loadDiskUsage(), loadAbout()]);
	// 	if (!guard.current(g)) return 'skipped';
	// 	return outcome([storageStatusFailed, !aboutOk].map((bad): PromiseSettledResult<null> => (bad ? { status: 'rejected', reason: null } : { status: 'fulfilled', value: null })));
	// }
	//
	// const refresh = registerPageRefresh(load);
	// onDestroy(refresh.unregister);
	// // The forms load once here, and again after a save, as before
	// onMount(() => {
	// 	loadNotificationConfig();
	// 	loadRetention();
	// 	loadExcludedIps();
	// 	loadApiKeys();
	// 	loadDisplaySettings();
	// 	loadCaptureSettings();
	// 	loadUnifiStatus();
	// 	// A link can open a tab: /settings?tab=network (the Live globe's "location isn't set" note)
	// 	const tab = new URLSearchParams(location.search).get('tab');
	// 	if (TABS.some((t) => t.value === tab)) activeTab = tab as TabId;
	// 	void refresh.run();
	// });
	// OLD CODE END

	// The open tab reports these (bound below); a tab that never sets them leaves them false
	let dirty = $state(false);
	let busy = $state(false);

	/** A navigation the guard stopped, kept so Discard can carry it on. */
	interface Pending {
		url: URL;
		type: NavigationType;
		/** Back or Forward: how far, since SvelteKit has already undone the step. */
		delta?: number;
		willUnload: boolean;
	}
	let pending = $state<Pending | null>(null);
	// Lets the one navigation Discard starts through the guard
	let bypass = false;

	function select(id: TabId) {
		void goto(`?tab=${id}`, { keepFocus: true, noScroll: true });
	}

	beforeNavigate((nav) => {
		if (bypass) {
			bypass = false;
			return;
		}
		if (!dirty && !busy) return;
		nav.cancel();
		// 'leave' (reload, closing the tab, typing an address): cancel() shows the browser's own prompt
		if (nav.type === 'leave' || !nav.to) return;
		pending = { url: nav.to.url, type: nav.type, delta: nav.delta, willUnload: nav.willUnload };
	});

	// The bar goes once nothing holds the navigation any more (a save finished, or the edits were undone)
	$effect(() => {
		if (!dirty && !busy) pending = null;
	});

	function discard() {
		const next = pending;
		pending = null;
		if (!next) return;
		dirty = false;
		bypass = true;
		if (next.type === 'popstate' && next.delta) history.go(next.delta);
		else if (next.willUnload) location.assign(next.url.href);
		else void goto(next.url);
	}
</script>

<svelte:head>
	<title>Settings | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<h1 class="page-title">Settings</h1>
		<!-- OLD CODE: <p class="page-sub">Alerts, storage, capture, credentials and display for this NetTap.</p> (NET-273: one page for every setting) -->
		<p class="page-sub">Everything you can set on this NetTap, grouped by what it controls.</p>
	</div>
	<!-- OLD CODE START — NET-273: the three pages are tabs of this page now
	NET-199: these pages had a back link to Settings but nothing led to them
	<nav class="head-actions" aria-label="More settings">
		<a class="btn" href="/settings/suricata-rules"><Icon name="threats" />Suricata rules</a>
		<a class="btn" href="/settings/notifications"><Icon name="alerts" />Notification channels</a>
		<a class="btn" href="/settings/backup"><Icon name="download" />Backup and restore</a>
	</nav>
	OLD CODE END -->
</div>

<!-- OLD CODE START — NET-273: eight tabs in one row; the grouped menu holds ten
<div class="tabs-scroll">
	<Pills options={TABS} bind:value={activeTab} ariaLabel="Settings sections" mode="tabs" idPrefix="settings" />
</div>

<div class="grid" role="tabpanel" id="settings-panel-{activeTab}" aria-labelledby="settings-tab-{activeTab}" tabindex="0">
OLD CODE END -->

<div class="settings-layout">
	<SettingsNav active={activeTab} onselect={select} />

	<div class="settings-body">
		{#if pending && (busy || dirty)}
			<div class="notice is-warn leave-bar" role="alert">
				<Icon name="warn" />
				{#if busy}
					<span>Saving your changes… wait for this to finish before leaving the tab.</span>
				{:else}
					<span>You have unsaved changes in {active.label}.</span>
					<span class="leave-actions">
						<button class="btn" type="button" onclick={() => (pending = null)}>Keep editing</button>
						<button class="btn" type="button" onclick={discard}>Discard and continue</button>
					</span>
				{/if}
			</div>
		{/if}

		<!-- Ten stable panels, so every tab's aria-controls resolves; only the open one has its component -->
		{#each SETTINGS_TABS as tab (tab.id)}
			<div
				class="settings-panel"
				role="tabpanel"
				id="settings-panel-{tab.id}"
				aria-labelledby="settings-tab-{tab.id}"
				tabindex="0"
				hidden={tab.id !== activeTab}
			>
				{#if tab.id === activeTab}
					<p class="panel-intro"><span class="eyebrow">{tab.group}</span><span>{tab.intro}</span></p>
					{#if tab.id === 'notifications'}
						<NotificationsTab bind:dirty bind:busy />
					{:else if tab.id === 'suricata-rules'}
						<SuricataRulesTab bind:dirty bind:busy />
					{:else if tab.id === 'retention'}
						<RetentionTab bind:dirty bind:busy />
					{:else if tab.id === 'capture'}
						<CaptureTab bind:dirty bind:busy />
					{:else if tab.id === 'backup'}
						<BackupTab bind:busy />
					{:else if tab.id === 'network'}
						<NetworkTab bind:dirty bind:busy />
					{:else if tab.id === 'integrations'}
						<IntegrationsTab bind:dirty bind:busy />
					{:else if tab.id === 'api-keys'}
						<ApiKeysTab bind:dirty bind:busy />
					{:else if tab.id === 'display'}
						<DisplayTab bind:dirty />
					{:else}
						<AboutTab />
					{/if}
				{/if}
			</div>
		{/each}
	</div>
</div>

<style>
	/* OLD CODE START — NET-273: the Pills row and the single panel are gone; the shared form rules
	   moved to settings.css and each tab's own rules moved with it
	.tabs-scroll {
		overflow-x: auto;
		padding: var(--sp-1);
		margin: calc(var(--sp-1) * -1);
	}

	.grid:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
		border-radius: var(--r-lg);
	}
	OLD CODE END */

	/* The menu as a rail beside the panel; on a phone it sits above as one scrolling row */
	.settings-layout {
		display: grid;
		grid-template-columns: minmax(12rem, auto) minmax(0, 1fr);
		gap: var(--sp-6);
		align-items: start;
	}

	.settings-body {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		min-width: 0;
	}

	.settings-panel:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
		border-radius: var(--r-lg);
	}

	.panel-intro {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		margin-bottom: var(--sp-4);
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.leave-bar {
		align-items: center;
		flex-wrap: wrap;
	}

	.leave-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
		margin-left: auto;
	}

	@container app (max-width: 760px) {
		.settings-layout {
			grid-template-columns: minmax(0, 1fr);
			gap: var(--sp-4);
		}
	}
</style>
