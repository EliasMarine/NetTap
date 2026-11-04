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
	import { createNotificationStream } from '$api/notification-stream';
	import { goto } from '$app/navigation';
	import Icon from '$lib/components/ui/Icon.svelte';

	// State
	let notifications = $state<Notification[]>([]);
	let unreadCount = $state(0);
	let open = $state(false);
	let loading = $state(false);
	// #96: the last fetch failed, so an empty list is not "No notifications"
	let fetchFailed = $state(false);

	// Fetch notifications
	async function fetchNotifications() {
		loading = true;
		try {
			const res = await getNotifications(15);
			notifications = res.notifications;
			unreadCount = res.unreadCount;
			fetchFailed = false;
		} catch {
			// OLD CODE START — #96: a failure was silent, so the bell said "No notifications"
			// // Silently fail — bell just shows 0
			// OLD CODE END
			// Keep the last list; the dropdown says it couldn't refresh
			fetchFailed = true;
		} finally {
			loading = false;
		}
	}

	// Trigger alert→notification conversion pipeline (best-effort)
	async function triggerAlertNotifications() {
		try {
			await fetch('/api/notifications/from-alerts');
		} catch {
			// Best-effort — don't block notification display
		}
	}

	// SSE real-time push with polling fallback
	$effect(() => {
		triggerAlertNotifications().then(() => fetchNotifications());

		// SSE real-time push
		const stream = createNotificationStream((notification) => {
			// Prepend new notification
			notifications = [notification, ...notifications].slice(0, 15);
			if (!notification.read) {
				unreadCount++;
			}
		});

		// Fallback polling — slower when SSE is active
		const interval = setInterval(
			() => {
				fetchNotifications();
			},
			stream.isConnected() ? 60_000 : 30_000
		);

		return () => {
			stream.close();
			clearInterval(interval);
		};
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
			if (n.type === 'alert') {
				goto('/threats');
				open = false;
			}
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
		class="icon-btn"
		type="button"
		onclick={toggleDropdown}
		aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
		aria-expanded={open}
	>
		<Icon name="alerts" />
		{#if unreadCount > 0}
			<span class="badge-dot" aria-hidden="true">{unreadCount > 99 ? '99+' : unreadCount}</span>
		{/if}
	</button>

	{#if open}
		<div class="notification-dropdown">
			<div class="dropdown-header">
				<span class="dropdown-title">Notifications</span>
				{#if unreadCount > 0}
					<button class="link mark-all-btn" type="button" onclick={handleMarkAllRead}>
						Mark all read
					</button>
				{/if}
			</div>

			<div class="dropdown-list">
				{#if loading && notifications.length === 0}
					<div class="dropdown-empty">Loading…</div>
				<!-- OLD CODE START — #96: a failed fetch read as "No notifications"
				{:else if notifications.length === 0}
					<div class="dropdown-empty">No notifications</div>
				{:else}
				OLD CODE END -->
				{:else if fetchFailed && notifications.length === 0}
					<div class="dropdown-empty">Couldn't load notifications: the request failed.</div>
				{:else if notifications.length === 0}
					<div class="dropdown-empty">No notifications</div>
				{:else}
					{#if fetchFailed}
						<div class="dropdown-stale">Couldn't refresh notifications: showing the last ones.</div>
					{/if}
					{#each notifications as notification (notification.id)}
						<button
							class="notification-item"
							type="button"
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
				<a class="link" href="/alerts" onclick={() => (open = false)}>View all alerts</a>
			</div>
		</div>
	{/if}
</div>

<style>
	/* Button and badge come from system.css (.icon-btn, .badge-dot); this styles the dropdown. */
	.notification-bell {
		position: relative;
	}

	.notification-dropdown {
		position: absolute;
		top: calc(100% + var(--sp-2));
		right: 0;
		z-index: 40;
		width: 360px;
		max-height: 480px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--surface-1);
		border: 1px solid var(--line-strong);
		border-radius: var(--r-lg);
		box-shadow: var(--shadow-pop);
	}

	.dropdown-header,
	.dropdown-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--sp-3) var(--sp-4);
	}

	.dropdown-header {
		border-bottom: 1px solid var(--line);
	}

	.dropdown-footer {
		justify-content: center;
		border-top: 1px solid var(--line);
	}

	.dropdown-title {
		font: 600 var(--text-sm) / 1.2 var(--font-display);
		color: var(--text-1);
	}

	.mark-all-btn {
		padding: 0;
		border: 0;
		background: none;
		cursor: pointer;
	}

	.dropdown-list {
		flex: 1;
		overflow-y: auto;
	}

	.dropdown-empty {
		padding: var(--sp-6) var(--sp-4);
		text-align: center;
		color: var(--text-3);
		font-size: var(--text-sm);
	}

	.dropdown-stale {
		padding: var(--sp-2) var(--sp-4);
		color: var(--sev-medium);
		font-size: var(--text-xs);
	}

	.notification-item {
		display: flex;
		gap: var(--sp-3);
		width: 100%;
		padding: var(--sp-3) var(--sp-4);
		text-align: left;
		font: inherit;
		color: var(--text-2);
		background: none;
		border: 0;
		border-bottom: 1px solid var(--line);
		cursor: pointer;
	}

	.notification-item:last-child {
		border-bottom: 0;
	}

	.notification-item:hover {
		background: var(--surface-2);
	}

	.notification-item.unread {
		background: color-mix(in srgb, var(--accent) 6%, transparent);
	}

	.notif-indicator {
		width: 8px;
		height: 8px;
		margin-top: 6px;
		flex: none;
		border-radius: 50%;
		background: var(--text-3);
	}

	.notif-indicator.severity-critical { background: var(--sev-critical); }
	.notif-indicator.severity-high { background: var(--sev-high); }
	.notif-indicator.severity-medium { background: var(--sev-medium); }
	.notif-indicator.severity-low { background: var(--sev-low); }

	.notif-content {
		flex: 1;
		min-width: 0;
	}

	.notif-title {
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-1);
	}

	.notif-message {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		margin-top: var(--sp-1);
		font-size: var(--text-xs);
	}

	.notif-meta {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		margin-top: var(--sp-1);
		font-size: var(--text-micro);
	}

	/* The word beside the dot: colour, shape and word together, in sentence case */
	.notif-severity {
		display: inline-block;
		font-weight: 600;
	}

	.notif-severity::first-letter {
		text-transform: uppercase;
	}

	.notif-severity.severity-critical { color: var(--sev-critical); }
	.notif-severity.severity-high { color: var(--sev-high); }
	.notif-severity.severity-medium { color: var(--sev-medium); }
	.notif-severity.severity-low { color: var(--sev-low); }

	.notif-time {
		color: var(--text-3);
	}

	@container app (max-width: 760px) {
		.notification-dropdown {
			position: fixed;
			top: var(--sp-8);
			left: var(--sp-4);
			right: var(--sp-4);
			width: auto;
		}
	}
</style>
