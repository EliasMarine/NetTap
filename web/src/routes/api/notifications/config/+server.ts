// OLD CODE: import { json } from '@sveltejs/kit'; (review L1: relayJSON answers)
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';
import { relayJSON } from '$lib/server/relay.js';
// OLD CODE START — NET-224: read the web container's env, which compose never set; the daemon keeps it now
// import { loadConfig } from '$lib/server/notifications.js';
//
// /**
//  * GET /api/notifications/config
//  * Returns current notification configuration (loaded from env vars).
//  * Passwords are redacted.
//  */
// export const GET: RequestHandler = async () => {
// 	const config = loadConfig();
//
// 	// Redact SMTP password for security
// 	return json({
// 		email: {
// 			enabled: config.email.enabled,
// 			recipients: config.email.recipients,
// 			smtpHost: config.email.smtpHost,
// 			smtpPort: config.email.smtpPort,
// 			smtpUser: config.email.smtpUser,
// 			smtpFrom: config.email.smtpFrom,
// 			// Password intentionally omitted
// 		},
// 		webhook: config.webhook,
// 		inApp: config.inApp,
// 		severityThreshold: config.severityThreshold,
// 	});
// };
// OLD CODE END

// OLD CODE START — F3: threw the body away and answered success, so the page said "saved
// successfully" when nothing was saved. Email and webhook come from the environment in this version.
// /**
//  * POST /api/notifications/config
//  * Save notification configuration.
//  *
//  * Note: In production, this would persist to a config file or database.
//  * For now, notification config is driven by environment variables.
//  * This endpoint acknowledges the save but the actual config comes from env.
//  */
// export const POST: RequestHandler = async ({ request }) => {
// 	try {
// 		const _body = await request.json();
// 		// In a full implementation, this would write to a config store.
// 		// For now, return success — config is managed via env vars.
// 		return json({
// 			success: true,
// 			message: 'Configuration received. Set environment variables and restart to apply SMTP/webhook changes.',
// 		});
// 	} catch {
// 		return json({ error: 'Invalid request body' }, { status: 400 });
// 	}
// };
// OLD CODE END

// OLD CODE START — NET-224: F3's honest 501; the daemon saves the settings for real now
// /**
//  * POST /api/notifications/config
//  * Not implemented: nothing here persists the settings, so it says so rather than claim a save.
//  */
// export const POST: RequestHandler = async () =>
// 	json(
// 		{ error: "Not saved: email and webhook notifications can't be set from this page in this version." },
// 		{ status: 501 },
// 	);
// OLD CODE END

// OLD CODE START — review L1: an unreadable 2xx came back as 200 { error }, which the page took for the saved settings
// /** The daemon's answer, with its status: a refusal keeps its reason for the page. */
// async function relay(res: Response): Promise<Response> {
// 	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
// 	return json(data, { status: res.status });
// }
// OLD CODE END

/**
 * GET /api/notifications/config
 * The Settings tab's alert email, webhook and minimum severity, kept by the daemon (NET-224).
 * It never carries the webhook URL or a password, only whether one is saved.
 */
export const GET: RequestHandler = async () => relayJSON(await daemonFetch('/api/notifications/config'));

/**
 * PUT /api/notifications/config
 * Body: { min_severity: 1-4, email: { enabled, recipients }, webhook: { enabled, url } }.
 * A blank url keeps the saved one. 400 says why it can't be saved.
 */
export const PUT: RequestHandler = async ({ request }) =>
	relayJSON(
		await daemonFetch('/api/notifications/config', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: await request.text(),
		}),
	);
