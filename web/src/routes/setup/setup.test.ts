import { describe, it, expect } from 'vitest';

/**
 * Tests for setup wizard logic.
 *
 * The wizard uses Svelte 5 runes ($state, $derived, $effect) which cannot be
 * rendered in a jsdom environment. We extract and test the pure logic:
 * step label computation, navigation validation, NIC validation, and
 * config payload construction.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from setup/+page.svelte
// ---------------------------------------------------------------------------

type CaptureMode = 'mirror' | 'bridge' | '';

/** Compute step labels based on the selected capture mode */
function getStepLabels(mode: CaptureMode): string[] {
	if (mode === 'mirror') {
		return ['Welcome', 'Capture Mode', 'Interfaces', 'Storage', 'Enrichment', 'Account'];
	} else if (mode === 'bridge') {
		return ['Welcome', 'Capture Mode', 'Interfaces', 'Bridge', 'Storage', 'Account'];
	}
	return ['Welcome', 'Capture Mode'];
}

/** Get the step name for a step number (1-based) */
function getStepName(stepLabels: string[], step: number): string {
	return stepLabels[step - 1] || '';
}

/** Check if NIC selection is valid for the current mode */
function isNicSelectionValid(
	mode: CaptureMode,
	selectedMirrorNic: string,
	selectedWan: string,
	selectedLan: string
): boolean {
	if (mode === 'mirror') {
		return selectedMirrorNic !== '';
	}
	return selectedWan !== '' && selectedLan !== '' && selectedWan !== selectedLan;
}

/** Check if the user can advance from the current step */
function canAdvance(
	stepName: string,
	requirementsChecked: boolean,
	selectedMode: CaptureMode,
	nicSelectionValid: boolean
): boolean {
	switch (stepName) {
		case 'Welcome':
			return requirementsChecked;
		case 'Capture Mode':
			return selectedMode !== '';
		case 'Interfaces':
			return nicSelectionValid;
		case 'Bridge':
			return true;
		case 'Storage':
			return true;
		case 'Enrichment':
			return true;
		case 'Account':
			return false;
		default:
			return false;
	}
}

/** Determine NIC requirement count based on mode */
function getMinNics(mode: CaptureMode): number {
	return mode === 'bridge' ? 2 : 1;
}

/** Build configuration payload for POST /api/setup/configure */
function buildConfigPayload(opts: {
	mode: CaptureMode;
	mirrorNic?: string;
	managementNic?: string;
	wan?: string;
	lan?: string;
	useUnifi?: boolean;
	unifiUrl?: string;
	unifiUsername?: string;
	unifiPassword?: string;
	hotDays?: number;
	warmDays?: number;
	coldDays?: number;
	diskThreshold?: number;
	emergencyThreshold?: number;
}): Record<string, unknown> {
	const payload: Record<string, unknown> = {
		capture_mode: opts.mode,
	};

	if (opts.mode === 'mirror') {
		payload.capture_interface = opts.mirrorNic || '';
		if (opts.managementNic) {
			payload.management_interface = opts.managementNic;
		}
		if (opts.useUnifi) {
			payload.unifi = {
				url: opts.unifiUrl || '',
				username: opts.unifiUsername || '',
				password: opts.unifiPassword || '',
			};
		}
	} else {
		payload.wan_interface = opts.wan || '';
		payload.lan_interface = opts.lan || '';
	}

	payload.storage = {
		hot_days: opts.hotDays ?? 90,
		warm_days: opts.warmDays ?? 180,
		cold_days: opts.coldDays ?? 30,
		disk_threshold_percent: opts.diskThreshold ?? 80,
		emergency_threshold_percent: opts.emergencyThreshold ?? 90,
	};

	return payload;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Setup Wizard — Step Labels', () => {
	it('returns only Welcome and Capture Mode when no mode is selected', () => {
		const labels = getStepLabels('');
		expect(labels).toEqual(['Welcome', 'Capture Mode']);
		expect(labels).toHaveLength(2);
	});

	it('returns 6 steps for mirror mode', () => {
		const labels = getStepLabels('mirror');
		expect(labels).toHaveLength(6);
		expect(labels).toContain('Enrichment');
		expect(labels).not.toContain('Bridge');
	});

	it('returns 6 steps for bridge mode', () => {
		const labels = getStepLabels('bridge');
		expect(labels).toHaveLength(6);
		expect(labels).toContain('Bridge');
		expect(labels).not.toContain('Enrichment');
	});

	it('mirror and bridge both have 6 visible steps', () => {
		expect(getStepLabels('mirror').length).toBe(getStepLabels('bridge').length);
	});

	it('both modes start with Welcome and end with Account', () => {
		for (const mode of ['mirror', 'bridge'] as CaptureMode[]) {
			const labels = getStepLabels(mode);
			expect(labels[0]).toBe('Welcome');
			expect(labels[labels.length - 1]).toBe('Account');
		}
	});
});

