import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getDetectionPacks,
	getDetectionPack,
	installPack,
	uninstallPack,
	enablePack,
	disablePack,
	checkPackUpdates,
	getPackStats,
} from './detection-packs';

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

const samplePack = {
	id: 'et-open-v1',
	name: 'Emerging Threats Open',
	description: 'Community Suricata rules from Emerging Threats',
	version: '2026.02.01',
	author: 'Proofpoint',
	rule_count: 45000,
	enabled: true,
	installed_at: '2026-02-01T00:00:00Z',
	updated_at: '2026-02-20T00:00:00Z',
	category: 'ids',
	tags: ['suricata', 'community'],
	source_url: 'https://rules.emergingthreats.net/open/',
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('detection-packs API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getDetectionPacks ---------------------------------------------------

	describe('getDetectionPacks', () => {
		it('returns parsed packs list on success', async () => {
			mockFetchSuccess({ packs: [samplePack] });

			const result = await getDetectionPacks();

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs');
			expect(result.packs).toHaveLength(1);
			expect(result.packs[0].name).toBe('Emerging Threats Open');
		});

		it('returns empty packs on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getDetectionPacks();

			expect(result.packs).toEqual([]);
		});
	});

	// -- getDetectionPack ----------------------------------------------------

	describe('getDetectionPack', () => {
		it('returns a single pack on success', async () => {
			mockFetchSuccess(samplePack);

			const result = await getDetectionPack('et-open-v1');

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/et-open-v1');
			expect(result?.name).toBe('Emerging Threats Open');
		});

		it('returns null on 404', async () => {
			mockFetchFailure(404);

			const result = await getDetectionPack('nonexistent');

			expect(result).toBeNull();
		});
	});

	// -- installPack ---------------------------------------------------------

	describe('installPack', () => {
		it('sends POST and returns installed pack on success', async () => {
			mockFetchSuccess(samplePack);

			const result = await installPack('et-open-v1');

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/et-open-v1/install', {
				method: 'POST',
			});
			expect(result?.id).toBe('et-open-v1');
		});

		it('returns null on failure', async () => {
			mockFetchFailure(500);

			const result = await installPack('bad-pack');

			expect(result).toBeNull();
		});
	});

	// -- uninstallPack -------------------------------------------------------

	describe('uninstallPack', () => {
		it('sends DELETE and returns true on success', async () => {
			mockFetchSuccess({ result: 'deleted' });

			const result = await uninstallPack('et-open-v1');

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/et-open-v1', {
				method: 'DELETE',
			});
			expect(result).toBe(true);
		});

		it('returns false on failure', async () => {
			mockFetchFailure(404);

			const result = await uninstallPack('nonexistent');

			expect(result).toBe(false);
		});
	});

	// -- enablePack / disablePack --------------------------------------------

	describe('enablePack', () => {
		it('sends POST to enable endpoint and returns true', async () => {
			mockFetchSuccess({ result: 'enabled' });

			const result = await enablePack('et-open-v1');

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/et-open-v1/enable', {
				method: 'POST',
			});
			expect(result).toBe(true);
		});
	});

	describe('disablePack', () => {
		it('sends POST to disable endpoint and returns true', async () => {
			mockFetchSuccess({ result: 'disabled' });

			const result = await disablePack('et-open-v1');

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/et-open-v1/disable', {
				method: 'POST',
			});
			expect(result).toBe(true);
		});
	});

	// -- checkPackUpdates ----------------------------------------------------

	describe('checkPackUpdates', () => {
		it('returns available updates on success', async () => {
			const updates = {
				updates: [
					{ pack_id: 'et-open-v1', current_version: '2026.02.01', available_version: '2026.02.15' },
				],
			};
			mockFetchSuccess(updates);

			const result = await checkPackUpdates();

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/updates');
			expect(result.updates).toHaveLength(1);
			expect(result.updates[0].available_version).toBe('2026.02.15');
		});

		it('returns empty updates on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await checkPackUpdates();

			expect(result.updates).toEqual([]);
		});
	});

	// -- getPackStats --------------------------------------------------------

	describe('getPackStats', () => {
		it('returns aggregate stats on success', async () => {
			mockFetchSuccess({ total: 5, enabled: 3, total_rules: 72000 });

			const result = await getPackStats();

			expect(fetch).toHaveBeenCalledWith('/api/detection-packs/stats');
			expect(result.total).toBe(5);
			expect(result.enabled).toBe(3);
			expect(result.total_rules).toBe(72000);
		});

		it('returns zero stats on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getPackStats();

			expect(result.total).toBe(0);
			expect(result.enabled).toBe(0);
			expect(result.total_rules).toBe(0);
		});
	});
});
