<script lang="ts">
	import { getCyberChefStatus, getRecipes, buildRecipeUrl } from '$api/cyberchef.js';
	import type { CyberChefStatus, CyberChefRecipe } from '$api/cyberchef.js';

	let status = $state<CyberChefStatus | null>(null);
	let recipes = $state<CyberChefRecipe[]>([]);
	let loading = $state(true);
	let inputData = $state('');
	let selectedRecipe = $state<CyberChefRecipe | null>(null);
	let iframeUrl = $state('');
	let buildingUrl = $state(false);
	let errorMessage = $state('');

	/** The base URL for the CyberChef container iframe. */
	const CYBERCHEF_BASE_URL = '/cyberchef/';

	async function fetchStatus() {
		loading = true;
		errorMessage = '';
		try {
			const [statusResult, recipesResult] = await Promise.all([
				getCyberChefStatus(),
				getRecipes(),
			]);
			status = statusResult;
			recipes = recipesResult.recipes;

			// Set default iframe URL if CyberChef is available
			if (statusResult.available && !iframeUrl) {
				iframeUrl = CYBERCHEF_BASE_URL;
			}
		} catch {
			errorMessage = 'Failed to fetch CyberChef status';
		} finally {
			loading = false;
		}
	}

	function selectRecipe(recipe: CyberChefRecipe) {
		selectedRecipe = recipe;
	}

	async function applyRecipe() {
		if (!selectedRecipe) return;

		buildingUrl = true;
		errorMessage = '';
		try {
			const result = await buildRecipeUrl(selectedRecipe.recipe_fragment, inputData);
			iframeUrl = result.url;
		} catch (err) {
			errorMessage = err instanceof Error ? err.message : 'Failed to build recipe URL';
		} finally {
			buildingUrl = false;
		}
	}

	function openInNewTab() {
		if (iframeUrl) {
			window.open(iframeUrl, '_blank', 'noopener,noreferrer');
		}
	}

	function resetView() {
		selectedRecipe = null;
		inputData = '';
		iframeUrl = CYBERCHEF_BASE_URL;
		errorMessage = '';
	}

	// Group recipes by category
	let recipesByCategory = $derived(
		recipes.reduce<Record<string, CyberChefRecipe[]>>((acc, recipe) => {
			const cat = recipe.category || 'Other';
			if (!acc[cat]) acc[cat] = [];
			acc[cat].push(recipe);
			return acc;
		}, {})
	);

	$effect(() => {
		fetchStatus();
	});
</script>

<svelte:head>
	<title>CyberChef | NetTap</title>
</svelte:head>

