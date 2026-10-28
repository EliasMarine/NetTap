import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for suricata-rules page module interactions.
 * Covers the API client calls that the page depends on.
 */

// Mock the API module
vi.mock('$lib/api/suricata-rules', () => ({
	getRuleSources: vi.fn(),
	enableRuleSource: vi.fn(),
	disableRuleSource: vi.fn(),
	updateRulesNow: vi.fn(),
	getRuleStats: vi.fn(),
	getUpdateSchedule: vi.fn(),
	setUpdateSchedule: vi.fn(),
	uploadCustomRules: vi.fn(),
	getCustomRules: vi.fn(),
	configureCommercial: vi.fn(),
	getCommercialConfig: vi.fn(),
}));

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
} from '$lib/api/suricata-rules';

describe('suricata-rules page data loading', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('getRuleSources returns sources array', async () => {
		const mockData = {
			sources: [
				{ id: 'et/open', enabled: true, description: 'ET Open' },
			],
			count: 1,
			last_update: '2026-03-01T00:00:00Z',
		};
		vi.mocked(getRuleSources).mockResolvedValue(mockData);

		const result = await getRuleSources();
		expect(result.sources).toHaveLength(1);
		expect(result.sources[0].id).toBe('et/open');
	});

	it('enableRuleSource calls with correct id', async () => {
		vi.mocked(enableRuleSource).mockResolvedValue(true);

		const result = await enableRuleSource('et/open');
		expect(result).toBe(true);
		expect(enableRuleSource).toHaveBeenCalledWith('et/open');
	});

	it('disableRuleSource calls with correct id', async () => {
		vi.mocked(disableRuleSource).mockResolvedValue(true);

		const result = await disableRuleSource('tgreen/hunting');
		expect(result).toBe(true);
		expect(disableRuleSource).toHaveBeenCalledWith('tgreen/hunting');
	});

	it('updateRulesNow returns update result', async () => {
		vi.mocked(updateRulesNow).mockResolvedValue({
			success: true,
			output: 'Updated',
			reload_output: 'Reloaded',
		});

		const result = await updateRulesNow();
		expect(result.success).toBe(true);
	});

	it('getRuleStats returns stats', async () => {
		vi.mocked(getRuleStats).mockResolvedValue({
			total_rules: 30000,
			enabled_sources: 5,
			total_sources: 7,
			categories: {},
			category_prefixes: {},
		});

		const result = await getRuleStats();
		expect(result.enabled_sources).toBe(5);
	});

	it('setUpdateSchedule sends interval', async () => {
		vi.mocked(setUpdateSchedule).mockResolvedValue({
			interval: 'weekly',
			enabled: true,
		});

		const result = await setUpdateSchedule('weekly');
		expect(result.interval).toBe('weekly');
		expect(setUpdateSchedule).toHaveBeenCalledWith('weekly');
	});

	it('uploadCustomRules sends content', async () => {
		vi.mocked(uploadCustomRules).mockResolvedValue({
			success: true,
			rules_written: 2,
			file: '/tmp/custom.rules',
		});

		const result = await uploadCustomRules('alert tcp any any -> any any (msg:"test";)');
		expect(result.rules_written).toBe(2);
	});

	it('configureCommercial sends type and key', async () => {
		vi.mocked(configureCommercial).mockResolvedValue({ success: true });

		const result = await configureCommercial('etpro', 'ABCD12345678');
		expect(result.success).toBe(true);
		expect(configureCommercial).toHaveBeenCalledWith('etpro', 'ABCD12345678');
	});

	it('getCommercialConfig returns config', async () => {
		vi.mocked(getCommercialConfig).mockResolvedValue({
			configured: true,
			source_type: 'etpro',
			license_key_masked: 'ABCD****5678',
		});

		const result = await getCommercialConfig();
		expect(result.configured).toBe(true);
		expect(result.source_type).toBe('etpro');
	});
});
