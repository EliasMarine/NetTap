import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HexDump from './HexDump.svelte';

describe('HexDump', () => {
	it('shows empty state when no data is provided', () => {
		render(HexDump, { props: {} });
		expect(screen.getByText(/select a packet/i)).toBeInTheDocument();
	});

	it('renders hex bytes and ASCII for provided data', () => {
		// "Hello" = 48 65 6c 6c 6f
		const data = '48656c6c6f';
		const { container } = render(HexDump, { props: { rawHex: data } });

		// Should show offset 0000
		expect(container.textContent).toContain('0000');
		// Should show hex bytes
		expect(container.textContent).toContain('48');
		expect(container.textContent).toContain('65');
		// Should show ASCII
		expect(container.textContent).toContain('Hello');
	});

	it('shows dots for non-printable ASCII', () => {
		// 0x01 0x02 0x41 (A)
		const data = '010241';
		const { container } = render(HexDump, { props: { rawHex: data } });
		expect(container.textContent).toContain('..A');
	});
});
