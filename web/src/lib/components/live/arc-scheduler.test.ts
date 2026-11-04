import { describe, it, expect, vi } from 'vitest';
import { createArcScheduler } from './arc-scheduler';

function fakeRaf() {
	const queue = new Map<number, FrameRequestCallback>();
	let next = 1;
	return {
		raf: vi.fn((cb: FrameRequestCallback) => {
			queue.set(next, cb);
			return next++;
		}),
		caf: vi.fn((id: number) => queue.delete(id)),
		/** Runs the frames queued so far, once each. */
		flush() {
			const pending = [...queue.entries()];
			queue.clear();
			for (const [, cb] of pending) cb(0);
		},
		get size() {
			return queue.size;
		},
	};
}

describe('arc scheduler, reduced motion', () => {
	it('draws the static frame on start, with no animation frame', () => {
		const frames = fakeRaf();
		const draw = vi.fn();
		const s = createArcScheduler({ draw, reduceMotion: true, isPaused: () => false, ...frames });
		s.start();
		expect(draw).toHaveBeenCalledTimes(1);
		expect(draw).toHaveBeenCalledWith(null);
		expect(frames.raf).not.toHaveBeenCalled();
	});

	it('redraws the static frame on every trigger', () => {
		const frames = fakeRaf();
		const draw = vi.fn();
		const s = createArcScheduler({ draw, reduceMotion: true, isPaused: () => false, ...frames });
		s.start();
		s.redraw();
		s.redraw();
		expect(draw).toHaveBeenCalledTimes(3);
		expect(draw.mock.calls.every(([phase]) => phase === null)).toBe(true);
		expect(frames.raf).not.toHaveBeenCalled();
	});
});

describe('arc scheduler, motion allowed', () => {
	it('runs a requestAnimationFrame loop that advances the pulse phase', () => {
		const frames = fakeRaf();
		const draw = vi.fn();
		const s = createArcScheduler({ draw, reduceMotion: false, isPaused: () => false, ...frames });
		s.start();
		expect(draw).not.toHaveBeenCalled();
		frames.flush();
		frames.flush();
		expect(draw).toHaveBeenCalledTimes(2);
		const [[first], [second]] = draw.mock.calls;
		expect(typeof first).toBe('number');
		expect(second).toBeGreaterThan(first);
		expect(frames.size).toBe(1); // the loop keeps itself scheduled
	});

	it('skips drawing while paused but keeps the loop alive', () => {
		const frames = fakeRaf();
		const draw = vi.fn();
		let paused = true;
		const s = createArcScheduler({ draw, reduceMotion: false, isPaused: () => paused, ...frames });
		s.start();
		frames.flush();
		expect(draw).not.toHaveBeenCalled();
		paused = false;
		frames.flush();
		expect(draw).toHaveBeenCalledTimes(1);
	});

	it('redraw is a no-op (the next frame picks up changes)', () => {
		const frames = fakeRaf();
		const draw = vi.fn();
		const s = createArcScheduler({ draw, reduceMotion: false, isPaused: () => false, ...frames });
		s.start();
		s.redraw();
		expect(draw).not.toHaveBeenCalled();
	});

	it('stop cancels the pending frame', () => {
		const frames = fakeRaf();
		const s = createArcScheduler({ draw: vi.fn(), reduceMotion: false, isPaused: () => false, ...frames });
		s.start();
		s.stop();
		expect(frames.caf).toHaveBeenCalledTimes(1);
		expect(frames.size).toBe(0);
	});
});
