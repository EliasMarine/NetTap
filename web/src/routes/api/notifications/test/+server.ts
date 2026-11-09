// OLD CODE: import { json } from '@sveltejs/kit'; (review L1: relayJSON answers)
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';
import { relayJSON } from '$lib/server/relay.js';
// OLD CODE: import { sendTestNotification } from '$lib/server/notifications.js'; (NET-224: the daemon sends)

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

// OLD CODE START — NET-224 (F3's version): sent from the web container's env, which compose never set,
// and email needed nodemailer, which the image doesn't have
// /**
//  * POST /api/notifications/test
//  * Sends a test through each enabled email/webhook channel, ignoring the severity threshold.
//  * 200 when every channel took it, 409 when none is set up, 502 naming the ones that failed.
//  */
// export const POST: RequestHandler = async () => {
// 	const results = await sendTestNotification();
// 	if (results.length === 0) {
// 		return json({ error: 'No email or webhook is set up, so there is nothing to test.' }, { status: 409 });
// 	}
// 	const failures = results.filter((r) => !r.ok);
// 	if (failures.length > 0) {
// 		const list = failures.map((f) => `${f.channel} (${f.error})`).join(', ');
// 		return json({ error: `The test didn't go through: ${list}.`, results }, { status: 502 });
// 	}
// 	return json({ success: true, results });
// };
// OLD CODE END

// Above the daemon's slowest test: SMTP gets 10 s to connect and 30 s for the rest
const TEST_TIMEOUT_MS = 60_000;

/**
 * POST /api/notifications/test
 * A test through every enabled channel, sent by the daemon (NET-224). 200 when every channel
 * took it, 409 when none is set up, 502 naming each failure and its reason.
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/notifications/test', { method: 'POST' }, TEST_TIMEOUT_MS);
	// OLD CODE START — review L1: an unreadable 200 came back as 200 { error }, read as "sent"
	// const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	// return json(data, { status: res.status });
	// OLD CODE END
	return relayJSON(res);
};
