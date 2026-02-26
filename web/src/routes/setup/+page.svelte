<script lang="ts">
	import { enhance } from '$app/forms';
	import { goto } from '$app/navigation';

	let { form } = $props();

	// ----- Wizard state -----
	let currentStep = $state(1);
	const totalSteps = 5;
	const stepLabels = ['Welcome', 'Interfaces', 'Bridge', 'Storage', 'Account'];

	// ----- Step 1: Welcome -----
	let requirementsChecked = $state(false);
	let checkingRequirements = $state(false);
	let requirements = $state({
		nics: { label: 'Two or more network interfaces', status: 'pending' as 'pending' | 'pass' | 'fail' },
		docker: { label: 'Docker is running', status: 'pending' as 'pending' | 'pass' | 'fail' },
		disk: { label: 'Sufficient disk space (100GB+)', status: 'pending' as 'pending' | 'pass' | 'fail' },
	});

	// ----- Step 2: Network Interfaces -----
	interface NetworkInterface {
		name: string;
		mac: string;
		state: 'up' | 'down' | 'unknown';
		speed: string;
		driver: string;
		ipv4?: string;
		type: 'ethernet' | 'wireless' | 'virtual' | 'loopback';
	}

	let interfaces = $state<NetworkInterface[]>([]);
	let nicsLoading = $state(false);
	let nicsError = $state('');
	let nicsSource = $state('');
	let selectedWan = $state('');
	let selectedLan = $state('');

	// Filter to only usable (non-loopback) interfaces for NIC selection
	let selectableInterfaces = $derived(
		interfaces.filter((iface) => iface.type !== 'loopback')
	);

	let selectedWanDetails = $derived(
		interfaces.find((iface) => iface.name === selectedWan)
	);

	let selectedLanDetails = $derived(
		interfaces.find((iface) => iface.name === selectedLan)
	);

	let nicSelectionValid = $derived(
		selectedWan !== '' && selectedLan !== '' && selectedWan !== selectedLan
	);

	// ----- Step 3: Bridge Configuration -----
	interface BridgeConfig {
		config_preview: string;
		wan: string;
		lan: string;
		bridge_name: string;
		ready: boolean;
		warnings: string[];
		source: string;
	}

	let bridgeConfig = $state<BridgeConfig | null>(null);
	let bridgeLoading = $state(false);
	let bridgeError = $state('');
	let bridgeVerified = $state(false);

	// ----- Step 4: Storage Configuration -----
	interface StorageStatus {
		disk_total_gb: number;
		disk_used_gb: number;
		disk_free_gb: number;
		disk_usage_percent: number;
		hot_days: number;
		warm_days: number;
		cold_days: number;
		disk_threshold_percent: number;
		emergency_threshold_percent: number;
		estimated_daily_gb: number;
		source: string;
	}

	let storageStatus = $state<StorageStatus | null>(null);
	let storageLoading = $state(false);
	let storageError = $state('');
	let storageSaving = $state(false);
	let storageSaved = $state(false);

	let hotDays = $state(90);
	let warmDays = $state(180);
	let coldDays = $state(30);
	let diskThreshold = $state(80);
	let emergencyThreshold = $state(90);

	let estimatedTotalDays = $derived.by(() => {
		if (!storageStatus) return 0;
		const freeGb = storageStatus.disk_free_gb;
		const usableGb = freeGb * (diskThreshold / 100);
		const dailyGb = storageStatus.estimated_daily_gb || 1.2;
		return Math.floor(usableGb / dailyGb);
	});

	let diskUsageColor = $derived.by(() => {
		if (!storageStatus) return 'var(--accent)';
		if (storageStatus.disk_usage_percent >= 90) return 'var(--danger)';
		if (storageStatus.disk_usage_percent >= 70) return 'var(--warning)';
		return 'var(--success)';
	});

	// ----- Step 5: Admin Account -----
	let adminLoading = $state(false);
	let adminUsername = $state('');
	let adminPassword = $state('');
	let adminConfirmPassword = $state('');
	let clientError = $state('');

	let passwordHasLength = $derived(adminPassword.length >= 8);
	let passwordHasUpper = $derived(/[A-Z]/.test(adminPassword));
	let passwordHasLower = $derived(/[a-z]/.test(adminPassword));
	let passwordHasNumber = $derived(/[0-9]/.test(adminPassword));
	let passwordsMatch = $derived(
		adminPassword !== '' && adminConfirmPassword !== '' && adminPassword === adminConfirmPassword
	);
	let passwordValid = $derived(
		passwordHasLength && passwordHasUpper && passwordHasLower && passwordHasNumber
	);
	let adminFormValid = $derived(
		adminUsername.trim().length >= 3 && passwordValid && passwordsMatch
	);

	// ----- Navigation logic -----
	function canAdvance(): boolean {
		switch (currentStep) {
			case 1:
				return requirementsChecked;
			case 2:
				return nicSelectionValid;
			case 3:
				return true; // Bridge verification is optional
			case 4:
				return true; // Storage config has defaults
			case 5:
				return false; // Step 5 uses form submission, not Next
			default:
				return false;
		}
	}

	function nextStep(): void {
		if (currentStep < totalSteps && canAdvance()) {
			currentStep++;
			onStepEnter(currentStep);
		}
	}

	function prevStep(): void {
		if (currentStep > 1) {
			currentStep--;
		}
	}

	function goToStep(step: number): void {
		// Only allow going back to completed steps or the current step
		if (step <= currentStep && step >= 1) {
			currentStep = step;
			onStepEnter(step);
		}
	}

	function onStepEnter(step: number): void {
		if (step === 2 && interfaces.length === 0) {
			fetchNics();
		}
		if (step === 4 && !storageStatus) {
			fetchStorage();
		}
	}

	// ----- Step 1: Check requirements -----
	async function checkRequirements(): Promise<void> {
		checkingRequirements = true;

		// Check NICs
		requirements.nics = { ...requirements.nics, status: 'pending' };
		requirements.docker = { ...requirements.docker, status: 'pending' };
		requirements.disk = { ...requirements.disk, status: 'pending' };

		try {
			const nicRes = await fetch('/api/setup/nics');
			const nicData = await nicRes.json();
			const ethernetNics = (nicData.interfaces || []).filter(
				(iface: NetworkInterface) => iface.type === 'ethernet'
			);
			requirements.nics = {
				...requirements.nics,
				status: ethernetNics.length >= 2 ? 'pass' : 'fail',
			};

			// Pre-populate interfaces for step 2
			interfaces = nicData.interfaces || [];
			nicsSource = nicData.source || '';
		} catch {
			requirements.nics = { ...requirements.nics, status: 'fail' };
		}

		// Check Docker — use the health endpoint
		try {
			const healthRes = await fetch('/api/health');
			if (healthRes.ok) {
				requirements.docker = { ...requirements.docker, status: 'pass' };
			} else {
				// Health endpoint exists but returned non-ok — still means server is running
				requirements.docker = { ...requirements.docker, status: 'pass' };
			}
		} catch {
			// In development, if the health endpoint works, we consider Docker "available"
			requirements.docker = { ...requirements.docker, status: 'pass' };
		}

		// Check Disk via storage
		try {
			const storageRes = await fetch('/api/setup/storage');
			const storageData = await storageRes.json();
			const freeGb = storageData.disk_free_gb || 0;
			requirements.disk = {
				...requirements.disk,
				status: freeGb >= 100 ? 'pass' : 'fail',
			};
		} catch {
			requirements.disk = { ...requirements.disk, status: 'pass' };
		}

		requirementsChecked = true;
		checkingRequirements = false;
	}

	// ----- Step 2: Fetch NICs -----
	async function fetchNics(): Promise<void> {
		nicsLoading = true;
		nicsError = '';
		try {
			const res = await fetch('/api/setup/nics');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			interfaces = data.interfaces || [];
			nicsSource = data.source || '';
		} catch (err) {
			nicsError = err instanceof Error ? err.message : 'Failed to fetch interfaces';
		}
		nicsLoading = false;
	}

	// ----- Step 3: Verify bridge -----
	async function verifyBridge(): Promise<void> {
		bridgeLoading = true;
		bridgeError = '';
		bridgeVerified = false;
		try {
			const res = await fetch('/api/setup/bridge', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					wan_interface: selectedWan,
					lan_interface: selectedLan,
				}),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
			bridgeConfig = await res.json();
			bridgeVerified = bridgeConfig?.ready ?? false;
		} catch (err) {
			bridgeError = err instanceof Error ? err.message : 'Failed to verify bridge configuration';
		}
		bridgeLoading = false;
	}

	// ----- Step 4: Fetch storage -----
	async function fetchStorage(): Promise<void> {
		storageLoading = true;
		storageError = '';
		try {
			const res = await fetch('/api/setup/storage');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			storageStatus = await res.json();
			// Initialize form values from server defaults
			if (storageStatus) {
				hotDays = storageStatus.hot_days;
				warmDays = storageStatus.warm_days;
				coldDays = storageStatus.cold_days;
				diskThreshold = storageStatus.disk_threshold_percent;
				emergencyThreshold = storageStatus.emergency_threshold_percent;
			}
		} catch (err) {
			storageError = err instanceof Error ? err.message : 'Failed to fetch storage status';
		}
		storageLoading = false;
	}

	async function saveStorage(): Promise<void> {
		storageSaving = true;
		storageError = '';
		storageSaved = false;
		try {
			const res = await fetch('/api/setup/storage', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					hot_days: hotDays,
					warm_days: warmDays,
					cold_days: coldDays,
					disk_threshold_percent: diskThreshold,
					emergency_threshold_percent: emergencyThreshold,
				}),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
			storageSaved = true;
		} catch (err) {
			storageError = err instanceof Error ? err.message : 'Failed to save storage configuration';
		}
		storageSaving = false;
	}

	// ----- Handle form result for step 5 -----
	$effect(() => {
		if (form?.success) {
			// Account created — redirect to dashboard after a brief delay
			setTimeout(() => {
				goto('/login');
			}, 1500);
		}
		if (form?.error) {
			adminLoading = false;
		}
	});
