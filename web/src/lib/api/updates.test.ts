import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getVersions,
	scanVersions,
	getAvailableUpdates,
	checkForUpdates,
	applyUpdates,
	getUpdateStatus,
	getUpdateHistory,
	getUpdateHistoryBatches,
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
	// OLD CODE: versions keyed by component (zeek: {…}, suricata: {…}); the daemon sends a list (NET-237)
	versions: [
		{
			name: 'Zeek',
			category: 'core' as const,
			current_version: '6.2.0',
			install_type: 'docker',
			last_checked: '2026-02-26T12:00:00Z',
			status: 'ok' as const,
			details: {},
		},
		{
			name: 'Suricata',
			category: 'core' as const,
			current_version: '7.0.3',
			install_type: 'docker',
			last_checked: '2026-02-26T12:00:00Z',
			status: 'ok' as const,
			details: {},
		},
	],
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

// OLD CODE START — one flat result per item; the daemon sends batches (sampleHistory below)
// const sampleHistory = [
// 	{
// 		component: 'suricata',
// 		success: true,
// 		old_version: '7.0.2',
// 		new_version: '7.0.3',
// 		started_at: '2026-02-20T10:00:00Z',
// 		completed_at: '2026-02-20T10:01:30Z',
// 		error: null,
// 		rollback_available: false,
// 	},
// ];
// OLD CODE END
const sampleResult = {
	component: 'suricata',
	success: true,
	old_version: '7.0.2',
	new_version: '7.0.3',
	started_at: '2026-02-20T10:00:00Z',
	completed_at: '2026-02-20T10:01:30Z',
	error: null,
	rollback_available: false,
};

