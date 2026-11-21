import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh } from '$lib/stores/pageRefresh';
// OLD CODE: import Page from './+page.svelte'; (NET-273: the page is a Settings tab now)
import Page from './BackupTab.svelte';

/** Validation always passes; the import answers with `importReply`. */
function stubFetch(importReply: { ok: boolean; status: number; body: unknown }) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url === '/api/backup/validate') {
				return { ok: true, status: 200, json: async () => ({ is_valid: true, warnings: [], errors: [], preview: {} }) };
			}
			if (url === '/api/backup/import') {
				return { ok: importReply.ok, status: importReply.status, json: async () => importReply.body };
			}
			return { ok: false, status: 500, json: async () => ({}) };
		}),
	);
}

async function applyConfig() {
	const { container } = render(Page);
	const input = container.querySelector('input[type="file"]') as HTMLInputElement;
	const file = new File([JSON.stringify({ metadata: { schema_version: 1 }, sections: {} })], 'nettap.json', { type: 'application/json' });
	await fireEvent.change(input, { target: { files: [file] } });
	await fireEvent.click(await screen.findByRole('button', { name: 'Apply configuration' }));
}

describe('Backup import when the daemon fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it("shows the daemon's reason when the import itself fails", async () => {
		stubFetch({ ok: false, status: 500, body: { error: 'Config import failed: disk full' } });
		await applyConfig();

		expect(await screen.findByText('Config import failed: disk full')).toBeInTheDocument();
		expect(screen.queryByText('Import successful')).not.toBeInTheDocument();
	});

	it('shows the rejected sections when the daemon refuses the config', async () => {
		stubFetch({ ok: false, status: 400, body: { success: false, applied: [], errors: ['Schema too new'], warnings: [] } });
		await applyConfig();

		expect(await screen.findByText('Import failed')).toBeInTheDocument();
		expect(screen.getByText('Errors: Schema too new')).toBeInTheDocument();
	});
});

// Forms only: nothing on this page comes from a loader, so the top bar hides Refresh (PLAN §5.5)
describe('Backup page refresh contract', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('registers no page loader', () => {
		stubFetch({ ok: true, status: 200, body: {} });
		render(Page);

		expect(get(pageRefresh).available).toBe(false);
	});
});

