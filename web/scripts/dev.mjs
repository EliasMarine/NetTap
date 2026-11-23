// `npm run dev` (NET-358): the dev server gets a private data folder for this checkout, outside the
// repository and its Docker build context, so dev users, session keys and setup codes never reach an
// image build, and two worktrees never share one user store. An explicit DATA_DIR wins.
// Only `npm run dev` runs this: preview, Vitest and builds keep data-dir.ts's default.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, realpathSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * The dev data folder for the checkout at `cwd`: ~/.nettap-web-dev/<first 12 hex of sha256(realpath)>.
 * @param {string} cwd
 * @returns {string}
 */
export function devDataDir(cwd) {
	const id = createHash('sha256').update(realpathSync(cwd)).digest('hex').slice(0, 12);
	return join(homedir(), '.nettap-web-dev', id);
}

function main() {
	const env = { ...process.env };
	if (!env.DATA_DIR) {
		env.DATA_DIR = devDataDir(process.cwd());
		mkdirSync(env.DATA_DIR, { recursive: true, mode: 0o700 });
	}
	// OLD CODE START — NET-358 review: a test-only setting in shipped code; the test puts a stand-in vite first on PATH instead
	// // NETTAP_DEV_VITE stands in for vite in the launcher's own test
	// const child = spawn(env.NETTAP_DEV_VITE || 'vite', ['dev', ...process.argv.slice(2)], { env, stdio: 'inherit' });
	// OLD CODE END
	const child = spawn('vite', ['dev', ...process.argv.slice(2)], { env, stdio: 'inherit' });
	for (const signal of /** @type {const} */ (['SIGINT', 'SIGTERM'])) {
		process.on(signal, () => child.kill(signal));
	}
	child.on('error', (err) => {
		console.error(`Couldn't start vite: ${err.message}`);
		process.exit(1);
	});
	child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) main();
