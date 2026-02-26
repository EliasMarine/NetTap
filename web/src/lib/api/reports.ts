/**
 * Client-side API helpers for scheduled report endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ReportSchedule {
	id: string;
	name: string;
	frequency: string;
	format: string;
	recipients: string[];
	sections: string[];
	enabled: boolean;
	last_run: string | null;
	next_run: string | null;
	created_at: string;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Get all report schedules.
 */
export async function getReportSchedules(): Promise<{ schedules: ReportSchedule[] }> {
	const res = await fetch('/api/reports/schedules');

	if (!res.ok) {
		return { schedules: [] };
	}

	return res.json();
}

/**
 * Create a new report schedule.
 */
export async function createReportSchedule(
	data: Partial<ReportSchedule>
): Promise<ReportSchedule | null> {
	const res = await fetch('/api/reports/schedules', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Get a single report schedule by ID.
 */
export async function getReportSchedule(id: string): Promise<ReportSchedule | null> {
	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}`);

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Update an existing report schedule.
 */
export async function updateReportSchedule(
	id: string,
	data: Partial<ReportSchedule>
): Promise<ReportSchedule | null> {
	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Delete a report schedule.
 */
export async function deleteReportSchedule(id: string): Promise<boolean> {
	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}`, {
		method: 'DELETE',
	});

	return res.ok;
}

/**
 * Enable a report schedule.
 */
export async function enableSchedule(id: string): Promise<boolean> {
	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}/enable`, {
		method: 'POST',
	});

	return res.ok;
}

/**
 * Disable a report schedule.
 */
export async function disableSchedule(id: string): Promise<boolean> {
	const res = await fetch(`/api/reports/schedules/${encodeURIComponent(id)}/disable`, {
		method: 'POST',
	});

	return res.ok;
}

/**
 * Generate a report on-demand from a schedule.
 */
export async function generateReport(id: string): Promise<Record<string, unknown> | null> {
	const res = await fetch(`/api/reports/generate/${encodeURIComponent(id)}`, {
		method: 'POST',
	});

	if (!res.ok) {
		return null;
	}

	return res.json();
}
