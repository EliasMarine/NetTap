import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getSystemHealth,
	getStorageStatus,
	getSmartHealth,
	getIndices,
	healthStage,
	pipelineStage,
	nothingFound,
	type PipelineHealth,
	type SystemHealth,
} from './system';

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
			json: () => (body !== undefined ? Promise.resolve(body) : Promise.reject(new Error('no body'))),
		}),
	);
}

function mockFetchNetworkError(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('system API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getSystemHealth -----------------------------------------------------

	describe('getSystemHealth', () => {
		it('returns parsed health data on success', async () => {
			const expected = {
				uptime: 86400,
				timestamp: '2026-02-26T12:00:00Z',
				storage: { disk_usage_percent: 42 },
				smart: { healthy: true },
				opensearch_reachable: true,
				healthy: true,
			};
			mockFetchSuccess(expected);

			const result = await getSystemHealth();

			expect(fetch).toHaveBeenCalledWith('/api/system/health');
			expect(result).toEqual(expected);
		});

		it('throws on HTTP error instead of reporting the system degraded', async () => {
			mockFetchFailure(503);

			await expect(getSystemHealth()).rejects.toThrow('HTTP 503');
		});

		it('handles network failure gracefully', async () => {
			mockFetchNetworkError();

			await expect(getSystemHealth()).rejects.toThrow('Failed to fetch');
		});
	});

	// -- getStorageStatus ----------------------------------------------------

	describe('getStorageStatus', () => {
		it('returns parsed storage data on success', async () => {
			const expected = {
				disk_usage_percent: 42,
				disk_total_bytes: 1000000000,
				disk_used_bytes: 420000000,
				disk_free_bytes: 580000000,
				retention: { hot_days: 90, warm_days: 180 },
				index_summary: { total_indices: 5 },
			};
			mockFetchSuccess(expected);

			const result = await getStorageStatus();

			expect(fetch).toHaveBeenCalledWith('/api/storage/status');
			expect(result).toEqual(expected);
		});

		it('throws on HTTP error instead of reporting 0% used', async () => {
			mockFetchFailure(500);

			await expect(getStorageStatus()).rejects.toThrow('HTTP 500');
		});
	});

	// -- getSmartHealth ------------------------------------------------------

	describe('getSmartHealth', () => {
		it('returns parsed SMART data on success', async () => {
			const expected = {
				device: '/dev/nvme0n1',
				device_type: 'nvme',
				model: 'Samsung 980 PRO',
				serial: 'S6B1NJ0TB12345',
				temperature_c: 38,
				percentage_used: 2,
				power_on_hours: 1200,
				total_bytes_written: 22162086016000,
				total_bytes_read: 44164000000000,
				media_errors: 0,
				reallocated_sectors: null,
				healthy: true,
				warnings: [],
				timestamp: '2026-03-22T14:30:00Z',
			};
			mockFetchSuccess(expected);

			const result = await getSmartHealth();

			expect(fetch).toHaveBeenCalledWith('/api/smart/health');
			expect(result).toEqual(expected);
			expect(result.total_bytes_written).toBe(22162086016000);
			expect(result.device_type).toBe('nvme');
			expect(result.serial).toBe('S6B1NJ0TB12345');
		});

		it('throws on HTTP error instead of reporting the drive degraded', async () => {
			mockFetchFailure(500);

			await expect(getSmartHealth()).rejects.toThrow('HTTP 500');
		});
	});

	// -- getIndices ----------------------------------------------------------

	describe('getIndices', () => {
		it('returns parsed index list on success', async () => {
			const expected = {
				indices: [
					{ name: 'zeek-conn-2026.02', size: '120mb', docs: 45000 },
					{ name: 'suricata-alert-2026.02', size: '8mb', docs: 320 },
				],
				count: 2,
			};
			mockFetchSuccess(expected);

			const result = await getIndices();

			expect(fetch).toHaveBeenCalledWith('/api/indices');
			expect(result).toEqual(expected);
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getIndices();

			expect(result.indices).toEqual([]);
			expect(result.count).toBe(0);
		});
	});
});

// NET-168: Home and System both read this map, so an incomplete check is amber everywhere
describe('healthStage', () => {
	it('maps each aggregate status to its pipeline stage', () => {
		expect(healthStage('healthy')).toEqual({ status: 'ok', detail: 'Healthy' });
		expect(healthStage('problem')).toEqual({ status: 'failing', detail: 'Reports a problem' });
		expect(healthStage('incomplete')).toEqual({ status: 'warn', detail: "Incomplete · some checks couldn't run" });
	});

	it('reads Unknown when an older daemon sends no status', () => {
		expect(healthStage(undefined)).toEqual({ status: 'unknown', detail: 'Unknown' });
	});
});

