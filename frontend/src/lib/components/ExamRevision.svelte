<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '#lib/api.js';
	import { confirmAction, toast } from '#lib/feedback.svelte.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import Icon from './Icon.svelte';
	import RevisionAnswer, { type RevisionAnswerData } from './RevisionAnswer.svelte';
	import Sheet from './Sheet.svelte';

	type ClassRow = { id: number; label: string; mine: boolean };
	type BookRow = { id: number; title: string; medium: string; class_ids: number[]; chapters: { no: number; title: string }[] };
	type Portion = {
		id: number;
		title: string;
		document_id: number;
		book_title: string;
		chapters: number[];
		visible_from: string;
		exam_on: string;
		drafts_per_chapter: number;
		classes: { id: number; grade: number; section: string }[];
		progress: Record<string, number>;
	};
	type Item = {
		id: number;
		question: string;
		source: 'drafted' | 'teacher';
		status: 'pending' | 'draft' | 'approved' | 'rejected' | 'not_in_book' | 'failed';
		answer: (RevisionAnswerData & { reason?: string }) | null;
		answer_kind: 'generated' | 'edited' | 'written' | null;
	};

	// Exam revision for teachers (W5 part 2). Questions live in one bank per book and chapter,
	// so 8A and 8B (same book) share every approved answer; an exam only picks classes,
	// chapters and dates. Answers are checked beside the textbook page they cite.
	let { books, classes }: { books: BookRow[]; classes: ClassRow[] } = $props();

	let today = $state('');
	let portions = $state<Portion[]>([]);
	let form = $state<(Omit<Portion, 'id' | 'book_title' | 'classes' | 'progress'> & { id: number | null; class_ids: number[] }) | null>(null);
	let review = $state<{ portion: Portion; chapter: number } | null>(null);
	let items = $state<Item[]>([]);
	let draft = $state({ question: '', answer: '', own: false });
	let editing = $state<Record<number, string>>({});

	const formBook = $derived(form ? books.find((book) => book.id === form!.document_id) : undefined);
	const eligible = $derived(classes.filter((c) => c.mine && formBook?.class_ids.includes(c.id)));
	const pending = $derived(items.some((item) => item.status === 'pending'));

	onMount(() => {
		load();
		const timer = setInterval(() => pending && review && loadBank(), 4000);
		return () => clearInterval(timer);
	});

	async function guard(action: () => Promise<unknown>): Promise<boolean> {
		try {
			await action();
			return true;
		} catch (error) {
			toast(t(error instanceof ApiError ? error.key : 'error.generic'), 'error');
			return false;
		}
	}

	async function load(): Promise<void> {
		await guard(async () => {
			const data = await api.get<{ today: string; portions: Portion[] }>('/api/teacher/exams');
			today = data.today;
			portions = data.portions;
		});
	}

	function newExam(): void {
		const book = books[0];
		form = {
			id: null,
			title: '',
			document_id: book?.id ?? 0,
			chapters: [],
			class_ids: [],
			visible_from: today,
			exam_on: today,
			drafts_per_chapter: 6
		};
	}

	function editExam(portion: Portion): void {
		form = { ...portion, chapters: [...portion.chapters], class_ids: portion.classes.map((c) => c.id) };
	}

	function toggle(list: number[], value: number): number[] {
		return list.includes(value) ? list.filter((item) => item !== value) : [...list, value].sort((a, b) => a - b);
	}

	async function saveExam(): Promise<void> {
		if (!form) return;
		const { id, ...body } = form;
		const ok = await guard(() => (id === null ? api.post('/api/teacher/exams', body) : api.put(`/api/teacher/exams/${id}`, body)));
		if (ok) {
			form = null;
			toast(t('revision.saved'), 'ok');
			await load();
		}
	}

	async function deleteExam(portion: Portion): Promise<void> {
		if (!(await confirmAction(t('revision.delete_confirm', { title: portion.title }), { danger: true }))) return;
		if (await guard(() => api.del(`/api/teacher/exams/${portion.id}`))) await load();
	}

	async function openReview(portion: Portion, chapter = portion.chapters[0]): Promise<void> {
		review = { portion, chapter };
		editing = {};
		await loadBank();
	}

	async function loadBank(): Promise<void> {
		if (!review) return;
		const { portion, chapter } = review;
		await guard(async () => {
			items = await api.get<Item[]>(`/api/teacher/revision/${portion.document_id}/${chapter}`);
		});
	}

	async function addQuestion(): Promise<void> {
		if (!review || draft.question.trim().length < 3) return;
		const body = {
			document_id: review.portion.document_id,
			chapter_no: review.chapter,
			question: draft.question.trim(),
			answer: draft.own ? draft.answer.trim() : ''
		};
		if (await guard(() => api.post('/api/teacher/revision', body))) {
			draft = { question: '', answer: '', own: false };
			await loadBank();
		}
	}

	async function act(item: Item, action: 'approve' | 'reject' | 'retry', text?: string): Promise<void> {
		const body = action === 'approve' ? { text: text ?? null } : {};
		if (await guard(() => api.post(`/api/teacher/revision/${item.id}/${action}`, body))) {
			delete editing[item.id];
			await loadBank();
			await load();
		}
	}

	const plain = (text: string) => text.replace(/\s*\[S\d+\]/g, '').replace(/\*\*(.+?)\*\*/g, '$1');
	const daysLeft = (p: Portion) => Math.round((Date.parse(p.exam_on) - Date.parse(today)) / 86_400_000);
	const classNames = (p: Portion) => p.classes.map((c) => `${c.grade}${c.section}`).join(', ');