describe('Setup Wizard — Step Name Resolution', () => {
	it('resolves step numbers to names correctly for mirror mode', () => {
		const labels = getStepLabels('mirror');
		expect(getStepName(labels, 1)).toBe('Welcome');
		expect(getStepName(labels, 2)).toBe('Capture Mode');
		expect(getStepName(labels, 3)).toBe('Interfaces');
		expect(getStepName(labels, 4)).toBe('Storage');
		expect(getStepName(labels, 5)).toBe('Enrichment');
		expect(getStepName(labels, 6)).toBe('Account');
	});

	it('resolves step numbers to names correctly for bridge mode', () => {
		const labels = getStepLabels('bridge');
		expect(getStepName(labels, 1)).toBe('Welcome');
		expect(getStepName(labels, 2)).toBe('Capture Mode');
		expect(getStepName(labels, 3)).toBe('Interfaces');
		expect(getStepName(labels, 4)).toBe('Bridge');
		expect(getStepName(labels, 5)).toBe('Storage');
		expect(getStepName(labels, 6)).toBe('Account');
	});

	it('returns empty string for out-of-range steps', () => {
		const labels = getStepLabels('mirror');
		expect(getStepName(labels, 0)).toBe('');
		expect(getStepName(labels, 99)).toBe('');
	});
});

describe('Setup Wizard — NIC Selection Validation', () => {
	it('mirror mode: valid when mirror NIC is selected', () => {
		expect(isNicSelectionValid('mirror', 'eth0', '', '')).toBe(true);
	});

	it('mirror mode: invalid when no mirror NIC is selected', () => {
		expect(isNicSelectionValid('mirror', '', '', '')).toBe(false);
	});

	it('bridge mode: valid when WAN and LAN are different', () => {
		expect(isNicSelectionValid('bridge', '', 'eth0', 'eth1')).toBe(true);
	});

	it('bridge mode: invalid when WAN is empty', () => {
		expect(isNicSelectionValid('bridge', '', '', 'eth1')).toBe(false);
	});

	it('bridge mode: invalid when LAN is empty', () => {
		expect(isNicSelectionValid('bridge', '', 'eth0', '')).toBe(false);
	});

	it('bridge mode: invalid when WAN and LAN are the same', () => {
		expect(isNicSelectionValid('bridge', '', 'eth0', 'eth0')).toBe(false);
	});
});

describe('Setup Wizard — Navigation (canAdvance)', () => {
	it('Welcome: requires requirements checked', () => {
		expect(canAdvance('Welcome', false, '', false)).toBe(false);
		expect(canAdvance('Welcome', true, '', false)).toBe(true);
	});

	it('Capture Mode: requires mode selected', () => {
		expect(canAdvance('Capture Mode', true, '', true)).toBe(false);
		expect(canAdvance('Capture Mode', true, 'mirror', true)).toBe(true);
		expect(canAdvance('Capture Mode', true, 'bridge', true)).toBe(true);
	});

	it('Interfaces: requires valid NIC selection', () => {
		expect(canAdvance('Interfaces', true, 'mirror', false)).toBe(false);
		expect(canAdvance('Interfaces', true, 'mirror', true)).toBe(true);
	});

	it('Bridge: always allows advancing (optional verification)', () => {
		expect(canAdvance('Bridge', true, 'bridge', true)).toBe(true);
	});

	it('Storage: always allows advancing (has defaults)', () => {
		expect(canAdvance('Storage', true, 'mirror', true)).toBe(true);
	});

	it('Enrichment: always allows advancing (optional)', () => {
		expect(canAdvance('Enrichment', true, 'mirror', true)).toBe(true);
	});

	it('Account: never allows advancing (uses form submission)', () => {
		expect(canAdvance('Account', true, 'mirror', true)).toBe(false);
	});
});

