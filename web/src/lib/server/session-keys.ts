import { existsSync, mkdirSync, readFileSync } from 'fs';
import { randomBytes } from 'crypto';
import { DATA_DIR } from './data-dir.js';
import { writeFileDurably } from './durable-write.js';

/**
 * Session signing keys (NET-358, plan step 3a).
 *
 * Every NetTap from aa234d73 (March 2026) until this release signs and checks sessions with
 * jwt-secret.txt (or JWT_SECRET). This release never signs with either. It signs with
 * jwt-secret-v2.txt, and at every start it replaces jwt-secret.txt with a fresh key no session
 * was ever signed with. An older build started
 * after a downgrade (rollback script, pinned image or rebuilt commit) therefore trusts no session
 * from before it, so a session ended by a password change can't come back that way.
 */

/** The key every older build reads, trimmed (`readFileSync(…).trim()`). */
const LEGACY_KEY_FILE = `${DATA_DIR}/jwt-secret.txt`;
/** This release's key file: no older build reads it. */
const SESSION_KEY_FILE = `${DATA_DIR}/jwt-secret-v2.txt`;
// OLD CODE START — NET-358 review: no install sets NETTAP_SESSION_SECRET; it was unvalidated and its label was copied in mint-session.cjs
// /** Mixed into NETTAP_SESSION_SECRET, so the value an older build had as JWT_SECRET never signs the same way here. */
// const SESSION_KEY_LABEL = 'nettap-session-v2';
// OLD CODE END
/** 64 random bytes as lowercase hex with no newline, as the old writer stored jwt-secret.txt. */
const KEY_SHAPE = /^[0-9a-f]{128}$/;
const KEY_FIX = 'Delete it and restart nettap-web; everyone then signs in again.';

// OLD CODE: export const JWT_SECRET_WARNING = 'JWT_SECRET is set, but this NetTap no longer reads it. Remove it; set NETTAP_SESSION_SECRET instead if you need a fixed key.'; (NET-358 review: NETTAP_SESSION_SECRET is gone)
export const JWT_SECRET_WARNING = "JWT_SECRET is set, but this NetTap no longer reads it. Remove it from the web container's settings.";

let cachedKey: string | null = null;

function newKey(): string {
	return randomBytes(64).toString('hex');
}

/** No `durable: false` for keys: a key write that isn't confirmed on disk stops the start. */
function writeKey(file: string, key: string): void {
	if (!writeFileDurably(file, key).durable) {
		throw new Error(`Couldn't confirm ${file} reached the disk, so the web app won't start. Restart nettap-web to try again.`);
	}
}

/** jwt-secret-v2.txt's key, made only when the file doesn't exist. Anything else wrong with it throws. */
function fileKey(): string {
	let raw: string;
	try {
		raw = readFileSync(SESSION_KEY_FILE, 'utf-8');
	} catch (err) {
		const code = (err as NodeJS.ErrnoException).code;
		if (code !== 'ENOENT') throw new Error(`${SESSION_KEY_FILE} can't be read (${code ?? 'unknown error'}). ${KEY_FIX}`);
		const key = newKey();
		writeKey(SESSION_KEY_FILE, key);
		return key;
	}
	const key = raw.trim(); // as the old reader did
	if (!KEY_SHAPE.test(key)) throw new Error(`${SESSION_KEY_FILE} doesn't hold a valid session key. ${KEY_FIX}`);
	return key;
}

// OLD CODE: export function initSessionKeys(): void { (NET-358 review: it returns the key, so getJwtSecret needs no cast)
/**
 * Run at every start, before the first request (hooks.server.ts `init`): replace the legacy key,
 * make sure this release's key exists, and only then cache and return it. Any failure throws, so the
 * web app doesn't start (and its health check doesn't pass) on a half-done migration; a restart retries.
 * Keys are never logged.
 */
export function initSessionKeys(): string {
	cachedKey = null;
	if (process.env.JWT_SECRET) console.warn(JWT_SECRET_WARNING);
	if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
	writeKey(LEGACY_KEY_FILE, newKey());
	// OLD CODE START — NET-358 review: the NETTAP_SESSION_SECRET override is gone; only jwt-secret-v2.txt signs
	// const secret = process.env.NETTAP_SESSION_SECRET;
	// cachedKey = secret ? createHmac('sha256', secret).update(SESSION_KEY_LABEL).digest('hex') : fileKey();
	// OLD CODE END
	cachedKey = fileKey();
	return cachedKey;
}

/** The key sessions are signed with. `init` has set it before any request; a caller without it (a test) runs the start-up steps. */
export function getJwtSecret(): string {
	// OLD CODE: if (cachedKey === null) initSessionKeys(); return cachedKey as string; (NET-358 review: initSessionKeys returns the key)
	return cachedKey ?? initSessionKeys();
}

/** An older build would still trust sessions signed with JWT_SECRET, so a password change is refused while it is set. */
export function legacySecretInEnv(): boolean {
	return Boolean(process.env.JWT_SECRET);
}