<div class="cyberchef-page">
	<!-- Header -->
	<div class="page-header">
		<div class="header-left">
			<div class="header-title-row">
				<a href="/system" class="back-link" aria-label="Back to System">
					<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="15 18 9 12 15 6" />
					</svg>
				</a>
				<h2>CyberChef</h2>
				{#if status}
					<span class={status.available ? 'badge badge-success' : 'badge badge-danger'}>
						{status.available ? 'Running' : 'Offline'}
					</span>
				{:else if loading}
					<span class="badge">Checking...</span>
				{/if}
			</div>
			<p class="text-muted">Data encoding, decoding, and analysis toolkit</p>
		</div>
		<div class="header-actions">
			{#if iframeUrl && iframeUrl !== CYBERCHEF_BASE_URL}
				<button class="btn btn-secondary btn-sm" onclick={resetView}>Reset</button>
			{/if}
			{#if iframeUrl}
				<button class="btn btn-secondary btn-sm" onclick={openInNewTab}>
					<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
						<polyline points="15 3 21 3 21 9" />
						<line x1="10" y1="14" x2="21" y2="3" />
					</svg>
					New Tab
				</button>
			{/if}
		</div>
	</div>

	{#if loading && !status}
		<div class="loading-state">
			<div class="spinner"></div>
			<p class="text-muted">Checking CyberChef status...</p>
		</div>
	{:else if !status?.available}
		<!-- CyberChef unavailable -->
		<div class="unavailable-state">
			<div class="empty-icon">
				<svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
					<polyline points="16 18 22 12 16 6" />
					<polyline points="8 6 2 12 8 18" />
					<line x1="1" y1="1" x2="23" y2="23" />
				</svg>
			</div>
			<h3>CyberChef Unavailable</h3>
			<p class="text-muted">
				The CyberChef container is not running. Make sure the Docker Compose stack is started and the CyberChef service is healthy.
			</p>
			<button class="btn btn-primary btn-sm" onclick={fetchStatus}>Retry</button>
		</div>
	{:else}
		<!-- Quick recipe bar + input -->
		<div class="recipe-panel">
			<!-- Recipe buttons -->
			{#if recipes.length > 0}
				<div class="recipe-section">
					<span class="section-label">Quick Recipes</span>
					<div class="recipe-categories">
						{#each Object.entries(recipesByCategory) as [category, categoryRecipes]}
							<div class="recipe-category">
								<span class="category-label">{category}</span>
								<div class="recipe-buttons">
									{#each categoryRecipes as recipe}
										<button
											class="recipe-btn"
											class:recipe-selected={selectedRecipe?.name === recipe.name}
											onclick={() => selectRecipe(recipe)}
											title={recipe.description}
										>
											{recipe.name}
										</button>
									{/each}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Input area -->
			{#if selectedRecipe}
				<div class="input-section">
					<div class="input-header">
						<span class="section-label">
							Recipe: <strong>{selectedRecipe.name}</strong>
						</span>
						<span class="text-muted">{selectedRecipe.description}</span>
					</div>
					<div class="input-row">
						<textarea
							class="input data-input"
							bind:value={inputData}
							placeholder="Paste data to analyze..."
							rows="3"
						></textarea>
						<button
							class="btn btn-primary"
							onclick={applyRecipe}
							disabled={buildingUrl || !inputData.trim()}
						>
							{buildingUrl ? 'Building...' : 'Apply Recipe'}
						</button>
					</div>
				</div>
			{/if}

			{#if errorMessage}
				<div class="alert alert-danger">{errorMessage}</div>
			{/if}
		</div>

		<!-- CyberChef iframe -->
		<div class="iframe-container">
			<iframe
				src={iframeUrl}
				title="CyberChef"
				class="cyberchef-iframe"
				sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
			></iframe>
		</div>
	{/if}
</div>

<style>
	.cyberchef-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		height: calc(100vh - var(--topbar-height) - var(--space-lg) * 2);
	}

	/* Header */
	.page-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-md);
		flex-wrap: wrap;
		flex-shrink: 0;
	}

	.header-title-row {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.header-title-row h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
	}

	.back-link {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-sm);
		color: var(--text-secondary);
		transition: all var(--transition-fast);
	}

	.back-link:hover {
		background-color: var(--bg-tertiary);
		color: var(--text-primary);
		text-decoration: none;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	/* Loading / unavailable states */
	.loading-state,
	.unavailable-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-3xl);
		gap: var(--space-md);
		text-align: center;
		flex: 1;
	}

	.unavailable-state {
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-lg);
	}

	.empty-icon {
		color: var(--text-muted);
	}

	.unavailable-state h3 {
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--text-primary);
	}

	.unavailable-state p {
		max-width: 480px;
		line-height: var(--leading-relaxed);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Recipe panel */
	.recipe-panel {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.section-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		font-weight: 500;
	}

	.recipe-section {
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md);
	}

	.recipe-categories {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-top: var(--space-sm);
	}

	.recipe-category {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
	}

	.category-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 600;
	}

	.recipe-buttons {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
	}

	.recipe-btn {
		padding: var(--space-xs) var(--space-sm);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--text-secondary);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition-fast);
		white-space: nowrap;
	}

	.recipe-btn:hover {
		color: var(--text-primary);
		border-color: var(--accent);
	}

	.recipe-selected {
		background-color: var(--accent-muted);
		color: var(--accent);
		border-color: var(--accent);
	}

	/* Input section */
	.input-section {
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md);
	}

	.input-header {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		margin-bottom: var(--space-sm);
		flex-wrap: wrap;
	}

	.input-row {
		display: flex;
		gap: var(--space-sm);
		align-items: flex-end;
	}

	.data-input {
		flex: 1;
		resize: vertical;
		font-family: var(--font-mono);
		min-height: 60px;
	}

	/* Iframe */
	.iframe-container {
		flex: 1;
		min-height: 400px;
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		overflow: hidden;
		background-color: var(--bg-secondary);
	}

	.cyberchef-iframe {
		width: 100%;
		height: 100%;
		border: none;
		background-color: #fff;
	}

	@media (max-width: 768px) {
		.cyberchef-page {
			height: auto;
		}

		.iframe-container {
			min-height: 500px;
		}

		.input-row {
			flex-direction: column;
		}

		.input-row .btn {
			width: 100%;
		}
	}
</style>
