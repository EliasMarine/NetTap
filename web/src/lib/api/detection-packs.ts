/**
 * Client-side API helpers for community detection pack endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DetectionPack {
	id: string;
	name: string;
	description: string;
	version: string;
	author: string;
	rule_count: number;
	enabled: boolean;
	installed_at: string;
	updated_at: string;
	category: string;
	tags: string[];
	source_url: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get all installed detection packs.
 */
export async function getDetectionPacks(): Promise<{ packs: DetectionPack[] }> {
	const res = await fetch('/api/detection-packs');

	if (!res.ok) {
		return { packs: [] };
	}

	return res.json();
}

/**
 * Get a single detection pack by ID.
 */
export async function getDetectionPack(id: string): Promise<DetectionPack | null> {
	const res = await fetch(`/api/detection-packs/${encodeURIComponent(id)}`);

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Install a detection pack from the community registry.
 */
export async function installPack(id: string): Promise<DetectionPack | null> {
	const res = await fetch(`/api/detection-packs/${encodeURIComponent(id)}/install`, {
		method: 'POST',
	});

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Uninstall (remove) a detection pack.
 */
export async function uninstallPack(id: string): Promise<boolean> {
	const res = await fetch(`/api/detection-packs/${encodeURIComponent(id)}`, {
		method: 'DELETE',
	});

	return res.ok;
}

/**
 * Enable a detection pack (activate its rules).
 */
export async function enablePack(id: string): Promise<boolean> {
	const res = await fetch(`/api/detection-packs/${encodeURIComponent(id)}/enable`, {
		method: 'POST',
	});

	return res.ok;
}

/**
 * Disable a detection pack (deactivate its rules).
 */
export async function disablePack(id: string): Promise<boolean> {
	const res = await fetch(`/api/detection-packs/${encodeURIComponent(id)}/disable`, {
		method: 'POST',
	});

	return res.ok;
}

/**
 * Check for available updates for installed detection packs.
 */
export async function checkPackUpdates(): Promise<{
	updates: { pack_id: string; current_version: string; available_version: string }[];
}> {
	const res = await fetch('/api/detection-packs/updates');

	if (!res.ok) {
		return { updates: [] };
	}

	return res.json();
}

/**
 * Get aggregate statistics about detection packs.
 */
export async function getPackStats(): Promise<{
	total: number;
	enabled: number;
	total_rules: number;
}> {
	const res = await fetch('/api/detection-packs/stats');

	if (!res.ok) {
		return { total: 0, enabled: 0, total_rules: 0 };
	}

	return res.json();
}
