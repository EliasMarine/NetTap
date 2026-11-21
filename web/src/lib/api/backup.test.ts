import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	// OLD CODE: exportConfig, (NET-344: retired; downloadConfigFile is covered below)
	downloadConfigFile,
	restoreBody,
	RESTORE_LIMIT_BYTES,
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

	// OLD CODE START — NET-344: exportConfig is retired; downloadConfigFile is covered below
	// // -- exportConfig -----------------------------------------------------
	//
	// describe('exportConfig', () => {
	// 	it('returns config on success', async () => {
	// 		const expected = {
	// 			metadata: {
	// 				nettap_version: '0.4.0',
	// 				schema_version: 1,
	// 				exported_at: '2026-03-08T00:00:00Z',
	// 			},
	// 			sections: {
	// 				excluded_ips: ['1.2.3.4'],
	// 			},
	// 		};
	// 		mockFetchSuccess(expected);
	//
	// 		const result = await exportConfig();
	// 		expect(result.metadata.nettap_version).toBe('0.4.0');
	// 		expect(result.sections.excluded_ips).toEqual(['1.2.3.4']);
	// 	});
	//
	// 	it('throws on failure', async () => {
	// 		mockFetchFailure();
	// 		await expect(exportConfig()).rejects.toThrow('Export failed');
	// 	});
	// });
	// OLD CODE END

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

			const result = await validateConfig('{"metadata":{},"sections":{}}');
			expect(result.is_valid).toBe(true);
		});

		it('throws on failure', async () => {
			mockFetchFailure();
			await expect(validateConfig('{}')).rejects.toThrow('Validation failed: 500');
		});

		// OLD CODE START — NET-344: the body was JSON.stringify(data), a re-encoding of the file
		// it('sends POST with JSON body', async () => {
		// 	mockFetchSuccess({ is_valid: true, warnings: [], errors: [], preview: {} });
		//
		// 	const data = { metadata: { schema_version: 1 }, sections: {} };
		// 	await validateConfig(data);
		//
		// 	const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		// 	expect(call[0]).toBe('/api/backup/validate');
		// 	expect(call[1].method).toBe('POST');
		// 	expect(JSON.parse(call[1].body)).toEqual(data);
		// });
		// OLD CODE END
		it('NET-344: sends the body it is given unchanged', async () => {
			mockFetchSuccess({ is_valid: true, warnings: [], errors: [], preview: {} });

			const body = '{\n  "metadata": {"schema_version": 1, "x": 1e-05},\n  "sections": {}\n}';
			await validateConfig(body);

			const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
			expect(call[0]).toBe('/api/backup/validate');
			expect(call[1].method).toBe('POST');
			expect(call[1].body).toBe(body);
		});

		it("NET-344: throws the daemon's 413 reason", async () => {
			mockFetchSuccess({ error: 'This file is over the 16 MB restore limit.' }, 413);
			await expect(validateConfig('{}')).rejects.toThrow('This file is over the 16 MB restore limit.');
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

			const result = await importConfig('{"metadata":{},"sections":{}}');
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

			const result = await importConfig('{"metadata":{"schema_version":999},"sections":{}}');
			expect(result.success).toBe(false);
			expect(result.errors).toContain('Schema too new');
		});

		it('A9: asks for the capture mode only when told to, since it restarts capture', async () => {
			mockFetchSuccess({ success: true, applied: [], skipped: [], errors: [], warnings: [] });
			const fetchMock = vi.mocked(fetch);

			await importConfig('{}');
			await importConfig('{}', true);

			expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(['/api/backup/import', '/api/backup/import?apply_capture=1']);
		});

		it("throws with the daemon's reason when the import itself fails (500)", async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 500,
					json: () => Promise.resolve({ error: 'Config import failed: disk full' }),
				}),
			);

			await expect(importConfig('{}')).rejects.toThrow('Config import failed: disk full');
		});

		it('NET-344: sends the body it is given unchanged', async () => {
			mockFetchSuccess({ success: true, applied: [], skipped: [], errors: [], warnings: [] });
			const body = '{ "metadata": {"x": 1e-05}, "sections": {} }';
			await importConfig(body);
			expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBe(body);
		});

		it("NET-344: throws the daemon's 413 reason", async () => {
			mockFetchSuccess({ error: 'This file is over the 16 MB restore limit.' }, 413);
			await expect(importConfig('{}')).rejects.toThrow('This file is over the 16 MB restore limit.');
		});
	});

	// -- readConfigFile ---------------------------------------------------

	describe('readConfigFile', () => {
		it('parses valid JSON file and keeps its text (NET-344)', async () => {
			const content = '{ "test": true }';
			const file = new File([content], 'config.json', { type: 'application/json' });

			const result = await readConfigFile(file);
			expect(result).toEqual({ text: content, data: { test: true } });
		});

		it('rejects invalid JSON file', async () => {
			const file = new File(['not json'], 'config.txt', { type: 'text/plain' });

			await expect(readConfigFile(file)).rejects.toThrow('Invalid JSON');
		});
	});
	// -- downloadConfigFile (NET-344) -----------------------------------------

	describe('downloadConfigFile', () => {
		/** Captures what would be saved: the blob and the file name. */
		function catchSave() {
			const blobs: Blob[] = [];
			vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (blobs.push(b), 'blob:x'), revokeObjectURL: () => {} }));
			const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
			const names = () => click.mock.contexts.map((a) => (a as HTMLAnchorElement).download);
			return { blobs, names };
		}

		function exportReply(body: string, status = 200, headers: Record<string, string> = {}) {
			vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status, headers })));
		}

		afterEach(() => vi.unstubAllGlobals());

		it("saves the daemon's bytes unchanged under its file name", async () => {
			// compact, an emoji and a number pretty-printing would rewrite (1e-05 becomes 0.00001)
			const body = '{"metadata":{"schema_version":2,"x":1e-05},"sections":{"device_aliases":{"a":"Kids’ iPad 🎮"}}}';
			exportReply(body, 200, {
				'Content-Type': 'application/json',
				'Content-Disposition': 'attachment; filename="nettap-config-2026-11-20.json"',
			});
			const { blobs, names } = catchSave();

			const result = await downloadConfigFile();

			// plain arrays: the blob and TextEncoder hand back Uint8Arrays from different realms
			expect([...new Uint8Array(await blobs[0].arrayBuffer())]).toEqual([...new TextEncoder().encode(body)]);
			expect(names()).toEqual(['nettap-config-2026-11-20.json']);
			expect(result).toEqual({ leftOut: 0 });
		});

		it('returns how many acknowledgements the daemon left out', async () => {
			exportReply('{"metadata":{"acknowledgements_left_out":1234},"sections":{}}');
			catchSave();
			expect(await downloadConfigFile()).toEqual({ leftOut: 1234 });
		});

		it('falls back to a dated name when the daemon sends none', async () => {
			exportReply('{"metadata":{},"sections":{}}');
			const { names } = catchSave();
			await downloadConfigFile();
			expect(names()[0]).toMatch(/^nettap-config-\d{4}-\d{2}-\d{2}\.json$/);
		});

		it.each([
			[413, 'This backup would be 17.4 MB, over the 16 MB restore limit. The largest part is device pictures (11.2 MB).'],
			[422, "Excluded IPs: 10.0.0.0/8 is a range. NetTap no longer keeps ranges, so it can't restore this one."],
			[503, 'A backup is already being made. Try again in a moment.'],
		])("throws the daemon's %i reason and saves nothing", async (status, error) => {
			exportReply(JSON.stringify({ error, code: 'x' }), status, { 'Content-Type': 'application/json' });
			const { blobs } = catchSave();
			await expect(downloadConfigFile()).rejects.toThrow(error);
			expect(blobs).toEqual([]);
		});

		it('says the status when the error reply has no reason', async () => {
			exportReply('Bad gateway', 502);
			catchSave();
			await expect(downloadConfigFile()).rejects.toThrow('Export failed: 502');
		});
	});

	// -- restoreBody (NET-344) ------------------------------------------------

	describe('restoreBody', () => {
		it("sends the file's own text when it is under the limit, to the last byte", () => {
			const text = `{"a":1}${' '.repeat(RESTORE_LIMIT_BYTES - 8)}`;
			expect(new TextEncoder().encode(text).length).toBe(RESTORE_LIMIT_BYTES - 1);
			expect(restoreBody(text, { a: 1 })).toBe(text);
		});

		it('sends the compacted JSON when only that fits (an older pretty-printed backup)', () => {
			const text = `{"a":1}${' '.repeat(RESTORE_LIMIT_BYTES - 7)}`;
			expect(new TextEncoder().encode(text).length).toBe(RESTORE_LIMIT_BYTES);
			expect(restoreBody(text, { a: 1 })).toBe('{"a":1}');
		});

		it('refuses, naming the size, when neither fits; counting UTF-8 bytes, not characters', () => {
			// half as many characters as the limit, but each is two bytes
			const value = 'é'.repeat(RESTORE_LIMIT_BYTES / 2);
			const text = JSON.stringify({ a: value });
			expect(text.length).toBeLessThan(RESTORE_LIMIT_BYTES);
			expect(() => restoreBody(text, { a: value })).toThrow('This file is 16.8 MB, over the 16 MB restore limit.');
		});
	});
});
