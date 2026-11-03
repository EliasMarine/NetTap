<script lang="ts">
	import { validateDhcpSubnet, DEFAULT_DHCP_SUBNET } from '$lib/utils/dhcpSubnet';

	let {
		subnet = $bindable(DEFAULT_DHCP_SUBNET),
		valid = $bindable(false),
		nicAddresses = [],
		selectedInterface = '',
	}: {
		subnet?: string;
		valid?: boolean;
		nicAddresses?: string[];
		selectedInterface?: string;
	} = $props();

	let check = $derived(validateDhcpSubnet(subnet, nicAddresses));

	// Lets the wizard gate its Next button on the same check the user sees.
	$effect(() => {
		valid = check.valid;
	});
</script>

<div class="dhcp-step">
	<div class="form-group">
		<label for="dhcp-subnet" class="label">
			Subnet for your devices
			<span class="text-muted">(NetTap hands out addresses from this range)</span>
		</label>
		<input
			id="dhcp-subnet"
			type="text"
			class="input mono"
			bind:value={subnet}
			autocomplete="off"
			spellcheck="false"
			aria-invalid={!check.valid}
			aria-describedby="dhcp-subnet-hint"
		/>
		<p id="dhcp-subnet-hint" class="field-hint" class:error={!check.valid} aria-live="polite">
			{check.valid ? 'Looks good. The default works for almost every home network.' : check.error}
		</p>
	</div>

	<section class="info-section">
		<h3>What happens next</h3>
		<ol>
			<li>Nothing changes on your network yet. At Go Live you'll turn off your router's DHCP server.</li>
			<li>
				NetTap then hands out addresses on this subnet from
				<span class="mono">{selectedInterface || 'the port plugged into your router'}</span>
				and routes your devices' traffic on to your router.
			</li>
			<li>Every device shows up in NetTap under its own address, so you can see what each one is doing.</li>
		</ol>
	</section>

	<section class="info-section">
		<h3>Good to know</h3>
		<ul>
			<li>
				Your router will see all your devices as NetTap (double NAT). Port forwards and UPnP set up on the
				router won't reach your devices, and game consoles may report a strict NAT.
			</li>
			<li>
				If your router hands out IPv6 addresses, that traffic can go around NetTap. Turn off IPv6 on the
				router to see everything.
			</li>
			<li>Devices with a manually set IP address keep talking to the router directly, so NetTap won't see them.</li>
			<li>
				NetTap must stay powered on. If it's off, devices that got their address from NetTap lose internet
				until you turn your router's DHCP back on.
			</li>
		</ul>
	</section>
</div>

<style>
	.dhcp-step {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
	}

	.field-hint {
		margin-top: var(--space-xs);
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.field-hint.error {
		color: var(--danger);
	}

	.info-section {
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-lg);
	}

	.info-section h3 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.info-section ol,
	.info-section ul {
		padding-left: var(--space-lg);
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: var(--leading-relaxed);
	}

	.info-section li {
		margin-bottom: var(--space-xs);
	}
</style>
