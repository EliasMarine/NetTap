<!--
  DeviceCustomise.svelte (NET-200): the owner names a device and gives it an icon or a photo.
  Two buttons open inline panels in the device's hero card (no modal). The page owns the save
  (`onsave`): it checks the device is still the one on screen before it shows the result, and
  this component reports the daemon's reason when a save fails. One save at a time.
-->
<script lang="ts">
	import { tick } from 'svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import DeviceTile from '$lib/components/ui/DeviceTile.svelte';
	import {
		DEVICE_ICONS,
		setDeviceName,
		clearDeviceName,
		setDevicePicture,
		clearDevicePicture,
		type DeviceIcon,
		type RegistryDevice,
	} from '$api/devices-registry';
	import { squarePicture } from '$lib/utils/device-picture';

	type Save = (action: (mac: string) => Promise<RegistryDevice>) => Promise<void>;
	let { device, onsave }: { device: RegistryDevice; onsave: Save } = $props();

	/** Plain names for the built-in icons, read by screen readers and shown on hover. */
	const ICON_LABELS: Record<DeviceIcon, string> = {
		laptop: 'Computer',
		phone: 'Phone',
		tablet: 'Tablet',
		tv: 'TV',
		nas: 'Network storage',
		gamepad: 'Games console',
		camera: 'Camera',
		speaker: 'Speaker',
		printer: 'Printer',
		iot: 'Smart device',
		infra: 'Network equipment',
		devices: 'Other device',
	};

	let panel = $state<'none' | 'name' | 'picture'>('none');
	let saving = $state(false);
	let error = $state<string | null>(null);
	let nameDraft = $state('');
	/** The picture the owner has chosen in the panel, not saved yet. */
	let choice = $state<{ icon: DeviceIcon } | { image: string } | null>(null);
	let reading = $state(false);
	/** Read out politely after a save (a screen reader otherwise hears nothing as the panel closes). */
	let announcement = $state('');
	let nameButton = $state<HTMLButtonElement>();
	let pictureButton = $state<HTMLButtonElement>();

	// Locally administered (randomised, "private") MACs set bit 0x02 of the first octet
	const randomised = $derived((parseInt(device.mac.slice(0, 2), 16) & 0x02) === 0x02);
	const hasPicture = $derived(!!device.icon || !!device.picture);

	function open(which: 'name' | 'picture'): void {
		error = null;
		if (panel === which) {
			panel = 'none';
			return;
		}
		panel = which;
		nameDraft = device.custom_name ?? '';
		choice = null;
	}

	// OLD CODE START — PR #214 review: focus was lost when the panel closed, and nothing was announced
	// function close(): void {
	// 	panel = 'none';
	// 	error = null;
	// 	choice = null;
	// }
	//
	// async function run(action: (mac: string) => Promise<RegistryDevice>): Promise<void> {
	// 	if (saving) return;
	// 	saving = true;
	// 	error = null;
	// 	try {
	// 		await onsave(action);
	// 		close();
	// 	} catch (e) {
	// 		error = e instanceof Error ? e.message : "Couldn't save the device.";
	// 	} finally {
	// 		saving = false;
	// 	}
	// }
	// OLD CODE END
	/** Close the open panel and put focus back on the button that opened it. */
	async function close(): Promise<void> {
		const trigger = panel === 'name' ? nameButton : pictureButton;
		panel = 'none';
		error = null;
		choice = null;
		await tick();
		trigger?.focus();
	}

	async function run(action: (mac: string) => Promise<RegistryDevice>, done: string): Promise<void> {
		if (saving) return;
		saving = true;
		error = null;
		announcement = '';
		let saved = false;
		try {
			await onsave(action);
			saved = true;
		} catch (e) {
			error = e instanceof Error ? e.message : "Couldn't save the device.";
		} finally {
			saving = false;
		}
		if (saved) {
			announcement = done;
			await close(); // after `saving` clears, so the trigger can take focus again
		}
	}

	function saveName(event: SubmitEvent): void {
		event.preventDefault();
		const name = nameDraft.trim();
		if (!name) {
			// OLD CODE: error = 'Enter a name, or use the discovered name.'; (PR #214 review)
			error = 'Enter a name, or cancel.';
			return;
		}
		void run((mac) => setDeviceName(mac, name), 'Name saved.');
	}

	async function pickPhoto(event: Event): Promise<void> {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		error = null;
		reading = true;
		try {
			choice = { image: await squarePicture(file) };
		} catch (e) {
			// OLD CODE: choice = null; (PR #214 review: a refused file kept no earlier choice)
			error = e instanceof Error ? e.message : "Couldn't read that picture.";
		} finally {
			reading = false;
			input.value = ''; // the same file can be picked again
		}
	}

	function pickIcon(icon: DeviceIcon): void {
		choice = { icon };
		error = null;
	}

	function savePicture(): void {
		const picked = choice;
		if (picked) void run((mac) => setDevicePicture(mac, picked), 'Picture saved.');
	}

	const chosenIcon = $derived(choice && 'icon' in choice ? choice.icon : null);
	const chosenImage = $derived(choice && 'image' in choice ? choice.image : null);
	/** Pressed: the icon just chosen, or with nothing chosen the saved icon (unless a photo shows). */
	const isPressed = (name: DeviceIcon): boolean =>
		choice ? chosenIcon === name : !device.picture && device.icon === name;
</script>

