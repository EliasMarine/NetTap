import { describe, it, expect } from 'vitest';
import { likelyType, osBasis, typeBasis } from './device-guess';

describe('device guesses (NET-226)', () => {
	it('marks a known type as likely, keeping IoT in capitals, and leaves Unknown alone', () => {
		expect(likelyType('Computer', 'computer')).toBe('Likely computer');
		expect(likelyType('IoT', 'iot')).toBe('Likely IoT');
		expect(likelyType('Unknown', 'unknown')).toBe('Unknown');
		expect(likelyType('Unknown', null)).toBe('Unknown');
	});

	it('says what the type came from, and nothing for an unknown type or basis', () => {
		expect(typeBasis('phone', 'name')).toBe('from its name');
		expect(typeBasis('computer', 'os')).toBe('from its OS');
		expect(typeBasis('media', 'vendor')).toBe('from its maker');
		expect(typeBasis('unknown', 'name')).toBeNull();
		expect(typeBasis('phone', null)).toBeNull();
	});

	it('says what the OS came from', () => {
		expect(osBasis('web traffic')).toBe('from web traffic');
		expect(osBasis(null)).toBeNull();
	});
});
