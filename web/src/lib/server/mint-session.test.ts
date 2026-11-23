// @vitest-environment node
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { spawnSync } from 'child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join, resolve } from 'path';
import jwt from 'jsonwebtoken';

/**
 * scripts/remote/mint-session.cjs (NET-358) signs the deploy scripts' 60-second sessions with its own
 * copy of the key lookup and the password stamp. It runs here the way the scripts run it (node reading
 * stdin, from the app folder so require finds jsonwebtoken) against a temp DATA_DIR and the real
 * auth module, so the two copies can't drift apart silently.
 */

const MINT = resolve(process.cwd(), '../scripts/remote/mint-session.cjs');
const USERS = () => join(dataDir, 'users.json');

let dataDir: string;
let auth: typeof import('$lib/server/auth.js');

/** Only PATH and DATA_DIR (plus `env`) reach the script, so the developer's own settings can't. */
function mint(env: Record<string, string> = {}) {
	return spawnSync(process.execPath, ['-'], {
		input: readFileSync(MINT),
		cwd: process.cwd(),
		env: { PATH: process.env.PATH ?? '', DATA_DIR: dataDir, ...env },
		encoding: 'utf-8',
	});
}

async function writeOwner(): Promise<string> {
	const passwordHash = await auth.hashPassword('Passw0rdOK');
	const now = new Date().toISOString();
	const owner = { username: 'owner', passwordHash, role: 'admin', createdAt: now, updatedAt: now };
	writeFileSync(USERS(), JSON.stringify({ users: [owner] }));
	return passwordHash;
}

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-mint-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', undefined);
	vi.resetModules();
	auth = await import('$lib/server/auth.js');
});

afterEach(() => {
	vi.unstubAllEnvs();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('mint-session.cjs', () => {
	it('prints only a 60 s session that verifyToken accepts, signed with jwt-secret-v2.txt', async () => {
		auth.initSessionKeys();
		const hash = await writeOwner();
		const run = mint();
		expect(run.stderr).toBe('');
		expect(run.status).toBe(0);
		expect(auth.verifyToken(run.stdout)).toEqual({ username: 'owner', role: 'admin' });
		const claims = jwt.decode(run.stdout) as jwt.JwtPayload;
		expect(Object.keys(claims).sort()).toEqual(['exp', 'iat', 'pwd', 'role', 'username']);
		expect(claims.pwd).toBe(auth.passwordStamp(hash));
		expect((claims.exp ?? 0) - (claims.iat ?? 0)).toBe(60);
		expect(run.stdout).not.toContain(readFileSync(join(dataDir, 'jwt-secret-v2.txt'), 'utf-8').trim());
	});

	it.each([
		['users.json is missing', null],
		['users.json holds no account', '{"users":[]}'],
	])('fails with a plain message and no token when %s', (_, store) => {
		auth.initSessionKeys();
		if (store !== null) writeFileSync(USERS(), store);
		const run = mint();
		expect(run.status).toBe(1);
		expect(run.stdout).toBe('');
		expect(run.stderr).toMatch(/^mint-session: .*users\.json has no account yet\n$/);
	});

	it("refuses a key file that isn't 128 hex characters instead of signing with it", async () => {
		auth.initSessionKeys();
		await writeOwner();
		writeFileSync(join(dataDir, 'jwt-secret-v2.txt'), 'abc123');
		const run = mint();
		expect(run.status).toBe(1);
		expect(run.stdout).toBe('');
		expect(run.stderr).toContain("isn't a 128-character hex key");
	});
});
