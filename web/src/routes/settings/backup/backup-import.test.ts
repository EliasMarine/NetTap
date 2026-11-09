import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh } from '$lib/stores/pageRefresh';
import Page from './+page.svelte';

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

	it('says what a backup leaves out', () => {
		stub({}, RESULT);
		render(Page);
		expect(screen.getByText(/Left out: passwords, API keys and tokens/)).toBeInTheDocument();
	});
});
