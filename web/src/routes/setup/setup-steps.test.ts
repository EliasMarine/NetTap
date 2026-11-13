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
// OLD CODE: function stubFetch(storage: Promise<unknown> = Promise.resolve(STORAGE)) {
function stubFetch(storage: Promise<unknown> = Promise.resolve(STORAGE), excluded: unknown = { excluded_ips: [] }) {
	const replies: Record<string, unknown> = {
		'/api/setup/nics': { interfaces: [{ name: 'eth0', type: 'ethernet', mac: '02:00:5e:00:00:01', state: 'up' }] },
		'/api/health': { status: 'ok', daemon: { status: 'ok' } },
		// OLD CODE: '/api/settings/excluded-ips': { excluded_ips: [] },
		'/api/settings/excluded-ips': excluded,
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
				// OLD CODE: return new Response(JSON.stringify(body), { status: 200 }); (A16: a body may carry its status)
				const { __status = 200, ...rest } = body as { __status?: number };
				return new Response(JSON.stringify(rest), { status: __status });
			}
			return new Response(JSON.stringify(replies[url] ?? { error: 'not mocked' }), { status: url in replies ? 200 : 404 });
		}),
	);
}

const steps = () => screen.getByRole('navigation', { name: 'Setup progress' });
const step = (name: RegExp) => within(steps()).getByRole('button', { name });

async function toInterfaces() {
	render(SetupPage, { props: { data: { username: null, setupVerified: true }, form: null } });
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
		render(SetupPage, { props: { data: { username: null, setupVerified: true }, form: null } });

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
		// OLD CODE: expect(screen.getByText('400 days')).toBeInTheDocument(); (B-m: a fixed 1.5 GB/day guess)
		expect(screen.getByText(/^No estimate yet/)).toBeInTheDocument();
	});

	it('B-m: estimates from the measured growth and says what it is based on', async () => {
		const growth = { index_bytes_per_day: 2e9, index_days_measured: 7, pcap_bytes_per_day: 66e9, pcap_days_measured: 7.4, pcap_days_kept: 7.4 };
		stubFetch(Promise.resolve({ ...STORAGE, growth_estimate: growth }));
		await toInterfaces();
		await fireEvent.change(screen.getByLabelText(/Capture interface/), { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		expect(
			await screen.findByText(
				'Estimate from the last 7 days: indices grow about 2.0 GB a day, so 90 days of them need about 180.0 GB. ' +
					'PCAP grows about 66.0 GB a day (measured over 7.4 days), so about 7.4 days of it is kept.',
			),
		).toBeInTheDocument();
	});

	it("shows NetTap's own IP as detected, not the owner's first excluded IP", async () => {
		stubFetch(Promise.resolve(STORAGE), { excluded_ips: ['203.0.113.10', '192.0.2.1'], appliance_ip: '192.0.2.1' });
		await toInterfaces();
		await fireEvent.change(screen.getByLabelText(/Capture interface/), { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		// old code: excluded_ips[0], the owner's 203.0.113.10
		await waitFor(() => expect(screen.getByLabelText('Self-traffic exclusion')).toHaveValue('192.0.2.1'));
	});

	// NET-211 #4: the field looked editable, but nothing saved what was typed
	it('shows the detected address read-only and points to Settings for other exclusions', async () => {
		stubFetch(Promise.resolve(STORAGE), { excluded_ips: [], appliance_ip: '192.0.2.1' });
		await toInterfaces();
		await fireEvent.change(screen.getByLabelText(/Capture interface/), { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		const field = await screen.findByLabelText('Self-traffic exclusion');
		await waitFor(() => expect(field).toHaveValue('192.0.2.1'));
		expect(field).toHaveAttribute('readonly');
		expect(screen.getByText(/Add other addresses in Settings › Network after setup/)).toBeInTheDocument();
	});

	it('says the address is not detected yet, with no MGMT_IP advice', async () => {
		stubFetch(Promise.resolve(STORAGE), { excluded_ips: [] });
		await toInterfaces();
		await fireEvent.change(screen.getByLabelText(/Capture interface/), { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		expect(await screen.findByText('Not detected yet')).toBeInTheDocument();
		expect(screen.queryByText(/MGMT_IP/)).not.toBeInTheDocument();
	});

	it("A16: says the disk figures are unavailable when the daemon isn't answering, with no made-up disk", async () => {
		const error = "The NetTap service isn't answering, so the disk figures are unavailable. Check that it's running, then try again.";
		stubFetch(Promise.resolve({ __status: 503, error }));
		await toInterfaces();
		await fireEvent.change(screen.getByLabelText(/Capture interface/), { target: { value: 'eth0' } });
		await fireEvent.click(screen.getByRole('button', { name: /Next/ }));

		expect(await screen.findByRole('heading', { name: 'Disk figures are unavailable' })).toBeInTheDocument();
		expect(screen.getByText(error)).toBeInTheDocument();
		expect(screen.queryByRole('meter', { name: 'Disk used' })).not.toBeInTheDocument();
		expect(screen.queryByText(/GB free/)).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Try again/ })).toBeInTheDocument();
	});
});
