/**
 * Client-side API helpers for investigation management endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InvestigationNote {
	id: string;
	content: string;
	created_at: string;
	updated_at: string;
}

export interface Investigation {
	id: string;
	title: string;
	description: string;
	status: string; // 'open' | 'in_progress' | 'resolved' | 'closed'
	severity: string; // 'low' | 'medium' | 'high' | 'critical'
	created_at: string;
	updated_at: string;
	alert_ids: string[];
	device_ips: string[];
	notes: InvestigationNote[];
	tags: string[];
}

export interface InvestigationStats {
	total: number;
	by_status: Record<string, number>;
	by_severity: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string | number | undefined>): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== '') {
			qs.set(key, String(value));
		}
	}
	const str = qs.toString();
	return str ? `?${str}` : '';
}

// ---------------------------------------------------------------------------
// Fetch helpers — Investigation CRUD
// ---------------------------------------------------------------------------

/**
 * Get a filtered list of investigations.
 */
export async function getInvestigations(
	opts?: { status?: string; severity?: string }
): Promise<{ investigations: Investigation[] }> {
	const query = buildQuery({ status: opts?.status, severity: opts?.severity });
	const res = await fetch(`/api/investigations${query}`);

	if (!res.ok) {
		return { investigations: [] };
	}

	return res.json();
}

/**
 * Create a new investigation.
 */
export async function createInvestigation(data: {
	title: string;
	description?: string;
	severity?: string;
	alert_ids?: string[];
	device_ips?: string[];
	tags?: string[];
}): Promise<Investigation> {
	const res = await fetch('/api/investigations', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});

	if (!res.ok) {
		return {
			id: '',
			title: data.title,
			description: data.description || '',
			status: 'open',
			severity: data.severity || 'medium',
			created_at: '',
			updated_at: '',
			alert_ids: data.alert_ids || [],
			device_ips: data.device_ips || [],
			notes: [],
			tags: data.tags || [],
		};
	}

	return res.json();
}

/**
 * Get a single investigation by ID.
 */
export async function getInvestigation(id: string): Promise<Investigation | null> {
	const res = await fetch(`/api/investigations/${encodeURIComponent(id)}`);

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Update an existing investigation.
 */
export async function updateInvestigation(
	id: string,
	data: Partial<Investigation>
): Promise<Investigation | null> {
	const res = await fetch(`/api/investigations/${encodeURIComponent(id)}`, {
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
 * Delete an investigation.
 */
export async function deleteInvestigation(id: string): Promise<boolean> {
	const res = await fetch(`/api/investigations/${encodeURIComponent(id)}`, {
		method: 'DELETE',
	});

	return res.ok;
}

// ---------------------------------------------------------------------------
// Fetch helpers — Notes
// ---------------------------------------------------------------------------

/**
 * Add a note to an investigation.
 */
export async function addNote(
	investigationId: string,
	content: string
): Promise<InvestigationNote | null> {
	const res = await fetch(
		`/api/investigations/${encodeURIComponent(investigationId)}/notes`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ content }),
		}
	);

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Update a note on an investigation.
 */
export async function updateNote(
	investigationId: string,
	noteId: string,
	content: string
): Promise<InvestigationNote | null> {
	const res = await fetch(
		`/api/investigations/${encodeURIComponent(investigationId)}/notes/${encodeURIComponent(noteId)}`,
		{
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ content }),
		}
	);

	if (!res.ok) {
		return null;
	}

	return res.json();
}

/**
 * Delete a note from an investigation.
 */
export async function deleteNote(
	investigationId: string,
	noteId: string
): Promise<boolean> {
	const res = await fetch(
		`/api/investigations/${encodeURIComponent(investigationId)}/notes/${encodeURIComponent(noteId)}`,
		{
			method: 'DELETE',
		}
	);

	return res.ok;
}

// ---------------------------------------------------------------------------
// Fetch helpers — Alert linking
// ---------------------------------------------------------------------------

/**
 * Link an alert to an investigation.
 */
export async function linkAlert(
	investigationId: string,
	alertId: string
): Promise<boolean> {
	const res = await fetch(
		`/api/investigations/${encodeURIComponent(investigationId)}/alerts`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ alert_id: alertId }),
		}
	);

	return res.ok;
}

/**
 * Unlink an alert from an investigation.
 */
export async function unlinkAlert(
	investigationId: string,
	alertId: string
): Promise<boolean> {
	const res = await fetch(
		`/api/investigations/${encodeURIComponent(investigationId)}/alerts/${encodeURIComponent(alertId)}`,
		{
			method: 'DELETE',
		}
	);

	return res.ok;
}

// ---------------------------------------------------------------------------
// Fetch helpers — Device linking
// ---------------------------------------------------------------------------

/**
 * Link a device IP to an investigation.
 */
export async function linkDevice(
	investigationId: string,
	deviceIp: string
): Promise<boolean> {
	const res = await fetch(
		`/api/investigations/${encodeURIComponent(investigationId)}/devices`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ device_ip: deviceIp }),
		}
	);

	return res.ok;
}

// ---------------------------------------------------------------------------
// Fetch helpers — Stats
// ---------------------------------------------------------------------------

/**
 * Get investigation statistics.
 */
export async function getInvestigationStats(): Promise<InvestigationStats> {
	const res = await fetch('/api/investigations/stats');

	if (!res.ok) {
		return {
			total: 0,
			by_status: {},
			by_severity: {},
		};
	}

	return res.json();
}
