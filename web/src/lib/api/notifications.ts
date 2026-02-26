/**
 * Client-side API helpers for the in-app notification system.
 */

import type { Notification } from '$lib/server/notifications.js';

// Re-export the Notification type for convenience
export type { Notification } from '$lib/server/notifications.js';

export interface NotificationsResponse {
	notifications: Notification[];
	unreadCount: number;
}

/**
 * Fetch recent notifications and unread count.
 */
export async function getNotifications(limit: number = 20): Promise<NotificationsResponse> {
	const res = await fetch(`/api/notifications?limit=${limit}`);

	if (!res.ok) {
		return { notifications: [], unreadCount: 0 };
	}

	return res.json();
}

/**
 * Mark a single notification as read.
 */
export async function markNotificationRead(id: string): Promise<boolean> {
	const res = await fetch('/api/notifications', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ action: 'markRead', id }),
	});

	return res.ok;
}

/**
 * Mark all notifications as read.
 */
export async function markAllNotificationsRead(): Promise<boolean> {
	const res = await fetch('/api/notifications', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ action: 'markAllRead' }),
	});

	return res.ok;
}
