/**
 * Client-side API helpers for the notification hub (multi-channel notifications + routing rules).
 * Wraps daemon endpoints at /api/notifications/channels, /api/notifications/rules, etc.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A channel's last send, as the daemon reports it (NET-224). */
export interface LastDelivery {
	ok: boolean;
	at: string;
	error: string | null;
}

export interface NotificationChannel {
	id: string;
	type: 'email' | 'discord' | 'slack' | 'telegram' | 'pushover' | 'webhook';
	name: string;
	/** NET-224: never a secret; secrets show as has_<key>, URLs as <key>_hint */
	config: Record<string, unknown>;
	created_at: string;
	/** NET-224: off channels get nothing (a Settings tab channel turned off keeps its settings) */
	enabled?: boolean;
	last_delivery?: LastDelivery | null;
}

/** A save, or the daemon's reason it couldn't (NET-224: "Failed" alone said nothing). */
export type SaveResult<T> = { ok: true; data: T } | { ok: false; error: string };

/** The reason in a refused reply's body, else its status. */
async function reasonOf(res: Response): Promise<string> {
	const body = await res.json().catch(() => null);
	return typeof body?.error === 'string' ? body.error : `HTTP ${res.status}`;
}

export interface ChannelsResponse {
	channels: NotificationChannel[];
	count: number;
}

export interface RoutingRule {
	id: string;
	event_type: string;
	channels: string[];
	min_severity: number;
	created_at: string;
}

export interface RulesResponse {
	rules: RoutingRule[];
	count: number;
}

export interface DeliveryLogEntry {
	channel_id: string;
	channel_type: string;
	title: string;
	severity: number;
	success: boolean;
	/** NET-224: why it failed */
	error?: string | null;
	timestamp: string;
}

export interface DeliveryLogResponse {
	log: DeliveryLogEntry[];
	count: number;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

// OLD CODE START — was: const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8880';
// Port 8880 is Docker-internal (expose, not ports). All API calls go through
// the SvelteKit catch-all proxy at /api/[...path] which forwards to the daemon.
// OLD CODE END

/**
 * List all configured notification channels.
 */
export async function getChannels(): Promise<ChannelsResponse> {
	// OLD CODE START — #96: a failed request read as "No channels configured"
	// try {
	// 	const res = await fetch(`/api/notifications/channels`);
	// 	if (!res.ok) return { channels: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { channels: [], count: 0 };
	// }
	// OLD CODE END
	const res = await fetch(`/api/notifications/channels`);
	if (!res.ok) throw new Error(`Notification channels request failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Create a new notification channel.
 */
// OLD CODE START — NET-224: null on any failure, so the page couldn't say why
// export async function createChannel(
// 	type: string,
// 	name: string,
// 	config: Record<string, unknown>,
// ): Promise<NotificationChannel | null> {
// 	try {
// 		const res = await fetch(`/api/notifications/channels`, {
// 			method: 'POST',
// 			headers: { 'Content-Type': 'application/json' },
// 			body: JSON.stringify({ type, name, config: { ...config, name } }),
// 		});
// 		if (!res.ok) return null;
// 		return res.json();
// 	} catch {
// 		return null;
// 	}
// }
// OLD CODE END
export async function createChannel(
	type: string,
	name: string,
	config: Record<string, unknown>,
): Promise<SaveResult<NotificationChannel>> {
	try {
		const res = await fetch(`/api/notifications/channels`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ type, name, config: { ...config, name } }),
		});
		if (!res.ok) return { ok: false, error: await reasonOf(res) };
		return { ok: true, data: await res.json() };
	} catch {
		return { ok: false, error: "couldn't reach NetTap" };
	}
}

/**
 * Delete a notification channel.
 */
export async function deleteChannel(id: string): Promise<boolean> {
	try {
		const res = await fetch(`/api/notifications/channels/${id}`, {
			method: 'DELETE',
		});
		return res.ok;
	} catch {
		return false;
	}
}

/**
 * Send a test notification to a channel.
 */
// OLD CODE START — NET-224: a bare bool, so a failed test had no reason
// export async function testChannel(id: string): Promise<boolean> {
// 	try {
// 		const res = await fetch(`/api/notifications/channels/${id}/test`, {
// 			method: 'POST',
// 		});
// 		if (!res.ok) return false;
// 		const data = await res.json();
// 		return data.success === true;
// 	} catch {
// 		return false;
// 	}
// }
// OLD CODE END
export async function testChannel(id: string): Promise<{ success: boolean; error?: string }> {
	try {
		const res = await fetch(`/api/notifications/channels/${id}/test`, {
			method: 'POST',
		});
		if (!res.ok) return { success: false, error: await reasonOf(res) };
		const data = await res.json();
		if (data.success === true) return { success: true };
		return { success: false, error: typeof data.error === 'string' ? data.error : undefined };
	} catch {
		return { success: false, error: "couldn't reach NetTap" };
	}
}

/**
 * Get recent delivery log.
 */
export async function getDeliveryLog(): Promise<DeliveryLogResponse> {
	// OLD CODE START — #96: a failed request read as "No delivery attempts yet"
	// try {
	// 	const res = await fetch(`/api/notifications/log`);
	// 	if (!res.ok) return { log: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { log: [], count: 0 };
	// }
	// OLD CODE END
	const res = await fetch(`/api/notifications/log`);
	if (!res.ok) throw new Error(`Notification delivery log request failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * List all routing rules.
 */
export async function getRules(): Promise<RulesResponse> {
	// OLD CODE START — #96: a failed request read as "No routing rules configured"
	// try {
	// 	const res = await fetch(`/api/notifications/rules`);
	// 	if (!res.ok) return { rules: [], count: 0 };
	// 	return res.json();
	// } catch {
	// 	return { rules: [], count: 0 };
	// }
	// OLD CODE END
	const res = await fetch(`/api/notifications/rules`);
	if (!res.ok) throw new Error(`Notification rules request failed: HTTP ${res.status}`);
	return res.json();
}

/**
 * Create a routing rule.
 */
// OLD CODE START — NET-224: null on any failure, so the page couldn't say why
// export async function createRule(
// 	event_type: string,
// 	channels: string[],
// 	min_severity: number,
// ): Promise<RoutingRule | null> {
// 	try {
// 		const res = await fetch(`/api/notifications/rules`, {
// 			method: 'POST',
// 			headers: { 'Content-Type': 'application/json' },
// 			body: JSON.stringify({ event_type, channels, min_severity }),
// 		});
// 		if (!res.ok) return null;
// 		return res.json();
// 	} catch {
// 		return null;
// 	}
// }
// OLD CODE END
export async function createRule(
	event_type: string,
	channels: string[],
	min_severity: number,
): Promise<SaveResult<RoutingRule>> {
	try {
		const res = await fetch(`/api/notifications/rules`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ event_type, channels, min_severity }),
		});
		if (!res.ok) return { ok: false, error: await reasonOf(res) };
		return { ok: true, data: await res.json() };
	} catch {
		return { ok: false, error: "couldn't reach NetTap" };
	}
}

/**
 * Delete a routing rule.
 */
export async function deleteRule(id: string): Promise<boolean> {
	try {
		const res = await fetch(`/api/notifications/rules/${id}`, {
			method: 'DELETE',
		});
		return res.ok;
	} catch {
		return false;
	}
}
