/**
 * Client-side API helpers for the notification hub (multi-channel notifications + routing rules).
 * Wraps daemon endpoints at /api/notifications/channels, /api/notifications/rules, etc.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NotificationChannel {
	id: string;
	type: 'email' | 'discord' | 'slack' | 'telegram' | 'pushover' | 'webhook';
	name: string;
	config: Record<string, unknown>;
	created_at: string;
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
	try {
		const res = await fetch(`/api/notifications/channels`);
		if (!res.ok) return { channels: [], count: 0 };
		return res.json();
	} catch {
		return { channels: [], count: 0 };
	}
}

/**
 * Create a new notification channel.
 */
export async function createChannel(
	type: string,
	name: string,
	config: Record<string, unknown>,
): Promise<NotificationChannel | null> {
	try {
		const res = await fetch(`/api/notifications/channels`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ type, name, config: { ...config, name } }),
		});
		if (!res.ok) return null;
		return res.json();
	} catch {
		return null;
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
export async function testChannel(id: string): Promise<boolean> {
	try {
		const res = await fetch(`/api/notifications/channels/${id}/test`, {
			method: 'POST',
		});
		if (!res.ok) return false;
		const data = await res.json();
		return data.success === true;
	} catch {
		return false;
	}
}

/**
 * Get recent delivery log.
 */
export async function getDeliveryLog(): Promise<DeliveryLogResponse> {
	try {
		const res = await fetch(`/api/notifications/log`);
		if (!res.ok) return { log: [], count: 0 };
		return res.json();
	} catch {
		return { log: [], count: 0 };
	}
}

/**
 * List all routing rules.
 */
export async function getRules(): Promise<RulesResponse> {
	try {
		const res = await fetch(`/api/notifications/rules`);
		if (!res.ok) return { rules: [], count: 0 };
		return res.json();
	} catch {
		return { rules: [], count: 0 };
	}
}

/**
 * Create a routing rule.
 */
export async function createRule(
	event_type: string,
	channels: string[],
	min_severity: number,
): Promise<RoutingRule | null> {
	try {
		const res = await fetch(`/api/notifications/rules`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ event_type, channels, min_severity }),
		});
		if (!res.ok) return null;
		return res.json();
	} catch {
		return null;
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
