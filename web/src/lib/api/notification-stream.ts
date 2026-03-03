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
		// EventSource auto-reconnects — no manual retry needed
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
