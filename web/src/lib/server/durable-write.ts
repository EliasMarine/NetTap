import { closeSync, fsyncSync, openSync, renameSync, rmSync, writeFileSync } from 'fs';
import { dirname } from 'path';

/** Platforms that refuse an fsync on a directory say so with one of these; nothing to confirm there. */
const DIR_FSYNC_UNSUPPORTED = new Set(['EISDIR', 'EPERM', 'EINVAL']);

function errorCode(err: unknown): string | undefined {
	return (err as NodeJS.ErrnoException | null)?.code;
}

/** Flush the directory entry, so a rename in it survives a power cut. */
function syncDirectory(dir: string): void {
	let fd: number | undefined;
	try {
		fd = openSync(dir, 'r');
		fsyncSync(fd);
	} catch (err) {
		if (!DIR_FSYNC_UNSUPPORTED.has(errorCode(err) ?? '')) throw err;
		console.warn(`This platform can't flush the folder ${dir} (${errorCode(err)}); writes there may not survive a power cut.`);
	} finally {
		if (fd !== undefined) closeSync(fd);
	}
}

/**
 * Replace `file` with `contents`, readable by this user only (0600), the way
 * daemon/services/report_schedule.py does it (NET-358): a fresh temp file in the same folder,
 * written and fsynced, renamed over `file`, then the folder fsynced.
 *
 * A failure before the rename throws and leaves `file` as it was. Once the rename is done the new
 * contents are live, so a failed folder fsync doesn't throw: it logs and answers `durable: false`
 * (the change may not survive a power cut).
 */
export function writeFileDurably(file: string, contents: string): { durable: boolean } {
	const tmp = `${file}.tmp`;
	rmSync(tmp, { force: true });
	const fd = openSync(tmp, 'wx', 0o600);
	try {
		try {
			writeFileSync(fd, contents, 'utf-8');
			fsyncSync(fd);
		} finally {
			closeSync(fd);
		}
		renameSync(tmp, file);
	} catch (err) {
		rmSync(tmp, { force: true });
		throw err;
	}
	try {
		syncDirectory(dirname(file));
	} catch (err) {
		console.error(`Saved ${file}, but couldn't confirm it reached the disk (${errorCode(err) ?? 'unknown error'}).`);
		return { durable: false };
	}
	return { durable: true };
}
