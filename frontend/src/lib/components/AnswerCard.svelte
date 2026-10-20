<script lang="ts">
	import type { Citation } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { renderMarkdown, splitSections } from '#lib/markdown.js';
	import type { Mode, Turn } from '#lib/study.svelte.js';
	import Icon from './Icon.svelte';
	import Logo from './Logo.svelte';
	import NotesCard from './NotesCard.svelte';
	import PageViewer from './PageViewer.svelte';
	import SolutionCard from './SolutionCard.svelte';

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

	// Rounded on purpose: the estimate comes from recent answer times, not a promise.
	function queueText(n: number, eta: number | null | undefined): string {
		if (eta == null) return t('step.queued', { n });
		if (eta < 60) return t('step.queued_soon', { n });
		return t('step.queued_eta', { n, m: Math.round(eta / 60) });
	}
	const failed = $derived(['refused', 'blocked', 'error'].includes(turn.status));
	const approved = $derived(turn.label === 'teacher_approved');
	// While streaming, split the raw text the same way the server will.
	const parts = $derived(
		turn.status === 'writing' || turn.status === 'stopped'
			? splitSections(turn.raw)
			: { text: turn.text, example: turn.example, check: turn.check, answers: turn.answers }
	);
	const html = $derived(renderMarkdown(parts.text, turn.status === 'done'));
	// A solve answer streams as "IDEA: …", then numbered lines: show the idea and how far it got.
	const solving = $derived(turn.mode === 'solve');
	const streamIdea = $derived(solving ? (turn.raw.match(/^IDEA:\s*(.*)$/m)?.[1] ?? '') : '');
	const stepsWritten = $derived(solving ? (turn.raw.match(/^\d+\. /gm) ?? []).length : 0);

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
		<header class="head">
			<Logo size={26} />
			<span class="who">{t('app.name')}</span>
			{#if turn.status === 'done'}
				<!-- Rule 5: every answer is labelled, before the student reads it. -->
				<span class="badge" class:ok={approved}>
					<Icon name={approved ? 'check' : 'sparkle'} size={13} />
					{t(approved ? 'label.approved_short' : 'label.ai_short')}
				</span>
			{/if}
		</header>

		<div class="body">
			{#if turn.status === 'searching' || turn.status === 'queued'}
				<div class="progress" aria-live="polite">
					{#if turn.status === 'queued'}
						<p class="queue"><Icon name="users" size={16} />{queueText(turn.queuePosition ?? 1, turn.queueEta)}</p>
					{/if}
					<ol class="steps">
						<li class:on={turn.status === 'searching' && !turn.step}>
							<span class="step-mark">{#if turn.status === 'searching' && !turn.step}<span class="spinner"></span>{/if}</span>
							{t('step.searching')}
						</li>
						{#if solving}
							<li class:on={turn.step === 'solving'}>
								<span class="step-mark">{#if turn.step === 'solving'}<span class="spinner"></span>{/if}</span>
								{t('step.solving')}
							</li>
						{/if}
						<!-- "method": the calculator could not take this problem; the method answer is
						     written in full and shown only after its checks, so the step stays here. -->
						<li class:on={turn.step === 'method'}>
							<span class="step-mark">{#if turn.step === 'method'}<span class="spinner"></span>{/if}</span>
							{t(turn.step === 'method' ? 'step.method' : 'step.writing')}
						</li>
					</ol>
					<div class="skeleton line"></div>
					<div class="skeleton line short"></div>
				</div>
			{:else if failed}
				<div class="failed-body">
					<span class="failed-icon"><Icon name={turn.status === 'refused' ? 'search' : 'alert'} size={18} /></span>
					<p>{t(turn.messageKey ?? 'error.generic')}</p>
				</div>
			{:else if turn.status === 'notes' && turn.notes}
				<NotesCard notes={turn.notes} />
			{:else if turn.status === 'done' && turn.card}
				<SolutionCard card={turn.card} language={turn.language} oncite={openCitation} />
			{:else if solving && turn.status === 'writing' && streamIdea}
				<div class="prose" lang={turn.language || undefined}>{@html renderMarkdown(streamIdea, false)}</div>
				<p class="writing"><span class="dot"></span>{t('solve.writing_step', { n: stepsWritten || 1 })}</p>
			{:else}
				{#if solving && turn.status === 'done' && turn.mathStatus && !['solved', 'not_numerical'].includes(turn.mathStatus)}
					<!-- A calculation the calculator could not check: say so, and give only the method.
					     A question with nothing to calculate ("why SI units?") is just a normal answer. -->
					<p class="not-checked">
						<Icon name="alert" size={16} />{t(turn.mathStatus === 'language_not_supported' ? 'solve.english_only' : 'solve.not_checked')}
					</p>
				{/if}
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
				<div class="prose" lang={turn.language || undefined} onclick={openCitation}>
					{@html html}{#if turn.status === 'writing'}<span class="caret" aria-hidden="true"></span>{/if}
				</div>
				{#if parts.example}
					<aside class="box example" lang={turn.language || undefined}>
						<p class="box-title"><Icon name="lightbulb" size={17} />{t(turn.mode === 'story' ? 'answer.story_box' : 'answer.example_box')}</p>
						<div class="prose">{@html renderMarkdown(parts.example, false)}</div>
						<p class="box-note">{t('answer.not_from_book')}</p>
					</aside>
				{/if}
				{#if parts.answers}
					<div class="box answers">
						{#if showAnswers}
							<p class="box-title"><Icon name="check" size={17} />{t('answer.quiz_answers')}</p>
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
						<p class="box-title"><Icon name="question" size={17} />{t('answer.check_yourself')}</p>
						<p>{parts.check}</p>
					</div>
				{/if}
				{#if turn.status === 'writing'}
					<p class="writing"><span class="dot"></span>{t('step.writing')}</p>
				{:else if turn.status === 'stopped'}
					<p class="muted small">{t('step.stopped')}</p>
				{/if}
				{#if turn.status === 'done'}
					{#if turn.citations.length}
						<section class="sources" aria-label={t('answer.sources')}>
							<p class="eyebrow">{t('answer.sources')}</p>
							<div class="source-row">
								{#each turn.citations as citation (citation.marker)}
									<button class="source" onclick={() => (opened = citation)}>
										<span class="source-num">{citation.marker.slice(1)}</span>
										<span class="source-text">
											<strong class="tabular">{pageLabel(citation)}</strong>
											<small>{citation.chapter_title}</small>
										</span>
										<Icon name="page" size={18} />
									</button>
								{/each}
							</div>
						</section>
					{/if}
					<div class="foot">
						<span class="label" class:approved>
							{#if approved}<Icon name="check" size={15} />{/if}
							{t(`label.${turn.label ?? 'ai_explanation'}`)}
						</span>
						<button class="btn ghost small icon" onclick={copy} aria-label={t('answer.copy')}>
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
		gap: 14px;
	}
	.question {
		justify-self: end;
		max-width: 85%;
		margin: 0;
		padding: 10px 16px;
		border-radius: 20px 20px 6px 20px;
		background: var(--surface-3);
		color: var(--text);
		font-weight: 500;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.answer {
		display: grid;
		gap: 10px;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.who {
		font-weight: 650;
		font-size: 0.92rem;
		margin-right: 2px;
	}
	.body {
		min-width: 0;
		display: grid;
		gap: 14px;
		padding-left: 34px;
	}
	@media (max-width: 480px) {
		.body {
			padding-left: 0;
		}
	}

	/* Progress */
	.progress {
		display: grid;
		gap: 10px;
		padding: 14px 16px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--surface);
	}
	.queue {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		justify-self: start;
		margin: 0 0 2px;
		padding: 4px 12px;
		border-radius: 999px;
		background: var(--warm-soft);
		border: 1px solid var(--warm-line);
		color: var(--warm);
		font-weight: 650;
		font-size: 0.86rem;
	}
	.steps {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 8px;
	}
	.steps li {
		display: flex;
		align-items: center;
		gap: 10px;
		color: var(--faint);
		font-size: 0.9rem;
	}
	.steps li.on {
		color: var(--text);
		font-weight: 550;
	}
	.step-mark {
		display: grid;
		place-items: center;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		border: 1.5px solid var(--line-strong);
		color: var(--accent);
	}
	.on .step-mark {
		border: 0;
	}
	.line {
		height: 11px;
		border-radius: 6px;
	}
	.line.short {
		width: 60%;
	}

	/* Refusal / error: calm, not alarming */
	.failed-body {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		padding: 14px 16px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--surface);
	}
	.failed-icon {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		background: var(--surface-2);
		color: var(--muted);
		flex-shrink: 0;
	}
	.failed-body p {
		margin: 6px 0 0;
		color: var(--text);
	}

	/* Answer text */
	.prose {
		font-size: 1.02rem;
		line-height: 1.65;
	}
	.prose :global(p) {
		margin: 0 0 0.7rem;
	}
	.prose :global(p:last-child) {
		margin-bottom: 0;
	}
	.prose :global(ul),
	.prose :global(ol) {
		margin: 0.2rem 0 0.7rem;
		padding-left: 1.3rem;
	}
	.prose :global(li) {
		margin: 0.3rem 0;
	}
	.prose :global(li::marker) {
		color: var(--faint);
	}
	.prose :global(strong) {
		font-weight: 650;
		color: var(--text);
	}
	.prose :global(.cite) {
		display: inline-grid;
		place-items: center;
		min-width: 19px;
		height: 19px;
		margin: 0 1px 0 3px;
		padding: 0 5px;
		border: 1px solid var(--accent-soft);
		border-radius: 6px;
		background: var(--accent-softer);
		color: var(--accent-strong);
		font-size: 0.68rem;
		font-weight: 700;
		line-height: 1;
		vertical-align: 0.25em;
		cursor: pointer;
		transition: background 0.15s;
	}
	.prose :global(.cite:hover) {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--on-accent);
	}

	/* Boxes */
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
		gap: 7px;
		font-weight: 650;
		font-size: 0.86rem;
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
		margin-top: 8px !important;
		font-size: 0.76rem;
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
	.not-checked {
		display: flex;
		gap: 8px;
		align-items: flex-start;
		margin: 0;
		padding: 10px 12px;
		border-radius: 12px;
		background: var(--warm-soft);
		border: 1px solid var(--warm-line);
		color: var(--text);
		font-size: 0.9rem;
	}
	.not-checked :global(svg) {
		color: var(--warm);
		flex-shrink: 0;
		margin-top: 2px;
	}
	.writing {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 0;
		color: var(--muted);
		font-size: 0.88rem;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--accent);
		animation: pulse 1.2s ease-in-out infinite;
	}
	.caret {
		display: inline-block;
		width: 7px;
		height: 1.05em;
		margin-left: 2px;
		vertical-align: text-bottom;
		background: var(--accent);
		border-radius: 2px;
		animation: blink 1s steps(2) infinite;
	}

	/* Sources: the proof. Large enough to tap, each opens the real page. */
	.sources {
		display: grid;
		gap: 8px;
	}
	.source-row {
		display: flex;
		gap: 8px;
		overflow-x: auto;
		padding-bottom: 2px;
		scrollbar-width: none;
	}
	.source {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 176px;
		max-width: 240px;
		padding: 10px 12px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--surface);
		box-shadow: var(--shadow-xs);
		color: var(--text);
		text-align: left;
		cursor: pointer;
		flex-shrink: 0;
		transition:
			border-color 0.15s,
			background 0.15s;
	}
	.source:hover {
		border-color: var(--accent);
		background: var(--accent-softer);
	}
	.source > :global(svg) {
		color: var(--faint);
	}
	.source-num {
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 6px;
		background: var(--accent-softer);
		border: 1px solid var(--accent-soft);
		color: var(--accent-strong);
		font-size: 0.72rem;
		font-weight: 700;
		flex-shrink: 0;
	}
	.source-text {
		flex: 1;
		min-width: 0;
		display: grid;
	}
	.source-text strong {
		font-size: 0.86rem;
		font-weight: 650;
	}
	.source-text small {
		font-size: 0.76rem;
		color: var(--muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border-top: 1px solid var(--line);
		padding-top: 8px;
	}
	.label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin: 0;
		font-size: 0.76rem;
		color: var(--muted);
	}
	.label.approved {
		color: var(--ok);
		font-weight: 650;
	}
	.follow {
		display: flex;
		gap: 8px;
		overflow-x: auto;
		padding: 0 0 4px 34px;
		scrollbar-width: none;
	}
	@media (max-width: 480px) {
		.follow {
			padding-left: 0;
		}
	}
	.follow .chip :global(svg) {
		color: var(--accent-strong);
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
