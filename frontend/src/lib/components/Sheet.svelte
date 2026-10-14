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
		background: rgb(6 10 9 / 0.5);
		backdrop-filter: blur(3px);
	}
	.sheet {
		background: var(--surface);
		border: 1px solid var(--line);
		border-bottom: 0;
		border-radius: 20px 20px 0 0;
		box-shadow: var(--shadow-lg);
		display: flex;
		flex-direction: column;
		max-height: 85dvh;
		padding-bottom: env(safe-area-inset-bottom);
		animation: rise 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
	}
	.grip {
		width: 36px;
		height: 4px;
		border-radius: 4px;
		background: var(--line-strong);
		margin: 8px auto 0;
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 8px 8px 20px;
	}
	.head h2 {
		margin: 0;
		font-size: 1.08rem;
		font-weight: 650;
	}
	.body {
		overflow-y: auto;
		padding: 0 16px 20px;
	}
	@media (min-width: 700px) {
		dialog {
			margin: auto;
		}
		.sheet {
			border-radius: 20px;
			border-bottom: 1px solid var(--line);
		}
		.grip {
			display: none;
		}
		.head {
			padding-top: 14px;
		}
	}
	@keyframes rise {
		from {
			transform: translateY(24px);
			opacity: 0;
		}
	}
</style>
