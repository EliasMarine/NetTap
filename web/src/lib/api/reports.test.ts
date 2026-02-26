import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getReportSchedules,
	createReportSchedule,
	getReportSchedule,
	updateReportSchedule,
	deleteReportSchedule,
	enableSchedule,
	disableSchedule,
	generateReport,
} from './reports';

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

const sampleSchedule = {
	id: 'sched-001',
	name: 'Weekly Security Summary',
	frequency: 'weekly',
	format: 'pdf',
	recipients: ['admin@example.com'],
	sections: ['alerts', 'top_talkers', 'bandwidth'],
	enabled: true,
	last_run: '2026-02-20T00:00:00Z',
	next_run: '2026-02-27T00:00:00Z',
	created_at: '2026-01-15T00:00:00Z',
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('reports API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getReportSchedules --------------------------------------------------

	describe('getReportSchedules', () => {
		it('returns parsed schedules on success', async () => {
			mockFetchSuccess({ schedules: [sampleSchedule] });

			const result = await getReportSchedules();

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules');
			expect(result.schedules).toHaveLength(1);
			expect(result.schedules[0].name).toBe('Weekly Security Summary');
		});

		it('returns empty schedules on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getReportSchedules();

			expect(result.schedules).toEqual([]);
		});
	});

	// -- createReportSchedule ------------------------------------------------

	describe('createReportSchedule', () => {
		it('sends POST and returns created schedule on success', async () => {
			mockFetchSuccess(sampleSchedule, 201);

			const result = await createReportSchedule({
				name: 'Weekly Security Summary',
				frequency: 'weekly',
				format: 'pdf',
			});

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: expect.any(String),
			});
			expect(result?.name).toBe('Weekly Security Summary');
		});

		it('returns null on failure', async () => {
			mockFetchFailure(400);

			const result = await createReportSchedule({ name: '' });

			expect(result).toBeNull();
		});
	});

	// -- getReportSchedule ---------------------------------------------------

	describe('getReportSchedule', () => {
		it('returns a single schedule on success', async () => {
			mockFetchSuccess(sampleSchedule);

			const result = await getReportSchedule('sched-001');

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001');
			expect(result?.frequency).toBe('weekly');
		});

		it('returns null on 404', async () => {
			mockFetchFailure(404);

			const result = await getReportSchedule('nonexistent');

			expect(result).toBeNull();
		});
	});

	// -- updateReportSchedule ------------------------------------------------

	describe('updateReportSchedule', () => {
		it('sends PUT and returns updated schedule on success', async () => {
			const updated = { ...sampleSchedule, name: 'Monthly Report' };
			mockFetchSuccess(updated);

			const result = await updateReportSchedule('sched-001', { name: 'Monthly Report' });

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ name: 'Monthly Report' }),
			});
			expect(result?.name).toBe('Monthly Report');
		});

		it('returns null on failure', async () => {
			mockFetchFailure(500);

			const result = await updateReportSchedule('sched-001', { name: 'fail' });

			expect(result).toBeNull();
		});
	});

	// -- deleteReportSchedule ------------------------------------------------

	describe('deleteReportSchedule', () => {
		it('sends DELETE and returns true on success', async () => {
			mockFetchSuccess({ result: 'deleted' });

			const result = await deleteReportSchedule('sched-001');

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001', {
				method: 'DELETE',
			});
			expect(result).toBe(true);
		});

		it('returns false on failure', async () => {
			mockFetchFailure(404);

			const result = await deleteReportSchedule('nonexistent');

			expect(result).toBe(false);
		});
	});

	// -- enableSchedule / disableSchedule ------------------------------------

	describe('enableSchedule', () => {
		it('sends POST and returns true on success', async () => {
			mockFetchSuccess({ result: 'enabled' });

			const result = await enableSchedule('sched-001');

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001/enable', {
				method: 'POST',
			});
			expect(result).toBe(true);
		});
	});

	describe('disableSchedule', () => {
		it('sends POST and returns true on success', async () => {
			mockFetchSuccess({ result: 'disabled' });

			const result = await disableSchedule('sched-001');

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001/disable', {
				method: 'POST',
			});
			expect(result).toBe(true);
		});
	});

	// -- generateReport ------------------------------------------------------

	describe('generateReport', () => {
		it('sends POST and returns generated report data', async () => {
			const reportData = { status: 'generated', download_url: '/reports/sched-001-2026-02-26.pdf' };
			mockFetchSuccess(reportData);

			const result = await generateReport('sched-001');

			expect(fetch).toHaveBeenCalledWith('/api/reports/generate/sched-001', {
				method: 'POST',
			});
			expect(result?.status).toBe('generated');
		});

		it('returns null on failure', async () => {
			mockFetchFailure(500);

			const result = await generateReport('sched-001');

			expect(result).toBeNull();
		});
	});
});
