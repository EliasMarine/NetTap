<script lang="ts">
	import { enhance } from '$app/forms';
	import BrandMark from '$lib/components/shell/BrandMark.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	let { form } = $props();

	let loading = $state(false);
</script>

<svelte:head>
	<title>Login | NetTap</title>
</svelte:head>

<!-- Bare route (no shell): a centred card with the brand, the form and the error state -->
<div class="login">
	<article class="card login-card">
		<header class="login-head">
			<h1 class="brand"><BrandMark />NetTap</h1>
			<p class="page-sub">Sign in with your admin account.</p>
		</header>

		{#if form?.error}
			<div class="notice is-error" role="alert">
				<Icon name="warn" />
				<span>{form.error}</span>
			</div>
		{/if}

		<form
			method="POST"
			use:enhance={() => {
				loading = true;
				return async ({ update }) => {
					loading = false;
					await update();
				};
			}}
		>
			<div class="form-group">
				<label for="username" class="label">Username</label>
				<input
					id="username"
					name="username"
					type="text"
					class="input"
					placeholder="admin"
					required
					autocomplete="username"
					value={form?.username ?? ''}
				/>
			</div>

			<div class="form-group">
				<label for="password" class="label">Password</label>
				<input
					id="password"
					name="password"
					type="password"
					class="input"
					placeholder="Enter your password"
					required
					autocomplete="current-password"
				/>
			</div>

			<!-- "Sign In" stays title case: the e2e specs (login, shell, the visual auth setup) name it -->
			<button type="submit" class="btn primary login-btn" disabled={loading}>
				{#if loading}
					Signing in…
				{:else}
					Sign In
				{/if}
			</button>
		</form>
	</article>
</div>

<style>
	.login {
		min-height: calc(100dvh - var(--sp-8));
		display: grid;
		place-items: center;
	}

	/* A card, not the page container: the page itself stays full width */
	.login-card {
		width: min(100%, 400px);
		display: flex;
		flex-direction: column;
		gap: var(--sp-5);
	}

	.login-head {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-2);
		text-align: center;
	}

	.login-head .brand {
		padding: 0;
	}

	.login-btn {
		width: 100%;
		justify-content: center;
	}
</style>
