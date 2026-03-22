<script lang="ts">
	import '$lib/styles/global.css';
	import { page } from '$app/stores';
	import NotificationBell from '$components/NotificationBell.svelte';
	import Breadcrumb from '$components/Breadcrumb.svelte';
	import { getCaptureMode } from '$api/capture';
	import type { CaptureMode } from '$api/capture';
	import { initCaptureMode } from '$lib/stores/captureMode';

	let { children } = $props();

	let sidebarCollapsed = $state(false);
	let mobileOpen = $state(false);
	let captureMode = $state<CaptureMode | null>(null);

	$effect(() => {
		getCaptureMode().then((mode) => {
			captureMode = mode;
		}).catch(() => {
			// Silently fail — badge just won't show
		});
		// Also populate the global store for drawer components
		initCaptureMode();
	});

	const navItems = [
		{ href: '/', label: 'Home', icon: 'home' },
		{ href: '/logs', label: 'Log Explorer', icon: 'search' },
		{ href: '/devices', label: 'Devices', icon: 'monitor' },
		{ href: '/alerts', label: 'Alerts', icon: 'bell' },
		{ href: '/threats', label: 'Threats', icon: 'alert-triangle' },
		{ href: '/connections', label: 'Connections', icon: 'link' },
		{ href: '/live', label: 'Live Monitor', icon: 'activity' },
		{ href: '/bandwidth', label: 'Bandwidth', icon: 'bar-chart-2' },
		{ href: '/dns', label: 'DNS Analytics', icon: 'globe' },
		{ href: '/iot', label: 'IoT & LAN', icon: 'shield' },
		{ href: '/changelog', label: 'Changelog', icon: 'clock' },
		{ href: '/certificates', label: 'Certificates', icon: 'lock' },
		{ href: '/pcap', label: 'PCAP Search', icon: 'download' },
		{ href: '/tools', label: 'Tools', icon: 'tool' },
		{ href: '/infrastructure', label: 'Infrastructure', icon: 'server' },
		{ href: '/system', label: 'System', icon: 'cpu' },
		{ href: '/settings', label: 'Settings', icon: 'settings' },
	];

	function isActive(href: string, currentPath: string): boolean {
		if (href === '/') return currentPath === '/';
		return currentPath.startsWith(href);
	}

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
	}

	function toggleMobile() {
		mobileOpen = !mobileOpen;
	}

	function closeMobile() {
		mobileOpen = false;
	}

	function getPageTitle(path: string): string {
		for (const item of navItems) {
			if (isActive(item.href, path)) return item.label;
		}
		return 'NetTap';
	}
</script>

<svelte:head>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
</svelte:head>

