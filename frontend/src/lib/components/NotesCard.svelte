<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';
	import type { Notes } from '#lib/study.svelte.js';
	import Icon from './Icon.svelte';
	import PageViewer from './PageViewer.svelte';

	let { notes, compact = false }: { notes: Notes; compact?: boolean } = $props();
	let opened = $state<{ first: number; last: number } | null>(null);
	let showAll = $state(false);
	const FIRST = 8; // the overview is the quick read; the full list is there when wanted
	const shown = $derived(showAll ? notes.points : notes.points.slice(0, FIRST));
	const pageLabel = (start: number, end: number) => (end > start ? `${start}–${end}` : `${start}`);
</script>

<div class="notes" lang={notes.language}>
	{#if !compact}
		<p class="kicker">{t('notes.kicker', { n: notes.chapter_no })}</p>
		<h2>{notes.chapter_title}</h2>
	{/if}
	<div class="overview">
		<Icon name="sparkle" size={18} />
		<p>{notes.overview}</p>
	</div>
	<h3>{t('notes.key_points')}</h3>
	<ol class="points">
		{#each shown as point, index (index)}
			<li>
				<span class="num">{index + 1}</span>
				<span class="point">{point.text}</span>
				<button class="page" onclick={() => (opened = { first: point.page_start, last: point.page_end })}>
					{t('notes.page', { page: pageLabel(point.page_start, point.page_end) })}
				</button>
			</li>
		{/each}
	</ol>
	{#if notes.points.length > FIRST && !showAll}
		<button class="btn soft block" onclick={() => (showAll = true)}>
			<Icon name="list" size={18} />{t('notes.show_all', { n: notes.points.length })}
		</button>
	{/if}
	<p class="label" class:approved={notes.label === 'teacher_approved'}>
		{#if notes.label === 'teacher_approved'}<Icon name="check" size={16} />{/if}
		{t(notes.label === 'teacher_approved' ? 'label.teacher_approved_notes' : 'label.ai_notes')}
	</p>
</div>

{#if opened}
	<PageViewer documentId={notes.document_id} first={opened.first} last={opened.last} onclose={() => (opened = null)} />
{/if}

<style>
	.notes {
		display: grid;
		gap: 10px;
	}
	.kicker {
		margin: 0;
		color: var(--accent-strong);
		font-weight: 750;
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	h2 {
		margin: 0;
	}
	h3 {
		margin: 6px 0 0;
		font-size: 0.95rem;
		color: var(--muted);
	}
	.overview {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		background: var(--accent-softer);
		border: 1px solid var(--accent-soft);
		border-radius: 14px;
		padding: 12px 14px;
		color: var(--text);
	}
	.overview :global(svg) {
		color: var(--accent-strong);
		margin-top: 4px;
	}
	.overview p {
		margin: 0;
	}
	.points {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 8px;
	}
	.points li {
		display: grid;
		grid-template-columns: 28px 1fr;
		gap: 4px 10px;
		align-items: start;
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--surface);
	}
	.num {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: var(--accent);
		color: var(--on-accent);
		font-weight: 800;
		font-size: 0.8rem;
		margin-top: 2px;
	}
	.page {
		grid-column: 2;
		justify-self: start;
		border: 0;
		background: none;
		padding: 0;
		color: var(--accent-strong);
		font-weight: 650;
		font-size: 0.82rem;
		cursor: pointer;
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.label {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 2px 0 0;
		font-size: 0.8rem;
		color: var(--muted);
	}
	.label.approved {
		color: var(--ok);
		font-weight: 700;
	}
</style>
