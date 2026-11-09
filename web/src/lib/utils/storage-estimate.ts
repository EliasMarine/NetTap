/**
 * B-m: the retention estimate in words, from the daemon's measured growth, with its basis.
 * It replaced a fixed 1.2 GB a day; the G11 writes about 2 GB of indices and 66 GB of PCAP a day.
 */
import type { GrowthEstimate } from '$api/system';
import { formatBytes } from '$api/logs';

const days = (n: number) => `${n} ${n === 1 ? 'day' : 'days'}`;

/**
 * One or two sentences; "No estimate yet…" until a full day of data has been measured.
 * `hotDays` is the live form value in setup, so it can be empty (null) while being typed.
 */
// OLD CODE: export function growthSummary(estimate: GrowthEstimate | null | undefined, hotDays: number): string {
export function growthSummary(estimate: GrowthEstimate | null | undefined, hotDays: number | null | undefined): string {
	const index = estimate?.index_bytes_per_day ?? null;
	const pcap = estimate?.pcap_bytes_per_day ?? null;
	if (!estimate || (index === null && pcap === null)) {
		return 'No estimate yet: it comes from how fast your data grows, and NetTap needs a full day of data first.';
	}
	const parts: string[] = [];
	if (index !== null) {
		// OLD CODE START — L8: an emptied hot-days field read "so null days of them need about 0 B"
		// parts.push(
		// 	`Estimate from the last ${days(estimate.index_days_measured)}: indices grow about ${formatBytes(index)} a day, ` +
		// 		`so ${days(hotDays)} of them need about ${formatBytes(index * hotDays)}.`,
		// );
		// OLD CODE END
		const rate = `Estimate from the last ${days(estimate.index_days_measured)}: indices grow about ${formatBytes(index)} a day`;
		parts.push(
			typeof hotDays === 'number' && Number.isFinite(hotDays) && hotDays > 0
				? `${rate}, so ${days(hotDays)} of them need about ${formatBytes(index * hotDays)}.`
				: `${rate}.`,
		);
	}
	if (pcap !== null) {
		const kept = estimate.pcap_days_kept;
		parts.push(
			`PCAP grows about ${formatBytes(pcap)} a day (measured over ${days(estimate.pcap_days_measured)})` +
				(kept === null ? '.' : `, so about ${days(kept)} of it is kept.`),
		);
	}
	return parts.join(' ');
}
