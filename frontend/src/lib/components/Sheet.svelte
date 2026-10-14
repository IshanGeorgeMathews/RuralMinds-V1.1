<script lang="ts">
	import type { Snippet } from 'svelte';
	import { t } from '#lib/i18n/index.svelte.js';
	import Icon from './Icon.svelte';

	// A bottom sheet on phones, a centred panel on wide screens.
	let { title, onclose, children }: { title: string; onclose: () => void; children: Snippet } =
		$props();
	let dialog: HTMLDialogElement;

	$effect(() => {
		dialog.showModal();
		return () => dialog.close();
	});
</script>

<dialog
	bind:this={dialog}
	{onclose}
	onclick={(event) => event.target === dialog && dialog.close()}
	aria-label={title}
>
	<div class="sheet">
		<div class="grip" aria-hidden="true"></div>
		<div class="head">
			<h2>{title}</h2>
			<button class="btn ghost icon" onclick={() => dialog.close()} aria-label={t('common.close')}>
				<Icon name="close" />
			</button>
		</div>
		<div class="body">{@render children()}</div>
	</div>
</dialog>

<style>
	dialog {
		margin: auto auto 0;
		padding: 0;
		border: 0;
		width: 100%;
		max-width: 560px;
		max-height: 85dvh;
		background: transparent;
		color: var(--text);
	}
	dialog::backdrop {
		background: rgb(10 16 14 / 0.45);
	}
	.sheet {
		background: var(--surface);
		border-radius: 22px 22px 0 0;
		box-shadow: var(--shadow-lg);
		display: flex;
		flex-direction: column;
		max-height: 85dvh;
		padding-bottom: env(safe-area-inset-bottom);
		animation: rise 0.2s ease-out;
	}
	.grip {
		width: 40px;
		height: 4px;
		border-radius: 4px;
		background: var(--line-strong);
		margin: 8px auto 0;
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 6px 8px 6px 18px;
	}
	.head h2 {
		margin: 0;
		font-size: 1.1rem;
	}
	.body {
		overflow-y: auto;
		padding: 0 16px 18px;
	}
	@media (min-width: 700px) {
		dialog {
			margin: auto;
		}
		.sheet {
			border-radius: 22px;
		}
	}
	@keyframes rise {
		from {
			transform: translateY(24px);
			opacity: 0;
		}
	}
</style>
