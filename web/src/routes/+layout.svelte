<script lang="ts">
	import '$lib/styles/global.css';
	import { page } from '$app/stores';
	import NotificationBell from '$components/NotificationBell.svelte';

	let { children } = $props();

	let sidebarOpen = $state(false);

	const navItems = [
		{ href: '/', label: 'Dashboard', icon: 'grid' },
		{ href: '/connections', label: 'Connections', icon: 'link' },
		{ href: '/alerts', label: 'Alerts', icon: 'bell' },
		{ href: '/system', label: 'System', icon: 'cpu' },
		{ href: '/settings', label: 'Settings', icon: 'settings' },
	];

	function isActive(href: string, currentPath: string): boolean {
		if (href === '/') return currentPath === '/';
		return currentPath.startsWith(href);
	}

	function toggleSidebar() {
		sidebarOpen = !sidebarOpen;
	}

	function closeSidebar() {
		sidebarOpen = false;
	}
</script>

{#if $page.url.pathname.startsWith('/login') || $page.url.pathname.startsWith('/setup')}
	<!-- No shell for login/setup pages -->
	{@render children()}
{:else}
	<div class="app-shell">
		<!-- Mobile overlay -->
		{#if sidebarOpen}
			<button class="sidebar-overlay" onclick={closeSidebar} aria-label="Close sidebar"></button>
		{/if}

		<!-- Sidebar -->
		<aside class="sidebar" class:sidebar-open={sidebarOpen}>
			<div class="sidebar-header">
				<div class="logo">
					<svg class="logo-icon" viewBox="0 0 32 32" width="28" height="28" fill="none">
						<rect width="32" height="32" rx="6" fill="var(--accent)" />
						<path d="M8 16h16M16 8v16M10 10l12 12M22 10L10 22" stroke="#fff" stroke-width="2" stroke-linecap="round" />
					</svg>
					<span class="logo-text">NetTap</span>
				</div>
			</div>

			<nav class="sidebar-nav">
				{#each navItems as item}
					<a
						href={item.href}
						class="nav-item"
						class:active={isActive(item.href, $page.url.pathname)}
						onclick={closeSidebar}
					>
						<svg class="nav-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							{#if item.icon === 'grid'}
								<rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
							{:else if item.icon === 'link'}
								<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
							{:else if item.icon === 'bell'}
								<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" />
							{:else if item.icon === 'cpu'}
								<rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" />
							{:else if item.icon === 'settings'}
								<circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
							{/if}
						</svg>
						<span class="nav-label">{item.label}</span>
					</a>
				{/each}
			</nav>

			<div class="sidebar-footer">
				<div class="sidebar-footer-info">
					<span class="version-text">v0.3.0</span>
				</div>
			</div>
		</aside>

		<!-- Main content area -->
		<div class="main-wrapper">
			<!-- Top bar -->
			<header class="topbar">
				<button class="mobile-menu-btn" onclick={toggleSidebar} aria-label="Toggle sidebar">
					<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="18" x2="21" y2="18" />
					</svg>
				</button>

				<div class="topbar-title">
					{#each navItems as item}
						{#if isActive(item.href, $page.url.pathname)}
							<h1>{item.label}</h1>
						{/if}
					{/each}
				</div>

				<div class="topbar-right">
					<div class="status-indicators">
						<span class="status-dot status-online" title="System Online"></span>
						<span class="status-label">Online</span>
					</div>

					<NotificationBell />

					<form method="POST" action="/api/auth/logout" class="logout-form">
						<button type="submit" class="btn btn-secondary btn-sm">Logout</button>
					</form>
				</div>
			</header>

			<!-- Page content -->
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
		background-color: var(--bg-secondary);
		border-right: 1px solid var(--border-default);
		display: flex;
		flex-direction: column;
		position: fixed;
		top: 0;
		left: 0;
		bottom: 0;
		z-index: 100;
		transition: transform var(--transition-normal);
	}

	.sidebar-header {
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--border-default);
		height: var(--topbar-height);
		display: flex;
		align-items: center;
	}

	.logo {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.logo-icon {
		flex-shrink: 0;
	}

	.logo-text {
		font-size: var(--text-xl);
		font-weight: 700;
		color: var(--text-primary);
		letter-spacing: -0.025em;
	}

	.sidebar-nav {
		flex: 1;
		padding: var(--space-sm);
		display: flex;
		flex-direction: column;
		gap: 2px;
		overflow-y: auto;
	}

	.nav-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		border-radius: var(--radius-md);
		color: var(--text-secondary);
		font-size: var(--text-sm);
		font-weight: 500;
		text-decoration: none;
		transition: all var(--transition-fast);
	}

	.nav-item:hover {
		background-color: var(--bg-tertiary);
		color: var(--text-primary);
		text-decoration: none;
	}

	.nav-item.active {
		background-color: var(--accent-muted);
		color: var(--accent);
	}

	.nav-icon {
		flex-shrink: 0;
	}

	.sidebar-footer {
		padding: var(--space-md);
		border-top: 1px solid var(--border-default);
	}

	.sidebar-footer-info {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.version-text {
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	/* ----- Main wrapper ----- */
	.main-wrapper {
		flex: 1;
		margin-left: var(--sidebar-width);
		display: flex;
		flex-direction: column;
		min-height: 100vh;
	}

	/* ----- Top bar ----- */
	.topbar {
		height: var(--topbar-height);
		background-color: var(--bg-secondary);
		border-bottom: 1px solid var(--border-default);
		display: flex;
		align-items: center;
		padding: 0 var(--space-lg);
		gap: var(--space-md);
		position: sticky;
		top: 0;
		z-index: 50;
	}

	.topbar-title h1 {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
	}

	.topbar-right {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	.status-indicators {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.status-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		display: inline-block;
	}

	.status-online {
		background-color: var(--success);
		box-shadow: 0 0 6px var(--success);
	}

	.status-label {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		font-weight: 500;
	}

	.logout-form {
		display: inline;
	}

	.mobile-menu-btn {
		display: none;
		background: none;
		border: none;
		color: var(--text-secondary);
		cursor: pointer;
		padding: var(--space-xs);
	}

	.mobile-menu-btn:hover {
		color: var(--text-primary);
	}

	/* ----- Content ----- */
	.content {
		flex: 1;
		padding: var(--space-lg);
	}

	/* ----- Overlay (mobile) ----- */
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
		}

		.sidebar-open {
			transform: translateX(0);
		}

		.sidebar-overlay {
			display: block;
		}

		.main-wrapper {
			margin-left: 0;
		}

		.mobile-menu-btn {
			display: flex;
		}

		.content {
			padding: var(--space-md);
		}
	}
</style>
