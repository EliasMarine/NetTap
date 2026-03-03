import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createNotificationStream } from './notification-stream';

// ---------------------------------------------------------------------------
// EventSource mock
// ---------------------------------------------------------------------------

type EventSourceListener = (event: MessageEvent) => void;

class MockEventSource {
	url: string;
	listeners: Record<string, EventSourceListener[]> = {};
	onopen: (() => void) | null = null;
	onerror: (() => void) | null = null;
	closed = false;

	constructor(url: string) {
		this.url = url;
		// Simulate async connection
		queueMicrotask(() => this.onopen?.());
	}

	addEventListener(event: string, callback: EventSourceListener) {
		if (!this.listeners[event]) this.listeners[event] = [];
		this.listeners[event].push(callback);
	}

	close() {
		this.closed = true;
	}

	// Test helper — simulate a server event
	_emit(event: string, data: string) {
		const listeners = this.listeners[event] || [];
		for (const cb of listeners) {
			cb(new MessageEvent(event, { data }));
		}
	}
}

let lastInstance: MockEventSource | null = null;

beforeEach(() => {
	lastInstance = null;
	vi.stubGlobal(
		'EventSource',
		class extends MockEventSource {
			constructor(url: string) {
				super(url);
				lastInstance = this;
			}
		}
	);
});

afterEach(() => {
	vi.restoreAllMocks();
	lastInstance = null;
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('createNotificationStream', () => {
	it('creates EventSource pointing to the correct URL', () => {
		const callback = vi.fn();
		createNotificationStream(callback);

		expect(lastInstance).not.toBeNull();
		expect(lastInstance!.url).toBe('/api/notifications/stream');
	});

	it('parses and forwards notification events to callback', () => {
		const callback = vi.fn();
		createNotificationStream(callback);

		const notification = {
			id: 'ntf_1',
			type: 'alert',
			severity: 'high',
			title: 'Test',
			message: 'Hello',
			timestamp: '2026-03-01T00:00:00Z',
			read: false,
		};

		lastInstance!._emit('notification', JSON.stringify(notification));

		expect(callback).toHaveBeenCalledTimes(1);
		expect(callback).toHaveBeenCalledWith(notification);
	});

	it('ignores malformed event data', () => {
		const callback = vi.fn();
		createNotificationStream(callback);

		lastInstance!._emit('notification', 'not-valid-json{{{');

		expect(callback).not.toHaveBeenCalled();
	});

	it('close() closes the EventSource', () => {
		const callback = vi.fn();
		const stream = createNotificationStream(callback);

		expect(lastInstance!.closed).toBe(false);

		stream.close();

		expect(lastInstance!.closed).toBe(true);
	});

	it('isConnected() returns false initially', () => {
		const callback = vi.fn();
		const stream = createNotificationStream(callback);

		// Before the microtask fires onopen, connected is false
		expect(stream.isConnected()).toBe(false);
	});

	it('isConnected() returns true after onopen fires', async () => {
		const callback = vi.fn();
		const stream = createNotificationStream(callback);

		// Wait for microtask (onopen fires)
		await new Promise<void>((r) => queueMicrotask(r));

		expect(stream.isConnected()).toBe(true);
	});

	it('isConnected() returns false after onerror fires', async () => {
		const callback = vi.fn();
		const stream = createNotificationStream(callback);

		// Connect first
		await new Promise<void>((r) => queueMicrotask(r));
		expect(stream.isConnected()).toBe(true);

		// Trigger error
		lastInstance!.onerror?.();

		expect(stream.isConnected()).toBe(false);
	});

	it('isConnected() returns false after close()', async () => {
		const callback = vi.fn();
		const stream = createNotificationStream(callback);

		await new Promise<void>((r) => queueMicrotask(r));
		expect(stream.isConnected()).toBe(true);

		stream.close();
		expect(stream.isConnected()).toBe(false);
	});
});
