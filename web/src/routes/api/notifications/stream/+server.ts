import type { RequestHandler } from './$types.js';
import { onNotification } from '$lib/server/notifications.js';

export const GET: RequestHandler = async ({ request }) => {
	const stream = new ReadableStream({
		start(controller) {
			const encoder = new TextEncoder();

			// Send initial connection comment
			controller.enqueue(encoder.encode(': connected\n\n'));

			// Subscribe to notifications
			const unsubscribe = onNotification((notification) => {
				try {
					const data = JSON.stringify(notification);
					controller.enqueue(encoder.encode(`event: notification\ndata: ${data}\n\n`));
				} catch {
					// Client disconnected
				}
			});

			// 30s keepalive to prevent proxy/browser timeouts
			const keepalive = setInterval(() => {
				try {
					controller.enqueue(encoder.encode(': keepalive\n\n'));
				} catch {
					clearInterval(keepalive);
				}
			}, 30_000);

			// Cleanup on client disconnect
			request.signal.addEventListener('abort', () => {
				unsubscribe();
				clearInterval(keepalive);
				try {
					controller.close();
				} catch {
					// Already closed
				}
			});
		},
	});

	return new Response(stream, {
		headers: {
			'Content-Type': 'text/event-stream',
			'Cache-Control': 'no-cache',
			Connection: 'keep-alive',
			'X-Accel-Buffering': 'no', // Critical for nginx reverse proxy
		},
	});
};
