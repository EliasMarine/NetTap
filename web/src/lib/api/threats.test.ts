import { describe, it, expect } from 'vitest';
import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel } from './threats';

describe('threats API client', () => {
	it('exports all fetch functions', () => {
		expect(typeof getThreatReport).toBe('function');
		expect(typeof getBeaconing).toBe('function');
		expect(typeof getLateralMovement).toBe('function');
		expect(typeof getDnsAnomalies).toBe('function');
		expect(typeof getThreatIntel).toBe('function');
	});
});