{#if $page.url.pathname.startsWith('/login') || $page.url.pathname.startsWith('/setup')}
	{@render children()}
{:else}
	<div class="app-shell" class:collapsed={sidebarCollapsed}>
		{#if mobileOpen}
			<button class="sidebar-overlay" onclick={closeMobile} aria-label="Close sidebar"></button>
		{/if}

		<aside class="sidebar" class:mobile-open={mobileOpen}>
			<div class="sidebar-header">
				<div class="logo">
					<svg class="logo-icon" viewBox="0 0 28 28" width="24" height="24" fill="none">
						<rect width="28" height="28" rx="5" fill="var(--cyan)" />
						<path d="M7 14h14M14 7v14" stroke="#000" stroke-width="2.5" stroke-linecap="round" />
						<circle cx="14" cy="14" r="4" stroke="#000" stroke-width="1.5" fill="none" />
					</svg>
					{#if !sidebarCollapsed}
						<span class="logo-text">NetTap</span>
					{/if}
				</div>
				<button class="collapse-btn desktop-only" onclick={toggleSidebar} aria-label="Toggle sidebar">
					<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
						{#if sidebarCollapsed}
							<path d="M6 3l5 5-5 5" />
						{:else}
							<path d="M10 3L5 8l5 5" />
						{/if}
					</svg>
				</button>
			</div>

			<nav class="sidebar-nav">
				{#each navItems as item}
					<a
						href={item.href}
						class="nav-item"
						class:active={isActive(item.href, $page.url.pathname)}
						onclick={closeMobile}
						title={sidebarCollapsed ? item.label : undefined}
					>
						<svg class="nav-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							{#if item.icon === 'home'}
								<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" /><polyline points="9,22 9,12 15,12 15,22" />
							{:else if item.icon === 'search'}
								<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
							{:else if item.icon === 'monitor'}
								<rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
							{:else if item.icon === 'alert-triangle'}
								<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
							{:else if item.icon === 'bell'}
								<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" />
							{:else if item.icon === 'link'}
								<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
							{:else if item.icon === 'activity'}
								<polyline points="22,12 18,12 15,21 9,3 6,12 2,12" />
							{:else if item.icon === 'bar-chart-2'}
								<line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
							{:else if item.icon === 'globe'}
								<circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
							{:else if item.icon === 'shield'}
								<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
							{:else if item.icon === 'clock'}
								<circle cx="12" cy="12" r="10" /><polyline points="12,6 12,12 16,14" />
							{:else if item.icon === 'lock'}
								<rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
							{:else if item.icon === 'file-text'}
								<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14,2 14,8 20,8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
							{:else if item.icon === 'download'}
								<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7,10 12,15 17,10" /><line x1="12" y1="15" x2="12" y2="3" />
							{:else if item.icon === 'tool'}
								<path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
							{:else if item.icon === 'server'}
								<rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" /><line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" />
							{:else if item.icon === 'cpu'}
								<rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" /><line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" /><line x1="20" y1="9" x2="23" y2="9" /><line x1="20" y1="14" x2="23" y2="14" /><line x1="1" y1="9" x2="4" y2="9" /><line x1="1" y1="14" x2="4" y2="14" />
							{:else if item.icon === 'settings'}
								<circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
							{/if}
						</svg>
						{#if !sidebarCollapsed}
							<span class="nav-label">{item.label}</span>
						{/if}
					</a>
				{/each}
			</nav>

			<div class="sidebar-footer">
				{#if !sidebarCollapsed}
					<span class="version-text">v0.4.0-dev</span>
				{/if}
			</div>
		</aside>

		<div class="main-wrapper">
			<header class="topbar">
				<button class="mobile-menu-btn" onclick={toggleMobile} aria-label="Toggle menu">
					<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
						<line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="18" x2="21" y2="18" />
					</svg>
				</button>

				<h1 class="topbar-title">{getPageTitle($page.url.pathname)}</h1>

				<div class="topbar-right">
					{#if captureMode}
						<span class="mode-badge {captureMode.mode === 'mirror' ? 'mode-mirror' : 'mode-bridge'}" title="Capture mode: {captureMode.mode}">
							{captureMode.mode === 'mirror' ? 'Mirror' : 'Bridge'}
						</span>
					{/if}

					<div class="status-indicator">
						<span class="health-dot green"></span>
						<span class="status-text">Online</span>
					</div>

					<NotificationBell />

					<form method="POST" action="/api/auth/logout" class="logout-form">
						<button type="submit" class="btn btn-secondary btn-sm">Logout</button>
					</form>
				</div>
			</header>

			<Breadcrumb />

			<main class="content">
				{@render children()}
			</main>
		</div>
	</div>
{/if}

<style>
	.app-shell {
		display: flex;
		min-height: 100vh;
	}

	/* ----- Sidebar ----- */
	.sidebar {
		width: var(--sidebar-width);
		background: var(--bg-primary);
		border-right: 1px solid var(--border-dim);
		display: flex;
		flex-direction: column;
		position: fixed;
		top: 0;
		left: 0;
		bottom: 0;
		z-index: 100;
		transition: width var(--transition-normal);
	}

	.collapsed .sidebar {
		width: var(--sidebar-collapsed-width);
	}

	.sidebar-header {
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-dim);
		height: var(--topbar-height);
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.logo {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		overflow: hidden;
	}

	.logo-icon {
		flex-shrink: 0;
	}

	.logo-text {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
		letter-spacing: -0.02em;
		white-space: nowrap;
	}

	.collapse-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: 4px;
		border-radius: var(--radius-sm);
		transition: color var(--transition-fast);
		flex-shrink: 0;
	}

	.collapse-btn:hover {
		color: var(--text-primary);
	}

	.sidebar-nav {
		flex: 1;
		padding: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: 1px;
		overflow-y: auto;
		overflow-x: hidden;
	}

	.nav-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: 7px var(--space-sm);
		border-radius: var(--radius-sm);
		color: var(--text-muted);
		font-size: var(--text-sm);
		font-weight: 500;
		text-decoration: none;
		transition: all var(--transition-fast);
		white-space: nowrap;
		overflow: hidden;
	}

	.nav-item:hover {
		background-color: rgba(255, 255, 255, 0.04);
		color: var(--text-primary);
		text-decoration: none;
	}

	.nav-item.active {
		background: var(--accent-muted);
		color: var(--accent);
	}

	.nav-icon {
		flex-shrink: 0;
	}

	.sidebar-footer {
		padding: var(--space-sm) var(--space-md);
		border-top: 1px solid var(--border-dim);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 36px;
	}

	.version-text {
		font-size: 11px;
		color: var(--text-dim);
		font-family: var(--font-mono);
	}

	/* ----- Main ----- */
	.main-wrapper {
		flex: 1;
		margin-left: var(--sidebar-width);
		display: flex;
		flex-direction: column;
		min-height: 100vh;
		transition: margin-left var(--transition-normal);
	}

	.collapsed .main-wrapper {
		margin-left: var(--sidebar-collapsed-width);
	}

	/* ----- Top bar ----- */
	.topbar {
		height: var(--topbar-height);
		background: var(--bg-primary);
		border-bottom: 1px solid var(--border-dim);
		display: flex;
		align-items: center;
		padding: 0 var(--space-lg);
		gap: var(--space-md);
		position: sticky;
		top: 0;
		z-index: 50;
	}

	.topbar-title {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.topbar-right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.status-indicator {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.status-text {
		font-size: 11px;
		color: var(--text-muted);
		font-weight: 500;
	}

	.logout-form {
		display: inline;
	}

	.mobile-menu-btn {
		display: none;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: var(--space-xs);
	}

	.mobile-menu-btn:hover {
		color: var(--text-primary);
	}

	/* Capture mode badge */
	.mode-badge {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		font-size: 11px;
		font-weight: 600;
		border-radius: var(--radius-full);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.mode-mirror {
		background-color: var(--cyan-dim);
		color: var(--cyan);
	}

	.mode-bridge {
		background-color: var(--green-dim);
		color: var(--green);
	}

	.desktop-only {
		display: block;
	}

	/* ----- Content ----- */
	.content {
		flex: 1;
		padding: var(--space-lg);
		background: var(--bg-void);
	}

	/* ----- Overlay ----- */
	.sidebar-overlay {
		display: none;
		position: fixed;
		inset: 0;
		background-color: var(--bg-overlay);
		z-index: 90;
		border: none;
		cursor: pointer;
	}

	/* ----- Mobile ----- */
	@media (max-width: 768px) {
		.sidebar {
			transform: translateX(-100%);
			width: var(--sidebar-width);
		}

		.sidebar.mobile-open {
			transform: translateX(0);
		}

		.collapsed .sidebar {
			width: var(--sidebar-width);
		}

		.sidebar-overlay {
			display: block;
		}

		.main-wrapper,
		.collapsed .main-wrapper {
			margin-left: 0;
		}

		.mobile-menu-btn {
			display: flex;
		}

		.desktop-only {
			display: none;
		}

		.content {
			padding: var(--space-md);
		}
	}
</style>
