<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';
	import Icon from './Icon.svelte';
	import PageViewer from './PageViewer.svelte';

	type Citation = { marker?: string; page_start: number; page_end: number; chapter_title?: string };
	export type RevisionAnswerData = {
		text: string;
		example?: string;
		check?: string;
		citations: Citation[];
	};

	// One approved (or draft) revision answer with the textbook pages it cites, so whoever
	// reads it can check it against the book. Used by the teacher's review and the student sheet.
	let {
		answer,
		documentId,
		label = ''
	}: { answer: RevisionAnswerData; documentId: number; label?: string } = $props();

	let opened = $state<Citation | null>(null);
	// Plain text on purpose (never {@html}: teachers type some of these answers). Drop the
	// source markers and the model's **bold** markup; line breaks and "- " points stay.
	const plain = (text: string) => text.replace(/\s*\[S\d+\]/g, '').replace(/\*\*(.+?)\*\*/g, '$1');
	const pages = (c: Citation) => (c.page_end > c.page_start ? `${c.page_start}–${c.page_end}` : `${c.page_start}`);
</script>

<div class="answer">
	<p class="text">{plain(answer.text)}</p>
	{#if answer.example}<p class="extra"><span class="eyebrow">{t('revision.example')}</span>{answer.example}</p>{/if}
	{#if answer.citations.length}
		<div class="sources" aria-label={t('answer.sources')}>
			{#each answer.citations as citation, index (index)}
				<button class="btn small soft" onclick={() => (opened = citation)}>
					<Icon name="page" size={16} />{t('revision.page', { pages: pages(citation) })}
				</button>
			{/each}
		</div>
	{:else if label === 'teacher_written'}
		<p class="muted small">{t('revision.no_page')}</p>
	{/if}
	{#if label}
		<p class="label"><Icon name="check" size={15} />{t(`label.${label}`)}</p>
	{/if}
</div>

{#if opened}
	<PageViewer {documentId} first={opened.page_start} last={opened.page_end} onclose={() => (opened = null)} />
{/if}

<style>
	.answer {
		display: grid;
		gap: 10px;
	}
	.text {
		margin: 0;
		white-space: pre-line;
		line-height: 1.55;
	}
	.extra {
		margin: 0;
		padding: 10px 12px;
		border-radius: var(--radius-sm);
		background: var(--warm-soft);
		display: grid;
		gap: 2px;
	}
	.sources {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.label {
		margin: 0;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.85rem;
		color: var(--ok);
	}
</style>
