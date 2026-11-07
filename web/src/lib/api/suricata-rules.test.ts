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
	// OLD CODE START — NET-191 slice 2: retired with Snort Subscriber
	// configureCommercial,
	// getCommercialConfig,
	// OLD CODE END
	getEtProStatus,
	saveEtProCode,
	clearEtProCode,
	getLiveRuleStatus,
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

		// NET-191 slice 2: a 500 read "Request failed" and lost the daemon's reason
		it("keeps the daemon's failure body on a 500", async () => {
			const status = { state: 'failed', reason: 'ET Open download timed out', stale: false, recovery_pending: false };
			mockFetchSuccess({ success: false, output: 'suricata-update exited 1', reload_output: '', status }, 500);

			const result = await updateRulesNow();

			expect(result).toMatchObject({ success: false, output: 'suricata-update exited 1', status });
		});

		it('says an update still running (202) is not a success', async () => {
			mockFetchSuccess({ success: false, output: '', reload_output: '', running: true }, 202);

			const result = await updateRulesNow();

			expect(result.success).toBe(false);
			expect(result.running).toBe(true);
		});

		it("carries a proxy error's text as the output", async () => {
			mockFetchSuccess({ error: 'Daemon unavailable', daemonAvailable: false }, 502);

			const result = await updateRulesNow();

			expect(result).toMatchObject({ success: false, output: 'Daemon unavailable', reload_output: '' });
		});

		it.each([500, 202])('ignores a non-string error on HTTP %i', async (status) => {
			mockFetchSuccess({ error: { detail: 'not text' }, running: status === 202 }, status);

			const result = await updateRulesNow();

			expect(result.output).toBe(`Request failed (HTTP ${status})`);
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

		// #96: an empty editor read as "no custom rules saved"
		it('throws on error', async () => {
			mockFetchFailure(500);

			await expect(getCustomRules()).rejects.toThrow('HTTP 500');
		});
	});

	// OLD CODE START — NET-191 slice 2: configureCommercial and getCommercialConfig are retired
	// // -- configureCommercial / getCommercialConfig --------------------------
	//
	// describe('configureCommercial', () => {
	// 	it('sends POST with source type and license key', async () => {
	// 		mockFetchSuccess({ success: true, source_type: 'etpro', configured_at: '2026-03-01' });
	//
	// 		const result = await configureCommercial('etpro', 'ABCDEFGH12345678');
	//
	// 		expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/commercial', {
	// 			method: 'POST',
	// 			headers: { 'Content-Type': 'application/json' },
	// 			body: JSON.stringify({ source_type: 'etpro', license_key: 'ABCDEFGH12345678' }),
	// 		});
	// 		expect(result.success).toBe(true);
	// 	});
	// });
	//
	// describe('getCommercialConfig', () => {
	// 	it('returns config on success', async () => {
	// 		mockFetchSuccess({
	// 			configured: true,
	// 			source_type: 'etpro',
	// 			license_key_masked: 'ABCD****5678',
	// 		});
	//
	// 		const result = await getCommercialConfig();
	//
	// 		expect(result.configured).toBe(true);
	// 		expect(result.source_type).toBe('etpro');
	// 	});
	//
	// 	// #96: "unconfigured" read as "no commercial license"
	// 	it('throws on error', async () => {
	// 		mockFetchFailure(500);
	//
	// 		await expect(getCommercialConfig()).rejects.toThrow('HTTP 500');
	// 	});
	// });
	// OLD CODE END

	// -- ET Pro (NET-191 slice 2) -------------------------------------------

	describe('getEtProStatus', () => {
		it('returns the status on success', async () => {
			const body = { configured: true, active: true, last_update_ok: true, applying: false, activation: null };
			mockFetchSuccess(body);

			await expect(getEtProStatus()).resolves.toEqual(body);
			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/commercial');
		});

		// "Not set" must never stand in for "unknown"
		it('throws on error', async () => {
			mockFetchFailure(500);

			await expect(getEtProStatus()).rejects.toThrow('HTTP 500');
		});
	});

	describe('saveEtProCode', () => {
		it('POSTs the code as {code} and reports 202 as ok', async () => {
			mockFetchSuccess({ saved: true, applying: true }, 202);

			const result = await saveEtProCode('abcd1234ABCD5678');

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/commercial', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ code: 'abcd1234ABCD5678' }),
			});
			expect(result).toEqual({ ok: true, status: 202, saved: true, applying: true });
		});

		it("returns the daemon's error on a 400 instead of throwing", async () => {
			mockFetchSuccess({ error: 'Proofpoint did not accept this code.' }, 400);

			await expect(saveEtProCode('abcd1234ABCD5678')).resolves.toEqual({
				ok: false,
				status: 400,
				error: 'Proofpoint did not accept this code.',
			});
		});

		it('names the HTTP status when the reply has no error text', async () => {
			mockFetchFailure(502);

			const result = await saveEtProCode('abcd1234ABCD5678');

			expect(result).toMatchObject({ ok: false, status: 502, error: 'The request failed (HTTP 502).' });
		});
	});

	describe('clearEtProCode', () => {
		it('sends DELETE and reports what was cleared', async () => {
			mockFetchSuccess({ cleared: true, applying: true }, 202);

			const result = await clearEtProCode();

			expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/commercial', { method: 'DELETE' });
			expect(result).toEqual({ ok: true, status: 202, cleared: true, applying: true });
		});

		it('returns the 409 error while a rule update runs', async () => {
			mockFetchSuccess({ error: 'A rule update is running. Try again in a few minutes.' }, 409);

			const result = await clearEtProCode();

			expect(result).toMatchObject({ ok: false, status: 409, error: 'A rule update is running. Try again in a few minutes.' });
		});
	});
});

// ---------------------------------------------------------------------------
// getLiveRuleStatus (#58)
// ---------------------------------------------------------------------------

describe('getLiveRuleStatus', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const LIVE = {
		available: true,
		enabled_rules: 64307,
		disabled_rules: 15954,
		last_updated: '2026-11-02T00:00:36+00:00',
		sources: ['https://sslbl.abuse.ch/blacklist/sslblacklist.rules'],
		schedule: '0 0 * * *',
		error: null,
	};

	it('returns what Suricata runs', async () => {
		mockFetchSuccess(LIVE);
		await expect(getLiveRuleStatus()).resolves.toEqual(LIVE);
		expect(fetch).toHaveBeenCalledWith('/api/suricata/rules/live');
	});

	it('throws the daemon error instead of reporting 0 rules', async () => {
		mockFetchSuccess({ available: false, error: 'Could not reach the Suricata container.' }, 502);
		await expect(getLiveRuleStatus()).rejects.toThrow('Could not reach the Suricata container.');
	});

	it('throws HTTP <status> when the body is not JSON', async () => {
		mockFetchFailure(503);
		await expect(getLiveRuleStatus()).rejects.toThrow('HTTP 503');
	});
});
