/**
 * CSV cells for the app's exports (moved from routes/changelog/changelog-rows.ts for NET-316, so
 * the Devices export escapes the same way).
 */

const FORMULA_START = /^[=+\-@\t\r]/;

/**
 * One CSV cell. Text that a spreadsheet would read as a formula (names come from discovery or the
 * owner) gets a leading `'`; then it is quoted with quotes doubled. Numbers stay numeric.
 */
export function csvCell(v: unknown): string {
	if (v === null || v === undefined) return '';
	if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
	const s = String(v);
	return `"${(FORMULA_START.test(s) ? `'${s}` : s).replace(/"/g, '""')}"`;
}
