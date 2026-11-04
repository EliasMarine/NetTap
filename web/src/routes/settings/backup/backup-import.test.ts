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
