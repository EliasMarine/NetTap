import { describe, it, expect } from 'vitest';
import { connectionDurationMs } from './connection-duration';

describe('connectionDurationMs', () => {
	it('reads length, the field the daemon sorts by', () => {
		expect(connectionDurationMs({ length: 21313625 })).toBe(21313625);
	});

	it("reads Malcolm 26.x's epoch-ms event.start/end text", () => {
		const conn = { event: { start: '1793683365306', end: '1793683365561' } };
		expect(connectionDurationMs(conn)).toBe(255);
	});

	it('still reads ISO dates', () => {
		const conn = { event: { start: '2026-03-08T10:00:00Z', end: '2026-03-08T10:00:01.500Z' } };
		expect(connectionDurationMs(conn)).toBe(1500);
	});

	it("falls back to Zeek's seconds, never event.duration's nanoseconds", () => {
		expect(connectionDurationMs({ zeek: { conn: { duration: 0.25 } }, event: { duration: 250000000 } })).toBe(250);
		expect(connectionDurationMs({ event: { duration: 250000000 } })).toBeNull();
	});

	it('is null when the record has no duration', () => {
		expect(connectionDurationMs({})).toBeNull();
		expect(connectionDurationMs({ event: { start: '1793683365561', end: '1793683365306' } })).toBeNull();
	});
});
