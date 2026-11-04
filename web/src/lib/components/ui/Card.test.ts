import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import Card from './Card.svelte';

const snippet = (html: string) => createRawSnippet(() => ({ render: () => html }));

describe('Card', () => {
	it('renders the system card head with an h2 title and subtitle', () => {
		const { container } = render(Card, { title: 'Bandwidth over time', sub: 'GB per hour · busiest at 21:00' });
		const card = container.querySelector('article.card')!;
		expect(card).not.toHaveClass('hero');
		expect(card).not.toHaveClass('col');
		const heading = screen.getByRole('heading', { level: 2, name: 'Bandwidth over time' });
		expect(heading).toHaveClass('card-title');
		expect(card.querySelector('.card-head > div > .card-sub')).toHaveTextContent('GB per hour · busiest at 21:00');
	});

	it('leaves the subtitle out when none is given', () => {
		const { container } = render(Card, { title: 'Top devices' });
		expect(container.querySelector('.card-sub')).toBeNull();
	});

	it('adds hero, col and the grid span class', () => {
		const { container } = render(Card, { title: 'Main chart', hero: true, col: true, class: 'c-8' });
		expect(container.querySelector('article')).toHaveClass('card', 'hero', 'col', 'c-8');
	});

	it('uses the requested heading level', () => {
		render(Card, { title: 'Nested card', headingLevel: 3 });
		expect(screen.getByRole('heading', { level: 3, name: 'Nested card' })).toHaveClass('card-title');
	});

	it('renders actions in the head, the body, and the foot in a .card-foot', () => {
		const { container } = render(Card, {
			title: 'Network protocols',
			actions: snippet('<a class="link" href="/alerts">View alerts</a>'),
			children: snippet('<p>Body text</p>'),
			foot: snippet('<span>Encrypted sessions</span>'),
		});
		expect(container.querySelector('.card-head > a.link')).toHaveTextContent('View alerts');
		expect(screen.getByText('Body text').parentElement).toBe(container.querySelector('article'));
		expect(container.querySelector('.card-foot')).toHaveTextContent('Encrypted sessions');
	});

	it('has no foot without a foot snippet', () => {
		const { container } = render(Card, { title: 'Top devices' });
		expect(container.querySelector('.card-foot')).toBeNull();
	});
});
