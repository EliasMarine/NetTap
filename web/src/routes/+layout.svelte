<script lang="ts">
	import '$lib/styles/tokens.css';
	import '$lib/styles/system.css';
	import '$lib/styles/forms.css';
	import '$lib/styles/a11y.css';
	import '$lib/styles/global.css';
	import { tick } from 'svelte';
	import { page } from '$app/stores';
	import { afterNavigate, goto } from '$app/navigation';
	// OLD CODE: import { getCaptureMode, getCaptureHealth } from '$api/capture'; (NET-225: the chip reads the shared store)
	import { getCaptureHealth } from '$api/capture';
	import type { CaptureHealthResponse, CaptureMode } from '$api/capture';
	import { getStorageStatus } from '$api/system';
	import type { StorageStatus } from '$api/system';
	import { captureMode as modeStore, initCaptureMode } from '$lib/stores/captureMode';
	import { SIGN_IN_FIRST } from '$lib/auth-errors';
	import { alertSnapshots, loadAlertSnapshot, refreshAlertSnapshots } from '$lib/stores/alertSnapshot';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import TopBar from '$lib/components/shell/TopBar.svelte';
	import BrandMark from '$lib/components/shell/BrandMark.svelte';
	import { isBare, pageTitle } from '$lib/components/shell/nav';
	import { captureChip, storageFoot, type Loaded } from '$lib/components/shell/status';

	let { children, data } = $props();

	// The sidebar's Alerts badge: last 24 hours, the same snapshot Home and Alerts read (PLAN.md §4.1).
	const ALERT_BADGE_HOURS = 24;
	const SHELL_POLL_MS = 30_000;
	/** The design system's phone breakpoint (bp-phone): below it the sidebar is a drawer. */
	const PHONE_MAX = 760;

	// OLD CODE: let captureMode = $state<Loaded<CaptureMode>>(null); (NET-225: loaded once, so a restore's new mode never reached it)
	// The interface comes from the health reply, which names the same capture interface
	let captureMode = $derived<Loaded<CaptureMode>>(
		$modeStore === 'unknown' ? 'failed' : $modeStore ? { mode: $modeStore, interface: '' } : null,
	);
	let captureHealth = $state<Loaded<CaptureHealthResponse>>(null);
	let storage = $state<Loaded<StorageStatus>>(null);

	// OLD CODE START — 2026-11-03 full redesign: the top-bar badge, the flat nav list, the
	// collapse toggle and the page-title lookup moved into the shell modules
	// (lib/components/shell/status.ts and nav.ts); the collapse toggle is dropped (the design
	// system's sidebar has no collapsed state).
	// let sidebarCollapsed = $state(false);
	// let mobileOpen = $state(false);
	// const MODE_BADGES: Record<string, { label: string; cls: string }> = {
	// 	mirror: { label: 'Mirror', cls: 'mode-mirror' },
	// 	dhcp_gateway: { label: 'DHCP Gateway', cls: 'mode-dhcp' },
	// };
	// const BRIDGE_BADGE = { label: 'Bridge', cls: 'mode-bridge' };
	// let modeBadge = $derived(captureMode ? (MODE_BADGES[captureMode.mode] ?? BRIDGE_BADGE) : null);
	// const navItems = [
	// 	{ href: '/', label: 'Home', icon: 'home' }, { href: '/logs', label: 'Log Explorer', icon: 'search' },
	// 	{ href: '/devices', label: 'Devices', icon: 'monitor' }, { href: '/alerts', label: 'Alerts', icon: 'bell' },
	// 	{ href: '/threats', label: 'Threats', icon: 'alert-triangle' }, { href: '/connections', label: 'Connections', icon: 'link' },
	// 	{ href: '/live', label: 'Live Monitor', icon: 'activity' }, { href: '/bandwidth', label: 'Bandwidth', icon: 'bar-chart-2' },
	// 	{ href: '/dns', label: 'DNS Analytics', icon: 'globe' }, { href: '/iot', label: 'IoT & LAN', icon: 'shield' },
	// 	{ href: '/changelog', label: 'Changelog', icon: 'clock' }, { href: '/certificates', label: 'Certificates', icon: 'lock' },
	// 	{ href: '/pcap', label: 'PCAP Search', icon: 'download' }, { href: '/tools', label: 'Tools', icon: 'tool' },
	// 	{ href: '/infrastructure', label: 'Infrastructure', icon: 'server' }, { href: '/system', label: 'System', icon: 'cpu' },
	// 	{ href: '/settings', label: 'Settings', icon: 'settings' },
	// ];
	// function isActive(href: string, currentPath: string): boolean {
	// 	if (href === '/') return currentPath === '/';
	// 	return currentPath.startsWith(href);
	// }
	// function toggleSidebar() { sidebarCollapsed = !sidebarCollapsed; }
	// function toggleMobile() { mobileOpen = !mobileOpen; }
	// function closeMobile() { mobileOpen = false; }
	// function getPageTitle(path: string): string {
	// 	for (const item of navItems) { if (isActive(item.href, path)) return item.label; }
	// 	return 'NetTap';
	// }
	// OLD CODE END

	let bare = $derived(isBare($page.url.pathname));

	// OLD CODE START — NET-225: the chip's own request, read once; refreshCaptureMode() never reached it.
	// pollShell asks the shared store now, so a failed startup request is asked again every 30 s.
	// $effect(() => {
	// 	if (bare) return; // login and setup have no shell to fill
	// 	getCaptureMode()
	// 		.then((mode) => (captureMode = mode))
	// 		.catch(() => (captureMode = 'failed'));
	// 	// Also populate the global store for drawer components
	// 	initCaptureMode();
	// });
	// OLD CODE END

	// OLD CODE START — 2026-11-03 full redesign: the top bar no longer says "Checking…"/"Online";
	// only the offline state shows, as a warning chip (PLAN.md §5.5).
	// const DAEMON_STATUS_TEXT = { checking: 'Checking…', online: 'Online', offline: "Can't reach NetTap" };
	// let daemonStatus = $state<keyof typeof DAEMON_STATUS_TEXT>('checking');
	// OLD CODE END
	// Offline only once the daemon has failed its liveness check, never while the first one runs.
	let daemonOffline = $state(false);

	// OLD CODE START — NET-198: a 401 (the session ran out) counted as offline, and nothing sent the user to sign in
	// async function checkDaemon() {
	// 	try {
	// 		const res = await fetch('/api/system/ping');
	// 		// a lapsed session answers 401 (NET-197), which is not the daemon answering
	// 		const body = res.ok ? await res.json() : null;
	// 		daemonOffline = body?.status !== 'ok';
	// 	} catch {
	// 		daemonOffline = true;
	// 	}
	// }
	// OLD CODE END

	/** True while a navigation to the sign-in page runs: no new poll starts meanwhile. */
	let redirecting = false;
	/** Bumped when the poller stops, so a ping that began in an earlier run can't act on its reply. */
	let shellRun = 0;

	/** NET-198: the session ran out, so open the sign-in page, which brings the user back to this page. */
	async function sendToSignIn() {
		if (redirecting) return;
		redirecting = true;
		try {
			await goto(`/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`);
		} catch (err) {
			console.error('Could not open the sign-in page:', err);
		} finally {
			redirecting = false; // a navigation that fell through leaves the shell polling, which asks again
		}
	}

	async function checkDaemon() {
		const run = shellRun;
		try {
			const res = await fetch('/api/system/ping');
			// the reply is whatever JSON came back: the fields are only compared, never trusted
			const body: { error?: unknown; status?: unknown } | null = res.ok || res.status === 401 ? await res.json() : null;
			if (run !== shellRun || redirecting) return;
			// Only the web app's own sign-in refusal (hooks.server.ts) means the session ran out; the
			// daemon's 401 is {"error":"Unauthorized"} and stays "offline", as does a login page's 200
			if (res.status === 401 && body?.error === SIGN_IN_FIRST) {
				void sendToSignIn();
				return;
			}
			daemonOffline = body?.status !== 'ok';
		} catch {
			if (run === shellRun && !redirecting) daemonOffline = true;
		}
	}

	/** Shell values each fail on their own: a failed call shows "—"/unknown, never throws. */
	function pollShell() {
		checkDaemon();
		void initCaptureMode(); // a no-op once the daemon has named the mode
		getCaptureHealth()
			.then((h) => (captureHealth = h))
			.catch(() => (captureHealth = 'failed'));
		getStorageStatus()
			.then((s) => (storage = s))
			.catch(() => (storage = 'failed'));
	}

	$effect(() => {
		if (bare) return;
		pollShell();
		loadAlertSnapshot(ALERT_BADGE_HOURS);
		const timer = setInterval(() => {
			if (document.hidden || redirecting) return; // paused while the tab is in the background
			pollShell();
			refreshAlertSnapshots();
		}, SHELL_POLL_MS);
		return () => {
			shellRun++;
			clearInterval(timer);
		};
	});

	// OLD CODE: let capture = $derived(captureChip(captureMode, captureHealth));
	let capture = $derived(
		captureChip(captureMode, captureHealth, typeof storage === 'object' && storage?.capture_paused_disk_full === true),
	);
	let storageInfo = $derived(storageFoot(storage));
	let alertCount = $derived.by(() => {
		const snap = $alertSnapshots[ALERT_BADGE_HOURS];
		return snap?.status === 'ok' && snap.data ? snap.data.counts.total : null;
	});
	/** NET-228 (audit HON-49): a failed count showed no badge, the same as zero */
	let alertCountFailed = $derived($alertSnapshots[ALERT_BADGE_HOURS]?.status === 'error');

	// ----- Phone navigation drawer -----
	let navOpen = $state(false);
	let appEl = $state<HTMLElement>();
	let sidebarEl = $state<HTMLElement>();
	let menuButton = $state<HTMLButtonElement>();

	function focusables(): HTMLElement[] {
		return sidebarEl ? [...sidebarEl.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')] : [];
	}

	async function openNav() {
		navOpen = true;
		await tick();
		focusables()[0]?.focus();
	}

	function closeNav(returnFocus = true) {
		if (!navOpen) return;
		navOpen = false;
		if (returnFocus) menuButton?.focus();
	}

	function onKeydown(e: KeyboardEvent) {
		if (!navOpen) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			closeNav();
		} else if (e.key === 'Tab') {
			// keep focus inside the open drawer
			const items = focusables();
			if (items.length === 0) return;
			const first = items[0];
			const last = items[items.length - 1];
			if (e.shiftKey && document.activeElement === first) {
				e.preventDefault();
				last.focus();
			} else if (!e.shiftKey && document.activeElement === last) {
				e.preventDefault();
				first.focus();
			}
		}
	}

	// Growing past the phone breakpoint closes the drawer (the sidebar shows normally again).
	$effect(() => {
		if (!appEl || typeof ResizeObserver === 'undefined') return;
		const ro = new ResizeObserver(([entry]) => {
			if (entry.contentRect.width > PHONE_MAX) closeNav(false);
		});
		ro.observe(appEl);
		return () => ro.disconnect();
	});

	afterNavigate(() => closeNav(false));