describe('Setup Wizard — NIC Requirements', () => {
	it('mirror mode requires 1 NIC', () => {
		expect(getMinNics('mirror')).toBe(1);
	});

	it('bridge mode requires 2 NICs', () => {
		expect(getMinNics('bridge')).toBe(2);
	});

	it('no mode selected requires 1 NIC (minimum)', () => {
		expect(getMinNics('')).toBe(1);
	});
});

describe('Setup Wizard — Config Payload Builder', () => {
	it('builds correct payload for mirror mode', () => {
		const payload = buildConfigPayload({
			mode: 'mirror',
			mirrorNic: 'eth0',
			managementNic: 'eth1',
		});
		expect(payload.capture_mode).toBe('mirror');
		expect(payload.capture_interface).toBe('eth0');
		expect(payload.management_interface).toBe('eth1');
		expect(payload).not.toHaveProperty('wan_interface');
		expect(payload).not.toHaveProperty('lan_interface');
	});

	it('builds correct payload for bridge mode', () => {
		const payload = buildConfigPayload({
			mode: 'bridge',
			wan: 'eth0',
			lan: 'eth1',
		});
		expect(payload.capture_mode).toBe('bridge');
		expect(payload.wan_interface).toBe('eth0');
		expect(payload.lan_interface).toBe('eth1');
		expect(payload).not.toHaveProperty('capture_interface');
	});

	it('includes storage defaults', () => {
		const payload = buildConfigPayload({ mode: 'mirror', mirrorNic: 'eth0' });
		const storage = payload.storage as Record<string, number>;
		expect(storage.hot_days).toBe(90);
		expect(storage.warm_days).toBe(180);
		expect(storage.cold_days).toBe(30);
		expect(storage.disk_threshold_percent).toBe(80);
		expect(storage.emergency_threshold_percent).toBe(90);
	});

	it('includes custom storage values', () => {
		const payload = buildConfigPayload({
			mode: 'bridge',
			wan: 'eth0',
			lan: 'eth1',
			hotDays: 60,
			warmDays: 120,
			coldDays: 14,
			diskThreshold: 75,
			emergencyThreshold: 95,
		});
		const storage = payload.storage as Record<string, number>;
		expect(storage.hot_days).toBe(60);
		expect(storage.warm_days).toBe(120);
		expect(storage.cold_days).toBe(14);
		expect(storage.disk_threshold_percent).toBe(75);
		expect(storage.emergency_threshold_percent).toBe(95);
	});

	it('includes UniFi config for mirror mode when enabled', () => {
		const payload = buildConfigPayload({
			mode: 'mirror',
			mirrorNic: 'eth0',
			useUnifi: true,
			unifiUrl: 'https://192.168.1.1:8443',
			unifiUsername: 'admin',
			unifiPassword: 'secret',
		});
		expect(payload.unifi).toEqual({
			url: 'https://192.168.1.1:8443',
			username: 'admin',
			password: 'secret',
		});
	});

	it('omits UniFi config when not enabled', () => {
		const payload = buildConfigPayload({
			mode: 'mirror',
			mirrorNic: 'eth0',
			useUnifi: false,
		});
		expect(payload).not.toHaveProperty('unifi');
	});

	it('omits management_interface when empty', () => {
		const payload = buildConfigPayload({
			mode: 'mirror',
			mirrorNic: 'eth0',
			managementNic: '',
		});
		expect(payload).not.toHaveProperty('management_interface');
	});
});

describe('Setup Wizard — Mode-Specific Step Flow', () => {
	it('mirror mode skips Bridge step entirely', () => {
		const labels = getStepLabels('mirror');
		expect(labels).not.toContain('Bridge');
	});

	it('bridge mode skips Enrichment step entirely', () => {
		const labels = getStepLabels('bridge');
		expect(labels).not.toContain('Enrichment');
	});

	it('mirror mode has Enrichment as step 5', () => {
		const labels = getStepLabels('mirror');
		expect(getStepName(labels, 5)).toBe('Enrichment');
	});

	it('bridge mode has Bridge as step 4', () => {
		const labels = getStepLabels('bridge');
		expect(getStepName(labels, 4)).toBe('Bridge');
	});

	it('both modes have Storage step', () => {
		expect(getStepLabels('mirror')).toContain('Storage');
		expect(getStepLabels('bridge')).toContain('Storage');
	});

	it('both modes have Interfaces step at position 3', () => {
		expect(getStepName(getStepLabels('mirror'), 3)).toBe('Interfaces');
		expect(getStepName(getStepLabels('bridge'), 3)).toBe('Interfaces');
	});
});
