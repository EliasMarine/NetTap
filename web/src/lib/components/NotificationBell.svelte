<script lang="ts">
	/**
	 * NotificationBell — Topbar notification bell with unread badge and dropdown panel.
	 *
	 * Fetches notifications on mount and polls periodically.
	 * Displays a dropdown with recent notifications.
	 * Clicking a notification marks it as read.
	 */

	import {
		getNotifications,
		markNotificationRead,
		markAllNotificationsRead,
		type Notification,
	} from '$api/notifications';

	// State
	let notifications = $state<Notification[]>([]);
	let unreadCount = $state(0);
	let open = $state(false);
	let loading = $state(false);

	// Fetch notifications
	async function fetchNotifications() {
		loading = true;
		try {
			const res = await getNotifications(15);
			notifications = res.notifications;
			unreadCount = res.unreadCount;
		} catch {
			// Silently fail — bell just shows 0
		} finally {
			loading = false;
		}
	}

	// Poll every 30 seconds
	$effect(() => {
		fetchNotifications();
		const interval = setInterval(fetchNotifications, 30_000);
		return () => clearInterval(interval);
	});

	// Close dropdown on outside click
	let bellRef: HTMLDivElement | undefined = $state(undefined);

	$effect(() => {
		if (!open) return;
		function handleClick(e: MouseEvent) {
			if (bellRef && !bellRef.contains(e.target as Node)) {
				open = false;
			}
		}
		document.addEventListener('click', handleClick);
		return () => document.removeEventListener('click', handleClick);
	});

	function toggleDropdown() {
		open = !open;
		if (open && notifications.length === 0) {
			fetchNotifications();
		}
	}

	async function handleMarkRead(id: string) {
		await markNotificationRead(id);
		const n = notifications.find((n) => n.id === id);
		if (n) {
			n.read = true;
			notifications = [...notifications]; // trigger reactivity
			unreadCount = Math.max(0, unreadCount - 1);
		}
	}

	async function handleMarkAllRead() {
		await markAllNotificationsRead();
		notifications = notifications.map((n) => ({ ...n, read: true }));
		unreadCount = 0;
	}

	function severityClass(severity: string): string {
		switch (severity) {
			case 'critical':
				return 'severity-critical';
			case 'high':
				return 'severity-high';
			case 'medium':
				return 'severity-medium';
			case 'low':
				return 'severity-low';
			default:
				return '';
		}
	}

	function timeAgo(timestamp: string): string {
		const diff = Date.now() - new Date(timestamp).getTime();
		const minutes = Math.floor(diff / 60_000);
		if (minutes < 1) return 'just now';
		if (minutes < 60) return `${minutes}m ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}
</script>

<div class="notification-bell" bind:this={bellRef}>
	<button
		class="bell-button"
		onclick={toggleDropdown}
		aria-label="Notifications"
		aria-expanded={open}
	>
		<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" />
			<path d="M13.73 21a2 2 0 01-3.46 0" />
		</svg>
		{#if unreadCount > 0}
			<span class="unread-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
		{/if}
	</button>

	{#if open}
		<div class="notification-dropdown">
			<div class="dropdown-header">
				<span class="dropdown-title">Notifications</span>
				{#if unreadCount > 0}
					<button class="mark-all-btn" onclick={handleMarkAllRead}>
						Mark all read
					</button>
				{/if}
			</div>

			<div class="dropdown-list">
				{#if loading && notifications.length === 0}
					<div class="dropdown-empty">Loading...</div>
				{:else if notifications.length === 0}
					<div class="dropdown-empty">No notifications</div>
				{:else}
					{#each notifications as notification (notification.id)}
						<button
							class="notification-item"
							class:unread={!notification.read}
							onclick={() => handleMarkRead(notification.id)}
						>
							<div class="notif-indicator {severityClass(notification.severity)}"></div>
							<div class="notif-content">
								<div class="notif-title">{notification.title}</div>
								<div class="notif-message">{notification.message}</div>
								<div class="notif-meta">
									<span class="notif-severity {severityClass(notification.severity)}">
										{notification.severity}
									</span>
									<span class="notif-time">{timeAgo(notification.timestamp)}</span>
								</div>
							</div>
						</button>
					{/each}
				{/if}
			</div>

			<div class="dropdown-footer">
				<a href="/alerts" onclick={() => (open = false)}>View all alerts</a>
			</div>
		</div>
	{/if}
</div>

<style>
	.notification-bell {
		position: relative;
	}

	.bell-button {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		background: none;
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		color: var(--text-secondary);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.bell-button:hover {
		background-color: var(--bg-tertiary);
		color: var(--text-primary);
	}

	.unread-badge {
		position: absolute;
		top: 2px;
		right: 2px;
		min-width: 16px;
		height: 16px;
		padding: 0 4px;
		font-size: 10px;
		font-weight: 700;
		line-height: 16px;
		text-align: center;
		background-color: var(--danger);
		color: #fff;
		border-radius: var(--radius-full);
	}

	.notification-dropdown {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		width: 360px;
		max-height: 480px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-lg);
		z-index: 200;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.dropdown-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-sm) var(--space-md);
		border-bottom: 1px solid var(--border-default);
	}

	.dropdown-title {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
	}

	.mark-all-btn {
		font-size: var(--text-xs);
		font-family: var(--font-sans);
		color: var(--accent);
		background: none;
		border: none;
		cursor: pointer;
		padding: 2px 4px;
		border-radius: var(--radius-sm);
	}

	.mark-all-btn:hover {
		background-color: var(--accent-muted);
	}

	.dropdown-list {
		flex: 1;
		overflow-y: auto;
		max-height: 380px;
	}

	.dropdown-empty {
		padding: var(--space-xl);
		text-align: center;
		color: var(--text-muted);
		font-size: var(--text-sm);
	}

	.notification-item {
		display: flex;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		width: 100%;
		text-align: left;
		background: none;
		border: none;
		border-bottom: 1px solid var(--border-muted);
		cursor: pointer;
		transition: background-color var(--transition-fast);
		font-family: var(--font-sans);
	}

	.notification-item:hover {
		background-color: var(--bg-tertiary);
	}

	.notification-item.unread {
		background-color: rgba(88, 166, 255, 0.04);
	}

	.notification-item:last-child {
		border-bottom: none;
	}

	.notif-indicator {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
		margin-top: 6px;
	}

	.severity-critical {
		background-color: var(--danger);
		color: var(--danger);
	}

	.severity-high {
		background-color: var(--warning);
		color: var(--warning);
	}

	.severity-medium {
		background-color: var(--accent);
		color: var(--accent);
	}

	.severity-low {
		background-color: var(--text-muted);
		color: var(--text-muted);
	}

	.notif-content {
		flex: 1;
		min-width: 0;
	}

	.notif-title {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--text-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.notif-message {
		font-size: var(--text-xs);
		color: var(--text-secondary);
		margin-top: 2px;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.notif-meta {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-top: 4px;
	}

	.notif-severity {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.notif-time {
		font-size: 10px;
		color: var(--text-muted);
	}

	.dropdown-footer {
		padding: var(--space-sm) var(--space-md);
		border-top: 1px solid var(--border-default);
		text-align: center;
	}

	.dropdown-footer a {
		font-size: var(--text-xs);
		font-weight: 500;
	}

	@media (max-width: 640px) {
		.notification-dropdown {
			width: calc(100vw - 32px);
			right: -8px;
		}
	}
</style>
