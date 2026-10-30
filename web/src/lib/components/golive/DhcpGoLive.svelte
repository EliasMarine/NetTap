<script lang="ts">
	/**
	 * DhcpGoLive — go-live flow for DHCP gateway capture mode
	 * (design 2026-10-30 §6.3 and §7).
	 *
	 * loading → error | blocked | ready → enabled → (turn off) → disabled.
	 * blocked/ready come from a fresh preflight; enabled polls status every 5 s
	 * until the view changes or the component is destroyed.
	 */
	import { onMount } from 'svelte';
	import {
		getDhcpPreflight,
		getDhcpStatus,
		enableDhcpGateway,
		disableDhcpGateway,
		DhcpGatewayError,
		type DhcpCheck,
		type DhcpLease,
		type DhcpPreflight,
		type DhcpStatus,
	} from '$api/dhcpGateway';
	import { staticAddressHint } from '$lib/utils/dhcpSubnet';

	type View = 'loading' | 'error' | 'blocked' | 'ready' | 'enabled' | 'disabled';
	type LeaseSortKey = 'hostname' | 'ip' | 'mac' | 'expires';

	const POLL_MS = 5000;
	const BOOTSTRAP_DOC_URL =
		'https://github.com/EliasMarine/NetTap/blob/develop/CLAUDE.md#opensearch-security-bootstrap-run-after-every-docker-compose-down--up';

	const CHECK_LABELS: Record<string, string> = {
		interface_up: 'Network port connected',
		upstream_detected: 'Router found',
		no_other_dhcp: "Router's DHCP server is off",
		no_subnet_conflict: 'Address range is free',
		ip_forward: 'Routing allowed',
		firewall_backend: 'Firewall ready',
		ipv6_bypass: 'IPv6 traffic',
	};

	let view = $state<View>('loading');
	let loadError = $state('');
	let actionError = $state('');
	let pollError = $state('');
	let preflight = $state<DhcpPreflight | null>(null);
	let status = $state<DhcpStatus | null>(null);
	let checking = $state(false);
	let confirmed = $state(false);
	let enabling = $state(false);
	let disableConfirmOpen = $state(false);
	let disabling = $state(false);
	// Enable answered with an error but the status shows it on (slow apply, proxy timeout)
	let enabledLate = $state(false);
	let captureRestartErrors = $state<string[]>([]);

	// The router's DHCP is on only when another server actually answered. A failed
	// no_other_dhcp check with no answers means NetTap's probe itself failed.
	let routerDhcpOn = $derived((preflight?.other_dhcp_servers.length ?? 0) > 0);
	let blockingFailures = $derived(preflight?.checks.filter((c) => c.blocking && !c.passed) ?? []);
	let probeFailed = $derived(
		!routerDhcpOn && blockingFailures.some((c) => c.name === 'no_other_dhcp')
	);
	let otherBlockingFailures = $derived(blockingFailures.filter((c) => c.name !== 'no_other_dhcp'));
	// Send the user to the router only when its DHCP is the one thing left to fix
	let showRouterGuide = $derived(routerDhcpOn && blockingFailures.length > 0 && otherBlockingFailures.length === 0);
	let recoveryHint = $derived(staticAddressHint(status?.upstream ?? preflight?.upstream ?? null));

	// ----- Data loading -----
	function errorText(e: unknown): string {
		return e instanceof Error && e.message ? e.message : 'Something went wrong.';
	}

	async function runPreflight() {
		preflight = await getDhcpPreflight();
		confirmed = false;
		view = preflight.ready ? 'ready' : 'blocked';
	}

	async function load() {
		view = 'loading';
		loadError = '';
		actionError = '';
		enabledLate = false;
		captureRestartErrors = [];
		try {
			status = await getDhcpStatus();
			if (status.dhcp_enabled) {
				view = 'enabled';
				return;
			}
			await runPreflight();
		} catch (e) {
			loadError = errorText(e);
			view = 'error';
		}
	}

	async function checkAgain() {
		checking = true;
		actionError = '';
		try {
			await runPreflight();
		} catch (e) {
			actionError = errorText(e);
		}
		checking = false;
	}

	async function poll() {
		try {
			status = await getDhcpStatus();
			pollError = '';
		} catch (e) {
			pollError = errorText(e);
		}
	}

	onMount(() => {
		load();
	});

	$effect(() => {
		if (view !== 'enabled') return;
		const id = setInterval(poll, POLL_MS);
		return () => clearInterval(id);
	});

	// ----- Actions -----
	async function enable() {
		if (!confirmed) return;
		enabling = true;
		actionError = '';
		try {
			const result = await enableDhcpGateway();
			captureRestartErrors = result.capture_restart?.errors ?? [];
			status = result;
			view = 'enabled';
		} catch (e) {
			actionError = errorText(e);
			if (e instanceof DhcpGatewayError && e.checks && preflight) {
				// 409: a fresh preflight on the daemon failed. Its body has only the
				// checks, so reload the preflight to know which DHCP servers answered.
				const checks = e.checks;
				try {
					await runPreflight();
				} catch {
					preflight = { ...preflight, checks, ready: false };
					view = 'blocked';
				}
			} else if (await turnedOnAnyway()) {
				actionError = '';
				enabledLate = true;
				view = 'enabled';
			}
		}
		enabling = false;
	}

	/** After an enable error: true (and status set) if the daemon reports it on anyway. */
	async function turnedOnAnyway(): Promise<boolean> {
		try {
			const current = await getDhcpStatus();
			// Routing alone survives a failed re-enable (dnsmasq didn't start), so
			// only the DHCP server being on counts as success.
			if (!current.dhcp_enabled) return false;
			status = current;
			return true;
		} catch {
			return false;
		}
	}

	async function disable() {
		disabling = true;
		actionError = '';
		try {
			status = await disableDhcpGateway();
			disableConfirmOpen = false;
			view = 'disabled';
		} catch (e) {
			actionError = errorText(e);
		}
		disabling = false;
	}

	// ----- Lease table sorting -----
	let sortField = $state<LeaseSortKey>('ip');
	let sortDir = $state<'asc' | 'desc'>('asc');

	function toggleSort(field: LeaseSortKey) {
		if (sortField === field) {
			sortDir = sortDir === 'desc' ? 'asc' : 'desc';
		} else {
			sortField = field;
			sortDir = 'desc';
		}
	}

	function ipToNumber(ip: string): number {
		return ip.split('.').reduce((n, octet) => n * 256 + Number(octet), 0);
	}

	function sortValue(lease: DhcpLease, field: LeaseSortKey): string | number {
		if (field === 'ip') return ipToNumber(lease.ip);
		if (field === 'expires') return lease.expires;
		return (lease[field] || '').toLowerCase();
	}

	let sortedLeases = $derived(
		[...(status?.leases ?? [])].sort((a, b) => {
			const av = sortValue(a, sortField);
			const bv = sortValue(b, sortField);
			const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			return sortDir === 'asc' ? cmp : -cmp;
		})
	);

	function ariaSort(field: LeaseSortKey): 'ascending' | 'descending' | 'none' {
		if (sortField !== field) return 'none';
		return sortDir === 'asc' ? 'ascending' : 'descending';
	}

	// ----- Formatting -----
	function checkLabel(check: DhcpCheck): string {
		if (check.name === 'no_other_dhcp' && probeFailed) return 'Check for other DHCP servers';
		return CHECK_LABELS[check.name] ?? check.name.replace(/_/g, ' ');
	}

	function checkIcon(check: DhcpCheck): string {
		if (check.passed) return '✓';
		return check.blocking ? '✗' : '!';
	}

	function hostnameLabel(hostname: string): string {
		return hostname && hostname !== '*' ? hostname : 'Unknown device';
	}

	function formatExpires(expires: number): string {
		if (!expires) return 'Never';
		const mins = Math.round((expires * 1000 - Date.now()) / 60_000);
		if (mins <= 0) return 'Expired';
		return mins < 60 ? `in ${mins} min` : `in ${Math.floor(mins / 60)} h ${mins % 60} min`;
	}
