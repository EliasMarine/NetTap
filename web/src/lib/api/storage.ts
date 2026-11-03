/**
 * Client-side API helpers for manual storage cleanup.
 * Wraps POST /api/storage/cleanup/preview and /api/storage/cleanup/execute.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CleanupIndexInfo {
	name: string;
	size_bytes: number;
	tier: string;
	parsed_date: string;
}

export interface CleanupPcapInfo {
	name: string;
	size_bytes: number;
	modified: string;
}

export interface CleanupPreview {
	indices: CleanupIndexInfo[];
	pcap_files: CleanupPcapInfo[];
	total_indices: number;
	total_pcap_files: number;
	total_size_bytes: number;
	index_size_bytes: number;
	pcap_size_bytes: number;
	cutoff_date: string;
	estimated_freed_bytes: number;
}

export interface CleanupResult {
	deleted_indices: number;
	deleted_pcap_files: number;
	freed_bytes_estimate: number;
	errors: string[];
	cutoff_date: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Preview what would be deleted by a manual cleanup.
 */
export async function previewCleanup(olderThanDays: number): Promise<CleanupPreview> {
	const res = await fetch('/api/storage/cleanup/preview', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ older_than_days: olderThanDays }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Preview failed' }));
		throw new Error(data.error || `Preview failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Execute manual data cleanup, deleting indices and PCAPs older than cutoff.
 */
export async function executeCleanup(olderThanDays: number): Promise<CleanupResult> {
	const res = await fetch('/api/storage/cleanup/execute', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ older_than_days: olderThanDays }),
	});

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Cleanup failed' }));
		throw new Error(data.error || `Cleanup failed: ${res.status}`);
	}

	return res.json();
}
