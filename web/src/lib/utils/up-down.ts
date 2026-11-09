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
