import type { RequestHandler } from './$types.js';
import { onNotification } from '$lib/server/notifications.js';
import { verifyToken } from '$lib/server/auth.js';

const KEEPALIVE_MS = 30_000;

// OLD CODE START — NET-358: the session was checked only when the stream opened (by the hook), so a
// browser whose session a password change had ended kept getting every notification until it disconnected
// export const GET: RequestHandler = async ({ request }) => {
// 	const stream = new ReadableStream({
// 		start(controller) {
// 			const encoder = new TextEncoder();
//
// 			// Send initial connection comment
// 			controller.enqueue(encoder.encode(': connected\n\n'));
//
// 			// Subscribe to notifications
// 			const unsubscribe = onNotification((notification) => {
// 				try {
// 					const data = JSON.stringify(notification);
// 					controller.enqueue(encoder.encode(`event: notification\ndata: ${data}\n\n`));
// 				} catch {
// 					// Client disconnected
// 				}
// 			});
//
// 			// 30s keepalive to prevent proxy/browser timeouts
// 			const keepalive = setInterval(() => {
// 				try {
// 					controller.enqueue(encoder.encode(': keepalive\n\n'));
// 				} catch {
// 					clearInterval(keepalive);
// 				}
// 			}, 30_000);
//
// 			// Cleanup on client disconnect
// 			request.signal.addEventListener('abort', () => {
// 				unsubscribe();
// 				clearInterval(keepalive);
// 				try {
// 					controller.close();
// 				} catch {
// 					// Already closed
// 				}
// 			});
// 		},
// 	});
// 	… (the Response below is unchanged)
// OLD CODE END

export const GET: RequestHandler = async ({ request, cookies }) => {
	// The hook let this request in on this cookie; it is checked again before every write
	const token = cookies.get('nettap_token') ?? '';
	const stream = new ReadableStream({
		start(controller) {
			const encoder = new TextEncoder();
			let open = true;
			let unsubscribe = () => {};
			let keepalive: ReturnType<typeof setInterval> | undefined;

			function close() {
				if (!open) return;
				open = false;
				unsubscribe();
				clearInterval(keepalive);
				try {
					controller.close();
				} catch {
					// Already closed
				}
			}

			/** NET-358: a session ended by a password change gets nothing more; its stream closes instead. */
			function send(chunk: string) {
				if (!open) return;
				if (!verifyToken(token)) {
					close();
					return;
				}
				try {
					controller.enqueue(encoder.encode(chunk));
				} catch {
					close(); // client disconnected
				}
			}

			controller.enqueue(encoder.encode(': connected\n\n'));
			unsubscribe = onNotification((notification) => send(`event: notification\ndata: ${JSON.stringify(notification)}\n\n`));
			// keepalive against proxy and browser timeouts; it also ends an idle revoked stream within 30 s
			keepalive = setInterval(() => send(': keepalive\n\n'), KEEPALIVE_MS);
			request.signal.addEventListener('abort', close);
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
