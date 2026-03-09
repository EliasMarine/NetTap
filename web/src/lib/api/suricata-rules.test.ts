import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getRuleSources,
	enableRuleSource,
	disableRuleSource,
	updateRulesNow,
	getRuleStats,
	getUpdateSchedule,
	setUpdateSchedule,
	uploadCustomRules,
	getCustomRules,
	configureCommercial,
	getCommercialConfig,
} from './suricata-rules';

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
// Tests
// ---------------------------------------------------------------------------

describe('suricata-rules API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getRuleSources -----------------------------------------------------

	describe('getRuleSources', () => {
		it('returns parsed sources list on success', async () => {
			const data = {
				sources: [
					{ id: 'et/open', enabled: true, description: 'ET Open rules' },
					{ id: 'sslbl/ssl-fp-blacklist', enabled: true, description: 'SSL Blacklist' },
				],
				count: 2,
				last_update: '2026-03-01T00:00:00Z',
			};
			mockFetchSuccess(data);

			const result = await getRuleSources();

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/sources');
			expect(result.sources).toHaveLength(2);
			expect(result.sources[0].id).toBe('et/open');
			expect(result.last_update).toBe('2026-03-01T00:00:00Z');
		});

		it('returns empty sources on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getRuleSources();

			expect(result.sources).toEqual([]);
			expect(result.count).toBe(0);
		});
	});

	// -- enableRuleSource / disableRuleSource -------------------------------

	describe('enableRuleSource', () => {
		it('sends POST and returns true on success', async () => {
			mockFetchSuccess({ result: 'enabled', id: 'et/open' });

			const result = await enableRuleSource('et/open');

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/sources/et%2Fopen/enable', {
				method: 'POST',
			});
			expect(result).toBe(true);
		});

		it('returns false on failure', async () => {
			mockFetchFailure(404);

			const result = await enableRuleSource('nonexistent');

			expect(result).toBe(false);
		});
	});

	describe('disableRuleSource', () => {
		it('sends POST and returns true on success', async () => {
			mockFetchSuccess({ result: 'disabled', id: 'tgreen/hunting' });

			const result = await disableRuleSource('tgreen/hunting');

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/sources/tgreen%2Fhunting/disable', {
				method: 'POST',
			});
			expect(result).toBe(true);
		});
	});

	// -- updateRulesNow -----------------------------------------------------

	describe('updateRulesNow', () => {
		it('sends POST and returns update result on success', async () => {
			const data = {
				success: true,
				output: 'Rules updated successfully',
				reload_output: 'Rules reloaded',
			};
			mockFetchSuccess(data);

			const result = await updateRulesNow();

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/update', { method: 'POST' });
			expect(result.success).toBe(true);
			expect(result.output).toBe('Rules updated successfully');
		});

		it('returns failure result on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await updateRulesNow();

			expect(result.success).toBe(false);
		});
	});

	// -- getRuleStats -------------------------------------------------------

	describe('getRuleStats', () => {
		it('returns stats on success', async () => {
			const data = {
				total_rules: 30000,
				enabled_sources: 5,
				total_sources: 7,
				categories: { Malware: 8000, Scanning: 3000 },
				category_prefixes: {},
			};
			mockFetchSuccess(data);

			const result = await getRuleStats();

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/stats');
			expect(result.total_rules).toBe(30000);
			expect(result.enabled_sources).toBe(5);
		});

		it('returns zero stats on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getRuleStats();

			expect(result.total_rules).toBe(0);
		});
	});

	// -- getUpdateSchedule / setUpdateSchedule ------------------------------

	describe('getUpdateSchedule', () => {
		it('returns schedule on success', async () => {
			mockFetchSuccess({ interval: 'weekly', enabled: true });

			const result = await getUpdateSchedule();

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/schedule');
			expect(result.interval).toBe('weekly');
		});

		it('returns default schedule on error', async () => {
			mockFetchFailure(500);

			const result = await getUpdateSchedule();

			expect(result.interval).toBe('daily');
		});
	});

	describe('setUpdateSchedule', () => {
		it('sends PUT with interval and returns updated schedule', async () => {
			mockFetchSuccess({ interval: 'weekly', enabled: true });

			const result = await setUpdateSchedule('weekly');

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/schedule', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ interval: 'weekly' }),
			});
			expect(result.interval).toBe('weekly');
		});
	});

	// -- uploadCustomRules / getCustomRules ---------------------------------

	describe('uploadCustomRules', () => {
		it('sends POST with rules content', async () => {
			mockFetchSuccess({ success: true, rules_written: 3, file: '/tmp/custom.rules' });

			const result = await uploadCustomRules('alert tcp any any -> any any (msg:"test"; sid:1000001;)');

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/custom', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: expect.any(String),
			});
			expect(result.success).toBe(true);
			expect(result.rules_written).toBe(3);
		});

		it('returns failure on HTTP error', async () => {
			mockFetchFailure(400);

			const result = await uploadCustomRules('bad');

			expect(result.success).toBe(false);
		});
	});

	describe('getCustomRules', () => {
		it('returns content on success', async () => {
			mockFetchSuccess({ content: 'alert tcp any any -> any any (msg:"test"; sid:1;)' });

			const result = await getCustomRules();

			expect(result).toContain('alert tcp');
		});

		it('returns empty string on error', async () => {
			mockFetchFailure(500);

			const result = await getCustomRules();

			expect(result).toBe('');
		});
	});

	// -- configureCommercial / getCommercialConfig --------------------------

	describe('configureCommercial', () => {
		it('sends POST with source type and license key', async () => {
			mockFetchSuccess({ success: true, source_type: 'etpro', configured_at: '2026-03-01' });

			const result = await configureCommercial('etpro', 'ABCDEFGH12345678');

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/commercial', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ source_type: 'etpro', license_key: 'ABCDEFGH12345678' }),
			});
			expect(result.success).toBe(true);
		});
	});

	describe('getCommercialConfig', () => {
		it('returns config on success', async () => {
			mockFetchSuccess({
				configured: true,
				source_type: 'etpro',
				license_key_masked: 'ABCD****5678',
			});

			const result = await getCommercialConfig();

			expect(result.configured).toBe(true);
			expect(result.source_type).toBe('etpro');
		});

		it('returns unconfigured on error', async () => {
			mockFetchFailure(500);

			const result = await getCommercialConfig();

			expect(result.configured).toBe(false);
		});
	});
});
