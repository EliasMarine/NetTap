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
}

export interface ImportResult {
	success: boolean;
	applied: string[];
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
 * Import and apply a config file.
 */
export async function importConfig(data: unknown): Promise<ImportResult> {
	const res = await fetch('/api/backup/import', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});

	return res.json();
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
