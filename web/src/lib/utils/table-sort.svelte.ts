/**
 * Table sorting shared by every page (design system: every table sorts both ways).
 *
 * Text compares the way people read it: 192.168.1.9 before 192.168.1.10, port 8 before 80,
 * case ignored. Plain `localeCompare` or `<` put 10.10.0.235 before 10.10.0.26.
 */

export type SortDir = 'asc' | 'desc';

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

function isBlank(value: unknown): boolean {
	return value === null || value === undefined || value === '' || Number.isNaN(value);
}

const NUMBER_TEXT = /^-?\d+(\.\d+)?$/;

/** A number, or text that is one ("0.0105", tshark's fields); null otherwise. */
function asNumber(value: unknown): number | null {
	if (typeof value === 'number') return value;
	return typeof value === 'string' && NUMBER_TEXT.test(value.trim()) ? Number(value) : null;
}

/** Numbers by value, everything else as text in reading order. */
export function compareValues(a: unknown, b: unknown): number {
	// OLD CODE START — numeric text went to the collator, which reads 0.000123 as "0 . 123" > 0.01
	// if (typeof a === 'number' && typeof b === 'number') return a - b;
	// OLD CODE END
	const x = asNumber(a);
	const y = asNumber(b);
	if (x !== null && y !== null) return x - y;
	return collator.compare(String(a ?? ''), String(b ?? ''));
}

/**
 * Suricata severity (1 = high … 3 = low, 4 = info) as a rank where higher is worse, so a
 * table's first (descending) click puts the worst on top. No severity ranks lowest.
 */
export function severityRank(severity: number | null | undefined): number {
	return severity ? 5 - severity : 0;
}

// OLD CODE START — 2026-11-06 (NET-166): no caller left; the daemon now sends index sizes in bytes
// (OpenSearch's `bytes=b`), so the Infrastructure page no longer parses its rounded 1024-based text
// const SIZE_TEXT = /^(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb|pb)$/i;
// const SIZE_POWER: Record<string, number> = { b: 0, kb: 1, mb: 2, gb: 3, tb: 4, pb: 5 };
//
// /** OpenSearch's human sizes ("512kb", "1.2gb", 1024-based) in bytes; null if not a size. */
// export function byteSize(text: string | null | undefined): number | null {
// 	const m = SIZE_TEXT.exec((text ?? '').trim());
// 	return m ? Number(m[1]) * 1024 ** SIZE_POWER[m[2].toLowerCase()] : null;
// }
// OLD CODE END

/** A sorted copy; blank values go last in both directions. */
export function sortRows<T>(rows: readonly T[], value: (row: T) => unknown, dir: SortDir): T[] {
	return [...rows].sort((x, y) => {
		const a = value(x);
		const b = value(y);
		if (isBlank(a) || isBlank(b)) return isBlank(a) === isBlank(b) ? 0 : isBlank(a) ? 1 : -1;
		const cmp = compareValues(a, b);
		return dir === 'asc' ? cmp : -cmp;
	});
}

/** One table's sort column and direction. */
export class TableSort<K extends string> {
	key: K;
	dir: SortDir;

	constructor(key: K, dir: SortDir = 'desc') {
		this.key = $state(key);
		this.dir = $state(dir);
	}

	/** Same column flips the direction; a new column starts descending. */
	toggle(key: K): void {
		if (this.key === key) {
			this.dir = this.dir === 'desc' ? 'asc' : 'desc';
		} else {
			this.key = key;
			this.dir = 'desc';
		}
	}

	/** The arrow for a header: ↓ / ↑ on the sorted column, nothing elsewhere. */
	arrow(key: K): string {
		if (this.key !== key) return '';
		return this.dir === 'desc' ? '↓' : '↑';
	}

	/** The rows in this table's order; `value` reads the sort value of a row for a column. */
	apply<T>(rows: readonly T[], value: (row: T, key: K) => unknown): T[] {
		const key = this.key;
		return sortRows(rows, (row) => value(row, key), this.dir);
	}
}