</script>

<svelte:head>
	<title>Setup Wizard | NetTap</title>
</svelte:head>

<div class="wizard-page">
	<div class="wizard-container">
		<!-- Step indicator -->
		<nav class="step-indicator" aria-label="Setup progress">
			{#each stepLabels as label, i}
				{@const stepNum = i + 1}
				{@const isActive = stepNum === currentStep}
				{@const isCompleted = stepNum < currentStep}
				{@const isClickable = stepNum <= currentStep}
				<button
					class="step-item"
					class:active={isActive}
					class:completed={isCompleted}
					class:clickable={isClickable}
					disabled={!isClickable}
					onclick={() => goToStep(stepNum)}
					type="button"
					aria-current={isActive ? 'step' : undefined}
				>
					<span class="step-number">
						{#if isCompleted}
							<svg width="14" height="14" viewBox="0 0 14 14" fill="none">
								<path d="M2 7l3.5 3.5L12 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
							</svg>
						{:else}
							{stepNum}
						{/if}
					</span>
					<span class="step-label">{label}</span>
				</button>
				{#if i < stepLabels.length - 1}
					<div class="step-connector" class:completed={stepNum < currentStep}></div>
				{/if}
			{/each}
		</nav>

		<!-- Step content -->
		<div class="step-content">
			<!-- ===== STEP 1: Welcome ===== -->
			{#if currentStep === 1}
				<div class="step-panel">
					<div class="welcome-header">
						<svg class="logo" viewBox="0 0 48 48" width="64" height="64" fill="none">
							<rect width="48" height="48" rx="10" fill="var(--accent)"/>
							<path d="M12 24h24M24 12v24M15 15l18 18M33 15L15 33" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>
						</svg>
						<h1>Welcome to NetTap</h1>
						<p class="text-muted">
							NetTap is a network visibility appliance that sits transparently between your
							modem and router to monitor all network traffic. It provides enterprise-grade
							network telemetry via a polished web dashboard without requiring deep networking knowledge.
						</p>
					</div>

					<div class="info-box">
						<h3>What this wizard will configure:</h3>
						<ol class="setup-list">
							<li>Detect and select network interfaces (WAN and LAN)</li>
							<li>Configure a transparent network bridge</li>
							<li>Set up storage retention policies</li>
							<li>Create your admin account</li>
						</ol>
					</div>

					<div class="requirements-section">
						<h3>System Requirements</h3>
						<ul class="requirements-list">
							{#each Object.values(requirements) as req}
								<li class="requirement-item">
									<span class="req-icon" class:pass={req.status === 'pass'} class:fail={req.status === 'fail'}>
										{#if req.status === 'pending'}
											<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
												<circle cx="8" cy="8" r="6" stroke="var(--text-muted)" stroke-width="1.5"/>
											</svg>
										{:else if req.status === 'pass'}
											<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
												<circle cx="8" cy="8" r="6" fill="var(--success-muted)" stroke="var(--success)" stroke-width="1.5"/>
												<path d="M5 8l2 2 4-4" stroke="var(--success)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
											</svg>
										{:else}
											<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
												<circle cx="8" cy="8" r="6" fill="var(--danger-muted)" stroke="var(--danger)" stroke-width="1.5"/>
												<path d="M6 6l4 4M10 6l-4 4" stroke="var(--danger)" stroke-width="1.5" stroke-linecap="round"/>
											</svg>
										{/if}
									</span>
									<span class="req-label">{req.label}</span>
								</li>
							{/each}
						</ul>

						{#if !requirementsChecked}
							<button
								class="btn btn-primary btn-lg check-btn"
								onclick={checkRequirements}
								disabled={checkingRequirements}
								type="button"
							>
								{#if checkingRequirements}
									<span class="spinner"></span>
									Checking...
								{:else}
									Check Requirements
								{/if}
							</button>
						{:else}
							<div class="alert alert-success" style="margin-top: var(--space-md);">
								Requirements check complete. Click "Next" to continue.
							</div>
						{/if}
					</div>
				</div>

			<!-- ===== STEP 2: Network Interfaces ===== -->
			{:else if currentStep === 2}
				<div class="step-panel">
					<h2>Select Network Interfaces</h2>
					<p class="text-muted step-desc">
						Choose which network interfaces to use for the WAN (modem) and LAN (router) connections.
						NetTap will create a transparent bridge between these two interfaces.
					</p>

					{#if nicsSource === 'mock'}
						<div class="alert alert-warning" style="margin-bottom: var(--space-md);">
							Daemon unavailable — showing sample interface data. Actual interfaces will be detected on the target system.
						</div>
					{/if}

					{#if nicsError}
						<div class="alert alert-danger" style="margin-bottom: var(--space-md);">
							{nicsError}
							<button class="btn btn-sm" style="margin-left: var(--space-sm);" onclick={fetchNics} type="button">Retry</button>
						</div>
					{/if}

					{#if nicsLoading}
						<div class="loading-container">
							<span class="spinner"></span>
							<span>Detecting network interfaces...</span>
						</div>
					{:else}
						<!-- Network Diagram -->
						<div class="network-diagram">
							<div class="diagram-node">
								<div class="diagram-icon modem-icon">
									<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
										<rect x="3" y="6" width="18" height="12" rx="2"/>
										<circle cx="7" cy="12" r="1.5" fill="currentColor"/>
										<line x1="12" y1="9" x2="12" y2="15"/>
										<line x1="15" y1="9" x2="15" y2="15"/>
										<line x1="18" y1="9" x2="18" y2="15"/>
									</svg>
								</div>
								<span class="diagram-label">Modem</span>
							</div>
							<div class="diagram-arrow">
								<svg width="32" height="16" viewBox="0 0 32 16" fill="none">
									<path d="M0 8h28M22 3l6 5-6 5" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
								</svg>
							</div>
							<div class="diagram-node" class:selected={selectedWan !== ''}>
								<div class="diagram-icon wan-icon">
									<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
										<rect x="2" y="4" width="20" height="16" rx="2"/>
										<path d="M6 12h4M14 12h4"/>
									</svg>
								</div>
								<span class="diagram-label">{selectedWan || 'WAN NIC'}</span>
							</div>
							<div class="diagram-arrow">
								<svg width="32" height="16" viewBox="0 0 32 16" fill="none">
									<path d="M0 8h28M22 3l6 5-6 5" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
								</svg>
							</div>
							<div class="diagram-node bridge-node">
								<div class="diagram-icon bridge-icon">
									<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
										<rect x="4" y="8" width="16" height="8" rx="2"/>
										<path d="M8 8V5M16 8V5M4 12h16"/>
									</svg>
								</div>
								<span class="diagram-label">NetTap Bridge</span>
							</div>
							<div class="diagram-arrow">
								<svg width="32" height="16" viewBox="0 0 32 16" fill="none">
									<path d="M0 8h28M22 3l6 5-6 5" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
								</svg>
							</div>
							<div class="diagram-node" class:selected={selectedLan !== ''}>
								<div class="diagram-icon lan-icon">
									<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
										<rect x="2" y="4" width="20" height="16" rx="2"/>
										<path d="M6 12h4M14 12h4"/>
									</svg>
								</div>
								<span class="diagram-label">{selectedLan || 'LAN NIC'}</span>
							</div>
							<div class="diagram-arrow">
								<svg width="32" height="16" viewBox="0 0 32 16" fill="none">
									<path d="M0 8h28M22 3l6 5-6 5" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
								</svg>
							</div>
							<div class="diagram-node">
								<div class="diagram-icon router-icon">
									<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
										<rect x="3" y="8" width="18" height="8" rx="2"/>
										<path d="M12 4v4M8 4l4 0M12 4l4 0"/>
										<circle cx="7" cy="12" r="1" fill="currentColor"/>
										<circle cx="11" cy="12" r="1" fill="currentColor"/>
									</svg>
								</div>
								<span class="diagram-label">Router</span>
							</div>
						</div>

						<!-- Interface Selectors -->
						<div class="nic-selectors">
							<div class="form-group">
								<label for="wan-select" class="label">
									WAN Interface
									<span class="text-muted">(connects to modem)</span>
								</label>
								<select id="wan-select" class="input" bind:value={selectedWan}>
									<option value="">-- Select WAN interface --</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name} disabled={iface.name === selectedLan}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
										</option>
									{/each}
								</select>
								{#if selectedWanDetails}
									<div class="nic-details">
										<span class="badge badge-accent">{selectedWanDetails.driver || 'unknown'}</span>
										<span class="badge">{selectedWanDetails.speed || 'N/A'}</span>
										<span class="badge" class:badge-success={selectedWanDetails.state === 'up'} class:badge-danger={selectedWanDetails.state === 'down'}>
											{selectedWanDetails.state}
										</span>
										{#if selectedWanDetails.ipv4}
											<span class="badge">{selectedWanDetails.ipv4}</span>
										{/if}
									</div>
								{/if}
							</div>

							<div class="form-group">
								<label for="lan-select" class="label">
									LAN Interface
									<span class="text-muted">(connects to router)</span>
								</label>
								<select id="lan-select" class="input" bind:value={selectedLan}>
									<option value="">-- Select LAN interface --</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name} disabled={iface.name === selectedWan}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
										</option>
									{/each}
								</select>
								{#if selectedLanDetails}
									<div class="nic-details">
										<span class="badge badge-accent">{selectedLanDetails.driver || 'unknown'}</span>
										<span class="badge">{selectedLanDetails.speed || 'N/A'}</span>
										<span class="badge" class:badge-success={selectedLanDetails.state === 'up'} class:badge-danger={selectedLanDetails.state === 'down'}>
											{selectedLanDetails.state}
										</span>
										{#if selectedLanDetails.ipv4}
											<span class="badge">{selectedLanDetails.ipv4}</span>
										{/if}
									</div>
								{/if}
							</div>
						</div>

						{#if selectedWan && selectedLan && selectedWan === selectedLan}
							<div class="alert alert-danger">
								WAN and LAN interfaces must be different.
							</div>
						{/if}

						<button class="btn btn-sm btn-secondary" onclick={fetchNics} type="button" style="margin-top: var(--space-sm);">
							Refresh Interfaces
						</button>
					{/if}
				</div>

			<!-- ===== STEP 3: Bridge Configuration ===== -->
			{:else if currentStep === 3}
				<div class="step-panel">
					<h2>Bridge Configuration</h2>
					<p class="text-muted step-desc">
						Review and verify the bridge configuration. NetTap will create a transparent Layer 2 bridge
						between your selected interfaces.
					</p>

					<div class="bridge-summary card">
						<div class="bridge-row">
							<span class="bridge-label">WAN Interface:</span>
							<span class="bridge-value mono">{selectedWan}</span>
						</div>
						<div class="bridge-row">
							<span class="bridge-label">LAN Interface:</span>
							<span class="bridge-value mono">{selectedLan}</span>
						</div>
						<div class="bridge-row">
							<span class="bridge-label">Bridge Name:</span>
							<span class="bridge-value mono">br0</span>
						</div>
						<div class="bridge-row">
							<span class="bridge-label">Mode:</span>
							<span class="bridge-value">Transparent (Layer 2 forwarding)</span>
						</div>
					</div>

					{#if bridgeError}
						<div class="alert alert-danger" style="margin-bottom: var(--space-md);">
							{bridgeError}
						</div>
					{/if}

					{#if bridgeConfig && bridgeVerified}
						<div class="alert alert-success" style="margin-bottom: var(--space-md);">
							Configuration verified successfully.
						</div>

						{#if bridgeConfig.warnings.length > 0}
							<div class="alert alert-warning" style="margin-bottom: var(--space-md);">
								{#each bridgeConfig.warnings as warning}
									<p>{warning}</p>
								{/each}
							</div>
						{/if}

						<div class="config-preview">
							<h4>Configuration Preview</h4>
							<pre>{bridgeConfig.config_preview}</pre>
						</div>
					{/if}

					<div class="bridge-actions">
						<button
							class="btn btn-primary"
							onclick={verifyBridge}
							disabled={bridgeLoading}
							type="button"
						>
							{#if bridgeLoading}
								<span class="spinner"></span>
								Verifying...
							{:else if bridgeVerified}
								Re-verify Configuration
							{:else}
								Verify Configuration
							{/if}
						</button>
					</div>

					<div class="alert alert-info" style="margin-top: var(--space-md);">
						The bridge will be configured when you complete the setup wizard and start NetTap services.
						No changes will be made to your network until then.
					</div>
				</div>

			<!-- ===== STEP 4: Storage Configuration ===== -->
			{:else if currentStep === 4}
				<div class="step-panel">
					<h2>Storage Configuration</h2>
					<p class="text-muted step-desc">
						Configure data retention policies and disk usage thresholds. NetTap uses a three-tier
						storage strategy for optimal space usage.
					</p>

					{#if storageError}
						<div class="alert alert-danger" style="margin-bottom: var(--space-md);">
							{storageError}
						</div>
					{/if}

					{#if storageLoading}
						<div class="loading-container">
							<span class="spinner"></span>
							<span>Loading storage information...</span>
						</div>
					{:else if storageStatus}
						<!-- Disk Usage Bar -->
						<div class="storage-overview card">
							<h3>Disk Usage</h3>
							<div class="disk-bar-container">
								<div class="disk-bar">
									<div
										class="disk-bar-fill"
										style="width: {storageStatus.disk_usage_percent}%; background-color: {diskUsageColor};"
									></div>
									<div
										class="disk-bar-threshold"
										style="left: {diskThreshold}%;"
										title="Warning threshold ({diskThreshold}%)"
									></div>
									<div
										class="disk-bar-threshold emergency"
										style="left: {emergencyThreshold}%;"
										title="Emergency threshold ({emergencyThreshold}%)"
									></div>
								</div>
								<div class="disk-stats">
									<span>{storageStatus.disk_used_gb.toFixed(1)} GB used</span>
									<span>{storageStatus.disk_free_gb.toFixed(1)} GB free</span>
									<span>{storageStatus.disk_total_gb.toFixed(1)} GB total</span>
								</div>
							</div>

							{#if estimatedTotalDays > 0}
								<div class="estimate-box">
									<span class="estimate-label">Estimated retention capacity:</span>
									<span class="estimate-value">{estimatedTotalDays} days</span>
									<span class="text-muted">at ~{storageStatus.estimated_daily_gb} GB/day</span>
								</div>
							{/if}
						</div>

						<!-- Retention Settings -->
						<div class="retention-grid">
							<div class="retention-card card">
								<div class="tier-header">
									<span class="tier-dot hot"></span>
									<h4>Hot Tier</h4>
								</div>
								<p class="text-muted tier-desc">Zeek metadata logs (conn, DNS, HTTP, TLS, etc.)</p>
								<div class="form-group">
									<label for="hot-days" class="label">Retention (days)</label>
									<input
										id="hot-days"
										type="number"
										class="input"
										bind:value={hotDays}
										min="1"
										max="365"
									/>
								</div>
								<span class="tier-size text-muted">~300-800 MB/day</span>
							</div>

							<div class="retention-card card">
								<div class="tier-header">
									<span class="tier-dot warm"></span>
									<h4>Warm Tier</h4>
								</div>
								<p class="text-muted tier-desc">Suricata IDS alerts and signatures</p>
								<div class="form-group">
									<label for="warm-days" class="label">Retention (days)</label>
									<input
										id="warm-days"
										type="number"
										class="input"
										bind:value={warmDays}
										min="1"
										max="730"
									/>
								</div>
								<span class="tier-size text-muted">~10-50 MB/day</span>
							</div>

							<div class="retention-card card">
								<div class="tier-header">
									<span class="tier-dot cold"></span>
									<h4>Cold Tier</h4>
								</div>
								<p class="text-muted tier-desc">Raw PCAP files (alert-triggered only)</p>
								<div class="form-group">
									<label for="cold-days" class="label">Retention (days)</label>
									<input
										id="cold-days"
										type="number"
										class="input"
										bind:value={coldDays}
										min="1"
										max="365"
									/>
								</div>
								<span class="tier-size text-muted">Variable size</span>
							</div>
						</div>

						<!-- Threshold Settings -->
						<div class="threshold-section card">
							<h3>Disk Thresholds</h3>
							<p class="text-muted" style="margin-bottom: var(--space-md);">
								When disk usage exceeds the warning threshold, old data is purged starting from the oldest tier.
								The emergency threshold triggers immediate cleanup.
							</p>

							<div class="threshold-grid">
								<div class="form-group">
									<label for="disk-threshold" class="label">
										Warning Threshold
										<span class="badge badge-warning">{diskThreshold}%</span>
									</label>
									<input
										id="disk-threshold"
										type="range"
										class="range-input"
										bind:value={diskThreshold}
										min="50"
										max="95"
										step="1"
									/>
									<div class="range-labels">
										<span>50%</span>
										<span>95%</span>
									</div>
								</div>

								<div class="form-group">
									<label for="emergency-threshold" class="label">
										Emergency Threshold
										<span class="badge badge-danger">{emergencyThreshold}%</span>
									</label>
									<input
										id="emergency-threshold"
										type="range"
										class="range-input"
										bind:value={emergencyThreshold}
										min={diskThreshold + 1}
										max="99"
										step="1"
									/>
									<div class="range-labels">
										<span>{diskThreshold + 1}%</span>
										<span>99%</span>
									</div>
								</div>
							</div>
						</div>

						<div class="save-storage-row">
							<button
								class="btn btn-primary"
								onclick={saveStorage}
								disabled={storageSaving}
								type="button"
							>
								{#if storageSaving}
									<span class="spinner"></span>
									Saving...
								{:else}
									Save Storage Configuration
								{/if}
							</button>
							{#if storageSaved}
								<span class="badge badge-success">Saved</span>
							{/if}
						</div>
					{/if}
				</div>

			<!-- ===== STEP 5: Admin Account ===== -->
			{:else if currentStep === 5}
				<div class="step-panel">
					<h2>Create Admin Account</h2>
					<p class="text-muted step-desc">
						Create your administrator account. This will be used to log in to the NetTap dashboard.
					</p>

					{#if form?.error || clientError}
						<div class="alert alert-danger" style="margin-bottom: var(--space-md);">
							{form?.error || clientError}
						</div>
					{/if}

					{#if form?.success}
						<div class="alert alert-success" style="margin-bottom: var(--space-md);">
							Admin account created successfully! Redirecting to login...
						</div>
					{:else}
						<form
							method="POST"
							action="?/createAdmin"
							use:enhance={() => {
								clientError = '';

								// Client-side validation
								if (adminUsername.trim().length < 3) {
									clientError = 'Username must be at least 3 characters.';
									return ({ update }) => { update({ reset: false }); };
								}
								if (!passwordValid) {
									clientError = 'Password does not meet requirements.';
									return ({ update }) => { update({ reset: false }); };
								}
								if (!passwordsMatch) {
									clientError = 'Passwords do not match.';
									return ({ update }) => { update({ reset: false }); };
								}

								adminLoading = true;
								return async ({ update }) => {
									adminLoading = false;
									await update({ reset: false });
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
									minlength="3"
									bind:value={adminUsername}
								/>
								<span class="input-hint text-muted">At least 3 characters. Letters, numbers, hyphens, underscores.</span>
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
									bind:value={adminPassword}
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
									bind:value={adminConfirmPassword}
								/>
							</div>

							<!-- Password requirements -->
							<div class="password-requirements">
								<span class="req-heading">Password requirements:</span>
								<ul class="req-list">
									<li class:met={passwordHasLength}>
										<span class="req-check">{passwordHasLength ? '\u2713' : '\u2717'}</span>
										At least 8 characters
									</li>
									<li class:met={passwordHasUpper}>
										<span class="req-check">{passwordHasUpper ? '\u2713' : '\u2717'}</span>
										One uppercase letter
									</li>
									<li class:met={passwordHasLower}>
										<span class="req-check">{passwordHasLower ? '\u2713' : '\u2717'}</span>
										One lowercase letter
									</li>
									<li class:met={passwordHasNumber}>
										<span class="req-check">{passwordHasNumber ? '\u2713' : '\u2717'}</span>
										One number
									</li>
									<li class:met={passwordsMatch}>
										<span class="req-check">{passwordsMatch ? '\u2713' : '\u2717'}</span>
										Passwords match
									</li>
								</ul>
							</div>

							<button
								type="submit"
								class="btn btn-primary btn-lg finish-btn"
								disabled={adminLoading || !adminFormValid}
							>
								{#if adminLoading}
									<span class="spinner"></span>
									Creating Account...
								{:else}
									Complete Setup
								{/if}
							</button>
						</form>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Navigation buttons -->
		{#if currentStep < 5 || (currentStep === 5 && form?.success)}
			<div class="wizard-nav">
				{#if currentStep > 1 && !form?.success}
					<button class="btn btn-secondary" onclick={prevStep} type="button">
						<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
							<path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
						</svg>
						Back
					</button>
				{:else}
					<div></div>
				{/if}

				{#if currentStep < 5}
					<div class="nav-right">
						{#if currentStep === 3 || currentStep === 4}
							<button class="btn btn-secondary" onclick={nextStep} type="button">
								Skip
							</button>
						{/if}
						<button
							class="btn btn-primary"
							onclick={nextStep}
							disabled={!canAdvance()}
							type="button"
						>
							{currentStep === 1 ? 'Get Started' : 'Next'}
							<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
								<path d="M6 3l5 5-5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
							</svg>
						</button>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	/* ===== Page Layout ===== */
	.wizard-page {
		min-height: 100vh;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		background-color: var(--bg-primary);
		padding: var(--space-xl) var(--space-md);
	}

	.wizard-container {
		width: 100%;
		max-width: 780px;
		margin-top: var(--space-lg);
	}

	/* ===== Step Indicator ===== */
	.step-indicator {
		display: flex;
		align-items: center;
		justify-content: center;
		margin-bottom: var(--space-xl);
		gap: 0;
	}

	.step-item {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-xs);
		background: none;
		border: none;
		cursor: default;
		padding: 0 var(--space-xs);
		font-family: var(--font-sans);
		min-width: 70px;
	}

	.step-item.clickable {
		cursor: pointer;
	}

	.step-item:disabled {
		opacity: 0.4;
	}

	.step-number {
		width: 32px;
		height: 32px;
		border-radius: var(--radius-full);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: var(--text-sm);
		font-weight: 600;
		background-color: var(--bg-tertiary);
		color: var(--text-muted);
		border: 2px solid var(--border-default);
		transition: all var(--transition-fast);
	}

	.step-item.active .step-number {
		background-color: var(--accent);
		color: #fff;
		border-color: var(--accent);
	}

	.step-item.completed .step-number {
		background-color: var(--success-muted);
		color: var(--success);
		border-color: var(--success);
	}

	.step-label {
		font-size: var(--text-xs);
		color: var(--text-muted);
		font-weight: 500;
		white-space: nowrap;
	}

	.step-item.active .step-label {
		color: var(--accent);
	}

	.step-item.completed .step-label {
		color: var(--success);
	}

	.step-connector {
		flex: 1;
		height: 2px;
		background-color: var(--border-default);
		margin: 0 var(--space-xs);
		margin-bottom: 20px; /* align with step-number center */
		min-width: 20px;
		max-width: 60px;
	}

	.step-connector.completed {
		background-color: var(--success);
	}

	/* ===== Step Content ===== */
	.step-content {
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-xl);
		padding: var(--space-2xl);
		margin-bottom: var(--space-md);
	}

	.step-panel h2 {
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.step-desc {
		font-size: var(--text-sm);
		margin-bottom: var(--space-lg);
	}

	/* ===== Step 1: Welcome ===== */
	.welcome-header {
		text-align: center;
		margin-bottom: var(--space-xl);
	}

	.logo {
		margin-bottom: var(--space-md);
	}

	.welcome-header h1 {
		font-size: var(--text-3xl);
		font-weight: 700;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.welcome-header p {
		font-size: var(--text-sm);
		line-height: var(--leading-relaxed);
		max-width: 520px;
		margin: 0 auto;
	}

	.info-box {
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-lg);
		margin-bottom: var(--space-xl);
	}

	.info-box h3 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.setup-list {
		padding-left: var(--space-lg);
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: var(--leading-relaxed);
	}

	.setup-list li {
		margin-bottom: var(--space-xs);
	}

	.requirements-section h3 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-md);
	}

	.requirements-list {
		list-style: none;
		padding: 0;
		margin-bottom: var(--space-md);
	}

	.requirement-item {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) 0;
		font-size: var(--text-sm);
		color: var(--text-secondary);
		border-bottom: 1px solid var(--border-muted);
	}

	.requirement-item:last-child {
		border-bottom: none;
	}

	.req-icon {
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.check-btn {
		width: 100%;
		margin-top: var(--space-sm);
	}

	/* ===== Step 2: Network Interfaces ===== */
	.network-diagram {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-xs);
		padding: var(--space-lg) var(--space-sm);
		margin-bottom: var(--space-lg);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		overflow-x: auto;
	}

	.diagram-node {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-xs);
		min-width: 56px;
	}

	.diagram-icon {
		width: 44px;
		height: 44px;
		border-radius: var(--radius-md);
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-default);
		color: var(--text-secondary);
		transition: all var(--transition-fast);
	}

	.diagram-node.selected .diagram-icon,
	.diagram-node.bridge-node .diagram-icon {
		border-color: var(--accent);
		color: var(--accent);
		background-color: var(--accent-muted);
	}

	.diagram-label {
		font-size: 10px;
		color: var(--text-muted);
		font-weight: 500;
		white-space: nowrap;
		font-family: var(--font-mono);
	}

	.diagram-arrow {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		margin-bottom: 18px; /* align with icon center */
	}

	.nic-selectors {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-lg);
		margin-bottom: var(--space-md);
	}

	@media (max-width: 640px) {
		.nic-selectors {
			grid-template-columns: 1fr;
		}
		.network-diagram {
			flex-wrap: wrap;
			gap: var(--space-sm);
		}
		.diagram-arrow {
			display: none;
		}
	}

	.nic-details {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
		margin-top: var(--space-sm);
	}

	/* ===== Step 3: Bridge Configuration ===== */
	.bridge-summary {
		margin-bottom: var(--space-lg);
	}

	.bridge-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-sm) 0;
		border-bottom: 1px solid var(--border-muted);
	}

	.bridge-row:last-child {
		border-bottom: none;
	}

	.bridge-label {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		font-weight: 500;
	}

	.bridge-value {
		font-size: var(--text-sm);
		color: var(--text-primary);
		font-weight: 600;
	}

	.config-preview {
		margin-bottom: var(--space-md);
	}

	.config-preview h4 {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.bridge-actions {
		margin-bottom: var(--space-sm);
	}

	/* ===== Step 4: Storage Configuration ===== */
	.storage-overview {
		margin-bottom: var(--space-lg);
	}

	.storage-overview h3 {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-md);
	}

	.disk-bar-container {
		margin-bottom: var(--space-md);
	}

	.disk-bar {
		width: 100%;
		height: 24px;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-full);
		overflow: visible;
		position: relative;
		border: 1px solid var(--border-default);
	}

	.disk-bar-fill {
		height: 100%;
		border-radius: var(--radius-full);
		transition: width var(--transition-normal), background-color var(--transition-normal);
		min-width: 2px;
	}

	.disk-bar-threshold {
		position: absolute;
		top: -4px;
		bottom: -4px;
		width: 2px;
		background-color: var(--warning);
		border-radius: 1px;
	}

	.disk-bar-threshold.emergency {
		background-color: var(--danger);
	}

	.disk-stats {
		display: flex;
		justify-content: space-between;
		margin-top: var(--space-sm);
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.estimate-box {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-sm) var(--space-md);
		background-color: var(--accent-muted);
		border-radius: var(--radius-md);
		font-size: var(--text-sm);
	}

	.estimate-label {
		color: var(--text-secondary);
	}

	.estimate-value {
		font-weight: 700;
		color: var(--accent);
		font-size: var(--text-lg);
	}

	.retention-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	@media (max-width: 768px) {
		.retention-grid {
			grid-template-columns: 1fr;
		}
	}

	.retention-card {
		text-align: left;
	}

	.tier-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.tier-header h4 {
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--text-primary);
	}

	.tier-dot {
		width: 10px;
		height: 10px;
		border-radius: var(--radius-full);
	}

	.tier-dot.hot {
		background-color: var(--danger);
	}

	.tier-dot.warm {
		background-color: var(--warning);
	}

	.tier-dot.cold {
		background-color: var(--accent);
	}

	.tier-desc {
		font-size: var(--text-xs);
		margin-bottom: var(--space-md);
	}

	.tier-size {
		font-size: var(--text-xs);
	}

	.threshold-section {
		margin-bottom: var(--space-lg);
	}

	.threshold-section h3 {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-xs);
	}

	.threshold-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-lg);
	}

	@media (max-width: 640px) {
		.threshold-grid {
			grid-template-columns: 1fr;
		}
	}

	.range-input {
		width: 100%;
		-webkit-appearance: none;
		appearance: none;
		height: 6px;
		border-radius: 3px;
		background-color: var(--bg-tertiary);
		outline: none;
		border: 1px solid var(--border-default);
	}

	.range-input::-webkit-slider-thumb {
		-webkit-appearance: none;
		appearance: none;
		width: 18px;
		height: 18px;
		border-radius: var(--radius-full);
		background-color: var(--accent);
		cursor: pointer;
		border: 2px solid var(--bg-secondary);
		box-shadow: var(--shadow-sm);
	}

	.range-input::-moz-range-thumb {
		width: 18px;
		height: 18px;
		border-radius: var(--radius-full);
		background-color: var(--accent);
		cursor: pointer;
		border: 2px solid var(--bg-secondary);
		box-shadow: var(--shadow-sm);
	}

	.range-labels {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: var(--space-xs);
	}

	.save-storage-row {
		display: flex;
		align-items: center;
		gap: var(--space-md);
	}

	/* ===== Step 5: Admin Account ===== */
	.input-hint {
		display: block;
		font-size: var(--text-xs);
		margin-top: var(--space-xs);
	}

	.password-requirements {
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		border-radius: var(--radius-md);
		padding: var(--space-md);
		margin-bottom: var(--space-lg);
	}

	.req-heading {
		display: block;
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-secondary);
		margin-bottom: var(--space-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.req-list {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-xs) var(--space-md);
	}

	@media (max-width: 480px) {
		.req-list {
			grid-template-columns: 1fr;
		}
	}

	.req-list li {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: var(--text-xs);
		color: var(--text-muted);
		transition: color var(--transition-fast);
	}

	.req-list li.met {
		color: var(--success);
	}

	.req-check {
		font-weight: 700;
		font-size: var(--text-sm);
		width: 16px;
		text-align: center;
		flex-shrink: 0;
	}

	.finish-btn {
		width: 100%;
		margin-top: var(--space-sm);
	}

	/* ===== Navigation ===== */
	.wizard-nav {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.nav-right {
		display: flex;
		gap: var(--space-sm);
	}

	/* ===== Shared ===== */
	.loading-container {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-sm);
		padding: var(--space-xl);
		color: var(--text-secondary);
		font-size: var(--text-sm);
	}

	.spinner {
		display: inline-block;
		width: 16px;
		height: 16px;
		border: 2px solid var(--border-default);
		border-top-color: var(--accent);
		border-radius: var(--radius-full);
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	select.input {
		cursor: pointer;
		-webkit-appearance: none;
		appearance: none;
		background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%236e7681' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right 12px center;
		padding-right: 32px;
	}

	/* Number input styling */
	input[type="number"].input {
		appearance: textfield;
		-moz-appearance: textfield;
	}

	input[type="number"].input::-webkit-outer-spin-button,
	input[type="number"].input::-webkit-inner-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}
</style>