</script>

{#snippet recoverySteps()}
	<ol class="steps">
		<li>
			<strong>Turn your router's DHCP server back on.</strong> While NetTap is off nothing hands out
			addresses, so first give a laptop a fixed address on your router's network: plug it into the router
			(or join its Wi-Fi) and set its IP address manually,
			{#if recoveryHint}
				<span class="mono">IP {recoveryHint.ip}, mask {recoveryHint.mask}</span>, then open
				<span class="mono">http://{recoveryHint.router}</span>
			{:else}
				using a free address in the router's range, then open the router's address in a browser (it is
				often on a sticker on the router)
			{/if}
			and turn the DHCP server on. If you manage your router with a phone app (most mesh systems), use the
			app instead, on mobile data if your Wi-Fi has no internet.
		</li>
		<li>
			Reconnect your devices (turn Wi-Fi off and on, or unplug and replug the cable). They get an
			address from the router straight away; otherwise they move over when their NetTap address runs out
			(within an hour). Set the laptop back to getting its address automatically.
		</li>
		<li>Once NetTap is healthy again, come back to Go Live to switch the DHCP gateway back on.</li>
	</ol>
{/snippet}

<div class="dhcp-go-live">
	<!-- ==================== Loading ==================== -->
	{#if view === 'loading'}
		<div class="card loading-card">
			<div class="loading-spinner"></div>
			<p class="text-muted">Checking your network. This takes a few seconds...</p>
		</div>

	<!-- ==================== Error ==================== -->
	{:else if view === 'error'}
		<div class="card">
			<div class="alert alert-danger">
				<strong>Couldn't check DHCP gateway mode.</strong>
				{loadError}
			</div>
			<div class="action-buttons">
				<button class="btn btn-secondary" onclick={load}>Retry</button>
			</div>
		</div>

	<!-- ==================== Blocked / Ready ==================== -->
	{:else if (view === 'blocked' || view === 'ready') && preflight}
		{#if actionError}
			<div class="alert alert-danger">{actionError}</div>
		{/if}

		<div class="card">
			<div class="card-header">
				<h2 class="card-title">Before you turn it on</h2>
				{#if preflight.ready}
					<span class="badge badge-success">Ready</span>
				{:else}
					<span class="badge badge-warning">Not ready</span>
				{/if}
			</div>

			<ul class="checklist">
				{#each preflight.checks as check}
					<li
						class="checklist-item"
						class:passed={check.passed}
						class:failed={!check.passed && check.blocking}
						class:warn={!check.passed && !check.blocking}
					>
						<span class="check-icon">{checkIcon(check)}</span>
						<div class="check-content">
							<span class="check-name">{checkLabel(check)}</span>
							{#if check.message}
								<span class="check-detail">{check.message}</span>
							{/if}
						</div>
					</li>
				{/each}
			</ul>

			{#if view === 'blocked'}
				{#if otherBlockingFailures.length > 0}
					<div class="guide">
						<h3>Fix the problems above first</h3>
						<p class="text-muted">
							Leave your router's settings as they are for now. Don't turn off its DHCP server yet: until
							NetTap is ready, your devices still need it.
						</p>
					</div>
				{:else if probeFailed}
					<div class="guide">
						<h3>NetTap couldn't check for other DHCP servers</h3>
						<p class="text-muted">
							This is a problem on NetTap's side, not your router's. Click <strong>Check again</strong>. If it
							keeps failing, restart NetTap and try again. Don't change your router's settings yet.
						</p>
					</div>
				{:else if showRouterGuide}
					<div class="guide">
						<h3>Turn off your router's DHCP server</h3>
						<p class="text-muted">
							NetTap can't hand out addresses while your router is still doing it. Two DHCP servers
							on one network give devices conflicting addresses.
						</p>
						{#if preflight.other_dhcp_servers.length > 0}
							<p class="text-muted">
								Still answering:
								{#each preflight.other_dhcp_servers as server, i}
									<span class="mono">{server.server_ip}</span>{i < preflight.other_dhcp_servers.length - 1 ? ', ' : ''}
								{/each}
							</p>
						{/if}
						<ol class="steps">
							<li>
								Open your router's admin page in a browser{#if preflight.upstream}
									(try <span class="mono">http://{preflight.upstream.gateway}</span>){/if}.
								The address and password are often on a sticker on the router. If you manage your router
								with a phone app (most mesh systems), look for the setting in the app.
							</li>
							<li>Find the DHCP server setting. It is usually under LAN, Network or Advanced.</li>
							<li>Turn the DHCP server off and save. Leave everything else as it is.</li>
							<li>Come back here and click <strong>Check again</strong>.</li>
						</ol>
						<p class="text-muted">
							Your devices keep their current addresses for a while, so carry straight on to the next
							step once the check passes.
						</p>
						<p class="text-muted">
							Can't turn it off? Some routers (often mesh systems and ISP-supplied routers) don't
							allow it. NetTap's other capture modes (Mirror and inline bridge) are chosen during
							first-time setup; switching modes after setup isn't available in the app yet.
						</p>
					</div>
				{/if}

				<div class="action-buttons">
					<button class="btn btn-primary" onclick={checkAgain} disabled={checking}>
						{checking ? 'Checking...' : 'Check again'}
					</button>
				</div>
			{/if}
		</div>

		{#if view === 'ready'}
			<div class="card">
				<div class="card-header">
					<h2 class="card-title">Turn on the DHCP gateway</h2>
				</div>
				<ul class="facts">
					<li>
						NetTap starts handing out addresses in <span class="mono">{preflight.subnet}</span> and becomes
						your devices' gateway (<span class="mono">{preflight.gateway_ip}</span>). Your router
						{#if preflight.upstream}(<span class="mono">{preflight.upstream.gateway}</span>){/if} still
						connects you to the internet.
					</li>
					<li>
						Devices move over when their current address from the router runs out (often up to a day),
						or straight away if you reconnect them (turn Wi-Fi off and on, or unplug and replug the cable).
					</li>
					<li>Devices with a fixed IP address keep going straight to the router, so NetTap won't see them.</li>
				</ul>

				<label class="confirm-box">
					<input type="checkbox" bind:checked={confirmed} />
					<span>
						I understand NetTap becomes my network's gateway. If NetTap is off or stops working, devices
						that got their address from NetTap lose internet until I turn my router's DHCP server back on.
					</span>
				</label>

				<div class="action-buttons">
					<button class="btn btn-primary btn-lg" onclick={enable} disabled={!confirmed || enabling}>
						{enabling ? 'Turning on...' : 'Enable DHCP gateway'}
					</button>
				</div>
			</div>
		{/if}

	<!-- ==================== Enabled ==================== -->
	{:else if view === 'enabled' && status}
		<div class="alert alert-success">
			<strong>NetTap is now your network's gateway.</strong>
			Devices that get their address from NetTap show up in the dashboard with their own address.
		</div>

		{#if enabledLate}
			<div class="alert alert-info">
				Turning on took longer than expected, so the page lost track of it, but NetTap reports the DHCP
				gateway is on. Check the status below.
			</div>
		{/if}

		{#if captureRestartErrors.length > 0}
			<div class="alert alert-warning">
				Capture is still on the old settings: {captureRestartErrors.join(' ')}
			</div>
		{/if}

		<div class="card">
			<div class="card-header">
				<h2 class="card-title">DHCP gateway</h2>
				{#if status.dhcp_server_running}
					<span class="badge badge-success">Running</span>
				{:else}
					<span class="badge badge-danger">Stopped</span>
				{/if}
			</div>

			{#if pollError}
				<div class="alert alert-warning">Couldn't refresh the status: {pollError}</div>
			{/if}

			<div class="grid grid-cols-4 stat-grid">
				<div class="stat">
					<span class="stat-label">DHCP server</span>
					<span class="stat-value" class:text-success={status.dhcp_server_running} class:text-danger={!status.dhcp_server_running}>
						{status.dhcp_server_running ? 'Running' : 'Stopped'}
					</span>
				</div>
				<div class="stat">
					<span class="stat-label">Routing</span>
					<span class="stat-value" class:text-success={status.routing_active} class:text-danger={!status.routing_active}>
						{status.routing_active ? 'On' : 'Off'}
					</span>
				</div>
				<div class="stat">
					<span class="stat-label">Address range</span>
					<span class="stat-value mono">{status.subnet}</span>
				</div>
				<div class="stat">
					<span class="stat-label">Devices</span>
					<span class="stat-value mono">{status.leases.length}</span>
				</div>
			</div>

			{#if status.issues.length > 0}
				<div class="issues">
					<h3>Issues</h3>
					<ul>
						{#each status.issues as issue}
							<li class="text-warning">{issue}</li>
						{/each}
					</ul>
				</div>
			{/if}
		</div>

		{#if preflight?.ipv6_router_advertisements}
			<div class="alert alert-warning">
				<strong>Some traffic skips NetTap.</strong>
				Your router hands out IPv6 addresses, so devices send IPv6 traffic straight to the router and NetTap
				can't see it. For full visibility, turn off IPv6 in your router's settings.
			</div>
		{/if}

		<div class="card">
			<div class="card-header">
				<h2 class="card-title">Finish setup</h2>
			</div>
			<ul class="facts">
				<li>
					<strong>Restart NetTap once.</strong> This makes NetTap's own address on your router's network
					permanent. Until then NetTap's own updates (threat feeds, GeoIP) may briefly fail; your devices
					are not affected.
					<span class="caveat">
						After the restart, run the OpenSearch security bootstrap or the dashboard shows no data. On the
						NetTap device, from the NetTap folder, run <span class="mono">bash scripts/remote/fix-opensearch.sh</span>
						(<a href={BOOTSTRAP_DOC_URL} target="_blank" rel="noopener noreferrer">bootstrap steps</a>).
					</span>
				</li>
				<li>
					<strong>Double NAT.</strong> Your router now sees all traffic coming from NetTap. Port forwards
					and UPnP on the router won't reach your devices, and game consoles may report a strict NAT type.
				</li>
			</ul>
		</div>

		<div class="card">
			<div class="card-header">
				<h2 class="card-title">Devices with a NetTap address</h2>
				<span class="badge badge-muted">{status.leases.length}</span>
			</div>
			{#if status.leases.length === 0}
				<div class="empty-state">
					<p class="empty-text">No devices yet</p>
					<p class="empty-hint">Devices appear here as they renew their address or reconnect.</p>
				</div>
			{:else}
				<div class="table-wrap">
					<table class="data-table">
						<thead>
							<tr>
								<th class="sortable" class:sorted={sortField === 'hostname'} aria-sort={ariaSort('hostname')} onclick={() => toggleSort('hostname')}>
									Device
									{#if sortField === 'hostname'}<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'ip'} aria-sort={ariaSort('ip')} onclick={() => toggleSort('ip')}>
									IP address
									{#if sortField === 'ip'}<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'mac'} aria-sort={ariaSort('mac')} onclick={() => toggleSort('mac')}>
									MAC address
									{#if sortField === 'mac'}<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>{/if}
								</th>
								<th class="sortable" class:sorted={sortField === 'expires'} aria-sort={ariaSort('expires')} onclick={() => toggleSort('expires')}>
									Lease expires
									{#if sortField === 'expires'}<span class="sort-arrow">{sortDir === 'desc' ? '↓' : '↑'}</span>{/if}
								</th>
							</tr>
						</thead>
						<tbody>
							{#each sortedLeases as lease}
								<tr>
									<td>{hostnameLabel(lease.hostname)}</td>
									<td class="mono">{lease.ip}</td>
									<td class="mono">{lease.mac}</td>
									<td class="mono">{formatExpires(lease.expires)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<div class="card">
			<div class="card-header">
				<h2 class="card-title">If your devices lose internet</h2>
			</div>
			{@render recoverySteps()}

			{#if actionError}
				<div class="alert alert-danger">{actionError}</div>
			{/if}

			{#if disableConfirmOpen}
				<div class="confirm-panel">
					<p>
						<strong>Turn your router's DHCP server back on first.</strong> If NetTap's DHCP server goes off
						while the router's is still off, devices lose internet when their NetTap address runs out
						(within an hour). Routing through NetTap stays on, so devices keep working until they move back
						to the router.
					</p>
					<div class="action-buttons">
						<button class="btn btn-secondary" onclick={() => { disableConfirmOpen = false; }} disabled={disabling}>
							Cancel
						</button>
						<button class="btn btn-danger" onclick={disable} disabled={disabling}>
							{disabling ? 'Turning off...' : 'Yes, turn off DHCP server'}
						</button>
					</div>
				</div>
			{:else}
				<div class="action-buttons">
					<a class="btn btn-primary" href="/">Go to Dashboard</a>
					<button class="btn btn-danger" onclick={() => { disableConfirmOpen = true; }}>
						Turn off DHCP server
					</button>
				</div>
			{/if}
		</div>

	<!-- ==================== Disabled (just turned off) ==================== -->
	{:else if view === 'disabled'}
		<div class="alert alert-warning">
			<strong>NetTap's DHCP server is off.</strong>
			Routing through NetTap stays on, so devices with a NetTap address keep working until they move back
			to your router.
		</div>
		<div class="card">
			<div class="card-header">
				<h2 class="card-title">Hand your network back to the router</h2>
			</div>
			{@render recoverySteps()}
			<div class="action-buttons">
				<button class="btn btn-secondary" onclick={load}>Set up the DHCP gateway again</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.dhcp-go-live {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.loading-card {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	h3 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	p {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
		margin-bottom: var(--space-sm);
	}

	a:not(.btn) {
		color: var(--text-link);
	}

	/* ----- Checklist ----- */
	.checklist {
		list-style: none;
		padding: 0;
		margin: var(--space-md) 0;
	}

	.checklist-item {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.checklist-item:last-child {
		border-bottom: none;
	}

	.check-icon {
		flex-shrink: 0;
		width: var(--space-lg);
		text-align: center;
		font-size: var(--text-lg);
		line-height: var(--leading-tight);
		color: var(--text-muted);
	}

	.checklist-item.passed .check-icon {
		color: var(--success);
	}

	.checklist-item.failed .check-icon {
		color: var(--danger);
	}

	.checklist-item.warn .check-icon {
		color: var(--warning);
	}

	.check-content {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.check-name {
		font-weight: 600;
		color: var(--text-primary);
	}

	.check-detail {
		font-size: var(--text-sm);
		color: var(--text-secondary);
	}

	/* ----- Guidance / facts ----- */
	.guide {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-default);
	}

	.steps,
	.facts {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		padding-left: var(--space-lg);
		margin-bottom: var(--space-md);
	}

	.facts {
		list-style: disc;
	}

	.steps li,
	.facts li {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
		color: var(--text-secondary);
	}

	.steps strong,
	.facts strong {
		color: var(--text-primary);
	}

	.caveat {
		display: block;
		margin-top: var(--space-xs);
		color: var(--warning);
	}

	.confirm-box {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		padding: var(--space-md);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
		color: var(--text-primary);
		cursor: pointer;
	}

	.confirm-box input {
		margin-top: var(--space-xs);
		accent-color: var(--accent);
	}

	.confirm-panel {
		margin-top: var(--space-md);
		padding: var(--space-md);
		background-color: var(--danger-muted);
		border: 1px solid var(--danger);
		border-radius: var(--radius-md);
		color: var(--text-primary);
	}

	.action-buttons {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-md);
		margin-top: var(--space-md);
	}

	/* ----- Status ----- */
	.stat-grid {
		margin: var(--space-md) 0;
	}

	.stat {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		padding: var(--space-sm);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-muted);
		border-radius: var(--radius-md);
	}

	.stat-label {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.stat-value {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
	}

	.issues {
		margin-top: var(--space-md);
		padding-top: var(--space-md);
		border-top: 1px solid var(--border-default);
	}

	.issues ul {
		list-style: disc;
		padding-left: var(--space-lg);
	}

	.issues li {
		font-size: var(--text-sm);
		margin-bottom: var(--space-xs);
	}

	/* ----- Lease table ----- */
	.table-wrap {
		overflow-x: auto;
		background: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
	}

	.data-table th.sorted {
		color: var(--accent);
	}

	.sort-arrow {
		color: var(--accent);
		margin-left: var(--space-xs);
	}

	@media (max-width: 768px) {
		.action-buttons {
			flex-direction: column;
		}
	}
</style>
