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
	upsertReportCard,
	getReportHistory,
	getReport,
	ReportsError,
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

function mockFetchFailure(status = 500, body?: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			// OLD CODE: json: () => Promise.reject(new Error('no body')), (NET-340: a 409 carries the daemon's sentence)
			json: () => (body === undefined ? Promise.reject(new Error('no body')) : Promise.resolve(body)),
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

			// OLD CODE: expect(fetch).toHaveBeenCalledWith('/api/reports/schedules'); (NET-340: one call helper passes init, undefined for a GET)
			expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/reports/schedules');
			expect(result.schedules).toHaveLength(1);
			expect(result.schedules[0].name).toBe('Weekly Security Summary');
		});

		// OLD CODE START — NET-340: a failure read as no schedules
		// it('returns empty schedules on HTTP error', async () => {
		// 	mockFetchFailure(500);
		// 	const result = await getReportSchedules();
		// 	expect(result.schedules).toEqual([]);
		// });
		// OLD CODE END
		it('throws on HTTP error, so a failure never reads as no schedules', async () => {
			mockFetchFailure(500);

			await expect(getReportSchedules()).rejects.toThrow('NetTap answered HTTP 500.');
		});

		it("throws the daemon's sentence and status when it sends one", async () => {
			mockFetchFailure(503, { error: 'Report schedules are unavailable.' });

			const err = await getReportSchedules().catch((e: unknown) => e);
			expect(err).toBeInstanceOf(ReportsError);
			expect(err).toMatchObject({ message: 'Report schedules are unavailable.', status: 503 });
		});

		it('says NetTap is unreachable when the request never lands', async () => {
			vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

			await expect(getReportSchedules()).rejects.toMatchObject({ status: 0, message: "Couldn't reach NetTap. Check the connection and try again." });
		});
	});

	// -- createReportSchedule ------------------------------------------------

	describe('createReportSchedule', () => {
		it('sends POST and returns created schedule on success', async () => {
			mockFetchSuccess(sampleSchedule, 201);

			// OLD CODE: format: 'pdf', (NET-340: the input leaves out format and sections, which the daemon ignores or refuses)
			const result = await createReportSchedule({
				name: 'Weekly Security Summary',
				frequency: 'weekly',
			});

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: expect.any(String),
			});
			expect(result.name).toBe('Weekly Security Summary');
		});

		// OLD CODE: it('returns null on failure', …) expected null (NET-340: helpers throw)
		it("throws the daemon's 400 reason", async () => {
			mockFetchFailure(400, { error: 'Enter a name of 1 to 100 characters.' });

			await expect(createReportSchedule({ name: '' })).rejects.toThrow('Enter a name of 1 to 100 characters.');
		});
	});

	// -- getReportSchedule ---------------------------------------------------

	describe('getReportSchedule', () => {
		it('returns a single schedule on success', async () => {
			mockFetchSuccess(sampleSchedule);

			const result = await getReportSchedule('sched-001');

			// OLD CODE: expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001'); (NET-340: init is undefined for a GET)
			expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/reports/schedules/sched-001');
			expect(result.frequency).toBe('weekly');
		});

		// OLD CODE: it('returns null on 404', …) expected null (NET-340: helpers throw)
		it('throws on 404', async () => {
			mockFetchFailure(404);

			await expect(getReportSchedule('nonexistent')).rejects.toMatchObject({ status: 404 });
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
			expect(result.name).toBe('Monthly Report');
		});

		// OLD CODE: it('returns null on failure', …) expected null (NET-340: helpers throw)
		it('throws the 409 the daemon sends during a send', async () => {
			mockFetchFailure(409, { error: 'A report is being sent. Try again in a minute.' });

			await expect(updateReportSchedule('sched-001', { recipients: ['a@example.com'] })).rejects.toMatchObject({
				status: 409,
				message: 'A report is being sent. Try again in a minute.',
			});
		});
	});

	// -- deleteReportSchedule ------------------------------------------------

	describe('deleteReportSchedule', () => {
		// OLD CODE: …and returns true on success / returns false on failure (NET-340: resolves, or throws)
		it('sends DELETE and resolves on success', async () => {
			mockFetchSuccess({ result: 'deleted' });

			await expect(deleteReportSchedule('sched-001')).resolves.toBeUndefined();

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001', {
				method: 'DELETE',
			});
		});

		it('throws on failure', async () => {
			mockFetchFailure(404);

			await expect(deleteReportSchedule('nonexistent')).rejects.toBeInstanceOf(ReportsError);
		});
	});

	// -- enableSchedule / disableSchedule ------------------------------------

	describe('enableSchedule', () => {
		// OLD CODE: it('sends POST and returns true on success', …) (NET-340: resolves, or throws)
		it('sends POST and resolves on success', async () => {
			mockFetchSuccess({ result: 'enabled' });

			await expect(enableSchedule('sched-001')).resolves.toBeUndefined();

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001/enable', {
				method: 'POST',
			});
		});
	});

	describe('disableSchedule', () => {
		// OLD CODE: it('sends POST and returns true on success', …) (NET-340: resolves, or throws)
		it('sends POST and resolves on success', async () => {
			mockFetchSuccess({ result: 'disabled' });

			await expect(disableSchedule('sched-001')).resolves.toBeUndefined();

			expect(fetch).toHaveBeenCalledWith('/api/reports/schedules/sched-001/disable', {
				method: 'POST',
			});
		});
	});

	// -- generateReport ------------------------------------------------------

	describe('generateReport', () => {
		// OLD CODE: the reply was { status: 'generated', download_url } (NET-340: the report itself)
		it('sends POST and returns the report', async () => {
			mockFetchSuccess({ id: '20261117T080012Z-a1b2c3', trigger: 'manual' });

			const result = await generateReport('sched-001');

			expect(fetch).toHaveBeenCalledWith('/api/reports/generate/sched-001', {
				method: 'POST',
			});
			expect(result.id).toBe('20261117T080012Z-a1b2c3');
		});

		// OLD CODE: it('returns null on failure', …) expected null (NET-340: the page shows the daemon's 409)
		it("throws the daemon's 409 while another report is being made", async () => {
			mockFetchFailure(409, { error: "A report is being generated. It will appear in the history when it's done." });

			await expect(generateReport('sched-001')).rejects.toMatchObject({
				status: 409,
				message: "A report is being generated. It will appear in the history when it's done.",
			});
		});
	});

	// -- NET-340: the card, the history and one report -------------------------

	describe('upsertReportCard', () => {
		it('PUTs the card body, confirm included', async () => {
			mockFetchSuccess({ ...sampleSchedule, card: true });
			const body = { enabled: true, weekday: 0, hour: 8, recipients: ['a@example.com'], confirm: true as const, confirm_token: 'tok', rev: 3 };

			await upsertReportCard(body);

			expect(fetch).toHaveBeenCalledWith('/api/reports/card', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
		});

		it("throws the stale-token 409's sentence", async () => {
			mockFetchFailure(409, { error: 'These settings changed in another window. Reload and check them.' });

			await expect(upsertReportCard({ enabled: true, weekday: 0, hour: 8, recipients: [], confirm: true })).rejects.toThrow(
				'These settings changed in another window. Reload and check them.',
			);
		});
	});

	describe('getReportHistory', () => {
		it("asks for one schedule's reports", async () => {
			mockFetchSuccess({ reports: [] });

			await getReportHistory('a b');

			expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/reports/history?schedule=a%20b');
		});

		it("asks for every schedule's reports without an id", async () => {
			mockFetchSuccess({ reports: [] });

			await getReportHistory();

			expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/reports/history');
		});

		it('throws on failure', async () => {
			mockFetchFailure(503);

			await expect(getReportHistory('s')).rejects.toMatchObject({ status: 503 });
		});
	});

	describe('getReport', () => {
		it('asks for one report by schedule and report id', async () => {
			mockFetchSuccess({ id: '20261117T080012Z-a1b2c3' });

			const report = await getReport('sched-001', '20261117T080012Z-a1b2c3');

			expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/reports/history/sched-001/20261117T080012Z-a1b2c3');
			expect(report.id).toBe('20261117T080012Z-a1b2c3');
		});

		it('throws on 404', async () => {
			mockFetchFailure(404, { error: 'Not found' });

			await expect(getReport('sched-001', 'x')).rejects.toThrow('Not found');
		});
	});
});
