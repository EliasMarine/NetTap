<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { getCyberChefStatus, getRecipes, buildRecipeUrl } from '$api/cyberchef.js';
	import type { CyberChefStatus, CyberChefRecipe } from '$api/cyberchef.js';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult, outcome } from '$lib/stores/pageRefresh';
	import { loadFailed } from '$lib/utils/load-failed';

	let status = $state<CyberChefStatus | null>(null);
	let recipes = $state<CyberChefRecipe[]>([]);
	let loading = $state(true);
	let inputData = $state('');
	let selectedRecipe = $state<CyberChefRecipe | null>(null);
	let iframeUrl = $state('');
	let buildingUrl = $state(false);
	let errorMessage = $state('');
	// the last status read failed while an earlier reading is still shown
	let statusFailed = $state(false);
	let recipesFailed = $state(false);

	/** The base URL for the CyberChef container iframe. */
	const CYBERCHEF_BASE_URL = '/cyberchef/';

	// OLD CODE START — the page refresh contract (PLAN.md §5.5); a failed recipe list also hid a
	// status that had loaded, because both went through one Promise.all
	// async function fetchStatus() {
	// 	loading = true;
	// 	errorMessage = '';
	// 	try {
	// 		const [statusResult, recipesResult] = await Promise.all([
	// 			getCyberChefStatus(),
	// 			getRecipes(),
	// 		]);
	// 		status = statusResult;
	// 		recipes = recipesResult.recipes;
	//
	// 		// Set default iframe URL if CyberChef is available
	// 		if (statusResult.available && !iframeUrl) {
	// 			iframeUrl = CYBERCHEF_BASE_URL;
	// 		}
	// 	} catch {
	// 		errorMessage = 'Failed to fetch CyberChef status';
	// 	} finally {
	// 		loading = false;
	// 	}
	// }
	// OLD CODE END
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		const results = await Promise.allSettled([getCyberChefStatus(), getRecipes()]);
		if (!guard.current(g)) return 'skipped';
		const [statusResult, recipesResult] = results;
		if (statusResult.status === 'fulfilled') {
			status = statusResult.value;
			// Set default iframe URL if CyberChef is available
			if (statusResult.value.available && !iframeUrl) iframeUrl = CYBERCHEF_BASE_URL;
		}
		if (recipesResult.status === 'fulfilled') recipes = recipesResult.value.recipes;
		statusFailed = statusResult.status === 'rejected';
		recipesFailed = recipesResult.status === 'rejected';
		loading = false;
		// OLD CODE START — counted by hand; outcome() in pageRefresh is the shared rule
		// const failures = results.filter((r) => r.status === 'rejected').length;
		// return failures === 0 ? 'ok' : failures === results.length ? 'failed' : 'partial';
		// OLD CODE END
		return outcome(results);
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	onMount(() => void refresh.run());
	const retry = () => void refresh.run();

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
</script>

<svelte:head>
	<title>CyberChef | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a href="/system" class="back"><Icon name="back" />System</a>
		<h1 class="page-title">CyberChef</h1>
		<p class="page-sub">Encode, decode and analyse data, on this NetTap</p>
	</div>
	<div class="head-actions">
		{#if status}
			<span class={['chip', status.available ? 'is-ok' : 'is-bad']}>{status.available ? 'Running' : 'Offline'}</span>
		{:else if loading}
			<span class="chip">Checking…</span>
		{:else}
			<span class="chip">Unknown</span>
		{/if}
		{#if iframeUrl && iframeUrl !== CYBERCHEF_BASE_URL}
			<button class="btn" type="button" onclick={resetView}>Reset</button>
		{/if}
		{#if iframeUrl}
			<button class="btn" type="button" onclick={openInNewTab}>Open in a new tab</button>
		{/if}
	</div>
</div>

{#if loading && !status}
	<Card title="CyberChef" sub="Checking the CyberChef container">
		<CardState state="loading" title="Checking CyberChef status" />
	</Card>
{:else if !status}
	<!-- #96: a failed status request is not "the container is not running" -->
	<Card title="CyberChef status unknown" sub="The CyberChef container">
		<CardState
			state="error"
			title="Couldn't check CyberChef status: the request failed."
			message="Check that NetTap is running on the System page, then try again."
			onaction={retry}
		/>
	</Card>
{:else if !status?.available}
	<Card title="CyberChef unavailable" sub="The CyberChef container">
		<CardState
			state="empty"
			icon="tools"
			title="CyberChef isn't running"
			message="The CyberChef container is not running. Make sure the Docker Compose stack is started and the CyberChef service is healthy."
			actionLabel="Check again"
			onaction={retry}
		/>
	</Card>
{:else}
	{#if statusFailed}
		<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('the CyberChef status', true)}</div>
	{/if}
	<div class="grid">
		<Card title="Quick recipes" sub="Ready-made CyberChef recipes · pick one, then paste your data" class="c-12">
			{#if recipesFailed}
				<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('the quick recipes', recipes.length > 0)}</div>
			{/if}
			{#if recipes.length > 0}
				<div class="categories">
					{#each Object.entries(recipesByCategory) as [category, categoryRecipes] (category)}
						<div class="category">
							<h3 class="eyebrow">{category}</h3>
							<div class="pills" role="group" aria-label="{category} recipes">
								{#each categoryRecipes as recipe (recipe.name)}
									<button
										class="pill"
										type="button"
										aria-pressed={selectedRecipe?.name === recipe.name}
										onclick={() => selectRecipe(recipe)}
										title={recipe.description}>{recipe.name}</button
									>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{:else if !recipesFailed}
				<CardState state="empty" title="No quick recipes" message="Ready-made recipes appear here when the daemon provides them. CyberChef itself still works below." />
			{/if}

			{#if selectedRecipe}
				<div class="apply">
					<div class="field">
						<label class="label" for="cyberchef-input">Recipe: {selectedRecipe.name}</label>
						<p class="field-help">{selectedRecipe.description}</p>
						<textarea id="cyberchef-input" class="textarea mono" bind:value={inputData} placeholder="Paste data to analyse…" rows="3"></textarea>
					</div>
					<div class="form-actions">
						<button class="btn primary" type="button" onclick={applyRecipe} disabled={buildingUrl || !inputData.trim()}>
							{buildingUrl ? 'Building…' : 'Apply recipe'}
						</button>
					</div>
				</div>
			{/if}

			{#if errorMessage}
				<div class="notice is-error" role="alert"><Icon name="warn" />{errorMessage}</div>
			{/if}
		</Card>

		<Card title="Workspace" sub="The CyberChef app · data you paste stays on this NetTap" class="c-12">
			<iframe
				src={iframeUrl}
				title="CyberChef"
				class="workspace"
				sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
			></iframe>
		</Card>
	</div>
{/if}

<style>
	.categories { display: flex; flex-direction: column; gap: var(--sp-4); }
	.category { display: flex; flex-direction: column; gap: var(--sp-2); }
	/* a long category wraps onto a second line, so its track takes the card radius, not a pill's */
	.category .pills { flex-wrap: wrap; width: fit-content; max-width: 100%; border-radius: var(--r-lg); }
	.apply { margin-top: var(--sp-5); padding-top: var(--sp-4); border-top: 1px solid var(--line); }
	.notice { margin-bottom: var(--sp-4); }
	.notice:last-child { margin: var(--sp-4) 0 0; }
	/* the app needs room to work; it scrolls inside its own frame */
	.workspace { display: block; width: 100%; height: max(500px, 70vh); border: 1px solid var(--line); border-radius: var(--r-md); background: var(--surface-1); }
</style>
