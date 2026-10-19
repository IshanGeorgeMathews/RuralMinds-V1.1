<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import Icon from './Icon.svelte';
	import RevisionAnswer, { type RevisionAnswerData } from './RevisionAnswer.svelte';
	import Sheet from './Sheet.svelte';

	type Question = { id: number; chapter_no: number; question: string };
	type Exam = { id: number; title: string; document_id: number; exam_on: string; today: string; questions: Question[] };

	// Teacher-approved revision questions for this class's exam (W5 part 2). Attempt-first:
	// the answer is fetched only after the student says they have tried. A tap costs the server
	// no model time, which is what keeps exam-eve load low.
	let { bookId, chapterNo }: { bookId: number; chapterNo: number | null } = $props();

	let exams = $state<Exam[]>([]);
	let showAll = $state(false);
	let open = $state<{ exam: Exam; index: number } | null>(null);
	let answer = $state<(RevisionAnswerData & { label: string }) | null>(null);
	let loading = $state(false);
	let errorKey = $state('');

	onMount(async () => {
		exams = await api.get<Exam[]>('/api/revision').catch(() => []);
	});

	const exam = $derived(exams.find((item) => item.document_id === bookId && item.questions.length));
	const questions = $derived(
		exam ? exam.questions.filter((q) => chapterNo === null || q.chapter_no === chapterNo) : []
	);
	const shown = $derived(showAll ? questions : questions.slice(0, 4));

	function daysLeft(item: Exam): number {
		return Math.round((Date.parse(item.exam_on) - Date.parse(item.today)) / 86_400_000);
	}

	function start(index: number): void {
		if (!exam) return;
		open = { exam, index };
		answer = null;
		errorKey = '';
	}

	async function reveal(): Promise<void> {
		if (!open) return;
		loading = true;
		try {
			const question = questions[open.index];
			answer = await api.post(`/api/revision/${question.id}/answer`);
		} catch (error) {
			errorKey = error instanceof ApiError ? error.key : 'error.generic';
		} finally {
			loading = false;
		}
	}
</script>

{#if exam && questions.length}
	{@const left = daysLeft(exam)}
	<section class="revision" aria-label={t('revision.title')}>
		<p class="head">
			<Icon name="quiz" size={18} />
			<strong>{t('revision.title')}</strong>
			<span class="muted small">
				{exam.title} · {left <= 0 ? t('revision.exam_today') : t('revision.days_left', { n: left })}
			</span>
		</p>
		<div class="chips">
			{#each shown as question, index (question.id)}
				<button class="chip" onclick={() => start(index)}>{question.question}</button>
			{/each}
			{#if questions.length > shown.length}
				<button class="chip soft" onclick={() => (showAll = true)}>{t('revision.more', { n: questions.length - shown.length })}</button>
			{/if}
		</div>
	</section>
{/if}

{#if open}
	{@const question = questions[open.index]}
	<Sheet title={t('revision.title')} onclose={() => (open = null)}>
		<div class="stack">
			<p class="muted small">{t('ask.chapter_short', { n: question.chapter_no })} · {open.index + 1} / {questions.length}</p>
			<p class="question">{question.question}</p>
			{#if answer}
				<RevisionAnswer {answer} documentId={open.exam.document_id} label={answer.label} />
				{#if open.index + 1 < questions.length}
					<button class="btn primary block" onclick={() => start(open!.index + 1)}>{t('revision.next')}<Icon name="chevronRight" size={18} /></button>
				{/if}
			{:else}
				<p class="try"><Icon name="lightbulb" size={18} />{t('revision.try_first')}</p>
				{#if errorKey}<p class="error">{t(errorKey)}</p>{/if}
				<button class="btn primary block" onclick={reveal} disabled={loading}>
					{#if loading}<span class="spinner"></span>{/if}{t('revision.show_answer')}
				</button>
			{/if}
		</div>
	</Sheet>
{/if}

<style>
	.revision {
		width: 100%;
		display: grid;
		gap: 8px;
		padding: 12px;
		border: 1px solid var(--warm-line);
		border-radius: var(--radius);
		background: var(--warm-soft);
		text-align: left;
	}
	.head {
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.chip {
		text-align: left;
	}
	.question {
		margin: 0;
		font-size: 1.1rem;
		font-weight: 600;
	}
	.try {
		margin: 0;
		display: flex;
		gap: 8px;
		align-items: flex-start;
		color: var(--muted);
	}
</style>