/** One batch per update run, as daemon/services/update_executor.py keeps them (newest first). */
const sampleHistory = [
	{
		results: [sampleResult],
		success: true,
		total: 1,
		succeeded: 1,
		failed: 0,
		components: ['suricata'],
		started_at: '2026-02-20T10:00:00Z',
		completed_at: '2026-02-20T10:01:30Z',
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
			expect(result.versions.map((v) => v.name)).toEqual(['Zeek', 'Suricata']);
			expect(result.versions[0].current_version).toBe('6.2.0');
			expect(result.last_scan).toBe('2026-02-26T12:00:00Z');
		});

		it('throws on HTTP error instead of reporting no versions', async () => {
			mockFetchFailure(500);

			await expect(getVersions()).rejects.toThrow('HTTP 500');
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
			expect(result.versions.map((v) => v.name)).toEqual(['Zeek', 'Suricata']);
		});

		it('returns empty versions on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await scanVersions();

			// OLD CODE: expect(result.versions).toEqual({}); (NET-237: an empty list, the daemon's shape)
			expect(result.versions).toEqual([]);
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

		it('throws on HTTP error instead of reporting everything up to date', async () => {
			mockFetchFailure(502);

			await expect(getAvailableUpdates()).rejects.toThrow('HTTP 502');
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

		it('throws on HTTP error instead of reporting no updates', async () => {
			mockFetchFailure(500);

			await expect(checkForUpdates()).rejects.toThrow('HTTP 500');
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

		// OLD CODE START — a failure returned an empty 'error' status, which dropped the daemon's reason
		// it('returns error status on HTTP failure', async () => {
		// 	mockFetchFailure(500);
		//
		// 	const result = await applyUpdates(['zeek']);
		//
		// 	expect(result.state).toBe('error');
		// 	expect(result.progress_percent).toBe(0);
		// 	expect(result.results).toEqual([]);
		// });
		// OLD CODE END
		it('throws with the HTTP status when a failure has no body', async () => {
			mockFetchFailure(500);

			await expect(applyUpdates(['zeek'])).rejects.toThrow('the request failed (HTTP 500).');
		});

		// the daemon now starts the work in the background and answers at once
		it('treats a 202 as started and returns its status', async () => {
			const started = { ...sampleUpdateStatus, state: 'in_progress', components: ['malcolm'], progress_percent: 0, results: [] };
			mockFetchSuccess(started, 202);

			const result = await applyUpdates(['malcolm']);

			expect(result).toEqual(started);
			expect(result.already_running).toBeUndefined();
		});

		it('returns the running update, flagged already_running, on a 409', async () => {
			const running = {
				error: 'An update is already running', state: 'in_progress', components: ['malcolm'], current_component: 'malcolm',
				current_step: 'Downloading Malcolm 26.10.0\'s images', progress_percent: 40, started_at: '2026-11-02T20:00:00Z',
				completed_at: null, results: [],
			};
			mockFetchSuccess(running, 409);

			const result = await applyUpdates(['suricata-rules']);

			expect(result.already_running).toBe(true);
			expect(result.state).toBe('in_progress');
			expect(result.components).toEqual(['malcolm']);
			expect(result.current_step).toBe("Downloading Malcolm 26.10.0's images");
		});

		// OLD CODE START — the 400's reason was dropped
		// it('still returns an empty error status on a 400', async () => {
		// 	mockFetchSuccess({ error: 'components array is required and must not be empty' }, 400);
		//
		// 	const result = await applyUpdates([]);
		//
		// 	expect(result.state).toBe('error');
		// 	expect(result.results).toEqual([]);
		// 	expect(result.already_running).toBeUndefined();
		// });
		// OLD CODE END
		it("throws the daemon's reason on a 400", async () => {
			mockFetchSuccess({ error: 'components must be names NetTap can update' }, 400);

			await expect(applyUpdates(['x'])).rejects.toThrow('components must be names NetTap can update');
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

		it('throws on HTTP error instead of reporting idle', async () => {
			mockFetchFailure(500);

			await expect(getUpdateStatus()).rejects.toThrow('HTTP 500');
		});
	});

	// -- getUpdateHistory -----------------------------------------------------

	describe('getUpdateHistory', () => {
		// the daemon replies {history, count}; the old client returned that object as the list
		it('returns the history list from the daemon reply', async () => {
			mockFetchSuccess({ history: sampleHistory, count: 1 });

			const result = await getUpdateHistory();

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/history');
			expect(result).toHaveLength(1);
			expect(result[0].component).toBe('suricata');
			expect(result[0].success).toBe(true);
		});

		it('returns an empty list when there are no past updates', async () => {
			mockFetchSuccess({ history: [], count: 0 });

			expect(await getUpdateHistory()).toEqual([]);
		});

		// each daemon item is a batch; reading one as a result gave "undefined → undefined" rows
		it('gives one row per result, with versions, across batches', async () => {
			const malcolm = { ...sampleResult, component: 'malcolm', old_version: '26.02.0', new_version: '26.10.0' };
			mockFetchSuccess({
				history: [
					{ ...sampleHistory[0], results: [malcolm, sampleResult], components: ['malcolm', 'suricata'] },
					sampleHistory[0],
				],
				count: 2,
			});

			const rows = await getUpdateHistory();

			expect(rows.map((r) => [r.component, r.old_version, r.new_version])).toEqual([
				['malcolm', '26.02.0', '26.10.0'],
				['suricata', '7.0.2', '7.0.3'],
				['suricata', '7.0.2', '7.0.3'],
			]);
		});

		it('keys every row uniquely, also for a repeated component with no timestamps', async () => {
			const bare = { ...sampleResult, component: 'malcolm', started_at: '', completed_at: '' };
			mockFetchSuccess({
				history: [{ ...sampleHistory[0], results: [bare, bare], started_at: '', completed_at: '' }],
				count: 1,
			});

			const rows = await getUpdateHistory();

			expect(new Set(rows.map((r) => r.key)).size).toBe(2);
		});
	});

	describe('getUpdateHistoryBatches', () => {
		it('returns the batches as the daemon sends them', async () => {
			mockFetchSuccess({ history: sampleHistory, count: 1 });

			const batches = await getUpdateHistoryBatches();

			expect(batches[0].started_at).toBe('2026-02-20T10:00:00Z');
			expect(batches[0].results[0].component).toBe('suricata');
		});

		it('throws on HTTP error', async () => {
			mockFetchFailure(502);

			await expect(getUpdateHistoryBatches()).rejects.toThrow('HTTP 502');
		});

		it('throws on HTTP error instead of reporting no past updates', async () => {
			mockFetchFailure(500);

			await expect(getUpdateHistory()).rejects.toThrow('HTTP 500');
		});
	});

	// -- rollbackComponent ----------------------------------------------------

	// The daemon answers {success, component, message}, {error} on a 500, and the proxy {error} on a 502;
	// the client read a {result} nothing sends
	describe('rollbackComponent', () => {
		// OLD CODE START — expected {result}
		// it('sends component name and returns result', async () => {
		// 	mockFetchSuccess({ result: 'ok' });
		// 	...
		// 	expect(result.result).toBe('ok');
		// });
		//
		// it('returns error result on HTTP failure', async () => {
		// 	mockFetchFailure(500);
		// 	const result = await rollbackComponent('zeek');
		// 	expect(result.result).toBe('error');
		// });
		// OLD CODE END
		it('sends the component and returns the daemon’s success and message', async () => {
			mockFetchSuccess({ success: true, component: 'suricata-rules', message: 'Restored from backup 20261116' });

			const result = await rollbackComponent('suricata-rules');

			expect(fetch).toHaveBeenCalledWith('/api/system/updates/rollback', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ component: 'suricata-rules' }),
			});
			expect(result).toEqual({ success: true, message: 'Restored from backup 20261116' });
		});

		it.each([
			[404, { success: false, component: 'geoip-db', message: 'No backup available for component: geoip-db' }, 'No backup available for component: geoip-db'],
			[500, { error: 'Rollback failed: disk full' }, 'Rollback failed: disk full'],
			[502, { error: 'Daemon unreachable', daemonAvailable: false }, 'Daemon unreachable'],
			[200, { success: false, message: '' }, 'the request failed (HTTP 200).'],
		])('turns a %i reply into {success: false, message}', async (status, body, message) => {
			mockFetchSuccess(body, status);

			expect(await rollbackComponent('geoip-db')).toEqual({ success: false, message });
		});

		it('uses the HTTP status when the reply is not JSON', async () => {
			mockFetchFailure(500);

			expect(await rollbackComponent('geoip-db')).toEqual({ success: false, message: 'the request failed (HTTP 500).' });
		});
	});
});
