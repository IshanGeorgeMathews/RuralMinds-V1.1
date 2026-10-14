<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';

	let {
		documentId,
		first,
		last,
		onclose
	}: { documentId: number; first: number; last: number; onclose: () => void } = $props();

	let page = $state(first);
	let failed = $state(false);
	let dialog: HTMLDialogElement;

	$effect(() => {
		dialog.showModal();
		return () => dialog.close();
	});
</script>

<dialog bind:this={dialog} onclose={onclose} aria-label={t('page.title', { page })}>
	<div class="head">
		<strong>{t('page.title', { page })}</strong>
		<div class="row">
			{#if last > first}
				<button
					class="btn small"
					disabled={page <= first}
					onclick={() => ((page -= 1), (failed = false))}
					aria-label={t('page.prev')}>‹</button
				>
				<button
					class="btn small"
					disabled={page >= last}
					onclick={() => ((page += 1), (failed = false))}
					aria-label={t('page.next')}>›</button
				>
			{/if}
			<button class="btn small primary" onclick={() => dialog.close()}>{t('page.close')}</button>
		</div>
	</div>
	<div class="page">
		{#if failed}
			<p class="error">{t('error.generic')}</p>
		{:else}
			<img
				src={`/api/page/${documentId}/${page}.png`}
				alt={t('page.title', { page })}
				onerror={() => (failed = true)}
			/>
		{/if}
	</div>
</dialog>

<style>
	dialog {
		width: min(100vw, 820px);
		max-width: 100vw;
		height: 100dvh;
		max-height: 100dvh;
		margin: 0 auto;
		padding: 0;
		border: 0;
		background: var(--surface);
		color: var(--text);
	}
	dialog[open] {
		display: flex;
		flex-direction: column;
	}
	dialog::backdrop {
		background: rgb(0 0 0 / 0.6);
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		border-bottom: 1px solid var(--line);
	}
	.page {
		flex: 1;
		overflow: auto;
		background: #fff;
		padding: 8px;
	}
	img {
		width: 100%;
		height: auto;
		display: block;
	}
</style>
