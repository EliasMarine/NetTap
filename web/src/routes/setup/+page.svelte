<script lang="ts">
	import { enhance } from '$app/forms';
	import { goto } from '$app/navigation';

	const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8880';

	let { form } = $props();

	// ----- Wizard state -----
	let currentStep = $state(1);

	// OLD CODE START — fixed totalSteps / stepLabels for bridge-only wizard
	// const totalSteps = 5;
	// const stepLabels = ['Welcome', 'Interfaces', 'Bridge', 'Storage', 'Account'];
	// OLD CODE END

	// Capture mode: 'mirror' (Mirror/SPAN) or 'bridge' (Inline Bridge)
	type CaptureMode = 'mirror' | 'bridge' | '';
	let selectedMode = $state<CaptureMode>('');

	// Dynamic step labels based on mode
	// Mirror: Welcome -> Capture Mode -> Interfaces (mirror) -> Storage -> Device Enrichment -> Account
	// Bridge: Welcome -> Capture Mode -> Interfaces (bridge) -> Bridge Config -> Storage -> Account
	// Before mode selected: Welcome -> Capture Mode (only 2 steps available)
	let stepLabels = $derived.by(() => {
		if (selectedMode === 'mirror') {
			return ['Welcome', 'Capture Mode', 'Interfaces', 'Storage', 'Enrichment', 'Account'];
		} else if (selectedMode === 'bridge') {
			return ['Welcome', 'Capture Mode', 'Interfaces', 'Bridge', 'Storage', 'Account'];
		}
		return ['Welcome', 'Capture Mode'];
	});

	let totalSteps = $derived(stepLabels.length);

	// ----- Step 1: Welcome -----
	let requirementsChecked = $state(false);
	let checkingRequirements = $state(false);
	let requirements = $state({
		nics: { label: 'One or more network interfaces', status: 'pending' as 'pending' | 'pass' | 'fail' },
		docker: { label: 'Docker is running', status: 'pending' as 'pending' | 'pass' | 'fail' },
		disk: { label: 'Sufficient disk space (100GB+)', status: 'pending' as 'pending' | 'pass' | 'fail' },
	});

	// Track detected NIC count for mode-dependent validation
	let detectedEthernetNicCount = $state(0);

	// ----- Step 3: Network Interfaces -----
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

	// Bridge mode NIC selection
	let selectedWan = $state('');
	let selectedLan = $state('');

	// Mirror mode NIC selection
	let selectedMirrorNic = $state('');
	let selectedManagementNic = $state('');

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

	let selectedMirrorNicDetails = $derived(
		interfaces.find((iface) => iface.name === selectedMirrorNic)
	);

	let selectedManagementNicDetails = $derived(
		interfaces.find((iface) => iface.name === selectedManagementNic)
	);

	let nicSelectionValid = $derived.by(() => {
		if (selectedMode === 'mirror') {
			return selectedMirrorNic !== '';
		}
		return selectedWan !== '' && selectedLan !== '' && selectedWan !== selectedLan;
	});

	// ----- Step 4 (bridge mode): Bridge Configuration -----
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

	// ----- Storage Configuration -----
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

	// ----- Device Enrichment (mirror mode only) -----
	let useUnifi = $state(false);
	let unifiUrl = $state('');
	let unifiUsername = $state('');
	let unifiPassword = $state('');
	let unifiTesting = $state(false);
	let unifiTestResult = $state<'success' | 'fail' | ''>('');
	let unifiTestError = $state('');

	// ----- Admin Account -----
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

	// ----- Saving config on completion -----
	let configSaving = $state(false);
	let configSaveError = $state('');

	// ----- Helper: get the logical step name for the current step number -----
	function getStepName(step: number): string {
		return stepLabels[step - 1] || '';
	}

	// ----- Navigation logic -----
	function canAdvance(): boolean {
		const stepName = getStepName(currentStep);
		switch (stepName) {
			case 'Welcome':
				return requirementsChecked;
			case 'Capture Mode':
				return selectedMode !== '';
			case 'Interfaces':
				return nicSelectionValid;
			case 'Bridge':
				return true; // Bridge verification is optional
			case 'Storage':
				return true; // Storage config has defaults
			case 'Enrichment':
				return true; // Enrichment is optional
			case 'Account':
				return false; // Step uses form submission, not Next
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
		const stepName = getStepName(step);
		if (stepName === 'Interfaces' && interfaces.length === 0) {
			fetchNics();
		}
		if (stepName === 'Storage' && !storageStatus) {
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
			if (!nicRes.ok) throw new Error(`HTTP ${nicRes.status}`);
			const text = await nicRes.text();
			let nicData: { interfaces?: NetworkInterface[]; source?: string };
			try {
				nicData = JSON.parse(text);
			} catch {
				throw new Error('Server returned invalid data');
			}
			// Count non-loopback, non-virtual interfaces available
			const bridgeableNics = (nicData.interfaces || []).filter(
				(iface: NetworkInterface) => iface.type === 'ethernet'
			);
			detectedEthernetNicCount = bridgeableNics.length;

			// Before mode is selected, require at least 1 NIC (minimum for mirror)
			// Once mode is selected, mirror needs 1+, bridge needs 2+
			const minNics = selectedMode === 'bridge' ? 2 : 1;
			requirements.nics = {
				...requirements.nics,
				label: minNics >= 2 ? 'Two or more network interfaces' : 'One or more network interfaces',
				status: bridgeableNics.length >= minNics ? 'pass' : 'fail',
			};

			// Pre-populate interfaces for step 3
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

	// ----- Step 3: Fetch NICs -----
	async function fetchNics(): Promise<void> {
		nicsLoading = true;
		nicsError = '';
		try {
			const res = await fetch('/api/setup/nics');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const text = await res.text();
			let data: { interfaces?: NetworkInterface[]; source?: string };
			try {
				data = JSON.parse(text);
			} catch {
				throw new Error('Server returned invalid data — daemon may need restart');
			}
			interfaces = data.interfaces || [];
			nicsSource = data.source || '';
		} catch (err) {
			nicsError = err instanceof Error ? err.message : 'Failed to fetch interfaces';
		}
		nicsLoading = false;
	}

	// ----- Bridge verify -----
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
			if (bridgeVerified && typeof window !== 'undefined') {
				localStorage.setItem('nettap_wan_iface', selectedWan);
				localStorage.setItem('nettap_lan_iface', selectedLan);
			}
		} catch (err) {
			bridgeError = err instanceof Error ? err.message : 'Failed to verify bridge configuration';
		}
		bridgeLoading = false;
	}

	// ----- Storage fetch/save -----
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

	// ----- Device Enrichment: test UniFi connection -----
	async function testUnifiConnection(): Promise<void> {
		unifiTesting = true;
		unifiTestResult = '';
		unifiTestError = '';
		try {
			const res = await fetch(`${API_BASE}/api/integrations/unifi/test`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					url: unifiUrl,
					username: unifiUsername,
					password: unifiPassword,
				}),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
			unifiTestResult = 'success';
		} catch (err) {
			unifiTestResult = 'fail';
			unifiTestError = err instanceof Error ? err.message : 'Connection test failed';
		}
		unifiTesting = false;
	}

	// ----- Save setup configuration -----
	async function saveSetupConfig(): Promise<void> {
		configSaving = true;
		configSaveError = '';
		try {
			const payload: Record<string, unknown> = {
				capture_mode: selectedMode,
			};

			if (selectedMode === 'mirror') {
				payload.capture_interface = selectedMirrorNic;
				if (selectedManagementNic) {
					payload.management_interface = selectedManagementNic;
				}
				if (useUnifi) {
					payload.unifi = {
						url: unifiUrl,
						username: unifiUsername,
						password: unifiPassword,
					};
				}
			} else {
				payload.wan_interface = selectedWan;
				payload.lan_interface = selectedLan;
			}

			payload.storage = {
				hot_days: hotDays,
				warm_days: warmDays,
				cold_days: coldDays,
				disk_threshold_percent: diskThreshold,
				emergency_threshold_percent: emergencyThreshold,
			};

			const res = await fetch(`${API_BASE}/api/setup/configure`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
		} catch (err) {
			configSaveError = err instanceof Error ? err.message : 'Failed to save configuration';
		}
		configSaving = false;
	}

	// ----- Handle form result for Account step -----
	$effect(() => {
		if (form?.success) {
			// Account created — save config then redirect
			saveSetupConfig().then(() => {
				setTimeout(() => {
					goto('/go-live');
				}, 1500);
			});
		}
		if (form?.error) {
			adminLoading = false;
		}
	});

	// Auto-run requirements check when page loads
	$effect(() => {
		if (!requirementsChecked && !checkingRequirements) {
			checkRequirements();
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
			<!-- ===== STEP: Welcome ===== -->
			{#if getStepName(currentStep) === 'Welcome'}
				<div class="step-panel">
					<div class="welcome-header">
						<svg class="logo" viewBox="0 0 48 48" width="64" height="64" fill="none">
							<rect width="48" height="48" rx="10" fill="var(--accent)"/>
							<path d="M12 24h24M24 12v24M15 15l18 18M33 15L15 33" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>
						</svg>
						<h1>Welcome to NetTap</h1>
						<p class="text-muted">
							NetTap is a network visibility appliance that provides enterprise-grade
							network telemetry via a polished web dashboard without requiring deep networking knowledge.
						</p>
					</div>

					<div class="info-box">
						<h3>What this wizard will configure:</h3>
						<ol class="setup-list">
							<li>Choose your capture mode (Mirror/SPAN or Inline Bridge)</li>
							<li>Detect and select network interfaces</li>
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

			<!-- ===== STEP: Capture Mode ===== -->
			{:else if getStepName(currentStep) === 'Capture Mode'}
				<div class="step-panel">
					<h2>Choose Capture Mode</h2>
					<p class="text-muted step-desc">
						Select how NetTap will capture network traffic. This determines the hardware
						setup and what traffic NetTap can see.
					</p>

					<div class="mode-cards">
						<button
							class="mode-card"
							class:selected={selectedMode === 'mirror'}
							onclick={() => { selectedMode = 'mirror'; }}
							type="button"
						>
							<div class="mode-badge recommended">Recommended</div>
							<div class="mode-icon">
								<svg width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5">
									<rect x="4" y="8" width="24" height="16" rx="3"/>
									<path d="M10 16h4M18 16h4"/>
									<path d="M16 4v4" stroke-dasharray="2 2"/>
									<circle cx="16" cy="3" r="1.5" fill="currentColor"/>
								</svg>
							</div>
							<h3>Mirror / SPAN</h3>
							<p class="mode-desc">
								My managed switch sends a copy of network traffic to NetTap.
								Zero risk to your network. Best for per-device visibility.
							</p>
							<ul class="mode-features">
								<li>Requires 1 NIC for capture</li>
								<li>No inline risk — switch handles mirroring</li>
								<li>See traffic per device on the LAN</li>
							</ul>
						</button>

						<button
							class="mode-card"
							class:selected={selectedMode === 'bridge'}
							onclick={() => { selectedMode = 'bridge'; }}
							type="button"
						>
							<div class="mode-icon">
								<svg width="32" height="32" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5">
									<rect x="2" y="12" width="12" height="8" rx="2"/>
									<rect x="18" y="12" width="12" height="8" rx="2"/>
									<path d="M14 16h4"/>
									<path d="M8 12V8M24 12V8"/>
								</svg>
							</div>
							<h3>Inline Bridge</h3>
							<p class="mode-desc">
								NetTap sits between your modem and router. Sees all WAN traffic.
								Requires two dedicated NICs.
							</p>
							<ul class="mode-features">
								<li>Requires 2 NICs (WAN + LAN)</li>
								<li>Transparent Layer 2 bridge</li>
								<li>Sees all WAN ingress/egress</li>
							</ul>
						</button>
					</div>

					{#if selectedMode === 'bridge' && detectedEthernetNicCount < 2}
						<div class="alert alert-warning" style="margin-top: var(--space-md);">
							Bridge mode requires 2 Ethernet NICs, but only {detectedEthernetNicCount} were detected.
							You may continue, but bridge configuration will fail without 2 NICs.
						</div>
					{/if}
				</div>

			<!-- ===== STEP: Interfaces (mode-dependent) ===== -->
			{:else if getStepName(currentStep) === 'Interfaces'}
				<div class="step-panel">
					{#if selectedMode === 'mirror'}
						<!-- Mirror mode: select capture NIC + optional management NIC -->
						<h2>Select Capture Interface</h2>
						<p class="text-muted step-desc">
							Choose which network interface receives the mirrored/SPAN traffic from your switch.
							This NIC will have no IP address assigned — it captures traffic in promiscuous mode.
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
							<!-- Mirror Network Diagram -->
							<div class="network-diagram">
								<div class="diagram-node">
									<div class="diagram-icon router-icon">
										<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
											<rect x="3" y="8" width="18" height="8" rx="2"/>
											<path d="M12 4v4M8 4l4 0M12 4l4 0"/>
											<circle cx="7" cy="12" r="1" fill="currentColor"/>
											<circle cx="11" cy="12" r="1" fill="currentColor"/>
										</svg>
									</div>
									<span class="diagram-label">Switch</span>
								</div>
								<div class="diagram-arrow">
									<svg width="32" height="16" viewBox="0 0 32 16" fill="none">
										<path d="M0 8h28M22 3l6 5-6 5" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
									</svg>
								</div>
								<div class="diagram-node" class:selected={selectedMirrorNic !== ''}>
									<div class="diagram-icon wan-icon">
										<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
											<rect x="2" y="4" width="20" height="16" rx="2"/>
											<path d="M6 12h4M14 12h4"/>
										</svg>
									</div>
									<span class="diagram-label">{selectedMirrorNic || 'Capture NIC'}</span>
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
									<span class="diagram-label">NetTap</span>
								</div>
							</div>

							<div class="nic-selectors">
								<div class="form-group">
									<label for="mirror-select" class="label">
										Capture Interface
										<span class="text-muted">(receives mirrored traffic)</span>
									</label>
									<select id="mirror-select" class="input" bind:value={selectedMirrorNic}>
										<option value="">-- Select capture interface --</option>
										{#each selectableInterfaces as iface}
											<option value={iface.name} disabled={iface.name === selectedManagementNic}>
												{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
											</option>
										{/each}
									</select>
									{#if selectedMirrorNicDetails}
										<div class="nic-details">
											<span class="badge badge-accent">{selectedMirrorNicDetails.driver || 'unknown'}</span>
											<span class="badge">{selectedMirrorNicDetails.speed || 'N/A'}</span>
											<span class="badge" class:badge-success={selectedMirrorNicDetails.state === 'up'} class:badge-danger={selectedMirrorNicDetails.state === 'down'}>
												{selectedMirrorNicDetails.state}
											</span>
										</div>
										<div class="alert alert-info" style="margin-top: var(--space-sm);">
											This NIC will have no IP address. It captures traffic in promiscuous mode only.
										</div>
									{/if}
								</div>

								<div class="form-group">
									<label for="mgmt-select" class="label">
										Management Interface
										<span class="text-muted">(optional — for dashboard access)</span>
									</label>
									<select id="mgmt-select" class="input" bind:value={selectedManagementNic}>
										<option value="">-- Auto-detect (default) --</option>
										{#each selectableInterfaces as iface}
											<option value={iface.name} disabled={iface.name === selectedMirrorNic}>
												{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
												{#if iface.ipv4} ({iface.ipv4}){/if}
											</option>
										{/each}
									</select>
									{#if selectedManagementNicDetails}
										<div class="nic-details">
											<span class="badge badge-accent">{selectedManagementNicDetails.driver || 'unknown'}</span>
											<span class="badge">{selectedManagementNicDetails.speed || 'N/A'}</span>
											{#if selectedManagementNicDetails.ipv4}
												<span class="badge">{selectedManagementNicDetails.ipv4}</span>
											{/if}
										</div>
									{/if}
								</div>
							</div>

							<button class="btn btn-sm btn-secondary" onclick={fetchNics} type="button" style="margin-top: var(--space-sm);">
								Refresh Interfaces
							</button>
						{/if}
					{:else}
						<!-- Bridge mode: WAN + LAN NIC selection (original flow) -->
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
					{/if}
				</div>

			<!-- ===== STEP: Bridge Configuration (bridge mode only) ===== -->
			{:else if getStepName(currentStep) === 'Bridge'}
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

			<!-- ===== STEP: Storage Configuration ===== -->
			{:else if getStepName(currentStep) === 'Storage'}
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

			<!-- ===== STEP: Device Enrichment (mirror mode only) ===== -->
			{:else if getStepName(currentStep) === 'Enrichment'}
				<div class="step-panel">
					<h2>Device Enrichment</h2>
					<p class="text-muted step-desc">
						NetTap automatically identifies devices on your network using passive techniques
						(MAC OUI, DHCP fingerprinting, mDNS, etc.). Optionally connect to a UniFi controller
						for richer device names and metadata.
					</p>

					<div class="enrichment-toggle card">
						<label class="toggle-row">
							<span class="toggle-label">
								<strong>Do you use UniFi network equipment?</strong>
								<span class="text-muted">Connect your UniFi controller for enhanced device identification.</span>
							</span>
							<label class="switch">
								<input type="checkbox" bind:checked={useUnifi} />
								<span class="slider"></span>
							</label>
						</label>
					</div>

					{#if useUnifi}
						<div class="unifi-config card" style="margin-top: var(--space-md);">
							<h3>UniFi Controller</h3>

							<div class="form-group">
								<label for="unifi-url" class="label">Controller URL</label>
								<input
									id="unifi-url"
									type="url"
									class="input"
									placeholder="https://192.168.1.1:8443"
									bind:value={unifiUrl}
								/>
								<span class="input-hint text-muted">The URL of your UniFi controller or Dream Machine.</span>
							</div>

							<div class="form-group">
								<label for="unifi-user" class="label">Username</label>
								<input
									id="unifi-user"
									type="text"
									class="input"
									placeholder="admin"
									bind:value={unifiUsername}
								/>
							</div>

							<div class="form-group">
								<label for="unifi-pass" class="label">Password</label>
								<input
									id="unifi-pass"
									type="password"
									class="input"
									placeholder="Controller password"
									bind:value={unifiPassword}
								/>
							</div>

							{#if unifiTestResult === 'success'}
								<div class="alert alert-success">
									Successfully connected to UniFi controller.
								</div>
							{:else if unifiTestResult === 'fail'}
								<div class="alert alert-danger">
									Connection failed: {unifiTestError}
								</div>
							{/if}

							<button
								class="btn btn-primary"
								onclick={testUnifiConnection}
								disabled={unifiTesting || !unifiUrl || !unifiUsername || !unifiPassword}
								type="button"
							>
								{#if unifiTesting}
									<span class="spinner"></span>
									Testing...
								{:else}
									Test Connection
								{/if}
							</button>
						</div>
					{:else}
						<div class="info-box" style="margin-top: var(--space-md);">
							<h3>Passive Identification (automatic)</h3>
							<p class="text-muted" style="margin-bottom: var(--space-sm);">
								Without a UniFi integration, NetTap still identifies devices using:
							</p>
							<ul class="setup-list">
								<li>MAC address OUI lookup (manufacturer identification)</li>
								<li>DHCP fingerprinting (OS and device type)</li>
								<li>mDNS/SSDP discovery (device names)</li>
								<li>HTTP User-Agent analysis</li>
								<li>TLS fingerprinting (JA3/JA4)</li>
							</ul>
						</div>
					{/if}
				</div>

			<!-- ===== STEP: Admin Account ===== -->
			{:else if getStepName(currentStep) === 'Account'}
				<div class="step-panel">
					<h2>Create Admin Account</h2>
					<p class="text-muted step-desc">
						Create your administrator account. This will be used to log in to the NetTap dashboard.
					</p>

					{#if form?.error || clientError || configSaveError}
						<div class="alert alert-danger" style="margin-bottom: var(--space-md);">
							{form?.error || clientError || configSaveError}
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
								return async ({ result, update }) => {
									adminLoading = false;
									if (result.type === 'error') {
										clientError = `Server error (${result.status}). Check browser console for details.`;
									}
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
								disabled={adminLoading || !adminFormValid || configSaving}
							>
								{#if adminLoading || configSaving}
									<span class="spinner"></span>
									{configSaving ? 'Saving Configuration...' : 'Creating Account...'}
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
		{#if getStepName(currentStep) !== 'Account' || form?.success}
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

				{#if getStepName(currentStep) !== 'Account'}
					<div class="nav-right">
						{#if getStepName(currentStep) === 'Bridge' || getStepName(currentStep) === 'Storage' || getStepName(currentStep) === 'Enrichment'}
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

	/* ===== Capture Mode Selection ===== */
	.mode-cards {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-lg);
	}

	@media (max-width: 640px) {
		.mode-cards {
			grid-template-columns: 1fr;
		}
	}

	.mode-card {
		position: relative;
		background-color: var(--bg-tertiary);
		border: 2px solid var(--border-default);
		border-radius: var(--radius-lg);
		padding: var(--space-xl) var(--space-lg);
		cursor: pointer;
		text-align: left;
		font-family: var(--font-sans);
		transition: all var(--transition-fast);
	}

	.mode-card:hover {
		border-color: var(--accent);
		background-color: var(--bg-secondary);
	}

	.mode-card.selected {
		border-color: var(--accent);
		background-color: var(--accent-muted);
		box-shadow: 0 0 0 1px var(--accent);
	}

	.mode-badge {
		position: absolute;
		top: calc(-1 * var(--space-xs));
		right: var(--space-md);
		font-size: var(--text-xs);
		font-weight: 600;
		padding: 2px var(--space-sm);
		border-radius: var(--radius-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.mode-badge.recommended {
		background-color: var(--success);
		color: #fff;
	}

	.mode-icon {
		margin-bottom: var(--space-md);
		color: var(--text-secondary);
	}

	.mode-card.selected .mode-icon {
		color: var(--accent);
	}

	.mode-card h3 {
		font-size: var(--text-lg);
		font-weight: 700;
		color: var(--text-primary);
		margin-bottom: var(--space-sm);
	}

	.mode-desc {
		font-size: var(--text-sm);
		color: var(--text-secondary);
		line-height: var(--leading-relaxed);
		margin-bottom: var(--space-md);
	}

	.mode-features {
		list-style: none;
		padding: 0;
		font-size: var(--text-xs);
		color: var(--text-muted);
	}

	.mode-features li {
		padding: var(--space-xs) 0;
		border-top: 1px solid var(--border-muted);
	}

	.mode-features li::before {
		content: '\2022 ';
		color: var(--accent);
		font-weight: bold;
		margin-right: var(--space-xs);
	}

	/* ===== Network Interfaces ===== */
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

	/* ===== Bridge Configuration ===== */
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

	/* ===== Storage Configuration ===== */
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

	/* ===== Device Enrichment ===== */
	.enrichment-toggle {
		margin-bottom: var(--space-md);
	}

	.toggle-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		cursor: pointer;
	}

	.toggle-label {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		flex: 1;
		margin-right: var(--space-lg);
	}

	.toggle-label strong {
		font-size: var(--text-base);
		color: var(--text-primary);
	}

	.toggle-label .text-muted {
		font-size: var(--text-sm);
	}

	.switch {
		position: relative;
		display: inline-block;
		width: 48px;
		height: 26px;
		flex-shrink: 0;
	}

	.switch input {
		opacity: 0;
		width: 0;
		height: 0;
	}

	.slider {
		position: absolute;
		cursor: pointer;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-default);
		transition: var(--transition-fast);
		border-radius: 26px;
	}

	.slider::before {
		position: absolute;
		content: '';
		height: 20px;
		width: 20px;
		left: 2px;
		bottom: 2px;
		background-color: var(--text-muted);
		transition: var(--transition-fast);
		border-radius: 50%;
	}

	.switch input:checked + .slider {
		background-color: var(--accent-muted);
		border-color: var(--accent);
	}

	.switch input:checked + .slider::before {
		transform: translateX(22px);
		background-color: var(--accent);
	}

	.unifi-config h3 {
		font-size: var(--text-lg);
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: var(--space-md);
	}

	/* ===== Admin Account ===== */
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
