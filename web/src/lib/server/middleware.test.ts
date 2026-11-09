/** The first-run setup cookie helpers (NET-229 follow-up), against the real auth module. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import type { RequestEvent } from '@sveltejs/kit';

let dataDir: string;

function eventWith(setupCookie?: string) {
	const cookies = {
		get: vi.fn((name: string) => (name === 'nettap_setup' ? setupCookie : undefined)),
		set: vi.fn(),
		delete: vi.fn(),
	};
	return { event: { cookies } as unknown as RequestEvent, cookies };
}

beforeEach(() => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-middleware-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', 'middleware-test-secret');
	vi.resetModules();
});

afterEach(() => {
	vi.unstubAllEnvs();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('setup cookie', () => {
	it('is httpOnly, lax and site-wide, and only the current token passes', async () => {
		const auth = await import('./auth.js');
		const { setSetupCookie, hasSetupCookie, clearSetupCookie } = await import('./middleware.js');
		const token = auth.setupToken() ?? '';

		const { event, cookies } = eventWith();
		setSetupCookie(event, token);
		expect(cookies.set).toHaveBeenCalledWith('nettap_setup', token, expect.objectContaining({ httpOnly: true, sameSite: 'lax', path: '/' }));

		expect(hasSetupCookie(eventWith(token).event)).toBe(true);
		expect(hasSetupCookie(eventWith(`${token}x`).event)).toBe(false);
		expect(hasSetupCookie(eventWith().event)).toBe(false);

		clearSetupCookie(event);
		expect(cookies.delete).toHaveBeenCalledWith('nettap_setup', { path: '/' });
	});
});
