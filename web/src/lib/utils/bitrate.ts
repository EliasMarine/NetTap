/**
 * A bit rate in decimal units (NET-166): 1 kbit/s is 1,000 bit/s, as ISPs quote line speeds.
 * Three significant figures above 1 kbit/s, whole bits below it, trailing zeros dropped:
 * "0 bit/s", "950 bit/s", "1.2 kbit/s", "12.3 Mbit/s", "1.05 Gbit/s". Not a rate gives "—".
 */
const UNITS = ['bit/s', 'kbit/s', 'Mbit/s', 'Gbit/s'] as const;

export function formatBitRate(bps: number): string {
	if (!Number.isFinite(bps) || bps < 0) return '—';
	if (bps < 999.5) return `${Math.round(bps)} bit/s`;
	// round first, so 999,950 bit/s reads "1 Mbit/s", not "1000 kbit/s"
	const rounded = Number(bps.toPrecision(3));
	const unit = Math.min(UNITS.length - 1, Math.floor(Math.log10(rounded) / 3));
	return `${Number((rounded / 1000 ** unit).toPrecision(3))} ${UNITS[unit]}`;
}
