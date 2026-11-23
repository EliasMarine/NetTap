'use strict';
// NET-358: a 60-second session for the deploy scripts' signed-in checks, signed inside nettap-web with
// the key the server signs with (session-keys.ts initSessionKeys). Run from the repository on the device:
//   sudo docker exec -i -w /app nettap-web node - < scripts/remote/mint-session.cjs
// -w /app lets require() find the app's jsonwebtoken. It prints only the token, for the first account
// in users.json, and never the key or a hash. web/src/lib/server/mint-session.test.ts checks that
// auth.ts verifyToken accepts what it prints.
// OLD CODE: const { createHash, createHmac } = require('crypto'); (NET-358 review: no NETTAP_SESSION_SECRET, so no HMAC)
const { createHash } = require('crypto');
const { readFileSync } = require('fs');

const KEY_SHAPE = /^[0-9a-f]{128}$/;

function fail(message) {
	process.stderr.write(`mint-session: ${message}\n`);
	process.exit(1);
}

// OLD CODE START — NET-358 review: the NETTAP_SESSION_SECRET override is gone from session-keys.ts
// /** The v2 key, read exactly as auth.ts reads it: NETTAP_SESSION_SECRET, else jwt-secret-v2.txt. */
// function sessionKey(dataDir) {
// 	if (process.env.NETTAP_SESSION_SECRET) {
// 		return createHmac('sha256', process.env.NETTAP_SESSION_SECRET).update('nettap-session-v2').digest('hex');
// 	}
// OLD CODE END
/** The v2 key, read exactly as session-keys.ts reads it: jwt-secret-v2.txt, trimmed. */
function sessionKey(dataDir) {
	const file = `${dataDir}/jwt-secret-v2.txt`;
	let key = '';
	try {
		key = readFileSync(file, 'utf-8').trim();
	} catch (err) {
		fail(`can't read ${file} (${err.code || 'unreadable'})`);
	}
	if (!KEY_SHAPE.test(key)) fail(`${file} isn't a 128-character hex key`);
	return key;
}

function firstAccount(dataDir) {
	const file = `${dataDir}/users.json`;
	let text = '';
	try {
		text = readFileSync(file, 'utf-8');
	} catch (err) {
		fail(err.code === 'ENOENT' ? `${file} has no account yet` : `can't read ${file} (${err.code || 'unreadable'})`);
	}
	let store;
	try {
		store = JSON.parse(text);
	} catch {
		fail(`${file} isn't valid JSON`); // not the parser's message: it can quote the file
	}
	const user = Array.isArray(store?.users) ? store.users[0] : undefined;
	if (!user || typeof user !== 'object') fail(`${file} has no account yet`);
	for (const field of ['username', 'passwordHash', 'role']) {
		if (typeof user[field] !== 'string' || !user[field]) fail(`the first account in ${file} has no ${field}`);
	}
	return user;
}

// Must match auth.ts passwordStamp: the session names the password it was issued against.
function passwordStamp(hash) {
	return createHash('sha256').update(hash).digest('base64url').slice(0, 22);
}

let jwt;
try {
	jwt = require('jsonwebtoken');
} catch {
	fail("jsonwebtoken isn't here: run this inside nettap-web with -w /app");
}

const dataDir = process.env.DATA_DIR || '/var/lib/nettap-web';
const user = firstAccount(dataDir);
const claims = { username: user.username, role: user.role, pwd: passwordStamp(user.passwordHash) };
process.stdout.write(jwt.sign(claims, sessionKey(dataDir), { algorithm: 'HS256', expiresIn: 60 }));
