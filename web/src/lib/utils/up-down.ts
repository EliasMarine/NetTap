/** NET-226: download, upload and local bytes, which add up to the total. */
interface UpDownLocal {
	download_bytes: number;
	upload_bytes: number;
	local_bytes: number;
}

/**
 * "↓ 4.7 GB down · ↑ 380 MB up · 1.2 GB local" (the local part only when there is some);
 * `words: false` drops "down" and "up" for a tooltip.
 */
export function upDownLocal(t: UpDownLocal, format: (bytes: number) => string, words = true): string {
	const text = `↓ ${format(t.download_bytes)}${words ? ' down' : ''} · ↑ ${format(t.upload_bytes)}${words ? ' up' : ''}`;
	return t.local_bytes > 0 ? `${text} · ${format(t.local_bytes)} local` : text;
}

/**
 * A slot with no connection record has no data (capture was down, or it is older than NetTap's oldest
 * record), not 0 B: network byte charts draw it as a "No data" gap (chart gaps). Strict, so a reply
 * without the field still counts as data.
 */
export const recorded = (p: { connections: number }): boolean => p.connections !== 0;
