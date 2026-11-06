<script lang="ts">
	/**
	 * NewDeviceBanner — Notification banner/toast for newly detected devices.
	 *
	 * Lists devices first seen in the last 24 hours (the New chip's rule) in a
	 * dismissible banner; a dismissal holds until a newer device appears.
	 */

	import type { RegistryDevice } from '$api/devices-registry';
	import { acknowledgeDevice, isNewDevice } from '$api/devices-registry';
	import Icon from '$lib/components/ui/Icon.svelte';

	interface Props {
		devices: RegistryDevice[];
	}

	let { devices }: Props = $props();

	// OLD CODE START — PR #174 review: is_new clears on the device's next registry update, so
	// the banner disagreed with the New chip and the "New in 24 h" count (NET-158)
	// let dismissed = $state(false);
	//
	// let newDevices = $derived(devices.filter((d) => d.is_new));
	//
	// let visible = $derived(newDevices.length > 0 && !dismissed);
	//
	// async function dismissAll() {
	// 	dismissed = true;
	// 	// Acknowledge devices in background
	// 	for (const device of newDevices) {
	// 		await acknowledgeDevice(device.mac);
	// 	}
	// }
	// OLD CODE END

	/** First-seen time of the newest device the user dismissed; anything newer shows again. */
	const DISMISSED_KEY = 'nettap-new-devices-dismissed';

	function readDismissed(): number {
		try {
			return Number(localStorage.getItem(DISMISSED_KEY)) || 0;
		} catch {
			return 0; // storage blocked: the dismissal lasts until the page reloads
		}
	}

	let dismissedThrough = $state(readDismissed());

	// The New chip's rule, so the banner, the chip and the count agree
	let newDevices = $derived(devices.filter((d) => isNewDevice(d) && Date.parse(d.first_seen) > dismissedThrough));

	let visible = $derived(newDevices.length > 0);

	async function dismissAll() {
		const shown = newDevices;
		dismissedThrough = Math.max(...shown.map((d) => Date.parse(d.first_seen)));
		try {
			localStorage.setItem(DISMISSED_KEY, String(dismissedThrough));
		} catch {
			// storage blocked: the dismissal lasts until the page reloads
		}
		for (const device of shown) {
			await acknowledgeDevice(device.mac);
		}
	}
</script>

{#if visible}
	<div class="new-device-banner" role="alert">
		<div class="banner-content">
			<span class="banner-icon"><Icon name="devices" /></span>
			<div class="banner-text">
				<strong>{newDevices.length} new device{newDevices.length !== 1 ? 's' : ''} detected</strong>
				<span class="device-list">
					{#each newDevices.slice(0, 3) as device, i}
						{#if i > 0}, {/if}
						<a href="/devices/mac/{encodeURIComponent(device.mac)}" class="link device-link">
							{device.display_name || device.mac}
						</a>
					{/each}
					{#if newDevices.length > 3}
						<span class="dim"> and {newDevices.length - 3} more</span>
					{/if}
				</span>
			</div>
		</div>
		<button class="icon-btn ghost banner-dismiss" onclick={dismissAll} aria-label="Dismiss">
			<Icon name="close" />
		</button>
	</div>
{/if}

<style>
	.new-device-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-4);
		padding: var(--sp-2) var(--sp-2) var(--sp-2) var(--sp-4);
		background-color: color-mix(in srgb, var(--accent) 8%, transparent);
		border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent);
		border-radius: var(--r-md);
		color: var(--text-1);
		font-size: var(--text-sm);
		animation: slideDown 0.3s var(--ease);
	}

	@keyframes slideDown {
		from {
			opacity: 0;
			transform: translateY(-8px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.banner-content {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		min-width: 0;
	}

	.banner-icon {
		display: inline-flex;
		flex-shrink: 0;
		color: var(--accent-strong);
	}

	.banner-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.device-list {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	/* .link is inline-flex; keep the comma-separated names on one line of text. */
	.device-link {
		display: inline;
	}
</style>
