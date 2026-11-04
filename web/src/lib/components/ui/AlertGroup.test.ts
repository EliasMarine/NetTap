import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import AlertGroup from './AlertGroup.svelte';

const children = createRawSnippet(() => ({ render: () => '<button type="button" class="alert-row">Row</button>' }));

describe('AlertGroup', () => {
	it('renders the group head, the plain sentence and the rows', () => {
		const { container } = render(AlertGroup, {
			title: 'Potentially Bad Traffic',
			count: 11,
			plain: 'Lookups or visits to places often used for scams or malware. Usually harmless, worth a look.',
			children,
		});
		const group = container.querySelector('section.alert-group')!;
		expect(screen.getByRole('heading', { level: 3, name: 'Potentially Bad Traffic' })).toHaveClass('group-title');
		expect(group.querySelector('.group-head > .num')).toHaveTextContent('11 alerts');
		expect(group.querySelector('.group-plain')).toHaveTextContent(/^Lookups or visits/);
		expect(group.querySelector('.alert-rows > .alert-row')).toBeInTheDocument();
	});

	it('says "1 alert" and leaves out the sentence when none is given', () => {
		const { container } = render(AlertGroup, { title: 'Not Suspicious Traffic', count: 1, children });
		expect(container.querySelector('.group-head > .num')).toHaveTextContent('1 alert');
		expect(container.querySelector('.group-head > .num')).not.toHaveTextContent('alerts');
		expect(container.querySelector('.group-plain')).toBeNull();
	});
});
