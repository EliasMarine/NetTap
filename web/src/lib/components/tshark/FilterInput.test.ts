import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import FilterInput from './FilterInput.svelte';

describe('FilterInput component', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('renders the filter input and buttons', () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit } });

		const input = screen.getByPlaceholderText(/enter display filter/i);
		expect(input).toBeInTheDocument();

		// Preset button
		const presetsBtn = screen.getByRole('button', { name: /presets/i });
		expect(presetsBtn).toBeInTheDocument();

		// Apply button
		const applyBtn = screen.getByRole('button', { name: /apply/i });
		expect(applyBtn).toBeInTheDocument();

		// Validate button
		const validateBtn = screen.getByRole('button', { name: /validate/i });
		expect(validateBtn).toBeInTheDocument();
	});

	it('shows preset options when Presets button is clicked', async () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit } });

		const presetsBtn = screen.getByRole('button', { name: /presets/i });
		await fireEvent.click(presetsBtn);

		// Check for some known presets
		expect(screen.getByText('HTTP requests')).toBeInTheDocument();
		expect(screen.getByText('DNS queries')).toBeInTheDocument();
		expect(screen.getByText('TLS handshakes')).toBeInTheDocument();
	});

	it('updates filter text when typing in the input', async () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit } });

		const input = screen.getByPlaceholderText(/enter display filter/i) as HTMLInputElement;
		await fireEvent.input(input, { target: { value: 'tcp.port == 80' } });

		expect(input.value).toBe('tcp.port == 80');
	});

	it('calls onsubmit with the filter text when Apply is clicked', async () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit } });

		const input = screen.getByPlaceholderText(/enter display filter/i);
		await fireEvent.input(input, { target: { value: 'http.request' } });

		const applyBtn = screen.getByRole('button', { name: /apply/i });
		await fireEvent.click(applyBtn);

		expect(onsubmit).toHaveBeenCalledOnce();
		expect(onsubmit).toHaveBeenCalledWith('http.request');
	});

	it('disables input and buttons when disabled prop is true', () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit, disabled: true } });

		const input = screen.getByPlaceholderText(/enter display filter/i) as HTMLInputElement;
		expect(input.disabled).toBe(true);

		const presetsBtn = screen.getByRole('button', { name: /presets/i }) as HTMLButtonElement;
		expect(presetsBtn.disabled).toBe(true);
	});

	it('selects a preset and fills the input', async () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit } });

		// Open presets
		const presetsBtn = screen.getByRole('button', { name: /presets/i });
		await fireEvent.click(presetsBtn);

		// Click the "HTTP requests" preset
		const httpPreset = screen.getByText('HTTP requests');
		await fireEvent.click(httpPreset);

		const input = screen.getByPlaceholderText(/enter display filter/i) as HTMLInputElement;
		expect(input.value).toBe('http.request');
	});

	it('Apply and Validate buttons are disabled when filter is empty', () => {
		const onsubmit = vi.fn();
		render(FilterInput, { props: { onsubmit } });

		const applyBtn = screen.getByRole('button', { name: /apply/i }) as HTMLButtonElement;
		const validateBtn = screen.getByRole('button', { name: /validate/i }) as HTMLButtonElement;

		expect(applyBtn.disabled).toBe(true);
		expect(validateBtn.disabled).toBe(true);
	});
});
