/** The redesigned wizard frame: the page heading, the pill step indicator and the storage card. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/svelte';

vi.mock('$app/forms', () => ({ enhance: () => ({ destroy: () => {} }) }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import SetupPage from './+page.svelte';

const STORAGE = {
	disk_total_gb: 1000, disk_used_gb: 250, disk_free_gb: 750, disk_usage_percent: 25,
	hot_days: 90, warm_days: 180, cold_days: 30, disk_threshold_percent: 80, emergency_threshold_percent: 90,
	estimated_daily_gb: 1.5, source: 'daemon',
};

/** Every GET the wizard makes answers; `storage` can be held back to see the loading state. */
function stubFetch(storage: Promise<unknown> = Promise.resolve(STORAGE)) {
	const replies: Record<string, unknown> = {
		'/api/setup/nics': { interfaces: [{ name: 'eth0', type: 'ethernet', mac: '02:00:5e:00:00:01', state: 'up' }] },
		'/api/health': { status: 'ok', daemon: { status: 'ok' } },
		'/api/settings/excluded-ips': { excluded_ips: [] },
	};
	let storageCalls = 0;
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			// the requirements check reads storage too; only the Storage step's read is held back
			if (url === '/api/setup/storage') {
				storageCalls++;
				const body = storageCalls === 1 ? STORAGE : await storage;
				return new Response(JSON.stringify(body), { status: 200 });
			}
			return new Response(JSON.stringify(replies[url] ?? { error: 'not mocked' }), { status: url in replies ? 200 : 404 });
		}),
	);
}

const steps = () => screen.getByRole('navigation', { name: 'Setup progress' });
const step = (name: RegExp) => within(steps()).getByRole('button', { name });

async function toInterfaces() {
	render(SetupPage, { props: { form: null } });
	const start = await screen.findByRole('button', { name: /Get started/ });
	await waitFor(() => expect(start).not.toBeDisabled());
	await fireEvent.click(start);
	await fireEvent.click(await screen.findByRole('button', { name: /Mirror \/ SPAN/ }));
	await fireEvent.click(screen.getByRole('button', { name: /Next/ }));
	await screen.findByRole('heading', { name: 'Select capture interface' });
}

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('setup wizard frame', () => {
	it('has one page heading and starts on Welcome, with later steps disabled', async () => {
		stubFetch();
		render(SetupPage, { props: { form: null } });

		expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
		expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Set up NetTap');
		expect(screen.getByRole('heading', { name: 'Welcome to NetTap' })).toBeInTheDocument();
		expect(step(/Welcome/)).toHaveAttribute('aria-current', 'step');
		expect(step(/Capture mode/)).toBeDisabled();
		expect(await screen.findByRole('img', { name: 'Passed' })).toBeInTheDocument();
	});

	it('marks finished steps done, and a done step takes you back', async () => {
		stubFetch();
		await toInterfaces();

		expect(screen.getByText('Step 3 of 7 · Interfaces')).toBeInTheDocument();
		expect(step(/Interfaces/)).toHaveAttribute('aria-current', 'step');
		expect(within(step(/Welcome/)).getByRole('img', { name: 'Done' })).toBeInTheDocument();
		expect(step(/Storage/)).toBeDisabled();

		await fireEvent.click(step(/Capture mode/));
		expect(await screen.findByRole('heading', { name: 'Choose capture mode' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Mirror \/ SPAN/ })).toHaveAttribute('aria-pressed', 'true');
	});

	it('shows the storage card loading, then the disk meter', async () => {
		let release!: (v: unknown) => void;
		stubFetch(new Promise((r) => (release = r)));
		await toInterfaces();
		await fireEvent.change(screen.getByLabelText(/Capture interface/), { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		expect(await screen.findByRole('status')).toHaveTextContent('Loading storage information');
		release(STORAGE);

		const meter = await screen.findByRole('meter', { name: 'Disk used' });
		expect(meter).toHaveAttribute('aria-valuenow', '25');
		expect(screen.getByText('25% used')).toBeInTheDocument();
		expect(screen.getByText('400 days')).toBeInTheDocument();
	});
});
