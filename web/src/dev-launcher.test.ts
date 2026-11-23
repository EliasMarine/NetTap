import { describe, it, expect, afterEach } from 'vitest';
import { spawnSync } from 'child_process';
import { createHash } from 'crypto';
import { chmodSync, existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from 'fs';
import { homedir, tmpdir } from 'os';
import { basename, dirname, join, resolve } from 'path';
import { devDataDir } from '../scripts/dev.mjs';

/**
 * `npm run dev` (NET-358) gives each checkout a private data folder outside the repository; an
 * explicit DATA_DIR wins. The subprocess tests run scripts/dev.mjs with a stand-in `vite` first on
 * PATH that records what it was started with, or with no vite on PATH at all.
 */

const WEB_DIR = resolve(__dirname, '..');
const LAUNCHER = join(WEB_DIR, 'scripts', 'dev.mjs');
const temps: string[] = [];

function temp(prefix: string): string {
	const dir = realpathSync(mkdtempSync(join(tmpdir(), prefix)));
	temps.push(dir);
	return dir;
}

afterEach(() => {
	for (const dir of temps.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/** Run the launcher from `cwd` with `PATH` (by absolute path to node, so PATH only decides which vite starts). */
function run(cwd: string, home: string, path: string, env: Record<string, string> = {}) {
	return spawnSync(process.execPath, [LAUNCHER, '--port', '4321'], { cwd, env: { PATH: path, HOME: home, ...env }, encoding: 'utf-8' });
}

/** Run the launcher with a stand-in `vite` first on PATH; returns its exit code and what vite received. */
function launch(cwd: string, home: string, env: Record<string, string> = {}) {
	const tools = temp('nettap-dev-vite-');
	const out = join(tools, 'seen.json');
	const vite = join(tools, 'vite');
	writeFileSync(
		vite,
		`#!/usr/bin/env node\nrequire('fs').writeFileSync(${JSON.stringify(out)}, JSON.stringify({ args: process.argv.slice(2), dataDir: process.env.DATA_DIR }));\nprocess.exit(3);\n`
	);
	chmodSync(vite, 0o755);
	// first on PATH, ahead of the project's real vite (npx puts node_modules/.bin on PATH)
	const result = run(cwd, home, `${tools}:${dirname(process.execPath)}:${process.env.PATH ?? ''}`, env);
	return { status: result.status, stderr: result.stderr, seen: JSON.parse(readFileSync(out, 'utf-8')) };
}

describe('devDataDir', () => {
	it('gives two checkouts two folders under the home folder, outside the repository', () => {
		const a = devDataDir(temp('nettap-checkout-a-'));
		const b = devDataDir(temp('nettap-checkout-b-'));

		expect(a).not.toBe(b);
		for (const dir of [a, b]) {
			expect(dirname(dir)).toBe(join(homedir(), '.nettap-web-dev'));
			expect(basename(dir)).toMatch(/^[0-9a-f]{12}$/);
			expect(dir.startsWith(WEB_DIR)).toBe(false);
		}
	});

	it('is the same for a checkout and a symlink to it', () => {
		const dir = temp('nettap-checkout-');
		const link = join(temp('nettap-links-'), 'checkout');
		symlinkSync(dir, link);
		expect(devDataDir(link)).toBe(devDataDir(dir));
	});
});

describe('scripts/dev.mjs', () => {
	it('starts vite dev with the private folder and the forwarded arguments, and exits with its code', () => {
		const home = temp('nettap-dev-home-');
		const checkout = temp('nettap-checkout-');

		const { status, seen } = launch(checkout, home);

		const id = createHash('sha256').update(checkout).digest('hex').slice(0, 12);
		const expected = join(home, '.nettap-web-dev', id);
		expect(seen).toEqual({ args: ['dev', '--port', '4321'], dataDir: expected });
		expect(statSync(expected).mode & 0o777).toBe(0o700);
		expect(status).toBe(3);
	});

	it('keeps an explicit DATA_DIR and makes no folder of its own', () => {
		const home = temp('nettap-dev-home-');
		const own = temp('nettap-own-data-');

		const { seen } = launch(temp('nettap-checkout-'), home, { DATA_DIR: own });

		expect(seen.dataDir).toBe(own);
		expect(existsSync(join(home, '.nettap-web-dev'))).toBe(false);
	});

	it('exits 1 with a plain message when there is no vite to start', () => {
		const result = run(temp('nettap-checkout-'), temp('nettap-dev-home-'), temp('nettap-empty-path-'));

		expect(result.status).toBe(1);
		expect(result.stderr).toMatch(/^Couldn't start vite: spawn vite ENOENT\n$/);
	});
});
