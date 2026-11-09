/** NET-229 follow-up: the Welcome step asks for the setup code before the wizard makes any API call. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';

type Submit = () => (opts: { result: Record<string, unknown> }) => Promise<void>;
const forms = vi.hoisted(() => ({ submits: new Map<string, Submit>() }));

// Keep each form's enhance callback, so a test can play the server's answer back to it
vi.mock('$app/forms', () => ({
	enhance: (form: HTMLFormElement, submit: Submit) => {
		forms.submits.set(form.getAttribute('action') ?? '', submit);
		return { destroy: () => {} };
	},
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import SetupPage from './+page.svelte';

function stubFetch() {
	const fetch = vi.fn(async (input: RequestInfo | URL) => {
		const body = String(input) === '/api/health' ? { status: 'ok' } : { interfaces: [] };
		return new Response(JSON.stringify(body), { status: 200 });
	});
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

async function answerVerifyCode(result: Record<string, unknown>) {
	const submit = forms.submits.get('?/verifyCode');
	expect(submit).toBeDefined();
	await submit!()({ result });
}

afterEach(() => {
	vi.unstubAllGlobals();
	forms.submits.clear();
});

describe('setup code on Welcome', () => {
	it('asks for the code and calls no API until it is in', async () => {
		const fetch = stubFetch();
		render(SetupPage, { props: { data: { username: null, setupVerified: false }, form: null } });

		expect(screen.getByLabelText('Setup code')).toBeInTheDocument();
		expect(screen.queryByText('System requirements')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Get started' })).toBeDisabled();
		expect(fetch).not.toHaveBeenCalled();
	});

	it('shows the server reason for a wrong code and stays on the code', async () => {
		stubFetch();
		render(SetupPage, { props: { data: { username: null, setupVerified: false }, form: null } });

		await answerVerifyCode({ type: 'failure', status: 400, data: { error: "That setup code isn't right." } });

		expect(await screen.findByRole('alert')).toHaveTextContent("That setup code isn't right.");
		expect(screen.getByLabelText('Setup code')).toBeInTheDocument();
	});

	it('runs the requirements check once the code is accepted', async () => {
		const fetch = stubFetch();
		render(SetupPage, { props: { data: { username: null, setupVerified: false }, form: null } });

		await answerVerifyCode({ type: 'success', status: 200, data: { verified: true } });

		expect(await screen.findByText('System requirements')).toBeInTheDocument();
		await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/setup/nics'));
		expect(screen.queryByLabelText('Setup code')).not.toBeInTheDocument();
	});

	it('never asks a browser that already typed it (or an install with an admin)', () => {
		stubFetch();
		render(SetupPage, { props: { data: { username: null, setupVerified: true }, form: null } });

		expect(screen.queryByLabelText('Setup code')).not.toBeInTheDocument();
		expect(screen.getByText('System requirements')).toBeInTheDocument();
	});
});
