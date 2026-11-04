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
			<span class="dim">(NetTap hands out addresses from this range)</span>
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
		<p id="dhcp-subnet-hint" class="field-help field-hint" class:field-error={!check.valid} aria-live="polite">
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
		gap: var(--sp-6);
	}

	/* .field-help and .field-error (forms.css) set the type and colour. */
	.field-hint {
		margin-top: var(--sp-1);
	}

	.dim {
		font-weight: 400;
	}

	.info-section {
		background-color: var(--surface-2);
		border: 1px solid var(--line);
		border-radius: var(--r-md);
		padding: var(--sp-5);
	}

	.info-section h3 {
		font: 500 var(--text-md)/1.3 var(--font-display);
		letter-spacing: -0.01em;
		color: var(--text-1);
		margin-bottom: var(--sp-2);
	}

	.info-section ol,
	.info-section ul {
		padding-left: var(--sp-6);
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.75;
	}

	.info-section li {
		margin-bottom: var(--sp-1);
	}
</style>
