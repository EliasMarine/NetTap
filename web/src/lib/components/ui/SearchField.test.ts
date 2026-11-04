import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SearchField from './SearchField.svelte';

describe('SearchField', () => {
	it('is a search input named by its hidden label, inside the .search pill', () => {
		const { container } = render(SearchField, {
			id: 'search-main',
			label: 'Search',
			placeholder: 'Search IPs, domains, devices…',
		});
		const input = screen.getByRole('searchbox', { name: 'Search' });
		expect(input).toHaveAttribute('id', 'search-main');
		expect(input).toHaveAttribute('placeholder', 'Search IPs, domains, devices…');
		const field = container.querySelector('label.search')!;
		expect(field).not.toHaveClass('is-toolbar');
		expect(field.querySelector('.sr-only')).toHaveTextContent('Search');
		expect(field.querySelector('svg.ic')).toHaveAttribute('aria-hidden', 'true');
		expect(field.querySelector('kbd')).toBeNull();
	});

	it('shows the shortcut hint without adding it to the name', () => {
		const { container } = render(SearchField, { id: 's', label: 'Search', kbdHint: '⌘K' });
		expect(container.querySelector('kbd')).toHaveTextContent('⌘K');
		expect(screen.getByRole('searchbox', { name: 'Search' })).toBeInTheDocument();
	});

	it('takes the toolbar size', () => {
		const { container } = render(SearchField, { id: 'f', label: 'Filter connections', size: 'toolbar' });
		expect(container.querySelector('label.search')).toHaveClass('is-toolbar');
	});

	it('passes ARIA and event attributes through to the input, so it can be a combobox', async () => {
		const oninput = vi.fn();
		render(SearchField, {
			id: 'search-main',
			label: 'Search',
			role: 'combobox',
			'aria-expanded': 'true',
			'aria-controls': 'search-results',
			'aria-autocomplete': 'list',
			autocomplete: 'off',
			oninput,
		});
		const input = screen.getByRole('combobox', { name: 'Search' });
		expect(input).toHaveAttribute('aria-expanded', 'true');
		expect(input).toHaveAttribute('aria-controls', 'search-results');
		expect(input).toHaveAttribute('aria-autocomplete', 'list');
		expect(input).toHaveAttribute('autocomplete', 'off');
		await fireEvent.input(input, { target: { value: '192.168' } });
		expect(oninput).toHaveBeenCalledOnce();
		expect(input).toHaveValue('192.168');
	});

	it('starts from the given value', () => {
		render(SearchField, { id: 's', label: 'Search', value: 'github.com' });
		expect(screen.getByRole('searchbox')).toHaveValue('github.com');
	});
});
