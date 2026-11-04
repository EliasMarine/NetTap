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
	import { compareValues } from '$lib/utils/table-sort.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

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
			// OLD CODE START — text order put 10.10.0.235 before 10.10.0.26; compareValues orders the numbers in text
			// const cmp = av < bv ? -1 : av > bv ? 1 : 0;
			// OLD CODE END
			const cmp = compareValues(av, bv);
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

	// OLD CODE START — the check glyphs (✓ ✗ !) are drawn with the system's icons now (checkIconName)
	// function checkIcon(check: DhcpCheck): string {
	// 	if (check.passed) return '✓';
	// 	return check.blocking ? '✗' : '!';
	// }
	// OLD CODE END
	function checkIconName(check: DhcpCheck): 'check' | 'close' | 'warn' {
		if (check.passed) return 'check';
		return check.blocking ? 'close' : 'warn';
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
			<p class="dim">Checking your network. This takes a few seconds…</p>
		</div>

	<!-- ==================== Error ==================== -->
	{:else if view === 'error'}
		<div class="card">
			<div class="notice is-error">
				<Icon name="warn" />
				<div><strong>Couldn't check DHCP gateway mode.</strong>
				{loadError}</div>
			</div>
			<div class="action-buttons">
				<button class="btn" onclick={load}>Retry</button>
			</div>
		</div>

	<!-- ==================== Blocked / Ready ==================== -->
	{:else if (view === 'blocked' || view === 'ready') && preflight}
		{#if actionError}
			<div class="notice is-error"><Icon name="warn" /><div>{actionError}</div></div>
		{/if}

		<div class="card">
			<div class="card-head">
				<h2 class="card-title">Before you turn it on</h2>
				{#if preflight.ready}
					<span class="chip is-ok"><Icon name="check" />Ready</span>
				{:else}
					<span class="chip is-warn"><Icon name="warn" />Not ready</span>
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
						<span class="check-icon"><Icon name={checkIconName(check)} label={check.passed ? 'Passed' : check.blocking ? 'Blocking' : 'Warning'} /></span>
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
						<p class="dim">
							Leave your router's settings as they are for now. Don't turn off its DHCP server yet: until
							NetTap is ready, your devices still need it.
						</p>
					</div>
				{:else if probeFailed}
					<div class="guide">
						<h3>NetTap couldn't check for other DHCP servers</h3>
						<p class="dim">
							This is a problem on NetTap's side, not your router's. Click <strong>Check again</strong>. If it
							keeps failing, restart NetTap and try again. Don't change your router's settings yet.
						</p>
					</div>
				{:else if showRouterGuide}
					<div class="guide">
						<h3>Turn off your router's DHCP server</h3>
						<p class="dim">
							NetTap can't hand out addresses while your router is still doing it. Two DHCP servers
							on one network give devices conflicting addresses.
						</p>
						{#if preflight.other_dhcp_servers.length > 0}
							<p class="dim">
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
						<p class="dim">
							Your devices keep their current addresses for a while, so carry straight on to the next
							step once the check passes.
						</p>
						<p class="dim">
							Can't turn it off? Some routers (often mesh systems and ISP-supplied routers) don't
							allow it. NetTap's other capture modes (Mirror and inline bridge) are chosen during
							first-time setup; switching modes after setup isn't available in the app yet.
						</p>
					</div>
				{/if}

				<div class="action-buttons">
					<button class="btn primary" onclick={checkAgain} disabled={checking}>
						{checking ? 'Checking…' : 'Check again'}
					</button>
				</div>
			{/if}
		</div>

		{#if view === 'ready'}
			<div class="card">
				<div class="card-head">
					<h2 class="card-title">Turn on the DHCP gateway</h2>
				</div>
				<ul class="fact-list">
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
					<button class="btn primary" onclick={enable} disabled={!confirmed || enabling}>
						{enabling ? 'Turning on…' : 'Enable DHCP gateway'}
					</button>
				</div>
			</div>
		{/if}

	<!-- ==================== Enabled ==================== -->
	{:else if view === 'enabled' && status}
		<div class="notice is-ok">
			<Icon name="check" />
			<div><strong>NetTap is now your network's gateway.</strong>
			Devices that get their address from NetTap show up in the dashboard with their own address.</div>
		</div>

		{#if enabledLate}
			<div class="notice is-info">
				Turning on took longer than expected, so the page lost track of it, but NetTap reports the DHCP
				gateway is on. Check the status below.
			</div>
		{/if}

		{#if captureRestartErrors.length > 0}
			<div class="notice is-warn">
				<Icon name="warn" />
				<div>Capture is still on the old settings: {captureRestartErrors.join(' ')}</div>
			</div>
		{/if}

		<div class="card">
			<div class="card-head">
				<h2 class="card-title">DHCP gateway</h2>
				{#if status.dhcp_server_running}
					<span class="chip is-ok"><Icon name="check" />Running</span>
				{:else}
					<span class="chip is-bad"><Icon name="warn" />Stopped</span>
				{/if}
			</div>

			{#if pollError}
				<div class="notice is-warn"><Icon name="warn" /><div>Couldn't refresh the status: {pollError}</div></div>
			{/if}

			<div class="stats stat-grid">
				<div class="stat">
					<div class="stat-k">DHCP server</div>
					<div class="stat-v" class:good={status.dhcp_server_running} class:bad={!status.dhcp_server_running}>
						<Icon name={status.dhcp_server_running ? 'check' : 'warn'} />{status.dhcp_server_running ? 'Running' : 'Stopped'}
					</div>
				</div>
				<div class="stat">
					<div class="stat-k">Routing</div>
					<div class="stat-v" class:good={status.routing_active} class:bad={!status.routing_active}>
						<Icon name={status.routing_active ? 'check' : 'warn'} />{status.routing_active ? 'On' : 'Off'}
					</div>
				</div>
				<div class="stat">
					<div class="stat-k">Address range</div>
					<div class="stat-v mono">{status.subnet}</div>
				</div>
				<div class="stat">
					<div class="stat-k">Devices</div>
					<div class="stat-v num">{status.leases.length}</div>
				</div>
			</div>

			{#if status.issues.length > 0}
				<div class="issues">
					<h3>Issues</h3>
					<ul>
						{#each status.issues as issue}
							<li class="issue-warn">{issue}</li>
						{/each}
					</ul>
				</div>
			{/if}
		</div>

		{#if preflight?.ipv6_router_advertisements}
			<div class="notice is-warn">
				<Icon name="warn" />
				<div><strong>Some traffic skips NetTap.</strong>
				Your router hands out IPv6 addresses, so devices send IPv6 traffic straight to the router and NetTap
				can't see it. For full visibility, turn off IPv6 in your router's settings.</div>
			</div>
		{/if}

		<div class="card">
			<div class="card-head">
				<h2 class="card-title">Finish setup</h2>
			</div>
			<ul class="fact-list">
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
			<div class="card-head">
				<h2 class="card-title">Devices with a NetTap address</h2>
				<span class="chip">{status.leases.length}</span>
			</div>
			{#if status.leases.length === 0}
				<div class="empty-state">
					<p class="empty-text">No devices yet</p>
					<p class="empty-hint">Devices appear here as they renew their address or reconnect.</p>
				</div>
			{:else}
				<div class="tbl-wrap">
					<table>
						<thead>
							<tr>
								<th class="sortable" aria-sort={ariaSort('hostname')} onclick={() => toggleSort('hostname')}>
									Device
									<Icon name="sort" class="s-none" /><Icon name="chevdown" class="s-dir" />
								</th>
								<th class="sortable" aria-sort={ariaSort('ip')} onclick={() => toggleSort('ip')}>
									IP address
									<Icon name="sort" class="s-none" /><Icon name="chevdown" class="s-dir" />
								</th>
								<th class="sortable" aria-sort={ariaSort('mac')} onclick={() => toggleSort('mac')}>
									MAC address
									<Icon name="sort" class="s-none" /><Icon name="chevdown" class="s-dir" />
								</th>
								<th class="sortable" aria-sort={ariaSort('expires')} onclick={() => toggleSort('expires')}>
									Lease expires
									<Icon name="sort" class="s-none" /><Icon name="chevdown" class="s-dir" />
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
			<div class="card-head">
				<h2 class="card-title">If your devices lose internet</h2>
			</div>
			{@render recoverySteps()}

			{#if actionError}
				<div class="notice is-error"><Icon name="warn" /><div>{actionError}</div></div>
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
						<button class="btn" onclick={() => { disableConfirmOpen = false; }} disabled={disabling}>
							Cancel
						</button>
						<button class="btn danger" onclick={disable} disabled={disabling}>
							{disabling ? 'Turning off…' : 'Yes, turn off DHCP server'}
						</button>
					</div>
				</div>
			{:else}
				<div class="action-buttons">
					<a class="btn primary" href="/">Go to dashboard</a>
					<button class="btn danger" onclick={() => { disableConfirmOpen = true; }}>
						Turn off DHCP server
					</button>
				</div>
			{/if}
		</div>

	<!-- ==================== Disabled (just turned off) ==================== -->
	{:else if view === 'disabled'}
		<div class="notice is-warn">
			<Icon name="warn" />
			<div><strong>NetTap's DHCP server is off.</strong>
			Routing through NetTap stays on, so devices with a NetTap address keep working until they move back
			to your router.</div>
		</div>
		<div class="card">
			<div class="card-head">
				<h2 class="card-title">Hand your network back to the router</h2>
			</div>
			{@render recoverySteps()}
			<div class="action-buttons">
				<button class="btn" onclick={load}>Set up the DHCP gateway again</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.dhcp-go-live {
		display: flex;
		flex-direction: column;
		gap: var(--sp-6);
	}

	.loading-card {
		display: flex;
		align-items: center;
		gap: var(--sp-4);
	}

	.loading-spinner {
		width: 24px;
		height: 24px;
		flex: none;
		border: 2px solid var(--line);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	h3 {
		font: 500 var(--text-base)/1.3 var(--font-display);
		color: var(--text-1);
		margin-bottom: var(--sp-2);
	}

	p {
		font-size: var(--text-sm);
		line-height: 1.75;
		margin-bottom: var(--sp-2);
	}

	a:not(.btn) {
		color: var(--accent-strong);
	}

	/* ----- Notices: a tint plus an icon, never colour alone ----- */
	/* ----- Checklist ----- */
	.checklist {
		list-style: none;
		padding: 0;
		margin: var(--sp-4) 0;
	}

	.checklist-item {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-3);
		padding: var(--sp-2) 0;
		border-bottom: 1px solid var(--line);
	}

	.checklist-item:last-child {
		border-bottom: none;
	}

	.check-icon {
		display: inline-flex;
		flex-shrink: 0;
		padding-top: 2px;
		color: var(--text-3);
	}

	.checklist-item.passed .check-icon {
		color: var(--ok);
	}

	.checklist-item.failed .check-icon {
		color: var(--sev-critical);
	}

	.checklist-item.warn .check-icon {
		color: var(--sev-medium);
	}

	.check-content {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
	}

	.check-name {
		font-weight: 600;
		color: var(--text-1);
	}

	.check-detail {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	/* ----- Guidance / fact lists ----- */
	.guide {
		margin-top: var(--sp-4);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	.steps,
	.fact-list {
		display: flex;
		flex-direction: column;
		gap: var(--sp-2);
		padding-left: var(--sp-6);
		margin-bottom: var(--sp-4);
	}

	.fact-list {
		list-style: disc;
	}

	.steps li,
	.fact-list li {
		font-size: var(--text-sm);
		line-height: 1.75;
		color: var(--text-2);
	}

	.steps strong,
	.fact-list strong {
		color: var(--text-1);
	}

	.caveat {
		display: block;
		margin-top: var(--sp-1);
		color: var(--sev-medium);
	}

	.confirm-box {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-2);
		padding: var(--sp-4);
		background-color: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		font-size: var(--text-sm);
		line-height: 1.75;
		color: var(--text-1);
		cursor: pointer;
	}

	.confirm-box input {
		margin-top: var(--sp-1);
	}

	.confirm-panel {
		margin-top: var(--sp-4);
		padding: var(--sp-4);
		background-color: color-mix(in srgb, var(--sev-critical) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--sev-critical) 26%, transparent);
		border-radius: var(--r-md);
		color: var(--text-1);
	}

	.action-buttons {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
		margin-top: var(--sp-4);
	}

	.btn.danger {
		color: var(--sev-critical);
	}

	/* ----- Status: the system's .stats strip ----- */
	.stat-grid {
		margin: var(--sp-4) 0;
	}

	.stat-v {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}

	.stat-v.good {
		color: var(--ok);
	}

	.stat-v.bad {
		color: var(--sev-critical);
	}

	.stat-v :global(.ic) {
		width: 20px;
		height: 20px;
	}

	.issues {
		margin-top: var(--sp-4);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	.issues ul {
		list-style: disc;
		padding-left: var(--sp-6);
	}

	.issues li {
		font-size: var(--text-sm);
		margin-bottom: var(--sp-1);
	}

	.issue-warn {
		color: var(--sev-medium);
	}

	/* ----- Empty lease list ----- */
	.empty-state {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		padding: var(--sp-4) 0;
	}

	.empty-text {
		font: 500 var(--text-md)/1.3 var(--font-display);
		color: var(--text-1);
		margin: 0;
	}

	.empty-hint {
		color: var(--text-2);
		margin: 0;
	}

	/* ----- Lease table (system.css styles the table) ----- */
	th.sortable {
		cursor: pointer;
	}

	th.sortable :global(.ic) {
		width: 12px;
		height: 12px;
		margin-left: var(--sp-1);
		stroke-width: 2.2;
		vertical-align: -1px;
	}

	@media (max-width: 768px) {
		.action-buttons {
			flex-direction: column;
		}
	}
</style>
