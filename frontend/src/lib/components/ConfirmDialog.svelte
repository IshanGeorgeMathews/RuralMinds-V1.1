<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';
	import { feedback, settleConfirm } from '#lib/feedback.svelte.js';
	import Icon from './Icon.svelte';

	let dialog = $state<HTMLDialogElement>();

	$effect(() => {
		if (feedback.confirm && dialog && !dialog.open) dialog.showModal();
	});
</script>

{#if feedback.confirm}
	{@const pending = feedback.confirm}
	<dialog bind:this={dialog} onclose={() => settleConfirm(false)} aria-label={pending.message}>
		<div class="panel">
			<span class="icon" class:danger={pending.danger}><Icon name={pending.danger ? 'alert' : 'question'} size={20} /></span>
			<p>{pending.message}</p>
			<div class="actions">
				<button class="btn" onclick={() => settleConfirm(false)}>{t('common.cancel')}</button>
				<button class="btn {pending.danger ? 'destroy' : 'primary'}" onclick={() => settleConfirm(true)}>
					{pending.confirmLabel || t('common.confirm')}
				</button>
			</div>
		</div>
	</dialog>
{/if}

<style>
	dialog {
		width: calc(100% - 32px);
		max-width: 420px;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--text);
	}
	dialog::backdrop {
		background: rgb(6 10 9 / 0.5);
		backdrop-filter: blur(3px);
	}
	.panel {
		display: grid;
		gap: 14px;
		padding: 22px;
		border-radius: 18px;
		border: 1px solid var(--line);
		background: var(--surface);
		box-shadow: var(--shadow-lg);
		animation: pop 0.18s cubic-bezier(0.2, 0.8, 0.2, 1);
	}
	.icon {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 12px;
		background: var(--accent-softer);
		color: var(--accent-strong);
	}
	.icon.danger {
		background: var(--danger-soft);
		color: var(--danger);
	}
	p {
		margin: 0;
		font-size: 1rem;
		line-height: 1.5;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		flex-wrap: wrap;
		margin-top: 4px;
	}
	.destroy {
		background: var(--danger);
		border-color: var(--danger);
		color: #fff;
	}
	.destroy:hover {
		background: color-mix(in srgb, var(--danger) 85%, #000);
	}
	@keyframes pop {
		from {
			transform: scale(0.96);
			opacity: 0;
		}
	}
</style>
