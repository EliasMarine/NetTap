<script lang="ts">
	/**
	 * NewDeviceBanner — Notification banner/toast for newly detected devices.
	 *
	 * Checks for devices with is_new: true from the registry and shows
	 * a dismissible banner listing them.
	 */

	import type { RegistryDevice } from '$api/devices-registry';
	import { acknowledgeDevice } from '$api/devices-registry';

	interface Props {
		devices: RegistryDevice[];
	}

	let { devices }: Props = $props();

	let dismissed = $state(false);

	let newDevices = $derived(devices.filter((d) => d.is_new));

	let visible = $derived(newDevices.length > 0 && !dismissed);

	async function dismissAll() {
		dismissed = true;
		// Acknowledge devices in background
		for (const device of newDevices) {
			await acknowledgeDevice(device.mac);
		}
	}
</script>

{#if visible}
	<div class="new-device-banner" role="alert">
		<div class="banner-content">
			<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
			</svg>
			<div class="banner-text">
				<strong>{newDevices.length} new device{newDevices.length !== 1 ? 's' : ''} detected</strong>
				<span class="device-list">
					{#each newDevices.slice(0, 3) as device, i}
						{#if i > 0}, {/if}
						<a href="/devices/mac/{encodeURIComponent(device.mac)}" class="device-link">
							{device.display_name || device.mac}
						</a>
					{/each}
					{#if newDevices.length > 3}
						<span class="text-muted"> and {newDevices.length - 3} more</span>
					{/if}
				</span>
			</div>
		</div>
		<button class="banner-dismiss" onclick={dismissAll} aria-label="Dismiss">
			<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
				<line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
			</svg>
		</button>
	</div>
{/if}

<style>
	.new-device-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		padding: var(--space-sm) var(--space-md);
		background-color: var(--cyan-dim);
		border: 1px solid rgba(0, 212, 255, 0.3);
		border-radius: var(--radius-md);
		color: var(--cyan);
		font-size: var(--text-sm);
		animation: slideDown 0.3s ease;
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
		gap: var(--space-sm);
		min-width: 0;
	}

	.banner-content svg {
		flex-shrink: 0;
	}

	.banner-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.device-list {
		font-size: var(--text-xs);
		color: var(--text-secondary);
	}

	.device-link {
		color: var(--cyan);
		font-weight: 500;
	}

	.device-link:hover {
		color: var(--accent-hover);
	}

	.banner-dismiss {
		flex-shrink: 0;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: var(--space-xs);
		border-radius: var(--radius-sm);
		transition: color var(--transition-fast);
	}

	.banner-dismiss:hover {
		color: var(--text-primary);
	}
</style>
