<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, ApiError } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';
	import NotesCard from '#lib/components/NotesCard.svelte';
	import StudentGate from '#lib/components/StudentGate.svelte';
	import StudentShell from '#lib/components/StudentShell.svelte';
	import { t } from '#lib/i18n/index.svelte.js';
	import { ask, choose, study, type Mode, type Notes } from '#lib/study.svelte.js';

	const docId = $derived(Number(page.params.doc));
	const chapterNo = $derived(Number(page.params.chapter));
	const book = $derived(study.books.find((b) => b.id === docId));
	const chapter = $derived(book?.chapters.find((c) => c.no === chapterNo));

	let notes = $state<Notes | null>(null);
	let missing = $state(false);
	let errorKey = $state('');

	$effect(() => {
		if (!study.loaded) return;
		notes = null;
		missing = false;
		api
			.get<Notes>(`/api/notes/${docId}/${chapterNo}`) // the book's language; the UI language is separate
			.then((result) => (notes = result))
			.catch((error) => {
				if (error instanceof ApiError && error.status === 404) missing = true;
				else errorKey = error instanceof ApiError ? error.key : 'error.generic';
			});
	});

	function start(mode: Mode | null, text: string): void {
		choose(docId, chapterNo);
		goto('/ask');
		ask(text, { mode });
	}
</script>

<StudentShell title={chapter ? t('ask.chapter_short', { n: chapterNo }) : ''} back="/">
	<StudentGate>
		<main class="wrap page">
			{#if chapter}
				<div class="actions">
					<button class="action" onclick={() => start('quiz', t('suggest.quiz'))}>
						<Icon name="quiz" /><span>{t('chapter.quiz')}</span>
					</button>
					<button class="action" onclick={() => (choose(docId, chapterNo), goto('/ask'))}>
						<Icon name="chat" /><span>{t('chapter.ask')}</span>
					</button>
					<button class="action" onclick={() => start('story', t('chapter.story_question', { title: chapter.title }))}>
						<Icon name="story" /><span>{t('chapter.story')}</span>
					</button>
				</div>
				{#if notes}
					<section class="card"><NotesCard {notes} /></section>
				{:else if missing}
					<section class="card">
						<p class="kicker">{t('notes.kicker', { n: chapterNo })}</p>
						<h2>{chapter.title}</h2>
						<div class="empty">
							<div class="art"><Icon name="list" size={28} /></div>
							<p>{t('notes.not_ready')}</p>
						</div>
					</section>
				{:else if errorKey}
					<p class="error">{t(errorKey)}</p>
				{:else}
					<div class="skeleton" style="height:320px"></div>
				{/if}
			{/if}
		</main>
	</StudentGate>
</StudentShell>

<style>
	.page {
		display: grid;
		gap: 14px;
		padding-top: 14px;
		padding-bottom: 24px;
	}
	.actions {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
	}
	.action {
		display: grid;
		justify-items: center;
		gap: 6px;
		padding: 14px 6px;
		border-radius: var(--radius);
		border: 1px solid var(--line);
		background: var(--surface);
		box-shadow: var(--shadow-sm);
		cursor: pointer;
		color: var(--text);
		font-weight: 650;
		font-size: 0.85rem;
	}
	.action :global(svg) {
		color: var(--accent-strong);
	}
	.action:hover {
		border-color: var(--accent);
	}
	.kicker {
		margin: 0;
		color: var(--accent-strong);
		font-weight: 750;
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
</style>
