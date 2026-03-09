/**
 * Client-side API helpers for the changelog (network event audit log).
 * Wraps daemon endpoints at /api/changelog.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChangelogEvent {
	_id: string;
	'@timestamp': string;
	event_type: string;
	title: string;
	description: string;
	metadata: Record<string, unknown>;
}

export interface ChangelogResponse {
	events: ChangelogEvent[];
	count: number;
}

export interface EventTypesResponse {
	event_types: string[];
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8880';

/**
 * Query changelog events with optional filters.
 */
export async function getChangelogEvents(params?: {
	from?: string;
	to?: string;
	type?: string;
	limit?: number;
}): Promise<ChangelogResponse> {
	try {
		const qs = new URLSearchParams();
		if (params?.from) qs.set('from', params.from);
		if (params?.to) qs.set('to', params.to);
		if (params?.type) qs.set('type', params.type);
		if (params?.limit) qs.set('limit', String(params.limit));

		const res = await fetch(`${API_BASE}/api/changelog?${qs.toString()}`);
		if (!res.ok) return { events: [], count: 0 };
		return res.json();
	} catch {
		return { events: [], count: 0 };
	}
}

/**
 * Get distinct event types.
 */
export async function getEventTypes(): Promise<string[]> {
	try {
		const res = await fetch(`${API_BASE}/api/changelog/types`);
		if (!res.ok) return [];
		const data: EventTypesResponse = await res.json();
		return data.event_types;
	} catch {
		return [];
	}
}
