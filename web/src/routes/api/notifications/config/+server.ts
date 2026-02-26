import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { loadConfig } from '$lib/server/notifications.js';

/**
 * GET /api/notifications/config
 * Returns current notification configuration (loaded from env vars).
 * Passwords are redacted.
 */
export const GET: RequestHandler = async () => {
	const config = loadConfig();

	// Redact SMTP password for security
	return json({
		email: {
			enabled: config.email.enabled,
			recipients: config.email.recipients,
			smtpHost: config.email.smtpHost,
			smtpPort: config.email.smtpPort,
			smtpUser: config.email.smtpUser,
			smtpFrom: config.email.smtpFrom,
			// Password intentionally omitted
		},
		webhook: config.webhook,
		inApp: config.inApp,
		severityThreshold: config.severityThreshold,
	});
};

/**
 * POST /api/notifications/config
 * Save notification configuration.
 *
 * Note: In production, this would persist to a config file or database.
 * For now, notification config is driven by environment variables.
 * This endpoint acknowledges the save but the actual config comes from env.
 */
export const POST: RequestHandler = async ({ request }) => {
	try {
		const _body = await request.json();
		// In a full implementation, this would write to a config store.
		// For now, return success — config is managed via env vars.
		return json({
			success: true,
			message: 'Configuration received. Set environment variables and restart to apply SMTP/webhook changes.',
		});
	} catch {
		return json({ error: 'Invalid request body' }, { status: 400 });
	}
};
