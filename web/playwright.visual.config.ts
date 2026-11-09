/**
 * Visual harness (PLAN.md §5.2): the production build against a fixture daemon.
 * Run with `npm run test:visual`. The existing playwright.config.ts is separate and unchanged.
 */
import { defineConfig, devices } from '@playwright/test';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';

const DAEMON_PORT = 3199;
const BUILD_COPY = '.visual-build';
export const DAEMON_URL = `http://127.0.0.1:${DAEMON_PORT}`;
export const APP_URL = 'http://127.0.0.1:3101';
export const FIRSTRUN_URL = 'http://127.0.0.1:3102';

// webServer entries start before globalSetup, so the temp dirs are made here, at config load.
// Workers load this module too; they inherit the env var and reuse the same root and token.
if (!process.env.NETTAP_VISUAL_TMP) {
	process.env.NETTAP_VISUAL_TMP = mkdtempSync(path.join(os.tmpdir(), 'nettap-visual-'));
	writeFileSync(path.join(process.env.NETTAP_VISUAL_TMP, 'daemon-token'), randomBytes(24).toString('hex'), {
		mode: 0o600,
	});
}
const root = process.env.NETTAP_VISUAL_TMP;
const tokenFile = path.join(root, 'daemon-token');
/** The signed-in session saved by auth.setup.ts; removed with the temp root. */
export const STORAGE_STATE = path.join(root, 'storage-state.json');
/** The `app` instance's DATA_DIR; auth.setup.ts reads its first-run setup code there (NET-229). */
export const APP_DATA_DIR = path.join(root, 'app', 'data');
/** The `firstrun` instance's DATA_DIR; firstrun.visual.ts reads its setup code there to open Go Live. */
export const FIRSTRUN_DATA_DIR = path.join(root, 'firstrun', 'data');

function instanceEnv(name: string, origin: string): Record<string, string> {
	const dataDir = path.join(root, name, 'data');
	const nettapDataDir = path.join(root, name, 'nettap');
	mkdirSync(dataDir, { recursive: true });
	mkdirSync(nettapDataDir, { recursive: true });
	return {
		HOST: '127.0.0.1',
		PORT: new URL(origin).port,
		ORIGIN: origin,
		DATA_DIR: dataDir,
		NETTAP_DATA_DIR: nettapDataDir,
		DAEMON_URL,
		DAEMON_TOKEN_FILE: tokenFile,
	};
}

export default defineConfig({
	testDir: './e2e/visual',
	outputDir: 'test-results/visual',
	workers: 1,
	fullyParallel: false,
	forbidOnly: !!process.env.CI,
	reporter: 'list',
	timeout: 120_000,
	globalTeardown: './e2e/visual/global-teardown.ts',
	// No traces by default: the screenshots are the output, and ~80 soft-failing tests each saving a
	// trace hung one test's teardown (ENOENT on the artifact zip). Debug with --trace on.
	// OLD CODE: use: { ...devices['Desktop Chrome'], baseURL: APP_URL, trace: 'off' },
	// Headless Chromium has no WebGL 2 unless software rendering is allowed: the Live globe (NET-207) must really
	// start here, so its test fails on a fallback instead of passing on the flat map.
	use: {
		...devices['Desktop Chrome'],
		baseURL: APP_URL,
		trace: 'off',
		launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
	},
	// Playwright starts these one at a time, each after the previous `url` answers,
	// so `firstrun` (no build) starts only once `app` has built and is serving.
	webServer: [
		{
			command: 'node --experimental-strip-types --disable-warning=ExperimentalWarning e2e/visual/fixture-daemon.ts',
			url: `${DAEMON_URL}/__fixture/health`,
			env: { FIXTURE_DAEMON_PORT: String(DAEMON_PORT), DAEMON_TOKEN_FILE: tokenFile },
			reuseExistingServer: false,
			stdout: 'pipe',
			stderr: 'pipe',
		},
		{
			// --logLevel error: the build's a11y and unused-CSS warnings would bury test output.
			// Served from a private copy: any `npm run build` elsewhere replaces build/ mid-run and
			// crashed the server (ERR_MODULE_NOT_FOUND). The copy stays under web/ so node_modules resolves,
			// and outside test-results/, which any other Playwright run empties when it starts.
			command: `npm run build -- --logLevel error && rm -rf ${BUILD_COPY} && cp -R build ${BUILD_COPY} && node ${BUILD_COPY}`,
			url: `${APP_URL}/login`,
			env: instanceEnv('app', APP_URL),
			reuseExistingServer: false,
			timeout: 240_000,
		},
		{
			command: `node ${BUILD_COPY}`,
			url: `${FIRSTRUN_URL}/login`,
			env: instanceEnv('firstrun', FIRSTRUN_URL),
			reuseExistingServer: false,
		},
	],
	projects: [
		{ name: 'auth-setup', testMatch: '**/auth.setup.ts' },
		{
			name: 'app',
			testMatch: '**/*.visual.ts',
			testIgnore: '**/firstrun.visual.ts',
			dependencies: ['auth-setup'],
			use: { storageState: STORAGE_STATE },
		},
		{
			name: 'reduced-motion',
			testMatch: ['**/routes.visual.ts', '**/live.visual.ts'],
			dependencies: ['auth-setup'],
			use: { storageState: STORAGE_STATE, contextOptions: { reducedMotion: 'reduce' } },
		},
		{
			name: 'firstrun',
			testMatch: '**/firstrun.visual.ts',
			use: { baseURL: FIRSTRUN_URL },
		},
		// `npm run capture:media` only: rewrites the README media in .github/assets/media/.
		// Headed, on the real GPU: under SwiftShader the globe is too slow to record and never starts.
		...(process.env.NETTAP_CAPTURE_MEDIA
			? [
					{
						name: 'media',
						testMatch: '**/media.capture.spec.ts',
						dependencies: ['auth-setup'],
						use: { storageState: STORAGE_STATE, headless: false, launchOptions: { args: ['--hide-scrollbars'] } },
					},
				]
			: []),
	],
});
