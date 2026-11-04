import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import ThemePicker from './ThemePicker.svelte';
import { setTheme } from '$lib/stores/theme';

describe('ThemePicker', () => {
	beforeEach(() => {
		setTheme('ember');
		localStorage.clear();
	});

	it('offers the three variants with Ember selected by default', async () => {
		render(ThemePicker);
		await tick();
		expect(screen.getByRole('radio', { name: 'Ember' })).toBeChecked();
		expect(screen.getByRole('radio', { name: 'Graphite' })).not.toBeChecked();
		expect(screen.getByRole('radio', { name: 'Spectrum' })).not.toBeChecked();
	});

	it('shows the current variant after mount', async () => {
		setTheme('spectrum');
		render(ThemePicker);
		await tick();
		expect(screen.getByRole('radio', { name: 'Spectrum' })).toBeChecked();
	});

	it('applies and remembers a choice', async () => {
		render(ThemePicker);
		await fireEvent.click(screen.getByRole('radio', { name: 'Graphite' }));
		expect(document.documentElement.dataset.variant).toBe('graphite');
		expect(localStorage.getItem('nettap-theme')).toBe('graphite');
		expect(screen.getByRole('radio', { name: 'Graphite' })).toBeChecked();
	});
});
