import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HexDump from './HexDump.svelte';

/** `n` bytes counting up from 00, as hex digits. */
const hexOf = (n: number) => Array.from({ length: n }, (_, i) => (i % 256).toString(16).padStart(2, '0')).join('');

describe('packets HexDump', () => {
	it('shows 8 bytes to a row, so a whole row and its ASCII fit the desktop drawer', () => {
		const { container } = render(HexDump, { props: { hex: hexOf(20), mark: null } });
		expect([...container.querySelectorAll('.off')].map((o) => o.textContent)).toEqual(['0000', '0008', '0010']);
		expect([...container.querySelectorAll('.hexrun')].map((r) => r.textContent)).toEqual([
			'00 01 02 03 04 05 06 07',
			'08 09 0a 0b 0c 0d 0e 0f',
			'10 11 12 13',
		]);
	});

	it('first shows 256 bytes, 32 rows, and offers the rest', () => {
		const { container } = render(HexDump, { props: { hex: hexOf(300), mark: null } });
		expect(container.querySelectorAll('.off')).toHaveLength(32);
		expect(screen.getByRole('button', { name: 'Show all 300 bytes' })).toBeInTheDocument();
	});
});
