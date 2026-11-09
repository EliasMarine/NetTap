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

/**
 * Export all configuration as JSON.
 */
export async function exportConfig(): Promise<BackupConfig> {
	const res = await fetch('/api/backup/export');

	if (!res.ok) {
		throw new Error(`Export failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Download the exported config as a file.
 */
export async function downloadConfigFile(): Promise<void> {
	const config = await exportConfig();
	const blob = new Blob([JSON.stringify(config, null, 2)], {
		type: 'application/json',
	});
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = `nettap-config-${new Date().toISOString().slice(0, 10)}.json`;
	a.click();
	URL.revokeObjectURL(url);
}

/**
 * Validate a config file without applying.
 */
export async function validateConfig(data: unknown): Promise<ValidationResult> {
	const res = await fetch('/api/backup/validate', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});

	if (!res.ok) {
		throw new Error(`Validation failed: ${res.status}`);
	}

	return res.json();
}

/**
 * Import and apply a config file. The capture mode is restored only with `applyCapture`,
 * because it restarts the capture containers (A9).
 */
// OLD CODE: export async function importConfig(data: unknown): Promise<ImportResult> {
export async function importConfig(data: unknown, applyCapture = false): Promise<ImportResult> {
	// OLD CODE: const res = await fetch('/api/backup/import', {
	const res = await fetch(`/api/backup/import${applyCapture ? '?apply_capture=1' : ''}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
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
 * Read a file as JSON from a File input.
 */
export async function readConfigFile(file: File): Promise<unknown> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => {
			try {
				resolve(JSON.parse(reader.result as string));
			} catch {
				reject(new Error('Invalid JSON file'));
			}
		};
		reader.onerror = () => reject(new Error('Failed to read file'));
		reader.readAsText(file);
	});
}
