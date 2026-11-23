import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * writeFileDurably (NET-358) against real files, with a pass-through `fs` that logs each step and can
 * fail any one of them: open, write, fsync and rename, for the temp file or the folder.
 */

type Step = 'open' | 'write' | 'fsync' | 'close' | 'rename';
const faults = vi.hoisted(() => ({
	log: [] as [string, string][],
	fail: null as null | ((step: string, path: string) => string | null),
	fdPaths: new Map<number, string>(),
}));

vi.mock('fs', async (importOriginal) => {
	const real = await importOriginal<typeof import('fs')>();
	const step = (name: string, path: string) => {
		faults.log.push([name, path]);
		const code = faults.fail?.(name, path);
		if (code) throw Object.assign(new Error(`injected ${name} failure`), { code });
	};
	const pathOf = (fd: number) => faults.fdPaths.get(fd) ?? `fd:${fd}`;
	const mocked = {
		...real,
		openSync: (path: string, ...rest: unknown[]) => {
			step('open', path);
			const fd = (real.openSync as (...a: unknown[]) => number)(path, ...rest);
			faults.fdPaths.set(fd, path);
			return fd;
		},
		writeFileSync: (file: unknown, ...rest: unknown[]) => {
			if (typeof file === 'number') step('write', pathOf(file));
			(real.writeFileSync as (...a: unknown[]) => void)(file, ...rest);
		},
		fsyncSync: (fd: number) => {
			step('fsync', pathOf(fd));
			real.fsyncSync(fd);
		},
		closeSync: (fd: number) => {
			step('close', pathOf(fd));
			real.closeSync(fd);
		},
		renameSync: (from: string, to: string) => {
			step('rename', to);
			real.renameSync(from, to);
		},
	};
	return { ...mocked, default: mocked };
});

import { writeFileDurably } from './durable-write';

let dir: string;
let file: string;
const tmp = () => `${file}.tmp`;
const failAt = (step: Step, path: () => string, code = 'EIO') => {
	faults.fail = (s, p) => (s === step && p === path() ? code : null);
};

beforeEach(() => {
	dir = mkdtempSync(join(tmpdir(), 'nettap-durable-'));
	file = join(dir, 'users.json');
	writeFileSync(file, 'old');
	faults.log = [];
	faults.fail = null;
});

afterEach(() => {
	vi.restoreAllMocks();
	rmSync(dir, { recursive: true, force: true });
});

describe('writeFileDurably', () => {
	it('writes a fresh 0600 temp file, fsyncs it, renames it over the file, then fsyncs the folder', () => {
		expect(writeFileDurably(file, 'new')).toEqual({ durable: true });

		expect(readFileSync(file, 'utf-8')).toBe('new');
		expect(statSync(file).mode & 0o777).toBe(0o600);
		expect(existsSync(tmp())).toBe(false);
		expect(faults.log).toEqual([
			['open', tmp()],
			['write', tmp()],
			['fsync', tmp()],
			['close', tmp()],
			['rename', file],
			['open', dir],
			['fsync', dir],
			['close', dir],
		]);
	});

	it('replaces a stale temp file left by a crash', () => {
		writeFileSync(tmp(), 'half-written');
		expect(writeFileDurably(file, 'new')).toEqual({ durable: true });
		expect(readFileSync(file, 'utf-8')).toBe('new');
	});

	// `opened`: the temp file's descriptor exists by then, so it must have been closed
	it.each<[Step, () => string, boolean]>([
		['open', tmp, false],
		['write', tmp, true],
		['fsync', tmp, true],
		['rename', () => file, true],
	])('throws and leaves the file as it was when %s fails before the rename', (step, path, opened) => {
		failAt(step, path);

		expect(() => writeFileDurably(file, 'new')).toThrow(`injected ${step} failure`);

		expect(readFileSync(file, 'utf-8')).toBe('old');
		expect(existsSync(tmp())).toBe(false);
		expect(faults.log.filter(([s, p]) => s === 'close' && p === tmp())).toHaveLength(opened ? 1 : 0);
	});

	it('answers durable: false, with the new contents live, when the folder fsync fails', () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		failAt('fsync', () => dir);

		expect(writeFileDurably(file, 'new')).toEqual({ durable: false });

		expect(readFileSync(file, 'utf-8')).toBe('new');
		expect(logged).toHaveBeenCalledWith(expect.stringContaining("couldn't confirm it reached the disk (EIO)"));
		// both descriptors closed: the temp file's, and the folder's despite its failed fsync
		expect(faults.log).toContainEqual(['close', tmp()]);
		expect(faults.log).toContainEqual(['close', dir]);
	});

	it('answers durable: false when the folder cannot be opened for its fsync', () => {
		vi.spyOn(console, 'error').mockImplementation(() => {});
		failAt('open', () => dir, 'EACCES');
		expect(writeFileDurably(file, 'new')).toEqual({ durable: false });
		expect(readFileSync(file, 'utf-8')).toBe('new');
	});

	it.each(['EISDIR', 'EPERM', 'EINVAL'])('skips the folder fsync with a warning where the platform refuses it (%s)', (code) => {
		const warned = vi.spyOn(console, 'warn').mockImplementation(() => {});
		failAt('fsync', () => dir, code);

		expect(writeFileDurably(file, 'new')).toEqual({ durable: true });
		expect(warned).toHaveBeenCalledTimes(1);
	});

	it('throws when the folder does not exist, and writes nothing', () => {
		const missing = join(dir, 'gone', 'users.json');
		expect(() => writeFileDurably(missing, 'new')).toThrow();
		expect(existsSync(join(dir, 'gone'))).toBe(false);
	});
});
