import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	exportConfig,
	validateConfig,
	importConfig,
	readConfigFile,
} from '$lib/api/backup';

/**
 * Page-level tests for the backup/restore page.
 * Tests the API integration functions used by the page.
 */

function mockFetchSuccess(body: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve(body),
		}),
	);
}

describe('backup/restore page integration', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('exports configuration', async () => {
		mockFetchSuccess({
			metadata: {
				nettap_version: '0.4.0',
				schema_version: 1,
				exported_at: '2026-03-08T00:00:00Z',
			},
			sections: {
				excluded_ips: ['1.2.3.4'],
				bandwidth_cap: { monthly_cap_gb: 1000 },
			},
		});

		const result = await exportConfig();
		expect(result.metadata.nettap_version).toBe('0.4.0');
		expect(result.sections.excluded_ips).toEqual(['1.2.3.4']);
	});

	it('validates import data', async () => {
		mockFetchSuccess({
			is_valid: true,
			warnings: [],
			errors: [],
			preview: { excluded_ips: { type: 'list', size: 1 } },
		});

		const result = await validateConfig({ metadata: {}, sections: {} });
		expect(result.is_valid).toBe(true);
		expect(result.preview).toHaveProperty('excluded_ips');
	});

	it('imports configuration', async () => {
		mockFetchSuccess({
			success: true,
			applied: ['excluded_ips', 'bandwidth_cap'],
			errors: [],
			warnings: [],
		});

		const result = await importConfig({ metadata: {}, sections: {} });
		expect(result.success).toBe(true);
		expect(result.applied).toContain('excluded_ips');
	});

	it('reads JSON file from File object', async () => {
		const content = JSON.stringify({ test: 'data' });
		const file = new File([content], 'config.json', { type: 'application/json' });

		const result = await readConfigFile(file);
		expect(result).toEqual({ test: 'data' });
	});

	it('rejects invalid JSON file', async () => {
		const file = new File(['not json'], 'bad.txt', { type: 'text/plain' });
		await expect(readConfigFile(file)).rejects.toThrow('Invalid JSON');
	});
});
