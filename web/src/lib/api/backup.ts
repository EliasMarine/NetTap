/**
 * Client-side API helpers for config backup/restore endpoints.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BackupMetadata {
	nettap_version: string;
	schema_version: number;
	exported_at: string;
}

export interface BackupConfig {
	metadata: BackupMetadata;
	sections: Record<string, unknown>;
}

export interface ValidationResult {
	is_valid: boolean;
	warnings: string[];
	errors: string[];
	preview: Record<string, { type: string; size: number }>;
	/** A9: the backup's capture mode differs from this box's, so restoring it restarts capture */
	capture_restart?: boolean;
}

export interface ImportResult {
	success: boolean;
	applied: string[];
	/** A9: sections left as they were, and why */
	skipped?: { section: string; reason: string }[];
	errors: string[];
	warnings: string[];
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

// OLD CODE START — NET-344: the tab downloads through downloadConfigFile, which saves the daemon's exact bytes
// /**
//  * Export all configuration as JSON.
//  */
// export async function exportConfig(): Promise<BackupConfig> {
// 	const res = await fetch('/api/backup/export');
//
// 	if (!res.ok) {
// 		throw new Error(`Export failed: ${res.status}`);
// 	}
//
// 	return res.json();
// }
// OLD CODE END

/**
 * NET-344: a body restores only when its UTF-8 length is under 16 MiB; the daemon refuses a body
 * of exactly `client_max_size` bytes.
 */
export const RESTORE_LIMIT_BYTES = 16 * 1024 * 1024;

const utf8Length = (text: string): number => new TextEncoder().encode(text).length;

/**
 * Download the exported config as a file, byte for byte as the daemon made it (NET-344), so the
 * size it was fitted to is the size that restores. `leftOut` counts the oldest alert
 * acknowledgements the daemon trimmed to fit.
 */
// OLD CODE START — NET-344: parsed and pretty-printed the export, which could push it over the restore limit
// export async function downloadConfigFile(): Promise<void> {
// 	const config = await exportConfig();
// 	const blob = new Blob([JSON.stringify(config, null, 2)], {
// 		type: 'application/json',
// 	});
// 	const url = URL.createObjectURL(blob);
// 	const a = document.createElement('a');
// 	a.href = url;
// 	a.download = `nettap-config-${new Date().toISOString().slice(0, 10)}.json`;
// 	a.click();
// 	URL.revokeObjectURL(url);
// }
// OLD CODE END
export async function downloadConfigFile(): Promise<{ leftOut: number }> {
	const res = await fetch('/api/backup/export');
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw new Error(body.error || `Export failed: ${res.status}`);
	}

	const blob = await res.blob();
	// Parsed before it is offered, so a reply that isn't a backup is never saved as one
	const leftOut: number = JSON.parse(await blob.text()).metadata?.acknowledgements_left_out ?? 0;
	const named = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') ?? '')?.[1];
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = named ?? `nettap-config-${new Date().toISOString().slice(0, 10)}.json`;
	a.click();
	URL.revokeObjectURL(url);
	return { leftOut };
}

/**
 * The body validate and import both send for one selected file (NET-344): the file's own text when
 * it fits, else the compacted JSON (an older pretty-printed backup), else a refusal naming the size.
 */
export function restoreBody(text: string, data: unknown): string {
	const size = utf8Length(text);
	if (size < RESTORE_LIMIT_BYTES) return text;
	const compact = JSON.stringify(data);
	if (utf8Length(compact) < RESTORE_LIMIT_BYTES) return compact;
	throw new Error(`This file is ${(size / 1_000_000).toFixed(1)} MB, over the 16 MB restore limit.`);
}

/**
 * Validate a config file without applying. `body` is sent unchanged (see `restoreBody`).
 */
// OLD CODE: export async function validateConfig(data: unknown): Promise<ValidationResult> { (NET-344: sent JSON.stringify(data))
export async function validateConfig(body: string): Promise<ValidationResult> {
	const res = await fetch('/api/backup/validate', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body,
	});

	if (!res.ok) {
		// OLD CODE: throw new Error(`Validation failed: ${res.status}`); (NET-344: the daemon's 413 says why)
		const reply = await res.json().catch(() => ({}));
		throw new Error(reply.error || `Validation failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Import and apply a config file. The capture mode is restored only with `applyCapture`,
 * because it restarts the capture containers (A9).
 */
// OLD CODE: export async function importConfig(data: unknown): Promise<ImportResult> {
// OLD CODE: export async function importConfig(data: unknown, applyCapture = false): Promise<ImportResult> { (NET-344: sent JSON.stringify(data))
export async function importConfig(body: string, applyCapture = false): Promise<ImportResult> {
	// OLD CODE: const res = await fetch('/api/backup/import', {
	const res = await fetch(`/api/backup/import${applyCapture ? '?apply_capture=1' : ''}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body,
	});

	// OLD CODE START — #96: a 500 `{error}` body was returned as an ImportResult with no
	// success/errors fields, which broke the page and hid the reason
	// return res.json();
	// OLD CODE END
	const result = await res.json().catch(() => ({}));
	// A 400 carries a real ImportResult (rejected sections); anything else without one is a failure
	if (!res.ok && typeof result.success !== 'boolean') {
		throw new Error(result.error || `Config import failed: HTTP ${res.status}`);
	}
	return result;
}

/**
 * Read a file from a File input: its text, kept for the upload (NET-344), and the parsed JSON.
 */
// OLD CODE: export async function readConfigFile(file: File): Promise<unknown> { (NET-344: the text was thrown away)
export async function readConfigFile(file: File): Promise<{ text: string; data: unknown }> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => {
			try {
				const text = reader.result as string;
				// OLD CODE: resolve(JSON.parse(reader.result as string));
				resolve({ text, data: JSON.parse(text) });
			} catch {
				reject(new Error('Invalid JSON file'));
			}
		};
		reader.onerror = () => reject(new Error('Failed to read file'));
		reader.readAsText(file);
	});
}
