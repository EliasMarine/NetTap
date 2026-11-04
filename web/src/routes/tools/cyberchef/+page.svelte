<script lang="ts">
	/**
	 * CyberChef: the quick-recipe card, then the CyberChef workspace in an iframe.
	 * The status and recipe requests run through the page refresh contract.
	 */
	import { onDestroy, onMount } from 'svelte';
	import { getCyberChefStatus, getRecipes, buildRecipeUrl } from '$api/cyberchef.js';
	import type { CyberChefStatus, CyberChefRecipe } from '$api/cyberchef.js';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';

	let status = $state<CyberChefStatus | null>(null);
	let recipes = $state<CyberChefRecipe[]>([]);
	let loading = $state(true);
	let inputData = $state('');
	let selectedRecipe = $state<CyberChefRecipe | null>(null);
	let iframeUrl = $state('');
	let buildingUrl = $state(false);
	let errorMessage = $state('');

	const CYBERCHEF_BASE_URL = '/cyberchef/';

	// OLD CODE START — the load now goes through the page refresh contract (PLAN.md §5.5):
	// it reports its result and a load guard drops a response that a newer load replaced
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
	async function fetchStatus(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		loading = true;
		errorMessage = '';
		try {
			const [statusResult, recipesResult] = await Promise.all([
				getCyberChefStatus(),
				getRecipes(),
			]);
			if (!guard.current(g)) return 'skipped';
			status = statusResult;
			recipes = recipesResult.recipes;

			if (statusResult.available && !iframeUrl) {
				iframeUrl = CYBERCHEF_BASE_URL;
			}
			return 'ok';
		} catch {
			if (!guard.current(g)) return 'skipped';
			errorMessage = 'Failed to fetch CyberChef status';
			return 'failed';
		} finally {
			if (guard.current(g)) loading = false;
		}
	}

	const refresh = registerPageRefresh(fetchStatus);
	onDestroy(refresh.unregister);
	const retry = () => refresh.run();

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

	let recipesByCategory = $derived(
		recipes.reduce<Record<string, CyberChefRecipe[]>>((acc, recipe) => {
			const cat = recipe.category || 'Other';
			if (!acc[cat]) acc[cat] = [];
			acc[cat].push(recipe);
			return acc;
		}, {})
	);

	// OLD CODE START — the first load runs once on mount, through the refresh contract
	// $effect(() => {
	// 	fetchStatus();
	// });
	// OLD CODE END
	onMount(() => {
		refresh.run();
	});
</script>

<svelte:head>
	<title>CyberChef | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">CyberChef</h1>
		<p class="page-sub">Data encoding, decoding and analysis toolkit, running on your NetTap.</p>
	</div>
	<div class="head-actions">
		{#if status}
			{#if status.available}
				<span class="chip is-ok"><Icon name="check" />Running</span>
			{:else}
				<span class="chip is-bad"><Icon name="warn" />Offline</span>
			{/if}
		{:else if loading}
			<span class="chip">Checking…</span>
		{:else}
			<span class="chip">Unknown</span>
		{/if}
		{#if iframeUrl && iframeUrl !== CYBERCHEF_BASE_URL}
			<button class="btn" type="button" onclick={resetView}>Reset</button>
		{/if}
		{#if iframeUrl}
			<button class="btn" type="button" onclick={openInNewTab}><Icon name="up" />New tab</button>
		{/if}
	</div>
</div>

{#if loading && !status}
	<Card title="CyberChef" sub="Container status">
		<CardState state="loading" title="Checking CyberChef status…" />
	</Card>
{:else if !status}
	<!-- #96: a failed status request is not "the container is not running" -->
	<Card title="CyberChef status unknown" sub="Container status">
		<CardState state="error" title="Couldn't check CyberChef status: the request failed." message="Check that NetTap is running on the System page, then try again." onaction={retry} />
	</Card>
{:else if !status?.available}
	<Card title="CyberChef unavailable" sub="Container status">
		<CardState
			state="error"
			title="CyberChef isn't running"
			message="The CyberChef container is not running. Make sure the Docker Compose stack is started and the CyberChef service is healthy."
			onaction={retry}
		/>
	</Card>
{:else}
	{#if recipes.length > 0}
		<Card title="Quick recipes" sub="{recipes.length} ready-made recipes, by category">
			<div class="recipes">
				{#each Object.entries(recipesByCategory) as [category, categoryRecipes] (category)}
					<div class="recipe-group">
						<h3 class="eyebrow" id="recipes-{category}">{category}</h3>
						<div class="pills recipe-pills" role="group" aria-labelledby="recipes-{category}">
							{#each categoryRecipes as recipe (recipe.name)}
								<button
									class="pill"
									type="button"
									aria-pressed={selectedRecipe?.name === recipe.name}
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

			{#if selectedRecipe}
				<div class="field recipe-input">
					<label class="label" for="cyberchef-input">Recipe: {selectedRecipe.name}</label>
					<span class="field-help">{selectedRecipe.description}</span>
					<textarea id="cyberchef-input" class="textarea mono" bind:value={inputData} placeholder="Paste data to analyse…" rows="3"></textarea>
				</div>
				<div class="form-actions">
					<button class="btn primary" type="button" onclick={applyRecipe} disabled={buildingUrl || !inputData.trim()}>
						{buildingUrl ? 'Building…' : 'Apply recipe'}
					</button>
				</div>
			{/if}
		</Card>
	{/if}

	{#if errorMessage}
		<p class="notice is-error" role="alert"><Icon name="warn" />{errorMessage}</p>
	{/if}

	<Card title="Workspace" sub="CyberChef {status.version} · served by your NetTap">
		<iframe
			src={iframeUrl}
			title="CyberChef"
			class="workspace"
			sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
		></iframe>
	</Card>
{/if}

<style>
	.recipes { display: flex; flex-direction: column; gap: var(--sp-4); }
	.recipe-group { display: flex; flex-direction: column; gap: var(--sp-2); }
	/* Layout glue: a category's recipes wrap onto more rows */
	.recipe-pills { flex-wrap: wrap; align-self: flex-start; border-radius: var(--r-lg); }
	.recipe-input { margin-top: var(--sp-5); }
	/* Layout glue: the workspace fills most of the screen; CyberChef draws its own light page */
	.workspace { display: block; width: 100%; height: 70vh; min-height: 400px; border: 1px solid var(--line); border-radius: var(--r-md); background: var(--text-1); }
</style>