// F2: Home's Data stage and System's "Data and sensors" row read these words
describe('pipelineStage', () => {
	const RUNNING = {
		'nettap-zeek-live': 'running',
		'nettap-suricata-live': 'running',
		'nettap-logstash': 'running',
		'nettap-filebeat': 'running',
	};
	const pipeline = (over: Partial<PipelineHealth>): PipelineHealth => ({
		state: 'fresh', newest_record_at: '2026-11-08T21:00:00+00:00', age_seconds: 40, threshold_seconds: 900,
		sensors: RUNNING, checked_at: '2026-11-08T21:00:40+00:00', ...over,
	});

	it('says how old the newest record is when data is fresh', () => {
		expect(pipelineStage(pipeline({ age_seconds: 40 }))).toEqual({ status: 'ok', detail: 'Newest record 40 s ago' });
		expect(pipelineStage(pipeline({ age_seconds: 300 }))).toEqual({ status: 'ok', detail: 'Newest record 5 min ago' });
	});

	it('says how long nothing new has arrived, past a day too', () => {
		expect(pipelineStage(pipeline({ state: 'stale', age_seconds: 47 * 60 }))).toEqual({ status: 'failing', detail: 'No new records for 47 min' });
		expect(pipelineStage(pipeline({ state: 'stale', age_seconds: 5 * 3600 }))).toEqual({ status: 'failing', detail: 'No new records for 5 h' });
		expect(pipelineStage(pipeline({ state: 'stale', age_seconds: 3 * 86400 }))).toEqual({ status: 'failing', detail: 'No new records for 3 days' });
	});

	it('names the stopped sensors in plain words', () => {
		expect(pipelineStage(pipeline({ state: 'sensor_stopped', sensors: { ...RUNNING, 'nettap-suricata-live': 'exited' } }))).toEqual({
			status: 'failing', detail: 'Suricata stopped',
		});
		const three = { ...RUNNING, 'nettap-zeek-live': 'exited', 'nettap-suricata-live': 'missing', 'nettap-filebeat': 'restarting' };
		expect(pipelineStage(pipeline({ state: 'sensor_stopped', sensors: three })).detail).toBe('Zeek, Suricata and Filebeat stopped');
	});

	it('words the empty, starting and unchecked states', () => {
		expect(pipelineStage(pipeline({ state: 'no_data', age_seconds: null }))).toEqual({ status: 'failing', detail: 'No records in the last 7 days' });
		expect(pipelineStage(pipeline({ state: 'starting', age_seconds: null }))).toEqual({ status: 'warn', detail: 'Starting up' });
		expect(pipelineStage(pipeline({ state: 'unknown', age_seconds: null }))).toEqual({ status: 'warn', detail: "Couldn't check" });
	});

	it('reads Unknown when an older daemon sends no pipeline', () => {
		expect(pipelineStage(undefined)).toEqual({ status: 'unknown', detail: 'Unknown' });
	});
});

// NET-228 (audit B5): a zero alert count is "can't tell" unless current data is arriving
describe('nothingFound', () => {
	const RUNNING = {
		'nettap-zeek-live': 'running',
		'nettap-suricata-live': 'running',
		'nettap-logstash': 'running',
		'nettap-filebeat': 'running',
	};
	const health = (pipeline?: Partial<PipelineHealth>): SystemHealth => ({
		uptime: 1, timestamp: '', storage: null, smart: null, opensearch_reachable: true, status: 'healthy', healthy: true,
		...(pipeline && {
			pipeline: {
				state: 'fresh', newest_record_at: '', age_seconds: 40, threshold_seconds: 900, sensors: RUNNING, checked_at: '', ...pipeline,
			},
		}),
	});
	const NONE = 'No counted rule matches in this period';

	it('keeps the stored-data sentence only while data is fresh, and labels the state as now', () => {
		expect(nothingFound(NONE, health({ state: 'fresh' }), false)).toEqual({
			trusted: true, title: NONE, detail: 'Data pipeline now: Newest record 40 s ago',
		});
	});

	it.each([
		[{ state: 'stale' as const, age_seconds: 47 * 60 }, 'Data pipeline now: No new records for 47 min'],
		[{ state: 'no_data' as const, age_seconds: null }, 'Data pipeline now: No records in the last 7 days'],
		[{ state: 'sensor_stopped' as const, sensors: { ...RUNNING, 'nettap-suricata-live': 'exited' } }, 'Data pipeline now: Suricata stopped'],
		[{ state: 'starting' as const, age_seconds: null }, 'Data pipeline now: Starting up'],
		[{ state: 'unknown' as const, age_seconds: null }, "Data pipeline now: Couldn't check"],
	])('reads "can\'t tell" when the pipeline is %o', (pipeline, detail) => {
		expect(nothingFound(NONE, health(pipeline), false)).toEqual({ trusted: false, title: "Can't tell if any rule matched", detail });
	});

	it("can't tell when the health request failed, an older daemon sent no pipeline, or it hasn't loaded", () => {
		expect(nothingFound(NONE, health({ state: 'fresh' }), true)).toMatchObject({ trusted: false, detail: "Data pipeline now: Couldn't check" });
		expect(nothingFound(NONE, health(), false)).toMatchObject({ trusted: false, detail: "Data pipeline now: Couldn't check" });
		expect(nothingFound(NONE, null, false)).toMatchObject({ trusted: false, detail: 'Data pipeline now: Checking…' });
	});

	it('takes its own "unsure" words', () => {
		expect(nothingFound('No alert groups to review in this period', health({ state: 'stale' }), false, "Can't tell if anything needs review").title).toBe(
			"Can't tell if anything needs review",
		);
	});
});
