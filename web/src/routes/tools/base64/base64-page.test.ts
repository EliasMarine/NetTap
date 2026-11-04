import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

describe('Base64 and hex converter page', () => {
	it('encodes as you type and counts characters', async () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'Base64 and hex converter' })).toBeInTheDocument();
		await fireEvent.input(screen.getByLabelText('Text'), { target: { value: 'héllo' } });
		expect(screen.getByLabelText('Output')).toHaveValue('aMOpbGxv');
		expect(screen.getByText('Converted text · 8 chars')).toBeInTheDocument();
	});

	it('shows the conversion error as a notice', async () => {
		render(Page);
		await fireEvent.change(screen.getByLabelText('Operation'), { target: { value: 'hex-decode' } });
		await fireEvent.input(screen.getByLabelText('Text'), { target: { value: 'abc' } });
		expect(screen.getByRole('alert')).toHaveTextContent('Hex string must have even length');
		expect(screen.queryByLabelText('Output')).not.toBeInTheDocument();
	});
});
