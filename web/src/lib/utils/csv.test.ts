import { describe, expect, it } from 'vitest';
import { csvCell } from './csv';

describe('csvCell', () => {
	it('leaves a missing value empty and keeps numbers bare', () => {
		expect(csvCell(null)).toBe('');
		expect(csvCell(undefined)).toBe('');
		expect(csvCell(1024)).toBe('1024');
		expect(csvCell(-5)).toBe('-5');
		expect(csvCell(Number.NaN)).toBe('');
		expect(csvCell(Number.POSITIVE_INFINITY)).toBe('');
	});

	it('quotes text and doubles its quotes', () => {
		expect(csvCell('laptop')).toBe('"laptop"');
		expect(csvCell('Kitchen "big", iPad')).toBe('"Kitchen ""big"", iPad"');
	});

	it.each(['=SUM(A1)', '+1', '-1', '@cmd', '\tx', '\rx'])('makes %j literal for spreadsheets', (v) => {
		expect(csvCell(v)).toBe(`"'${v}"`);
	});
});
