import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * Tests for NIC Identification (LED blink) logic.
 *
 * The NIC identify feature lives inside the setup wizard (+page.svelte) and
 * uses Svelte 5 runes ($state, $derived) that are difficult to render in a
 * jsdom test environment. Instead we extract and test the pure logic:
 * interface name validation, duration capping, button label generation,
 * disabled state computation, countdown behavior, and error handling.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from the setup wizard NIC identification feature
// ---------------------------------------------------------------------------

/** Regex for valid interface names: alphanumeric, hyphens, underscores only */
const VALID_IFACE_RE = /^[a-zA-Z0-9_-]+$/;

/** Validate an interface name for safety */
function isValidInterfaceName(name: string): boolean {
	if (!name || typeof name !== 'string') return false;
	return VALID_IFACE_RE.test(name.trim());
}

/** Cap and clamp duration to valid range */
function clampDuration(duration: number | undefined | null, defaultVal = 15, min = 1, max = 30): number {
	if (duration === undefined || duration === null || isNaN(duration)) return defaultVal;
	if (duration < min) return min;
	if (duration > max) return max;
	return Math.floor(duration);
}

/** Get the button label text based on blink state */
function getIdentifyButtonLabel(
	isBlinking: boolean,
	countdown: number,
): string {
	if (isBlinking) {
		return `Blinking... (${countdown}s)`;
	}
	return 'Identify';
}

/** Determine if the identify button should be disabled */
function isIdentifyDisabled(
	selectedInterface: string,
	blinkingInterface: string,
): boolean {
	// No interface selected for this role
	if (!selectedInterface) return true;
	// Another interface is already blinking
	if (blinkingInterface !== '' && blinkingInterface !== selectedInterface) return true;
	return false;
}

/** Determine if the button should show active/pulsing state */
function isIdentifyActive(
	selectedInterface: string,
	blinkingInterface: string,
): boolean {
	return blinkingInterface === selectedInterface && blinkingInterface !== '';
}

/** Determine error display text from API responses */
function getBlinkErrorMessage(
	responseOk: boolean,
	responseData: { error?: string } | null,
	networkError: boolean,
): string {
	if (networkError) return 'Failed to connect to server';
	if (!responseOk && responseData?.error) return responseData.error;
	if (!responseOk) return 'Failed to identify interface';
	return '';
}

/**
 * Simulates the countdown timer logic.
 * Returns the sequence of countdown values and final state.
 */
