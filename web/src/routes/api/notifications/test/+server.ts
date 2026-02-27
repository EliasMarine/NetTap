import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { sendNotification } from '$lib/server/notifications.js';

/**
 * POST /api/notifications/test
 * Sends a test notification through all configured channels.
 */
export const POST: RequestHandler = async () => {
	try {
		const notification = await sendNotification({
			type: 'system',
			severity: 'medium',
			title: 'Test Notification',
			message: 'This is a test notification from NetTap. If you received this, your notification settings are working correctly.',
		});

		return json({
			success: true,
			notification: {
				id: notification.id,
				timestamp: notification.timestamp,
			},
		});
	} catch (err) {
		return json(
			{
				error: `Failed to send test notification: ${err instanceof Error ? err.message : 'Unknown error'}`,
			},
			{ status: 500 }
		);
	}
};