</script>

<svelte:window onkeydown={onKeydown} />

{#if bare}
	{@render children()}
{:else}
	<div class="app" class:nav-open={navOpen} bind:this={appEl}>
		<a class="skip btn" href="#main">Skip to content</a>
		<div class="shell">
			<Sidebar
				path={$page.url.pathname}
				{capture}
				{alertCount}
				{alertCountFailed}
				storage={storageInfo}
				username={data?.username ?? null}
				onnavigate={() => closeNav(false)}
				bind:sidebarEl
			/>
			<main class="main" id="main" tabindex="-1">
				<div class="m-top">
					<a class="brand" href="/" aria-label="NetTap home"><BrandMark /></a>
					<span class="m-title">{pageTitle($page.url.pathname)}</span>
					<button
						class="icon-btn"
						type="button"
						bind:this={menuButton}
						aria-label="Open menu"
						aria-expanded={navOpen}
						aria-controls="app-sidebar"
						onclick={() => (navOpen ? closeNav() : openNav())}
					>
						<Icon name="menu" />
					</button>
				</div>
				<TopBar offline={daemonOffline} />
				{@render children()}
			</main>
		</div>
		<button class="scrim" type="button" tabindex="-1" aria-label="Close menu" onclick={() => closeNav()}></button>
	</div>
{/if}
