/**
 * NET-373: PCAP Search opens "Download filtered" in a new tab. When the daemon refuses before any
 * packet is sent (no capture holds the window, too many packets, busy…), that tab showed its raw
 * JSON. This page says the same thing in words, and hands the reason back to the PCAP page that
 * opened the tab, which shows it beside the download's dates and closes the tab.
 */

import { DOWNLOAD_ERROR_MESSAGE } from '$lib/api/pcap';

const FALLBACK = 'The download failed.';

const HTML_ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** Text for an HTML element. The reason can echo the operator's own filter text (TShark's message). */
function escapeHtml(text: string): string {
	return text.replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

/** A JSON literal that is safe inside <script>: nothing in it can end the element or the line. */
function scriptLiteral(value: unknown): string {
	return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

/** The daemon's refusal as a readable page, with the daemon's status. */
export function downloadErrorPage(reason: unknown, status: number): Response {
	const message = typeof reason === 'string' && reason.trim() ? reason : FALLBACK;
	const payload = scriptLiteral({ type: DOWNLOAD_ERROR_MESSAGE, message });
	// No colours or sizes of its own: the browser's defaults, light or dark as the system is
	const html = `<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Download not started | NetTap</title>
</head>
<body>
<h1>The download didn't start</h1>
<p>${escapeHtml(message)}</p>
<p>Close this tab to go back to PCAP Search.</p>
<script>if (window.opener) window.opener.postMessage(${payload}, location.origin);</script>
</body>
</html>
`;
	return new Response(html, {
		status,
		headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
	});
}
