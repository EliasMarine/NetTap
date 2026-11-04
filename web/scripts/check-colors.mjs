#!/usr/bin/env node
/**
 * Colour gate: fails when web/src uses a colour literal outside the token block.
 * Rules: web/DESIGN-SYSTEM.md ("Colour gate"). Run: npm run check:colors
 *
 * Where it looks (so prose like "PR #147" or `white-space` never trips it):
 * - .css files, and <style> blocks in .svelte: the whole CSS
 * - .ts files, <script> blocks and Svelte markup: quoted strings only
 * What it skips: src/lib/styles/tokens.css (the design system's token file, the one
 * place literals live), test files, any TOKENS START/END block and comments. OLD CODE
 * blocks are comments, so they're skipped too; live code between the markers is
 * still checked.
 */
import { readFileSync, readdirSync, realpathSync, statSync } from 'node:fs';
import { join, relative, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC_DIR = join(WEB_DIR, 'src');
const ALLOWLIST_FILE = join(WEB_DIR, 'scripts', 'check-colors.allowlist');
const TOKEN_FILE = join(SRC_DIR, 'lib', 'styles', 'tokens.css');

const HEX = /(?<![\w&/])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g;
const FUNC = /\b(?:rgba?|hsla?)\(/g;
const NAMED_CSS = /(?<![-\w$.])(?:white|black)(?![-\w])/g;
const NAMED_STRING = /^(?:white|black)$/;
const NAMED_IN_STYLE = /(?<=:\s*)(?:white|black)(?![-\w])/g;
const STRING = /'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g;

/** Replace a region with spaces, keeping newlines so line numbers stay right. */
const blank = (/** @type {string} */ text) => text.replace(/[^\n]/g, ' ');

/** @param {string} text @param {RegExp} re */
function blankRegions(text, re) {
	return text.replace(re, (m) => blank(m));
}

/** Remove everything the gate must ignore, keeping offsets. @param {string} text */
export function stripIgnored(text) {
	let out = blankRegions(text, /\/\* TOKENS START \*\/[\s\S]*?\/\* TOKENS END \*\//g);
	out = blankRegions(out, /<!--[\s\S]*?-->/g);
	out = blankRegions(out, /\/\*[\s\S]*?\*\//g);
	// Line comments: `//` at line start or after whitespace/punctuation, never in `://`
	out = out.replace(/(^|[\s;{}(),])\/\/[^\n]*/gm, (/** @type {string} */ m, /** @type {string} */ lead) => lead + blank(m.slice(lead.length)));
	return out;
}

/** @param {string} text @param {number} index */
function lineOf(text, index) {
	let line = 1;
	for (let i = 0; i < index; i++) if (text.charCodeAt(i) === 10) line++;
	return line;
}

/** @typedef {{ index: number, match: string }} Hit */

/** @param {string} text @param {number} offset @param {Hit[]} out */
function scanCss(text, offset, out) {
	for (const re of [HEX, FUNC, NAMED_CSS]) {
		for (const m of text.matchAll(re)) out.push({ index: offset + m.index, match: m[0] });
	}
}

/** @param {string} text @param {number} offset @param {Hit[]} out */
function scanStrings(text, offset, out) {
	for (const s of text.matchAll(STRING)) {
		const body = s[0].slice(1, -1);
		const base = offset + s.index + 1;
		if (NAMED_STRING.test(body.trim())) out.push({ index: base, match: body });
		for (const re of [HEX, FUNC, NAMED_IN_STYLE]) {
			for (const m of body.matchAll(re)) out.push({ index: base + m.index, match: m[0] });
		}
	}
}

/**
 * Find colour literals in one file.
 * @param {string} path @param {string} source
 * @returns {{ line: number, match: string }[]}
 */
export function findColorLiterals(path, source) {
	const text = stripIgnored(source);
	/** @type {Hit[]} */
	const hits = [];

	if (path.endsWith('.css')) {
		scanCss(text, 0, hits);
	} else if (path.endsWith('.ts')) {
		scanStrings(text, 0, hits);
	} else if (path.endsWith('.svelte')) {
		let rest = text;
		for (const m of text.matchAll(/(<style[^>]*>)([\s\S]*?)<\/style>/g)) {
			const start = m.index + m[1].length;
			scanCss(m[2], start, hits);
			rest = rest.slice(0, m.index) + blank(m[0]) + rest.slice(m.index + m[0].length);
		}
		scanStrings(rest, 0, hits);
	}

	// `colour-gate: allow-next-line <reason>` exempts one line, for output that can never
	// read CSS variables (for example email HTML). Every use must give its reason.
	const lines = source.split('\n');
	const exempt = new Set();
	lines.forEach((/** @type {string} */ l, /** @type {number} */ i) => {
		if (/colour-gate: allow-next-line \S/.test(l)) exempt.add(i + 2);
	});

	return hits
		.sort((a, b) => a.index - b.index)
		.map((h) => ({ line: lineOf(source, h.index), match: h.match }))
		.filter((h) => !exempt.has(h.line));
}

const isTest = (/** @type {string} */ p) =>
	/\.(test|spec)\.(ts|js)$/.test(p) || relative(SRC_DIR, p).startsWith('tests/');

/** @param {string} dir @param {string[]} [files] @returns {string[]} */
function walk(dir, files = []) {
	for (const name of readdirSync(dir)) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) walk(full, files);
		else if (/\.(svelte|ts|css)$/.test(name) && !isTest(full)) files.push(full);
	}
	return files;
}

function readAllowlist() {
	try {
		return new Set(
			readFileSync(ALLOWLIST_FILE, 'utf8')
				.split('\n')
				.map((l) => l.replace(/#.*$/, '').trim())
				.filter(Boolean),
		);
	} catch {
		return new Set();
	}
}

function main() {
	const allow = readAllowlist();
	let count = 0;
	for (const file of walk(SRC_DIR)) {
		const rel = relative(WEB_DIR, file);
		if (allow.has(rel) || file === TOKEN_FILE) continue;
		for (const hit of findColorLiterals(file, readFileSync(file, 'utf8'))) {
			console.error(`${rel}:${hit.line}: ${hit.match}`);
			count++;
		}
	}
	if (count > 0) {
		console.error(`\n${count} colour literal(s) outside the token block. Use a token: see web/DESIGN-SYSTEM.md.`);
		process.exit(1);
	}
	console.log(`Colour gate: clean (${allow.size} file(s) allowlisted).`);
}

// realpath on both sides, so running it through a symlink still runs it
if (process.argv[1] && realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1])) main();
