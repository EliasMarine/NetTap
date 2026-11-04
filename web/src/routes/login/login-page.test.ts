/** The login card: brand heading, the form the e2e specs name, and the error notice. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import LoginPage from './+page.svelte';

vi.mock('$app/forms', () => ({ enhance: () => ({ destroy: () => {} }) }));

describe('Login page', () => {
	it('shows the brand heading and the form, with no error', () => {
		render(LoginPage, { props: { form: null } });

		expect(screen.getByRole('heading', { level: 1, name: 'NetTap' })).toBeInTheDocument();
		expect(screen.getByLabelText('Username')).toHaveAttribute('autocomplete', 'username');
		expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
		// e2e/login.spec.ts, e2e/shell.spec.ts and e2e/visual/auth.setup.ts click this button by name
		expect(screen.getByRole('button', { name: 'Sign In' })).toHaveAttribute('type', 'submit');
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});

	it('shows a failed sign-in as an error notice and keeps the username', () => {
		render(LoginPage, { props: { form: { error: 'Invalid username or password.', username: 'admin' } } });

		const alert = screen.getByRole('alert');
		expect(alert).toHaveClass('notice', 'is-error');
		expect(alert).toHaveTextContent('Invalid username or password.');
		expect(screen.getByLabelText('Username')).toHaveValue('admin');
	});
});