</script>

<section class="card stack">
	<p class="muted small">{t('revision.intro')}</p>
	<p class="small clock"><Icon name="alert" size={16} />{t('revision.server_date', { date: today })}</p>
	<div class="row"><button class="btn primary" onclick={newExam} disabled={!books.length}><Icon name="plus" size={18} />{t('revision.new')}</button></div>

	{#if portions.length === 0}
		<div class="empty"><div class="art"><Icon name="quiz" size={28} /></div><p>{t('revision.empty')}</p></div>
	{:else}
		<ul class="portions">
			{#each portions as portion (portion.id)}
				{@const left = daysLeft(portion)}
				<li class="portion">
					<div class="grow">
						<p class="title"><strong>{portion.title}</strong> <span class="muted small">· {portion.book_title}</span></p>
						<p class="muted small">
							{classNames(portion)} · {t('revision.chapters', { list: portion.chapters.join(', ') })} ·
							{t('revision.exam_on', { date: portion.exam_on })}
							{#if left >= 0}({left === 0 ? t('revision.exam_today') : t('revision.days_left', { n: left })}){:else}({t('revision.over')}){/if}
						</p>
						<p class="badges">
							<span class="badge ok">{t('revision.count.approved', { n: portion.progress.approved ?? 0 })}</span>
							{#if portion.progress.draft}<span class="badge warn">{t('revision.count.to_check', { n: portion.progress.draft })}</span>{/if}
							{#if portion.progress.pending}<span class="badge">{t('revision.count.pending', { n: portion.progress.pending })}</span>{/if}
						</p>
					</div>
					<div class="row actions">
						<button class="btn small primary" onclick={() => openReview(portion)}><Icon name="check" size={16} />{t('revision.review')}</button>
						<button class="btn small" onclick={() => editExam(portion)}><Icon name="pencil" size={16} />{t('revision.edit')}</button>
						<button class="btn small ghost" aria-label={t('revision.delete')} onclick={() => deleteExam(portion)}><Icon name="trash" size={16} /></button>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>

{#if review}
	{@const portion = review.portion}
	<section class="card stack">
		<div class="row between">
			<h2 class="section-title"><Icon name="quiz" size={20} />{portion.title}</h2>
			<button class="btn small ghost" onclick={() => (review = null)}><Icon name="close" size={16} />{t('common.close')}</button>
		</div>
		<div class="tabs" role="group" aria-label={t('revision.form.chapters')}>
			{#each portion.chapters as chapter (chapter)}
				<button class="chip" class:selected={review.chapter === chapter} aria-pressed={review.chapter === chapter} onclick={() => openReview(portion, chapter)}>{t('ask.chapter_short', { n: chapter })}</button>
			{/each}
		</div>

		<form class="add stack" onsubmit={(event) => (event.preventDefault(), addQuestion())}>
			<label class="field"><span>{t('revision.add_question')}</span>
				<input bind:value={draft.question} maxlength="500" placeholder={t('revision.add_placeholder')} /></label>
			<label class="check"><input type="checkbox" bind:checked={draft.own} />{t('revision.own_answer')}</label>
			{#if draft.own}
				<label class="field"><span>{t('revision.your_answer')}</span><textarea bind:value={draft.answer} rows="3" maxlength="4000"></textarea></label>
				<p class="muted small">{t('revision.own_note')}</p>
			{/if}
			<div class="row"><button class="btn primary small" disabled={draft.question.trim().length < 3 || (draft.own && !draft.answer.trim())}>
				<Icon name="plus" size={16} />{draft.own ? t('revision.add_own') : t('revision.add_ai')}</button></div>
		</form>

		{#if items.length === 0}
			<p class="muted">{t('revision.bank_empty')}</p>
		{/if}
		<ul class="bank">
			{#each items as item (item.id)}
				<li class={`item ${item.status}`}>
					<p class="q">{item.question} {#if item.source === 'drafted'}<span class="badge">{t('revision.drafted')}</span>{/if}</p>
					{#if item.status === 'pending'}
						<p class="muted small"><span class="spinner"></span> {t('revision.answering')}</p>
					{:else if item.status === 'failed'}
						<p class="muted small">{t('revision.failed')}</p>
						<div class="row"><button class="btn small" onclick={() => act(item, 'retry')}><Icon name="refresh" size={16} />{t('revision.retry')}</button></div>
					{:else if item.status === 'not_in_book' && editing[item.id] === undefined}
						<p class="muted small">{t('revision.not_in_book')}</p>
						<div class="row">
							<button class="btn small" onclick={() => (editing[item.id] = '')}><Icon name="pencil" size={16} />{t('revision.write_answer')}</button>
							<button class="btn small ghost" onclick={() => act(item, 'reject')}>{t('revision.remove')}</button>
						</div>
					{:else if editing[item.id] !== undefined}
						<textarea bind:value={editing[item.id]} rows="4" maxlength="4000"></textarea>
						{#if item.answer?.citations?.length}<p class="muted small">{t('revision.edit_keeps_pages')}</p>{/if}
						<div class="row">
							<button class="btn small primary" disabled={!editing[item.id]?.trim()} onclick={() => act(item, 'approve', editing[item.id])}><Icon name="check" size={16} />{t('revision.save_approve')}</button>
							<button class="btn small ghost" onclick={() => delete editing[item.id]}>{t('common.cancel')}</button>
						</div>
					{:else if item.answer}
						<RevisionAnswer answer={item.answer} documentId={portion.document_id}
							label={item.status === 'approved' ? (item.answer_kind === 'written' ? 'teacher_written' : 'teacher_approved') : ''} />
						<div class="row">
							{#if item.status !== 'approved'}
								<button class="btn small primary" onclick={() => act(item, 'approve')}><Icon name="check" size={16} />{t('revision.approve')}</button>
							{/if}
							<button class="btn small" onclick={() => (editing[item.id] = plain(item.answer?.text ?? ''))}><Icon name="pencil" size={16} />{t('revision.edit_answer')}</button>
							{#if item.status === 'rejected'}
								<button class="btn small ghost" onclick={() => act(item, 'retry')}><Icon name="refresh" size={16} />{t('revision.retry')}</button>
							{:else}
								<button class="btn small ghost" onclick={() => act(item, 'reject')}>{item.status === 'approved' ? t('revision.withdraw') : t('revision.reject')}</button>
							{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	</section>
{/if}

{#if form}
	<Sheet title={form.id === null ? t('revision.new') : t('revision.edit')} onclose={() => (form = null)}>
		<form class="stack" onsubmit={(event) => (event.preventDefault(), saveExam())}>
			<label class="field"><span>{t('revision.form.title')}</span><input bind:value={form.title} maxlength="120" required placeholder={t('revision.form.title_hint')} /></label>
			<label class="field"><span>{t('revision.form.book')}</span>
				<select bind:value={form.document_id} onchange={() => form && ((form.chapters = []), (form.class_ids = []))}>
					{#each books as book (book.id)}<option value={book.id}>{book.title} ({t(`medium.${book.medium}`)})</option>{/each}
				</select></label>
			<fieldset class="field"><legend>{t('revision.form.classes')}</legend>
				<div class="choices">
					{#each eligible as klass (klass.id)}
						<label class="check"><input type="checkbox" checked={form.class_ids.includes(klass.id)} onchange={() => form && (form.class_ids = toggle(form.class_ids, klass.id))} />{klass.label}</label>
					{/each}
				</div>
				<p class="muted small">{t('revision.form.other_book_note')}</p>
			</fieldset>
			<fieldset class="field"><legend>{t('revision.form.chapters')}</legend>
				<div class="choices">
					{#each formBook?.chapters ?? [] as chapter (chapter.no)}
						<label class="check"><input type="checkbox" checked={form.chapters.includes(chapter.no)} onchange={() => form && (form.chapters = toggle(form.chapters, chapter.no))} />{chapter.no}. {chapter.title}</label>
					{/each}
				</div>
			</fieldset>
			<div class="row dates">
				<label class="field"><span>{t('revision.form.visible_from')}</span><input type="date" bind:value={form.visible_from} required /></label>
				<label class="field"><span>{t('revision.form.exam_on')}</span><input type="date" bind:value={form.exam_on} min={form.visible_from} required /></label>
			</div>
			<label class="field"><span>{t('revision.form.per_chapter', { n: form.drafts_per_chapter })}</span>
				<input type="range" min="0" max="20" bind:value={form.drafts_per_chapter} />
				<small class="muted">{t('revision.form.per_chapter_hint')}</small></label>
			<button class="btn primary block" disabled={!form.title.trim() || !form.chapters.length || !form.class_ids.length}>{t('revision.form.save')}</button>
		</form>
	</Sheet>
{/if}

<style>
	.clock {
		margin: 0;
		display: flex;
		gap: 6px;
		align-items: center;
		color: var(--muted);
	}
	.portions,
	.bank {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 10px;
	}
	.portion,
	.item {
		padding: 12px;
		border: 1px solid var(--line);
		border-radius: var(--radius);
		display: grid;
		gap: 8px;
	}
	.portion {
		grid-template-columns: 1fr auto;
		align-items: center;
	}
	@media (max-width: 560px) {
		.portion {
			grid-template-columns: 1fr;
		}
	}
	.portion p,
	.item p {
		margin: 0;
	}
	.badges {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}
	.item.approved {
		border-color: var(--ok);
	}
	.item.rejected {
		opacity: 0.6;
	}
	.q {
		font-weight: 600;
	}
	.section-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 1rem;
		margin: 0;
	}
	.chip.selected {
		background: var(--accent);
		color: var(--on-accent);
		border-color: var(--accent);
	}
	.between {
		justify-content: space-between;
	}
	.choices {
		display: grid;
		gap: 6px;
	}
	.check {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.dates > .field {
		flex: 1;
	}
	textarea {
		width: 100%;
	}
</style>