<div class="customise">
	<div class="cust-actions">
		<button
			class="btn"
			type="button"
			bind:this={nameButton}
			aria-expanded={panel === 'name'}
			aria-controls={panel === 'name' ? 'device-name-panel' : undefined}
			onclick={() => open('name')}
			disabled={saving}>Rename</button
		>
		<button
			class="btn"
			type="button"
			bind:this={pictureButton}
			aria-expanded={panel === 'picture'}
			aria-controls={panel === 'picture' ? 'device-picture-panel' : undefined}
			onclick={() => open('picture')}
			disabled={saving}>Change picture</button
		>
	</div>
	<p class="sr-only" role="status">{announcement}</p>

	{#if panel !== 'none' && randomised}
		<p class="notice is-warn" role="note">
			<Icon name="warn" /><span>This device uses a private (randomised) MAC address, so the name and picture may not stay with it if it changes address.</span>
		</p>
	{/if}

	{#if panel === 'name'}
		<form id="device-name-panel" class="cust-panel" onsubmit={saveName}>
			<div class="field">
				<label class="label" for="device-name">Name</label>
				<input
					id="device-name"
					class="input"
					maxlength="64"
					autocomplete="off"
					bind:value={nameDraft}
					aria-invalid={error ? 'true' : undefined}
					aria-describedby="device-name-help{error ? ' device-name-error' : ''}"
				/>
				<span class="field-help" id="device-name-help">Up to 64 characters. NetTap shows it on every page in place of the name the network gives it{device.discovered_name ? ` (${device.discovered_name})` : ''}.</span>
				{#if error}<span class="field-error" id="device-name-error" role="alert">{error}</span>{/if}
			</div>
			<div class="form-actions">
				{#if device.custom_name}
					<button class="btn" type="button" onclick={() => run((mac) => clearDeviceName(mac), 'Name cleared.')} disabled={saving}>Use the discovered name</button>
				{/if}
				<button class="btn" type="button" onclick={close} disabled={saving}>Cancel</button>
				<button class="btn primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
			</div>
		</form>
	{/if}

	{#if panel === 'picture'}
		<div id="device-picture-panel" class="cust-panel">
			<div class="pic-layout">
				<div class="pic-preview">
					<DeviceTile size="lg" category={device.category} picture={chosenImage ?? (chosenIcon ? null : device.picture)} icon={chosenIcon ?? device.icon} />
					<span class="field-help">{choice ? 'Preview' : 'Current'}</span>
				</div>
				<div class="pic-choices">
					<fieldset class="icon-set">
						<legend class="label">Pick an icon</legend>
						<div class="icon-grid">
							{#each DEVICE_ICONS as name (name)}
								<button
									class="icon-choice"
									type="button"
									aria-pressed={isPressed(name)}
									aria-label={ICON_LABELS[name]}
									title={ICON_LABELS[name]}
									onclick={() => pickIcon(name)}
									disabled={saving || reading}><Icon {name} /></button
								>
							{/each}
						</div>
					</fieldset>
					<div class="field">
						<label class="label" for="device-photo">Or upload a photo</label>
						<input id="device-photo" class="file" type="file" accept="image/png,image/jpeg,image/webp" onchange={pickPhoto} disabled={saving || reading} />
						<span class="field-help">PNG, JPEG or WebP. NetTap crops it to a square and makes it small before it leaves this browser.</span>
					</div>
				</div>
			</div>
			{#if error}<p class="field-error" role="alert">{error}</p>{/if}
			<div class="form-actions">
				{#if hasPicture}
					<button class="btn" type="button" onclick={() => run((mac) => clearDevicePicture(mac), 'Picture reset.')} disabled={saving}>Reset to default</button>
				{/if}
				<button class="btn" type="button" onclick={close} disabled={saving}>Cancel</button>
				<button class="btn primary" type="button" onclick={savePicture} disabled={saving || reading || !choice}>{saving ? 'Saving…' : 'Save'}</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.customise { display: flex; flex-direction: column; gap: var(--sp-3); margin-top: var(--sp-4); }
	.cust-actions { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
	.cust-panel { padding: var(--sp-4); border: 1px solid var(--line); border-radius: var(--r-md); background: var(--surface-2); }
	.cust-panel .form-actions { justify-content: flex-start; }
	.pic-layout { display: flex; flex-wrap: wrap; gap: var(--sp-5); align-items: flex-start; }
	.pic-preview { display: flex; flex-direction: column; align-items: center; gap: var(--sp-2); }
	.pic-choices { display: flex; flex-direction: column; gap: var(--sp-4); flex: 1 1 16rem; min-width: 0; }
	.icon-set { border: 0; margin: 0; padding: 0; min-width: 0; }
	.icon-grid { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
	.icon-choice {
		display: grid; place-items: center; width: 44px; height: 44px;
		border-radius: var(--r-sm); border: 1px solid var(--line-strong); background: var(--surface-1);
		color: var(--text-2); cursor: pointer; transition: background var(--dur-fast);
	}
	.icon-choice:hover { background: var(--surface-3); color: var(--text-1); }
	.icon-choice[aria-pressed='true'] { border-color: var(--accent); color: var(--accent); background: var(--surface-3); }
	.icon-choice:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
	.icon-choice:disabled { opacity: 0.5; cursor: not-allowed; }
	.icon-choice :global(.ic) { width: 20px; height: 20px; }
	.file { color: var(--text-1); font-size: var(--text-sm); max-width: 100%; }
	.file:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
</style>