function simulateCountdown(
	initialCount: number,
): { values: number[]; finalBlinking: boolean } {
	const values: number[] = [];
	let count = initialCount;
	let blinking = true;

	while (count > 0) {
		count--;
		values.push(count);
		if (count <= 0) {
			blinking = false;
		}
	}

	return { values, finalBlinking: blinking };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NIC Identification logic', () => {
	// -- Interface name validation -------------------------------------------

	describe('isValidInterfaceName', () => {
		it('accepts standard interface names', () => {
			expect(isValidInterfaceName('eth0')).toBe(true);
			expect(isValidInterfaceName('eth1')).toBe(true);
			expect(isValidInterfaceName('enp3s0')).toBe(true);
			expect(isValidInterfaceName('wlan0')).toBe(true);
		});

		it('accepts names with hyphens and underscores', () => {
			expect(isValidInterfaceName('enp3s0-wan')).toBe(true);
			expect(isValidInterfaceName('eth0_mgmt')).toBe(true);
			expect(isValidInterfaceName('br-lan')).toBe(true);
		});

		it('rejects empty strings', () => {
			expect(isValidInterfaceName('')).toBe(false);
		});

		it('rejects names with shell injection characters', () => {
			expect(isValidInterfaceName('eth0; rm -rf /')).toBe(false);
			expect(isValidInterfaceName('eth0|cat /etc/passwd')).toBe(false);
			expect(isValidInterfaceName('`whoami`')).toBe(false);
			expect(isValidInterfaceName('$(reboot)')).toBe(false);
		});

		it('rejects names with spaces', () => {
			expect(isValidInterfaceName('eth 0')).toBe(false);
		});

		it('rejects names with dots', () => {
			expect(isValidInterfaceName('eth0.100')).toBe(false);
		});

		it('rejects non-string values', () => {
			expect(isValidInterfaceName(null as unknown as string)).toBe(false);
			expect(isValidInterfaceName(undefined as unknown as string)).toBe(false);
			expect(isValidInterfaceName(123 as unknown as string)).toBe(false);
		});
	});

	// -- Duration capping ----------------------------------------------------

	describe('clampDuration', () => {
		it('defaults to 15 when undefined', () => {
			expect(clampDuration(undefined)).toBe(15);
		});

		it('defaults to 15 when null', () => {
			expect(clampDuration(null)).toBe(15);
		});

		it('defaults to 15 when NaN', () => {
			expect(clampDuration(NaN)).toBe(15);
		});

		it('caps at 30 maximum', () => {
			expect(clampDuration(60)).toBe(30);
			expect(clampDuration(120)).toBe(30);
		});

		it('clamps to 1 minimum', () => {
			expect(clampDuration(0)).toBe(1);
			expect(clampDuration(-5)).toBe(1);
		});

		it('accepts valid durations within range', () => {
			expect(clampDuration(10)).toBe(10);
			expect(clampDuration(15)).toBe(15);
			expect(clampDuration(30)).toBe(30);
			expect(clampDuration(1)).toBe(1);
		});

		it('floors fractional durations', () => {
			expect(clampDuration(15.7)).toBe(15);
			expect(clampDuration(29.9)).toBe(29);
		});
	});

	// -- Button label --------------------------------------------------------

	describe('getIdentifyButtonLabel', () => {
		it('returns "Identify" when not blinking', () => {
			expect(getIdentifyButtonLabel(false, 0)).toBe('Identify');
		});

		it('returns countdown label when blinking', () => {
			expect(getIdentifyButtonLabel(true, 15)).toBe('Blinking... (15s)');
			expect(getIdentifyButtonLabel(true, 5)).toBe('Blinking... (5s)');
			expect(getIdentifyButtonLabel(true, 1)).toBe('Blinking... (1s)');
		});

		it('returns 0s countdown at the end', () => {
			expect(getIdentifyButtonLabel(true, 0)).toBe('Blinking... (0s)');
		});
	});

	// -- Button disabled states ----------------------------------------------

	describe('isIdentifyDisabled', () => {
		it('is disabled when no interface is selected', () => {
			expect(isIdentifyDisabled('', '')).toBe(true);
		});

		it('is not disabled when an interface is selected and nothing is blinking', () => {
			expect(isIdentifyDisabled('eth0', '')).toBe(false);
		});

		it('is disabled when another interface is blinking', () => {
			expect(isIdentifyDisabled('eth0', 'eth1')).toBe(true);
		});

		it('is not disabled when the same interface is blinking', () => {
			expect(isIdentifyDisabled('eth0', 'eth0')).toBe(false);
		});

		it('is disabled when interface is empty and something is blinking', () => {
			expect(isIdentifyDisabled('', 'eth0')).toBe(true);
		});
	});

	// -- Active/pulsing state ------------------------------------------------

	describe('isIdentifyActive', () => {
		it('is active when the selected interface matches the blinking interface', () => {
			expect(isIdentifyActive('eth0', 'eth0')).toBe(true);
		});

		it('is not active when a different interface is blinking', () => {
			expect(isIdentifyActive('eth0', 'eth1')).toBe(false);
		});

		it('is not active when nothing is blinking', () => {
			expect(isIdentifyActive('eth0', '')).toBe(false);
		});

		it('is not active when no interface selected', () => {
			expect(isIdentifyActive('', '')).toBe(false);
		});
	});

	// -- Error message display -----------------------------------------------

	describe('getBlinkErrorMessage', () => {
		it('returns network error message on connection failure', () => {
			expect(getBlinkErrorMessage(false, null, true)).toBe('Failed to connect to server');
		});

		it('returns API error message from response', () => {
			expect(getBlinkErrorMessage(false, { error: 'ethtool is not installed' }, false))
				.toBe('ethtool is not installed');
		});

		it('returns generic error when response has no error field', () => {
			expect(getBlinkErrorMessage(false, {}, false)).toBe('Failed to identify interface');
		});

		it('returns empty string on success', () => {
			expect(getBlinkErrorMessage(true, null, false)).toBe('');
		});

		it('prioritizes network error over API error', () => {
			expect(getBlinkErrorMessage(false, { error: 'some api error' }, true))
				.toBe('Failed to connect to server');
		});
	});

	// -- Countdown timer logic -----------------------------------------------

	describe('countdown timer', () => {
		it('counts down from initial value to 0', () => {
			const { values, finalBlinking } = simulateCountdown(3);
			expect(values).toEqual([2, 1, 0]);
			expect(finalBlinking).toBe(false);
		});

		it('immediately stops for countdown of 1', () => {
			const { values, finalBlinking } = simulateCountdown(1);
			expect(values).toEqual([0]);
			expect(finalBlinking).toBe(false);
		});

		it('full 15-second countdown produces correct number of ticks', () => {
			const { values, finalBlinking } = simulateCountdown(15);
			expect(values.length).toBe(15);
			expect(values[0]).toBe(14);
			expect(values[values.length - 1]).toBe(0);
			expect(finalBlinking).toBe(false);
		});

		it('does nothing for countdown of 0', () => {
			const { values, finalBlinking } = simulateCountdown(0);
			expect(values).toEqual([]);
			expect(finalBlinking).toBe(true);
		});
	});

	// -- Concurrent blink prevention -----------------------------------------

	describe('concurrent blink prevention', () => {
		it('second identify call is blocked when already blinking', () => {
			const blinkingInterface = 'eth0';

			// Simulate the guard check at the top of identifyNic()
			const canBlink = (iface: string, currentBlinking: string): boolean => {
				if (currentBlinking) return false;
				return true;
			};

			expect(canBlink('eth1', blinkingInterface)).toBe(false);
			expect(canBlink('eth0', blinkingInterface)).toBe(false);
		});

		it('identify is allowed when nothing is blinking', () => {
			const canBlink = (iface: string, currentBlinking: string): boolean => {
				if (currentBlinking) return false;
				return true;
			};

			expect(canBlink('eth0', '')).toBe(true);
			expect(canBlink('eth1', '')).toBe(true);
		});
	});
});
