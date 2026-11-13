import type { Notification } from '$lib/server/notifications.js';

export interface NotificationStream {
	close(): void;
	isConnected(): boolean;
}

export function createNotificationStream(
	onNotification: (notification: Notification) => void
): NotificationStream {
	let connected = false;
	const es = new EventSource('/api/notifications/stream');

	es.addEventListener('notification', (event) => {
		try {
			const notification = JSON.parse(event.data) as Notification;
			onNotification(notification);
		} catch {
			// Malformed event data — ignore
		}
	});

	es.onopen = () => {
		connected = true;
	};

	es.onerror = () => {
		connected = false;
		// OLD CODE: // EventSource auto-reconnects — no manual retry needed (NET-198: only true after a network drop)
		// After an HTTP error such as a 401 (the session ran out) the browser closes it for good. The shell's
		// ping then sends the user to sign in, and the bell opens a new stream when the shell mounts again.
	};

	return {
		close() {
			es.close();
			connected = false;
		},
		isConnected() {
			return connected;
		},
	};
}