// A9: a restore said "Import successful" although it skipped capture mode and retention
describe('Backup restore reports what it did (A9)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	/** Validation answers `validation`; the import answers `body`; returns the fetch mock. */
	function stub(validation: Record<string, unknown>, body: unknown) {
		const fn = vi.fn(async (url: string) => {
			if (url === '/api/backup/validate') {
				return { ok: true, status: 200, json: async () => ({ is_valid: true, warnings: [], errors: [], preview: {}, ...validation }) };
			}
			if (url.startsWith('/api/backup/import')) return { ok: true, status: 200, json: async () => body };
			return { ok: false, status: 500, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fn);
		return fn;
	}

	async function chooseFile() {
		const { container } = render(Page);
		const input = container.querySelector('input[type="file"]') as HTMLInputElement;
		const file = new File([JSON.stringify({ metadata: { schema_version: 2 }, sections: {} })], 'nettap.json', { type: 'application/json' });
		await fireEvent.change(input, { target: { files: [file] } });
		return screen.findByRole('button', { name: 'Apply configuration' });
	}

	const RESULT = { success: true, applied: ['storage_retention'], skipped: [], errors: [], warnings: [] };

	it('asks before restoring a different capture mode, and sends it only when ticked', async () => {
		const fn = stub({ capture_restart: true }, RESULT);
		const apply = await chooseFile();
		const box = screen.getByRole('checkbox', { name: /Also restore the capture mode/ });
		expect(box).not.toBeChecked();
		expect(screen.getByText(/restarts the capture containers/)).toBeInTheDocument();

		await fireEvent.click(box);
		await fireEvent.click(apply);
		await screen.findByText('Import successful');
		expect(fn.mock.calls.map((c) => c[0])).toContain('/api/backup/import?apply_capture=1');
	});

	// review M2: five pages word things by the capture mode; a restore that changed it must reach them
	it('reads the capture mode again once a restore applied it', async () => {
		const { captureMode } = await import('$lib/stores/captureMode');
		captureMode.set('mirror');
		const fn = stub({ capture_restart: true }, { ...RESULT, applied: ['capture_mode_config'] });
		const daemon = fn.getMockImplementation()!;
		fn.mockImplementation(async (url: string) =>
			url === '/api/capture/mode' ? { ok: true, status: 200, json: async () => ({ mode: 'bridge', interface: 'br0' }) } : daemon(url),
		);
		const apply = await chooseFile();
		await fireEvent.click(screen.getByRole('checkbox', { name: /Also restore the capture mode/ }));
		await fireEvent.click(apply);
		await screen.findByText('Import successful');

		await vi.waitFor(() => expect(get(captureMode)).toBe('bridge'));
		captureMode.set(null);
	});

	it('does not ask for the capture mode when a restore left it alone', async () => {
		const fn = stub({ capture_restart: true }, RESULT);
		await fireEvent.click(await chooseFile());
		await screen.findByText('Import successful');
		expect(fn.mock.calls.map((c) => c[0])).not.toContain('/api/capture/mode');
	});

	it('restores without the capture mode when the box is left unticked', async () => {
		const fn = stub({ capture_restart: true }, RESULT);
		await fireEvent.click(await chooseFile());
		await screen.findByText('Import successful');
		expect(fn.mock.calls.map((c) => c[0])).toContain('/api/backup/import');
		expect(fn.mock.calls.map((c) => c[0])).not.toContain('/api/backup/import?apply_capture=1');
	});

	it('offers no capture choice when the capture mode is the same', async () => {
		stub({ capture_restart: false }, RESULT);
		await chooseFile();
		expect(screen.queryByRole('checkbox', { name: /Also restore the capture mode/ })).not.toBeInTheDocument();
	});

	it('names what was restored and what was skipped, and why, instead of "Import successful"', async () => {
		stub({}, {
			...RESULT,
			skipped: [{ section: 'capture_mode_config', reason: "Not applied: restoring it restarts capture, and that wasn't confirmed" }],
		});
		await fireEvent.click(await chooseFile());

		expect(await screen.findByText('Imported, some sections skipped')).toBeInTheDocument();
		expect(screen.getByText('Restored: Retention')).toBeInTheDocument();
		expect(screen.getByText("Capture mode: Not applied: restoring it restarts capture, and that wasn't confirmed")).toBeInTheDocument();
		expect(screen.queryByText('Import successful')).not.toBeInTheDocument();
	});

	it("names a section the daemon sends that isn't in the label list by its key, never a built-in (L6)", async () => {
		stub({}, { ...RESULT, applied: ['constructor', 'storage_retention'] });
		await fireEvent.click(await chooseFile());

		// old code: SECTION_LABELS['constructor'] is Object, so "Restored: function Object() …"
		expect(await screen.findByText('Restored: constructor, Retention')).toBeInTheDocument();
	});

	it('names the quiet hours section by its label, not its key (F8)', async () => {
		stub({}, { ...RESULT, applied: ['notification_rules', 'notification_quiet'] });
		await fireEvent.click(await chooseFile());

		expect(await screen.findByText('Restored: Notification rules, Quiet hours')).toBeInTheDocument();
	});

	it('says what a backup leaves out', () => {
		stub({}, RESULT);
		render(Page);
		expect(screen.getByText(/Left out: passwords, API keys and tokens/)).toBeInTheDocument();
	});
});

// NET-344: every downloadable backup restores, so the bytes are kept both ways
describe('Backup keeps the bytes and the selection straight (NET-344)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	const VALID = { is_valid: true, warnings: [], errors: [], preview: {} };
	const IMPORTED = { success: true, applied: [], skipped: [], errors: [], warnings: [] };

	function input(container: HTMLElement) {
		return container.querySelector('input[type="file"]') as HTMLInputElement;
	}

	it("sends the file's own text, pretty-printed as it is, to validate and import", async () => {
		const text = '{\n  "metadata": { "schema_version": 2, "x": 1e-05 },\n  "sections": {}\n}\n';
		const fn = vi.fn(async (url: string, _init?: RequestInit) =>
			url === '/api/backup/validate'
				? { ok: true, status: 200, json: async () => VALID }
				: { ok: true, status: 200, json: async () => IMPORTED },
		);
		vi.stubGlobal('fetch', fn);
		const { container } = render(Page);
		await fireEvent.change(input(container), { target: { files: [new File([text], 'pretty.json')] } });
		await fireEvent.click(await screen.findByRole('button', { name: 'Apply configuration' }));
		await screen.findByText('Import successful');

		expect(fn.mock.calls.map((c) => [c[0], c[1]?.body])).toEqual([
			['/api/backup/validate', text],
			['/api/backup/import', text],
		]);
	});

	it("never applies an earlier file's body under a later file's name, whatever order they finish in", async () => {
		const A = '{"metadata":{"schema_version":2},"sections":{"excluded_ips":["10.0.0.1"]}}';
		const B = '{"metadata":{"schema_version":2},"sections":{"excluded_ips":["10.0.0.2"]}}';
		const pending = new Map<string, (v: unknown) => void>();
		const fn = vi.fn((url: string, init?: RequestInit) => {
			if (url === '/api/backup/validate') {
				return new Promise((resolve) => pending.set(init?.body as string, resolve));
			}
			return Promise.resolve({ ok: true, status: 200, json: async () => IMPORTED });
		});
		vi.stubGlobal('fetch', fn);
		const answer = (body: string, warnings: string[]) =>
			pending.get(body)!({ ok: true, status: 200, json: async () => ({ ...VALID, warnings }) });

		const { container } = render(Page);
		await fireEvent.change(input(container), { target: { files: [new File([A], 'a.json')] } });
		await vi.waitFor(() => expect(pending.has(A)).toBe(true));
		await fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
		await fireEvent.change(input(container), { target: { files: [new File([B], 'b.json')] } });
		await vi.waitFor(() => expect(pending.has(B)).toBe(true));

		// A finishes first, while B is still being checked: nothing of A's is shown or offered
		answer(A, ['from file A']);
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('from file A')).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Apply configuration' })).not.toBeInTheDocument();
		expect(screen.getByText('Validating configuration…')).toBeInTheDocument();

		answer(B, ['from file B']);
		await fireEvent.click(await screen.findByRole('button', { name: 'Apply configuration' }));
		await screen.findByText('Import successful');

		expect(screen.getByText('b.json')).toBeInTheDocument();
		expect(screen.queryByText('from file A')).not.toBeInTheDocument();
		const imports = fn.mock.calls.filter((c) => c[0].startsWith('/api/backup/import'));
		expect(imports.map((c) => c[1]?.body)).toEqual([B]);
	});

	it('drops a slower earlier check that lands after the later one', async () => {
		const A = '{"metadata":{"schema_version":2},"sections":{"bandwidth_cap":{"monthly_cap_gb":1}}}';
		const B = '{"metadata":{"schema_version":2},"sections":{"bandwidth_cap":{"monthly_cap_gb":2}}}';
		const pending = new Map<string, (v: unknown) => void>();
		const fn = vi.fn((url: string, init?: RequestInit) =>
			url === '/api/backup/validate'
				? new Promise((resolve) => pending.set(init?.body as string, resolve))
				: Promise.resolve({ ok: true, status: 200, json: async () => IMPORTED }),
		);
		vi.stubGlobal('fetch', fn);

		const { container } = render(Page);
		await fireEvent.change(input(container), { target: { files: [new File([A], 'a.json')] } });
		await vi.waitFor(() => expect(pending.has(A)).toBe(true));
		await fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
		await fireEvent.change(input(container), { target: { files: [new File([B], 'b.json')] } });
		await vi.waitFor(() => expect(pending.has(B)).toBe(true));

		pending.get(B)!({ ok: true, status: 200, json: async () => VALID });
		const apply = await screen.findByRole('button', { name: 'Apply configuration' });
		// A's invalid answer arrives last and must not replace B's
		pending.get(A)!({ ok: true, status: 200, json: async () => ({ ...VALID, is_valid: false, errors: ['from file A'] }) });
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('from file A')).not.toBeInTheDocument();

		await fireEvent.click(apply);
		await screen.findByText('Import successful');
		expect(fn.mock.calls.filter((c) => c[0].startsWith('/api/backup/import')).map((c) => c[1]?.body)).toEqual([B]);
	});

	it("shows the daemon's warning about left-out acknowledgements before Apply", async () => {
		const warning = 'This backup leaves out 12 alert acknowledgements. Restoring replaces this NetTap\'s acknowledgements with the 30 it carries.';
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ...VALID, warnings: [warning] }) })));
		const { container } = render(Page);
		await fireEvent.change(input(container), { target: { files: [new File(['{}'], 'n.json')] } });

		expect(await screen.findByText(warning)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Apply configuration' })).toBeEnabled();
	});

	it("shows the daemon's 413 when the restore is over the limit", async () => {
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 413, json: async () => ({ error: 'This file is over the 16 MB restore limit.' }) })));
		const { container } = render(Page);
		await fireEvent.change(input(container), { target: { files: [new File(['{}'], 'n.json')] } });

		expect(await screen.findByText('This file is over the 16 MB restore limit.')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Apply configuration' })).not.toBeInTheDocument();
	});

	describe('export', () => {
		function exportAnswers(response: Response) {
			vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }));
			vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
			vi.stubGlobal('fetch', vi.fn(async () => response));
		}

		it('says which acknowledgements a saved backup left out', async () => {
			exportAnswers(new Response('{"metadata":{"acknowledgements_left_out":46000},"sections":{}}', { status: 200 }));
			render(Page);
			await fireEvent.click(screen.getByRole('button', { name: 'Export configuration' }));

			expect(
				await screen.findByText(
					'Backup saved. It leaves out the 46,000 oldest alert acknowledgements to stay under the 16 MB restore limit; after a restore those alerts show as not acknowledged.',
				),
			).toBeInTheDocument();
		});

		it('says plainly that it saved when nothing was left out', async () => {
			exportAnswers(new Response('{"metadata":{},"sections":{}}', { status: 200 }));
			render(Page);
			await fireEvent.click(screen.getByRole('button', { name: 'Export configuration' }));

			expect(await screen.findByText('Configuration exported successfully')).toBeInTheDocument();
			expect(screen.queryByText(/leaves out/)).not.toBeInTheDocument();
		});

		it("shows the daemon's refusal as it wrote it", async () => {
			const error = 'A backup is already being made. Try again in a moment.';
			exportAnswers(new Response(JSON.stringify({ error }), { status: 503, headers: { 'Retry-After': '30' } }));
			render(Page);
			await fireEvent.click(screen.getByRole('button', { name: 'Export configuration' }));

			expect(await screen.findByRole('alert')).toHaveTextContent(error);
		});
	});
});
