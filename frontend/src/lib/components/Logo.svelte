<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';

	// The RuralMinds mark: an open textbook under a local Wi-Fi signal, on an ink tile.
	// Colours are fixed (not theme tokens) so the mark looks the same everywhere, like the favicon.
	let { size = 32, wordmark = false }: { size?: number; wordmark?: boolean } = $props();
</script>

<span class="logo" class:wordmark>
	<svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
		<rect width="32" height="32" rx="8" fill="#0b1311" />
		<rect x="0.5" y="0.5" width="31" height="31" rx="7.5" fill="none" stroke="#ffffff" stroke-opacity="0.12" />
		<path d="M6 13c3.2-1.3 6.4-1 10 1.2v11c-3.6-2.2-6.8-2.5-10-1.2z" fill="#3fc1b0" />
		<path d="M26 13c-3.2-1.3-6.4-1-10 1.2v11c3.6-2.2 6.8-2.5 10-1.2z" fill="#22a493" />
		<circle cx="16" cy="10.2" r="1.3" fill="#ffffff" />
		<path d="M13.3 7.6a3.8 3.8 0 0 1 5.4 0M10.9 5.2a7.2 7.2 0 0 1 10.2 0" fill="none" stroke="#ffffff" stroke-width="1.6" stroke-linecap="round" />
	</svg>
	{#if wordmark}<span class="name">{t('app.name')}</span>{/if}
</span>

<style>
	.logo {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		flex-shrink: 0;
	}
	svg {
		display: block;
		border-radius: 22%;
	}
	.name {
		font-weight: 720;
		font-size: 1.08rem;
		letter-spacing: -0.025em;
		color: var(--text);
	}
</style>
