<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';
	import { dismissToast, feedback } from '#lib/feedback.svelte.js';
	import Icon from './Icon.svelte';

	const ICONS = { ok: 'check', error: 'alert', info: 'sparkle' };
</script>

<div class="toaster no-print" aria-live="polite">
	{#each feedback.toasts as item (item.id)}
		<div class="toast {item.kind}" role={item.kind === 'error' ? 'alert' : 'status'}>
			<span class="icon"><Icon name={ICONS[item.kind]} size={16} /></span>
			<p>{item.message}</p>
			<button class="close" onclick={() => dismissToast(item.id)} aria-label={t('common.close')}>
				<Icon name="close" size={16} />
			</button>
		</div>
	{/each}
</div>

<style>
	.toaster {
		position: fixed;
		z-index: 100;
		left: 16px;
		right: 16px;
		bottom: calc(var(--nav-height) + env(safe-area-inset-bottom) + 12px);
		display: grid;
		justify-items: center;
		gap: 8px;
		pointer-events: none;
	}
	@media (min-width: 900px) {
		.toaster {
			left: auto;
			bottom: 24px;
			right: 24px;
			justify-items: end;
		}
	}
	.toast {
		pointer-events: auto;
		display: flex;
		align-items: flex-start;
		gap: 10px;
		width: 100%;
		max-width: 420px;
		padding: 12px 8px 12px 14px;
		border-radius: 14px;
		background: var(--primary);
		color: var(--on-primary);
		box-shadow: var(--shadow-lg);
		animation: enter 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
	}
	.icon {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: rgb(127 127 127 / 0.22);
		flex-shrink: 0;
	}
	.ok .icon {
		background: var(--ok);
		color: #fff;
	}
	.error .icon {
		background: var(--danger);
		color: #fff;
	}
	p {
		flex: 1;
		margin: 2px 0 0;
		font-size: 0.92rem;
		font-weight: 500;
	}
	.close {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: inherit;
		opacity: 0.7;
		cursor: pointer;
	}
	.close:hover {
		opacity: 1;
		background: rgb(127 127 127 / 0.2);
	}
	@keyframes enter {
		from {
			transform: translateY(12px);
			opacity: 0;
		}
	}
</style>
