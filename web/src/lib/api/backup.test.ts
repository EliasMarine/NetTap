import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	exportConfig,
	validateConfig,
	importConfig,
	readConfigFile,
} from './backup';

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

describe('backup API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- exportConfig -----------------------------------------------------

	describe('exportConfig', () => {
		it('returns config on success', async () => {
			const expected = {
				metadata: {
					nettap_version: '0.4.0',
					schema_version: 1,
					exported_at: '2026-03-08T00:00:00Z',
				},
				sections: {
					excluded_ips: ['1.2.3.4'],
				},
			};
			mockFetchSuccess(expected);

			const result = await exportConfig();
			expect(result.metadata.nettap_version).toBe('0.4.0');
			expect(result.sections.excluded_ips).toEqual(['1.2.3.4']);
		});

		it('throws on failure', async () => {
			mockFetchFailure();
			await expect(exportConfig()).rejects.toThrow('Export failed');
		});
	});

	// -- validateConfig ---------------------------------------------------

	describe('validateConfig', () => {
		it('returns validation result on success', async () => {
			const expected = {
				is_valid: true,
				warnings: [],
				errors: [],
				preview: { excluded_ips: { type: 'list', size: 2 } },
			};
			mockFetchSuccess(expected);

			const result = await validateConfig({ metadata: {}, sections: {} });
			expect(result.is_valid).toBe(true);
		});

		it('throws on failure', async () => {
			mockFetchFailure();
			await expect(validateConfig({})).rejects.toThrow('Validation failed');
		});

		it('sends POST with JSON body', async () => {
			mockFetchSuccess({ is_valid: true, warnings: [], errors: [], preview: {} });

			const data = { metadata: { schema_version: 1 }, sections: {} };
			await validateConfig(data);

			const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			expect(call[0]).toBe('/api/backup/validate');
			expect(call[1].method).toBe('POST');
			expect(JSON.parse(call[1].body)).toEqual(data);
		});
	});

	// -- importConfig -----------------------------------------------------

	describe('importConfig', () => {
		it('returns result on success', async () => {
			mockFetchSuccess({
				success: true,
				applied: ['excluded_ips'],
				errors: [],
				warnings: [],
			});

			const result = await importConfig({ metadata: {}, sections: {} });
			expect(result.success).toBe(true);
			expect(result.applied).toContain('excluded_ips');
		});

		it('returns result on validation failure (400)', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 400,
					json: () =>
						Promise.resolve({
							success: false,
							applied: [],
							errors: ['Schema too new'],
							warnings: [],
						}),
				}),
			);

			const result = await importConfig({ metadata: { schema_version: 999 }, sections: {} });
			expect(result.success).toBe(false);
			expect(result.errors).toContain('Schema too new');
		});
	});

	// -- readConfigFile ---------------------------------------------------

	describe('readConfigFile', () => {
		it('parses valid JSON file', async () => {
			const content = JSON.stringify({ test: true });
			const file = new File([content], 'config.json', { type: 'application/json' });

			const result = await readConfigFile(file);
			expect(result).toEqual({ test: true });
		});

		it('rejects invalid JSON file', async () => {
			const file = new File(['not json'], 'config.txt', { type: 'text/plain' });

			await expect(readConfigFile(file)).rejects.toThrow('Invalid JSON');
		});
	});
});
