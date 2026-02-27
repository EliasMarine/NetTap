import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getVersions,
	scanVersions,
	getAvailableUpdates,
	checkForUpdates,
	applyUpdates,
	getUpdateStatus,
	getUpdateHistory,
	rollbackComponent,
} from './updates';

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

const sampleVersions = {
	versions: {
		zeek: {
			name: 'Zeek',
			category: 'core' as const,
			current_version: '6.2.0',
			install_type: 'docker',
			last_checked: '2026-02-26T12:00:00Z',
			status: 'ok' as const,
			details: {},
		},
		suricata: {
			name: 'Suricata',
			category: 'core' as const,
			current_version: '7.0.3',
			install_type: 'docker',
			last_checked: '2026-02-26T12:00:00Z',
			status: 'ok' as const,
			details: {},
		},
	},
	last_scan: '2026-02-26T12:00:00Z',
};

const sampleUpdates: any[] = [
	{
		component: 'zeek',
		current_version: '6.2.0',
		latest_version: '6.3.0',
		update_type: 'minor',
		release_url: 'https://github.com/zeek/zeek/releases/tag/v6.3.0',
		release_date: '2026-02-20',
		changelog: 'Bug fixes and performance improvements',
		size_mb: 120,
		requires_restart: true,
	},
];

const sampleUpdateStatus = {
	state: 'completed' as const,
	current_component: null,
	progress_percent: 100,
	started_at: '2026-02-26T12:00:00Z',
	results: [
		{
			component: 'zeek',
			success: true,
			old_version: '6.2.0',
			new_version: '6.3.0',
			started_at: '2026-02-26T12:00:00Z',
			completed_at: '2026-02-26T12:02:00Z',
			error: null,
			rollback_available: true,
		},
	],
};

const sampleHistory = [
	{
		component: 'suricata',
		success: true,
		old_version: '7.0.2',
		new_version: '7.0.3',
		started_at: '2026-02-20T10:00:00Z',
		completed_at: '2026-02-20T10:01:30Z',
		error: null,
		rollback_available: false,
	},
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('updates API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getVersions ----------------------------------------------------------

	describe('getVersions', () => {
		it('returns versions and last_scan on success', async () => {
			mockFetchSuccess(sampleVersions);

			const result = await getVersions();

			expect(fetch).toHaveBeenCalledWith('/api/system/versions');
			expect(result.versions).toHaveProperty('zeek');
			expect(result.versions.zeek.current_version).toBe('6.2.0');
			expect(result.last_scan).toBe('2026-02-26T12:00:00Z');
		});

		it('returns empty versions on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getVersions();

			expect(result.versions).toEqual({});
			expect(result.last_scan).toBe('');
		});
	});

	// -- scanVersions ---------------------------------------------------------

	describe('scanVersions', () => {
		it('calls POST and returns scanned versions', async () => {
			mockFetchSuccess({ versions: sampleVersions.versions });

			const result = await scanVersions();

			expect(fetch).toHaveBeenCalledWith('/api/system/versions/scan', {
				method: 'POST',
			});
			expect(result.versions).toHaveProperty('zeek');
		});

		it('returns empty versions on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await scanVersions();

			expect(result.versions).toEqual({});
		});
	});

	// -- getAvailableUpdates --------------------------------------------------

	describe('getAvailableUpdates', () => {
		it('returns updates and last_check on success', async () => {
			mockFetchSuccess({ updates: sampleUpdates, last_check: '2026-02-26T12:00:00Z' });

			const result = await getAvailableUpdates();

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/available');
			expect(result.updates).toHaveLength(1);
			expect(result.updates[0].component).toBe('zeek');
			expect(result.last_check).toBe('2026-02-26T12:00:00Z');
		});

		it('returns empty updates on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getAvailableUpdates();

			expect(result.updates).toEqual([]);
			expect(result.last_check).toBe('');
		});
	});

	// -- checkForUpdates ------------------------------------------------------

	describe('checkForUpdates', () => {
		it('calls POST and returns updates', async () => {
			mockFetchSuccess({ updates: sampleUpdates });

			const result = await checkForUpdates();

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/check', {
				method: 'POST',
			});
			expect(result.updates).toHaveLength(1);
		});

		it('returns empty updates on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await checkForUpdates();

			expect(result.updates).toEqual([]);
		});
	});

	// -- applyUpdates ---------------------------------------------------------

	describe('applyUpdates', () => {
		it('sends component list and returns status', async () => {
			mockFetchSuccess(sampleUpdateStatus);

			const result = await applyUpdates(['zeek', 'suricata']);

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/apply', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ components: ['zeek', 'suricata'] }),
			});
			expect(result.state).toBe('completed');
			expect(result.progress_percent).toBe(100);
		});

		it('returns error status on HTTP failure', async () => {
			mockFetchFailure(500);

			const result = await applyUpdates(['zeek']);

			expect(result.state).toBe('error');
			expect(result.progress_percent).toBe(0);
			expect(result.results).toEqual([]);
		});

		it('sends a single component correctly', async () => {
			mockFetchSuccess(sampleUpdateStatus);

			await applyUpdates(['zeek']);

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/apply', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ components: ['zeek'] }),
			});
		});
	});

	// -- getUpdateStatus ------------------------------------------------------

	describe('getUpdateStatus', () => {
		it('returns update status on success', async () => {
			mockFetchSuccess(sampleUpdateStatus);

			const result = await getUpdateStatus();

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/status');
			expect(result.state).toBe('completed');
			expect(result.results).toHaveLength(1);
			expect(result.results[0].success).toBe(true);
		});

		it('returns idle status on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getUpdateStatus();

			expect(result.state).toBe('idle');
			expect(result.current_component).toBeNull();
			expect(result.results).toEqual([]);
		});
	});

	// -- getUpdateHistory -----------------------------------------------------

	describe('getUpdateHistory', () => {
		it('returns history array on success', async () => {
			mockFetchSuccess(sampleHistory);

			const result = await getUpdateHistory();

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/history');
			expect(result).toHaveLength(1);
			expect(result[0].component).toBe('suricata');
			expect(result[0].success).toBe(true);
		});

		it('returns empty array on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getUpdateHistory();

			expect(result).toEqual([]);
		});
	});

	// -- rollbackComponent ----------------------------------------------------

	describe('rollbackComponent', () => {
		it('sends component name and returns result', async () => {
			mockFetchSuccess({ result: 'ok' });

			const result = await rollbackComponent('zeek');

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/rollback', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ component: 'zeek' }),
			});
			expect(result.result).toBe('ok');
		});

		it('returns error result on HTTP failure', async () => {
			mockFetchFailure(500);

			const result = await rollbackComponent('zeek');

			expect(result.result).toBe('error');
		});
	});
});
