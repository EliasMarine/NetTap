import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getInvestigations,
	createInvestigation,
	getInvestigation,
	updateInvestigation,
	deleteInvestigation,
	addNote,
	updateNote,
	deleteNote,
	linkAlert,
	unlinkAlert,
	linkDevice,
	getInvestigationStats,
} from './investigations';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const sampleNote = {
	id: 'note-1',
	content: 'Initial finding: suspicious outbound traffic to known C2 server.',
	created_at: '2026-02-26T10:00:00Z',
	updated_at: '2026-02-26T10:00:00Z',
};

const sampleInvestigation = {
	id: 'inv-001',
	title: 'Suspicious C2 Traffic from 192.168.1.50',
	description: 'Device 192.168.1.50 has been making repeated connections to known C2 infrastructure.',
	status: 'open',
	severity: 'high',
	created_at: '2026-02-26T09:00:00Z',
	updated_at: '2026-02-26T10:00:00Z',
	alert_ids: ['alert-abc', 'alert-def'],
	device_ips: ['192.168.1.50'],
	notes: [sampleNote],
	tags: ['c2', 'malware'],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('investigations API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getInvestigations -----------------------------------------------------

	describe('getInvestigations', () => {
		it('returns parsed investigations on success', async () => {
			mockFetchSuccess({ investigations: [sampleInvestigation] });

			const result = await getInvestigations();

			expect(fetch).toHaveBeenCalledWith('/api/investigations');
			expect(result.investigations).toHaveLength(1);
			expect(result.investigations[0].title).toBe('Suspicious C2 Traffic from 192.168.1.50');
		});

		it('passes status filter parameter', async () => {
			mockFetchSuccess({ investigations: [] });

			await getInvestigations({ status: 'open' });

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('status=open');
		});

		it('passes severity filter parameter', async () => {
			mockFetchSuccess({ investigations: [] });

			await getInvestigations({ severity: 'high' });

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('severity=high');
		});

		it('returns empty investigations on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getInvestigations();

			expect(result.investigations).toEqual([]);
		});
	});

	// -- createInvestigation --------------------------------------------------

	describe('createInvestigation', () => {
		it('sends POST request with investigation data', async () => {
			mockFetchSuccess(sampleInvestigation);

			const result = await createInvestigation({
				title: 'Suspicious C2 Traffic from 192.168.1.50',
				description: 'Testing',
				severity: 'high',
				tags: ['c2'],
			});

			expect(fetch).toHaveBeenCalledWith('/api/investigations', expect.objectContaining({
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
			}));
			expect(result.id).toBe('inv-001');
		});

		it('returns fallback investigation on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await createInvestigation({ title: 'Test Investigation' });

			expect(result.id).toBe('');
			expect(result.title).toBe('Test Investigation');
			expect(result.status).toBe('open');
		});
	});

	// -- getInvestigation -----------------------------------------------------

	describe('getInvestigation', () => {
		it('returns parsed investigation on success', async () => {
			mockFetchSuccess(sampleInvestigation);

			const result = await getInvestigation('inv-001');

			expect(fetch).toHaveBeenCalledWith('/api/investigations/inv-001');
			expect(result).not.toBeNull();
			expect(result!.id).toBe('inv-001');
		});

		it('returns null on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await getInvestigation('inv-999');

			expect(result).toBeNull();
		});
	});

	// -- updateInvestigation --------------------------------------------------

	describe('updateInvestigation', () => {
		it('sends PUT request with partial update data', async () => {
			const updated = { ...sampleInvestigation, status: 'in_progress' };
			mockFetchSuccess(updated);

			const result = await updateInvestigation('inv-001', { status: 'in_progress' });

			expect(fetch).toHaveBeenCalledWith('/api/investigations/inv-001', expect.objectContaining({
				method: 'PUT',
			}));
			expect(result).not.toBeNull();
			expect(result!.status).toBe('in_progress');
		});

		it('returns null on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await updateInvestigation('inv-999', { status: 'closed' });

			expect(result).toBeNull();
		});
	});

	// -- deleteInvestigation --------------------------------------------------

	describe('deleteInvestigation', () => {
		it('returns true on successful deletion', async () => {
			mockFetchSuccess({ deleted: true });

			const result = await deleteInvestigation('inv-001');

			expect(fetch).toHaveBeenCalledWith('/api/investigations/inv-001', expect.objectContaining({
				method: 'DELETE',
			}));
			expect(result).toBe(true);
		});

		it('returns false on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await deleteInvestigation('inv-999');

			expect(result).toBe(false);
		});
	});

	// -- addNote --------------------------------------------------------------

	describe('addNote', () => {
		it('sends POST request with note content', async () => {
			mockFetchSuccess(sampleNote);

			const result = await addNote('inv-001', 'New note content');

			expect(fetch).toHaveBeenCalledWith(
				'/api/investigations/inv-001/notes',
				expect.objectContaining({ method: 'POST' }),
			);
			expect(result).not.toBeNull();
			expect(result!.content).toBe('Initial finding: suspicious outbound traffic to known C2 server.');
		});

		it('returns null on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await addNote('inv-001', 'New note');

			expect(result).toBeNull();
		});
	});

	// -- updateNote -----------------------------------------------------------

	describe('updateNote', () => {
		it('sends PUT request with updated content', async () => {
			const updatedNote = { ...sampleNote, content: 'Updated content' };
			mockFetchSuccess(updatedNote);

			const result = await updateNote('inv-001', 'note-1', 'Updated content');

			expect(fetch).toHaveBeenCalledWith(
				'/api/investigations/inv-001/notes/note-1',
				expect.objectContaining({ method: 'PUT' }),
			);
			expect(result).not.toBeNull();
			expect(result!.content).toBe('Updated content');
		});
	});

	// -- deleteNote -----------------------------------------------------------

	describe('deleteNote', () => {
		it('returns true on successful deletion', async () => {
			mockFetchSuccess({ deleted: true });

			const result = await deleteNote('inv-001', 'note-1');

			expect(fetch).toHaveBeenCalledWith(
				'/api/investigations/inv-001/notes/note-1',
				expect.objectContaining({ method: 'DELETE' }),
			);
			expect(result).toBe(true);
		});

		it('returns false on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await deleteNote('inv-001', 'note-999');

			expect(result).toBe(false);
		});
	});

	// -- linkAlert / unlinkAlert -----------------------------------------------

	describe('linkAlert', () => {
		it('sends POST request with alert_id', async () => {
			mockFetchSuccess({ linked: true });

			const result = await linkAlert('inv-001', 'alert-xyz');

			expect(fetch).toHaveBeenCalledWith(
				'/api/investigations/inv-001/alerts',
				expect.objectContaining({ method: 'POST' }),
			);
			expect(result).toBe(true);
		});
	});

	describe('unlinkAlert', () => {
		it('sends DELETE request for the alert', async () => {
			mockFetchSuccess({ unlinked: true });

			const result = await unlinkAlert('inv-001', 'alert-xyz');

			expect(fetch).toHaveBeenCalledWith(
				'/api/investigations/inv-001/alerts/alert-xyz',
				expect.objectContaining({ method: 'DELETE' }),
			);
			expect(result).toBe(true);
		});
	});

	// -- linkDevice -----------------------------------------------------------

	describe('linkDevice', () => {
		it('sends POST request with device_ip', async () => {
			mockFetchSuccess({ linked: true });

			const result = await linkDevice('inv-001', '192.168.1.100');

			expect(fetch).toHaveBeenCalledWith(
				'/api/investigations/inv-001/devices',
				expect.objectContaining({ method: 'POST' }),
			);
			expect(result).toBe(true);
		});
	});

	// -- getInvestigationStats ------------------------------------------------

	describe('getInvestigationStats', () => {
		it('returns parsed stats on success', async () => {
			const expected = {
				total: 15,
				by_status: { open: 5, in_progress: 3, resolved: 4, closed: 3 },
				by_severity: { low: 3, medium: 5, high: 4, critical: 3 },
			};
			mockFetchSuccess(expected);

			const result = await getInvestigationStats();

			expect(fetch).toHaveBeenCalledWith('/api/investigations/stats');
			expect(result.total).toBe(15);
			expect(result.by_status.open).toBe(5);
		});

		it('returns empty stats on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getInvestigationStats();

			expect(result.total).toBe(0);
			expect(result.by_status).toEqual({});
			expect(result.by_severity).toEqual({});
		});
	});
});
