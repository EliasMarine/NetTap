import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { sendTestNotification } from '$lib/server/notifications.js';

// OLD CODE START — F3: answered success whatever happened: no channel set up, a webhook that
// refused it, an SMTP error swallowed. It also went through the severity threshold.
// import { sendNotification } from '$lib/server/notifications.js';
//
// /**
//  * POST /api/notifications/test
//  * Sends a test notification through all configured channels.
//  */
// export const POST: RequestHandler = async () => {
// 	try {
// 		const notification = await sendNotification({
// 			type: 'system',
// 			severity: 'medium',
// 			title: 'Test Notification',
// 			message: 'This is a test notification from NetTap. If you received this, your notification settings are working correctly.',
// 		});
//
// 		return json({
// 			success: true,
// 			notification: {
// 				id: notification.id,
// 				timestamp: notification.timestamp,
// 			},
// 		});
// 	} catch (err) {
// 		return json(
// 			{
// 				error: `Failed to send test notification: ${err instanceof Error ? err.message : 'Unknown error'}`,
// 			},
// 			{ status: 500 }
// 		);
// 	}
// };
// OLD CODE END

/**
 * POST /api/notifications/test
 * Sends a test through each enabled email/webhook channel, ignoring the severity threshold.
 * 200 when every channel took it, 409 when none is set up, 502 naming the ones that failed.
 */
export const POST: RequestHandler = async () => {
	const results = await sendTestNotification();
	if (results.length === 0) {
		return json({ error: 'No email or webhook is set up, so there is nothing to test.' }, { status: 409 });
	}
	const failures = results.filter((r) => !r.ok);
	if (failures.length > 0) {
		const list = failures.map((f) => `${f.channel} (${f.error})`).join(', ');
		return json({ error: `The test didn't go through: ${list}.`, results }, { status: 502 });
	}
	return json({ success: true, results });
};
