import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';

const table = () => screen.getByRole('table', { name: 'Well-known ports' });
const firstPorts = (n: number) =>
	within(table())
		.getAllByRole('row')
		.slice(1, n + 1)
		.map((row) => within(row).getAllByRole('cell')[0].textContent?.trim());

describe('Port reference page', () => {
	it('starts sorted by port, ascending, and every column sorts', async () => {
		render(Page);
		expect(firstPorts(3)).toEqual(['1', '5', '7']);
		const headers = within(table()).getAllByRole('columnheader');
		expect(headers.map((h) => h.textContent?.trim())).toEqual(['Port', 'Protocol', 'Service', 'Description']);
		expect(headers[0]).toHaveAttribute('aria-sort', 'ascending');
		for (const h of headers.slice(1)) expect(h).toHaveAttribute('aria-sort', 'none');

		await fireEvent.click(within(headers[0]).getByRole('button'));
		expect(headers[0]).toHaveAttribute('aria-sort', 'descending');
		expect(firstPorts(1)).toEqual(['51413']);
	});

	it('filters by search and by protocol, and counts what it shows', async () => {
		render(Page);
		const total = screen.getByText(/^Showing \d+ of \d+ ports$/).textContent?.match(/of (\d+)/)?.[1];

		await fireEvent.input(screen.getByRole('searchbox', { name: 'Search ports' }), { target: { value: 'ssh' } });
		expect(firstPorts(2)).toEqual(['22', '2222']);
		expect(screen.getByText(`Showing 2 of ${total} ports`)).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'UDP' }));
		expect(screen.getByRole('button', { name: 'UDP' })).toHaveAttribute('aria-pressed', 'true');
		expect(screen.getByText('No ports match your search.')).toBeInTheDocument();
	});
});
