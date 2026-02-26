<script lang="ts">
	import { enhance } from '$app/forms';

	let { form } = $props();

	let loading = $state(false);
</script>

<svelte:head>
	<title>Setup | NetTap</title>
</svelte:head>

<div class="setup-page">
	<div class="setup-container">
		<div class="setup-header">
			<svg class="setup-logo" viewBox="0 0 32 32" width="48" height="48" fill="none">
				<rect width="32" height="32" rx="6" fill="var(--accent)" />
				<path d="M8 16h16M16 8v16M10 10l12 12M22 10L10 22" stroke="#fff" stroke-width="2" stroke-linecap="round" />
			</svg>
			<h1>Welcome to NetTap</h1>
			<p class="text-muted">Create your admin account to get started.</p>
		</div>

		{#if form?.error}
			<div class="alert alert-danger">
				{form.error}
			</div>
		{/if}

		{#if form?.success}
			<div class="alert alert-success">
				Account created successfully! <a href="/login">Sign in now</a>
			</div>
		{:else}
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
						placeholder="Choose a strong password"
						required
						minlength="8"
						autocomplete="new-password"
					/>
				</div>

				<div class="form-group">
					<label for="confirmPassword" class="label">Confirm Password</label>
					<input
						id="confirmPassword"
						name="confirmPassword"
						type="password"
						class="input"
						placeholder="Confirm your password"
						required
						minlength="8"
						autocomplete="new-password"
					/>
				</div>

				<button type="submit" class="btn btn-primary btn-lg setup-btn" disabled={loading}>
					{#if loading}
						Creating account...
					{:else}
						Create Admin Account
					{/if}
				</button>
			</form>
		{/if}
	</div>
</div>

<style>
	.setup-page {
		min-height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-primary);
		padding: var(--space-md);
	}

	.setup-container {
		width: 100%;
		max-width: 440px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-xl);
		padding: var(--space-2xl);
	}

	.setup-header {
		text-align: center;
		margin-bottom: var(--space-xl);
	}

	.setup-logo {
		margin-bottom: var(--space-md);
	}

	.setup-header h1 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.setup-header p {
		font-size: var(--text-sm);
	}

	.alert {
		margin-bottom: var(--space-md);
	}

	.setup-btn {
		width: 100%;
		margin-top: var(--space-sm);
	}
</style>
