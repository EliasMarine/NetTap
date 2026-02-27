import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import {
	getNotifications,
	getUnreadCount,
	markRead,
	markAllRead,
} from '$lib/server/notifications.js';

/**
 * GET /api/notifications?limit=20
 * Returns recent in-app notifications and unread count.
 */
export const GET: RequestHandler = async ({ url }) => {
	const limit = parseInt(url.searchParams.get('limit') || '20', 10);
	const notifications = getNotifications(limit);
	const unreadCount = getUnreadCount();

	return json({
		notifications,
		unreadCount,
	});
};

/**
 * POST /api/notifications
 * Body: { action: 'markRead', id: string } | { action: 'markAllRead' }
 * Marks notification(s) as read.
 */
export const POST: RequestHandler = async ({ request }) => {
	try {
		const body = await request.json();
		const action = body.action as string;

		if (action === 'markRead' && typeof body.id === 'string') {
			const success = markRead(body.id);
			if (!success) {
				return json({ error: 'Notification not found' }, { status: 404 });
			}
			return json({ success: true });
		}

		if (action === 'markAllRead') {
			const count = markAllRead();
			return json({ success: true, markedCount: count });
		}

		return json({ error: 'Invalid action. Use "markRead" or "markAllRead".' }, { status: 400 });
	} catch {
		return json({ error: 'Invalid request body' }, { status: 400 });
	}
};
