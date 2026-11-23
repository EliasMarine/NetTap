<!--
  Settings › Account (NET-358): change the signed-in user's password. The server re-checks the current
  password (throttled like a sign-in) and applies the setup wizard's rules, so this form only checks that
  every field is filled and the two new ones match. Only a change being sent holds navigation (`busy`):
  a typed, unsent password doesn't.
-->
<script lang="ts">
	import { page } from '$app/state';
	import { trackPasswordChange } from '$lib/password-change';
	import Card from '$lib/components/ui/Card.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Feedback from '../Feedback.svelte';

	interface Props {
		/** A change is being sent. */
		busy?: boolean;
	}

	let { busy = $bindable(false) }: Props = $props();

	// The root layout's load (+layout.server.ts) gives the signed-in name
	const username = $derived<string | null>(page.data.username ?? null);

	let current = $state('');
	let password = $state('');
	let confirm = $state('');
	let pending = $state(false);
	let error = $state('');
	let changed = $state(false);
	/** The server's note when the new password is live but not confirmed on disk. */
	let warning = $state('');

	$effect(() => {
		busy = pending;
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		// One change at a time: a second Enter or click while one is sent does nothing
		if (pending) return;
		error = '';
		changed = false;
		warning = '';
		if (!current || !password || !confirm) {
			error = 'Enter your current password, then the new one twice.';
			return;
		}
		if (password !== confirm) {
			error = "The new passwords don't match.";
			return;
		}
		pending = true;
		try {
			// OLD CODE START — NET-358 review: no timeout, so a hung request held the hub and the shell's late-401 check for ever;
			// and the tracker took an `ok` callback
			// const res = await trackPasswordChange(
			// 	fetch('/api/account/password', {
			// 		method: 'POST',
			// 		headers: { 'Content-Type': 'application/json' },
			// 		body: JSON.stringify({ current, password }),
			// 	}),
			// 	(r) => r.ok,
			// );
			// OLD CODE END
			// Registered so a late 401 from the old cookie doesn't send this browser to sign in (PLAN.md Observability)
			const res = await trackPasswordChange(
				fetch('/api/account/password', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ current, password }),
					signal: AbortSignal.timeout(30_000),
				}),
			);
			// A proxy's HTML error page or a JSON null has no fields, not an unanswered request
			const data: { error?: unknown; warning?: unknown } = (await res.json().catch(() => null)) ?? {};
			if (res.ok) {
				current = '';
				password = '';
				confirm = '';
				changed = true;
				warning = typeof data.warning === 'string' ? data.warning : '';
			} else {
				if (res.status === 401) current = '';
				error = typeof data.error === 'string' && data.error ? data.error : `Couldn't change the password: NetTap answered ${res.status}.`;
			}
		} catch {
			// OLD CODE: error = "Couldn't change the password: NetTap didn't answer. Check the connection and try again."; (NET-358 review: a lost answer can follow a change that went through)
			error = "NetTap didn't answer, so the password may or may not have changed. If you're signed out, sign in with the new password.";
		} finally {
			pending = false;
		}
	}
</script>

<div class="grid">
	<Card title="Password" sub={username ? `Signed in as ${username}` : undefined} class="c-6">
		<form class="stack" onsubmit={submit}>
			<Feedback message={error} isError />
			{#if changed}
				<div class="notice is-ok" role="status">
					<Icon name="check" />
					<span>
						Password changed. Any other browser signed in to NetTap has to sign in again. Close NetTap tabs on other devices
						that still show Dashboards or Grafana.
					</span>
				</div>
				{#if warning}
					<p class="notice is-warn" role="status"><Icon name="warn" /><span>{warning}</span></p>
				{/if}
			{/if}
			<div class="form-grid">
				<div class="field">
					<label class="label" for="account-username">Username</label>
					<input class="input" id="account-username" type="text" autocomplete="username" value={username ?? ''} readonly />
				</div>
				<div class="field">
					<label class="label" for="account-current">Current password</label>
					<input class="input" id="account-current" type="password" autocomplete="current-password" bind:value={current} readonly={pending} />
				</div>
				<div class="field">
					<label class="label" for="account-new">New password</label>
					<input
						class="input"
						id="account-new"
						type="password"
						autocomplete="new-password"
						aria-describedby="account-new-help"
						bind:value={password}
						readonly={pending}
					/>
					<p class="field-help" id="account-new-help">At least 8 characters, with an upper-case letter, a lower-case letter and a number.</p>
				</div>
				<div class="field">
					<label class="label" for="account-confirm">Confirm new password</label>
					<input class="input" id="account-confirm" type="password" autocomplete="new-password" bind:value={confirm} readonly={pending} />
				</div>
			</div>
			<div class="form-actions">
				<button class="btn primary" type="submit" disabled={pending}>{pending ? 'Changing…' : 'Change password'}</button>
			</div>
		</form>
	</Card>
</div>
