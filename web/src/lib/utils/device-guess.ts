/**
 * NET-226 (DEV-7/8): a device's type and OS are guesses, shown as such with what they came from.
 */
export type GuessBasis = 'name' | 'os' | 'vendor';

const BASIS: Record<GuessBasis, string> = { name: 'from its name', os: 'from its OS', vendor: 'from its maker' };

/** "Likely phone" for a type label; an unknown type is not a guess. */
export function likelyType(label: string, category: string | null | undefined): string {
	if (!category || category === 'unknown') return label;
	return `Likely ${label === 'IoT' ? label : label.toLowerCase()}`;
}

/** "from its name" for a guessed type, or null when the type is unknown or the basis isn't sent. */
export function typeBasis(category: string | null | undefined, basis: string | null | undefined): string | null {
	if (!category || category === 'unknown' || !basis) return null;
	// OLD CODE: return BASIS[basis as GuessBasis] ?? null; (review L6: 'constructor' read an inherited function)
	return Object.hasOwn(BASIS, basis) ? BASIS[basis as GuessBasis] : null;
}

/** "from web traffic" for an OS guess, or null. */
export function osBasis(basis: string | null | undefined): string | null {
	return basis ? `from ${basis}` : null;
}
