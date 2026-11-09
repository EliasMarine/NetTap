// @vitest-environment node
/** The `media` project (`npm run capture:media`) opens a headed browser and rewrites .github/assets/media/:
 * a plain `npm run test:visual`, or CI, must never include it. */
import { afterAll, afterEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// The config makes its temp dirs at load, under NETTAP_VISUAL_TMP: point it at one this test removes.
const root = mkdtempSync(path.join(os.tmpdir(), 'nettap-visual-config-test-'));

async function loadProjects(captureMedia: string) {
	vi.resetModules();
	vi.stubEnv('NETTAP_VISUAL_TMP', root);
	vi.stubEnv('NETTAP_CAPTURE_MEDIA', captureMedia);
	const { default: config } = await import('./playwright.visual.config.ts');
	return config.projects ?? [];
}

afterEach(() => vi.unstubAllEnvs());
afterAll(() => rmSync(root, { recursive: true, force: true }));

describe('playwright.visual.config media project', () => {
	it('is absent from a plain visual run', async () => {
		const projects = await loadProjects('');
		expect(projects.map((p) => p.name)).not.toContain('media');
	});

	it('exists under NETTAP_CAPTURE_MEDIA: signed in, headed, and only the capture spec', async () => {
		const media = (await loadProjects('1')).find((p) => p.name === 'media');
		expect(media).toMatchObject({
			testMatch: '**/media.capture.spec.ts',
			dependencies: ['auth-setup'],
			use: { headless: false },
		});
	});
});
