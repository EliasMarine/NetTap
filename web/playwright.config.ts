import { defineConfig, devices } from '@playwright/test';
import path from 'path';
import os from 'os';

/** Shared temp directory for E2E test data (auth users file, etc.).
 *  Must match the value imported by e2e/ test files. */
export const E2E_DATA_DIR = path.join(os.tmpdir(), 'nettap-e2e-data');

export default defineConfig({
	testDir: './e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 1 : undefined,
	reporter: 'html',
	use: {
		baseURL: 'http://localhost:3000',
		trace: 'on-first-retry',
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] },
		},
	],
	webServer: {
		command: 'npm run build && node build',
		url: 'http://localhost:3000',
		reuseExistingServer: !process.env.CI,
		timeout: 120_000,
		env: {
			DATA_DIR: E2E_DATA_DIR,
			ORIGIN: 'http://localhost:3000',
		},
	},
});
