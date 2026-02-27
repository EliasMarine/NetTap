<script lang="ts">
	import { enhance } from '$app/forms';

	let { form } = $props();

	let loading = $state(false);
</script>

<svelte:head>
	<title>Login | NetTap</title>
</svelte:head>

<div class="login-page">
	<div class="login-container">
		<div class="login-header">
			<svg class="login-logo" viewBox="0 0 32 32" width="48" height="48" fill="none">
				<rect width="32" height="32" rx="6" fill="var(--accent)" />
				<path d="M8 16h16M16 8v16M10 10l12 12M22 10L10 22" stroke="#fff" stroke-width="2" stroke-linecap="round" />
			</svg>
			<h1>NetTap</h1>
			<p class="text-muted">Network Visibility Appliance</p>
		</div>

		{#if form?.error}
			<div class="alert alert-danger">
				{form.error}
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

			<button type="submit" class="btn btn-primary btn-lg login-btn" disabled={loading}>
				{#if loading}
					Signing in...
				{:else}
					Sign In
				{/if}
			</button>
		</form>
	</div>
</div>

<style>
	.login-page {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-primary);
		padding: var(--space-md);
	}

	.login-container {
		width: 100%;
		max-width: 400px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-xl);
		padding: var(--space-2xl);
	}

	.login-header {
		text-align: center;
		margin-bottom: var(--space-xl);
	}

	.login-logo {
		margin-bottom: var(--space-md);
	}

	.login-header h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.login-header p {
		font-size: var(--text-sm);
	}

	.alert {
		margin-bottom: var(--space-md);
	}

	.login-btn {
		width: 100%;
		margin-top: var(--space-sm);
	}
</style>
