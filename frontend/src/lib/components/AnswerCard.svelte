<script lang="ts">
	import type { Citation } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { renderMarkdown, splitSections } from '#lib/markdown.js';
	import type { Mode, Turn } from '#lib/study.svelte.js';
	import Icon from './Icon.svelte';
	import NotesCard from './NotesCard.svelte';
	import PageViewer from './PageViewer.svelte';

	let {
		turn,
		last = false,
		teacherMode = false,
		onfollow,
		onapprove
	}: {
		turn: Turn;
		last?: boolean;
		teacherMode?: boolean;
		onfollow?: (mode: Mode) => void;
		onapprove?: (turn: Turn) => void;
	} = $props();

	let opened = $state<Citation | null>(null);
	let showAnswers = $state(false);
	let copied = $state(false);

	const working = $derived(['searching', 'queued', 'writing'].includes(turn.status));
	const failed = $derived(['refused', 'blocked', 'error'].includes(turn.status));
	// While streaming, split the raw text the same way the server will.
	const parts = $derived(
		turn.status === 'writing' || turn.status === 'stopped'
			? splitSections(turn.raw)
			: { text: turn.text, example: turn.example, check: turn.check, answers: turn.answers }
	);
	const html = $derived(renderMarkdown(parts.text, turn.status === 'done'));

	const FOLLOW: { mode: Mode; icon: string; key: string }[] = [
		{ mode: 'simpler', icon: 'simpler', key: 'follow.simpler' },
		{ mode: 'example', icon: 'lightbulb', key: 'follow.example' },
		{ mode: 'story', icon: 'story', key: 'follow.story' },
		{ mode: 'quiz', icon: 'quiz', key: 'follow.quiz' }
	];

	function pageLabel(citation: Citation): string {
		const page =
			citation.page_end > citation.page_start
				? `${citation.page_start}–${citation.page_end}`
				: `${citation.page_start}`;
		return t('answer.chapter_page', { chapter: citation.chapter_no, page });
	}

	function openCitation(event: MouseEvent): void {
		const target = (event.target as HTMLElement).closest<HTMLElement>('[data-cite]');
		if (!target) return;
		opened = turn.citations.find((c) => c.marker === `S${target.dataset.cite}`) ?? null;
	}

	async function copy(): Promise<void> {
		const plain = [parts.text, parts.example, parts.check].filter(Boolean).join('\n\n').replace(/\[S\d+\]/g, '');
		try {
			await navigator.clipboard.writeText(plain);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch {
			// clipboard needs HTTPS on some phones; nothing else to do
		}
	}
</script>

<article class="turn">
	<p class="question" lang={turn.language || undefined}>{turn.shown}</p>

	<div class="answer" class:failed aria-busy={working}>
		<div class="avatar" aria-hidden="true"><Icon name="sparkle" size={18} /></div>
		<div class="bubble">
			{#if turn.status === 'searching' || turn.status === 'queued'}
				<div class="steps" aria-live="polite">
					<p class="step on"><span class="dot"></span>{turn.status === 'queued' ? t('step.queued', { n: turn.queuePosition ?? 1 }) : t('step.searching')}</p>
					<div class="skeleton line"></div>
					<div class="skeleton line short"></div>
				</div>
			{:else if failed}
				<div class="failed-body">
					<Icon name={turn.status === 'refused' ? 'search' : 'alert'} />
					<p>{t(turn.messageKey ?? 'error.generic')}</p>
				</div>
			{:else if turn.status === 'notes' && turn.notes}
				<NotesCard notes={turn.notes} />
			{:else}
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
				<div class="prose" lang={turn.language || undefined} onclick={openCitation}>
					{@html html}{#if turn.status === 'writing'}<span class="caret" aria-hidden="true"></span>{/if}
				</div>
				{#if parts.example}
					<aside class="box example" lang={turn.language || undefined}>
						<p class="box-title"><Icon name="lightbulb" size={18} />{t(turn.mode === 'story' ? 'answer.story_box' : 'answer.example_box')}</p>
						<div class="prose">{@html renderMarkdown(parts.example, false)}</div>
						<p class="box-note">{t('answer.not_from_book')}</p>
					</aside>
				{/if}
				{#if parts.answers}
					<div class="box answers">
						{#if showAnswers}
							<p class="box-title"><Icon name="check" size={18} />{t('answer.quiz_answers')}</p>
							<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
							<div class="prose" onclick={openCitation}>{@html renderMarkdown(parts.answers, turn.status === 'done')}</div>
						{:else}
							<button class="btn soft block" onclick={() => (showAnswers = true)}>
								<Icon name="eye" size={18} />{t('answer.show_answers')}
							</button>
						{/if}
					</div>
				{/if}
				{#if parts.check}
					<div class="box check" lang={turn.language || undefined}>
						<p class="box-title"><Icon name="question" size={18} />{t('answer.check_yourself')}</p>
						<p>{parts.check}</p>
					</div>
				{/if}
				{#if turn.status === 'writing'}
					<p class="step"><span class="dot"></span>{t('step.writing')}</p>
				{:else if turn.status === 'stopped'}
					<p class="muted small">{t('step.stopped')}</p>
				{/if}
				{#if turn.status === 'done'}
					{#if turn.citations.length}
						<div class="sources">
							<span class="muted small">{t('answer.from_your_book')}</span>
							{#each turn.citations as citation (citation.marker)}
								<button class="chip soft" onclick={() => (opened = citation)}>
									<Icon name="page" size={16} />{pageLabel(citation)}
								</button>
							{/each}
						</div>
					{/if}
					<div class="foot">
						<span class="label" class:approved={turn.label === 'teacher_approved'}>
							{#if turn.label === 'teacher_approved'}<Icon name="check" size={16} />{/if}
							{t(`label.${turn.label ?? 'ai_explanation'}`)}
						</span>
						<button class="btn ghost small" onclick={copy} aria-label={t('answer.copy')}>
							<Icon name={copied ? 'check' : 'copy'} size={16} />
						</button>
					</div>
				{/if}
			{/if}

			{#if teacherMode && turn.gate && !working}
				<details class="inspect">
					<summary>{t('try.details')}</summary>
					<p>{t('try.searched_for')}: <q>{turn.gate.search_query}</q></p>
					<p>{t('try.similarity')}: {turn.gate.top_similarity ?? '—'} · {t('try.keyword')}: {turn.gate.keyword_hit ? t('try.yes') : t('try.no')}</p>
					<p>{t('try.pages')}: {(turn.gate.retrieved ?? []).map((hit: any) => `${hit.chapter_no}/${hit.page_start}`).join(', ')}</p>
				</details>
			{/if}
			{#if teacherMode && turn.status === 'done' && turn.firstTurn && turn.label !== 'teacher_approved'}
				{#if turn.approved}
					<p class="label approved"><Icon name="check" size={16} />{t('try.approved')}</p>
				{:else}
					<button class="btn small" onclick={() => onapprove?.(turn)}><Icon name="check" size={16} />{t('try.approve')}</button>
				{/if}
			{/if}
		</div>
	</div>

	{#if last && (turn.status === 'done' || turn.status === 'notes') && onfollow}
		<div class="follow no-print" role="group" aria-label={t('follow.label')}>
			{#each FOLLOW as option (option.mode)}
				<button class="chip" onclick={() => onfollow(option.mode)}>
					<Icon name={option.icon} size={16} />{t(option.key)}
				</button>
			{/each}
		</div>
	{/if}
</article>

{#if opened}
	<PageViewer documentId={turn.documentId} first={opened.page_start} last={opened.page_end} onclose={() => (opened = null)} />
{/if}

<style>
	.turn {
		display: grid;
		gap: 10px;
	}
	.question {
		justify-self: end;
		max-width: 85%;
		margin: 0;
		padding: 10px 16px;
		border-radius: 20px 20px 6px 20px;
		background: var(--accent);
		color: var(--on-accent);
		font-weight: 600;
		white-space: pre-wrap;
		box-shadow: var(--shadow-sm);
	}
	.answer {
		display: grid;
		grid-template-columns: 34px 1fr;
		gap: 10px;
		align-items: start;
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 12px;
		background: linear-gradient(135deg, var(--accent), var(--accent-strong));
		color: #fff;
	}
	.bubble {
		min-width: 0;
		display: grid;
		gap: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 6px 20px 20px 20px;
		padding: 14px 16px;
		box-shadow: var(--shadow);
	}
	.failed .bubble {
		background: var(--surface-2);
		box-shadow: none;
	}
	.failed-body {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		color: var(--muted);
	}
	.failed-body p {
		margin: 0;
		color: var(--text);
	}
	.prose {
		font-size: 1.02rem;
	}
	.prose :global(p) {
		margin: 0 0 0.55rem;
	}
	.prose :global(p:last-child) {
		margin-bottom: 0;
	}
	.prose :global(ul),
	.prose :global(ol) {
		margin: 0.2rem 0 0.55rem;
		padding-left: 1.3rem;
	}
	.prose :global(li) {
		margin: 0.2rem 0;
	}
	.prose :global(strong) {
		color: var(--accent-strong);
	}
	.prose :global(.cite) {
		display: inline-grid;
		place-items: center;
		min-width: 20px;
		height: 20px;
		margin: 0 1px 0 3px;
		padding: 0 5px;
		border: 0;
		border-radius: 6px;
		background: var(--accent-soft);
		color: var(--accent-strong);
		font-size: 0.7rem;
		font-weight: 800;
		vertical-align: super;
		cursor: pointer;
	}
	.box {
		border-radius: 14px;
		padding: 12px 14px;
	}
	.box p {
		margin: 0;
	}
	.box-title {
		display: flex;
		align-items: center;
		gap: 6px;
		font-weight: 750;
		font-size: 0.88rem;
		margin-bottom: 6px !important;
	}
	.example {
		background: var(--warm-soft);
		border: 1px solid var(--warm-line);
	}
	.example .box-title {
		color: var(--warm);
	}
	.box-note {
		margin-top: 6px !important;
		font-size: 0.78rem;
		color: var(--muted);
	}
	.check {
		border: 1.5px dashed var(--line-strong);
	}
	.check .box-title {
		color: var(--accent-strong);
	}
	.answers {
		background: var(--accent-softer);
		border: 1px solid var(--accent-soft);
	}
	.sources {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		align-items: center;
	}
	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border-top: 1px solid var(--line);
		padding-top: 8px;
		margin-top: -2px;
	}
	.label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.78rem;
		color: var(--muted);
	}
	.label.approved {
		color: var(--ok);
		font-weight: 700;
	}
	.steps {
		display: grid;
		gap: 8px;
	}
	.line {
		height: 12px;
		border-radius: 6px;
	}
	.line.short {
		width: 60%;
	}
	.step {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 0;
		color: var(--muted);
		font-size: 0.9rem;
	}
	.dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: var(--accent);
		animation: pulse 1.2s ease-in-out infinite;
	}
	.caret {
		display: inline-block;
		width: 8px;
		height: 1.05em;
		margin-left: 2px;
		vertical-align: text-bottom;
		background: var(--accent);
		border-radius: 2px;
		animation: blink 1s steps(2) infinite;
	}
	.follow {
		display: flex;
		gap: 8px;
		overflow-x: auto;
		padding: 0 0 4px 44px;
		scrollbar-width: none;
	}
	.inspect {
		font-size: 0.82rem;
		color: var(--muted);
		border-top: 1px solid var(--line);
		padding-top: 8px;
	}
	.inspect p {
		margin: 4px 0;
	}
	.small {
		font-size: 0.82rem;
		margin: 0;
	}
	@keyframes pulse {
		50% {
			opacity: 0.25;
			transform: scale(0.7);
		}
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}
</style>
