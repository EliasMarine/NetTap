/**
 * Decides when GeoMap's canvas is drawn. Drawing itself stays in the component.
 *
 * - Motion allowed: a requestAnimationFrame loop advances the pulse phase and
 *   draws every frame, except while paused (the last frame stays up).
 * - Reduced motion: no loop. The static frame (arcs, no pulses) is drawn on
 *   start and on every redraw() call (data, viewport or theme change).
 */
export type DrawFrame = (pulsePhase: number | null) => void;

export interface ArcScheduler {
	start(): void;
	redraw(): void;
	stop(): void;
}

interface Options {
	draw: DrawFrame;
	reduceMotion: boolean;
	isPaused: () => boolean;
	raf?: (cb: FrameRequestCallback) => number;
	caf?: (id: number) => void;
}

const PHASE_STEP = 0.005;

export function createArcScheduler({
	draw,
	reduceMotion,
	isPaused,
	raf = requestAnimationFrame,
	caf = cancelAnimationFrame,
}: Options): ArcScheduler {
	let frameId: number | null = null;
	let phase = 0;

	function tick() {
		frameId = raf(tick);
		if (isPaused()) return;
		phase = (phase + PHASE_STEP) % 1;
		draw(phase);
	}

	return {
		start() {
			if (reduceMotion) {
				draw(null);
			} else if (frameId === null) {
				frameId = raf(tick);
			}
		},
		redraw() {
			// With motion on, the next frame picks up the change anyway.
			if (reduceMotion) draw(null);
		},
		stop() {
			if (frameId !== null) caf(frameId);
			frameId = null;
		},
	};
}
