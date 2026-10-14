<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError, type Book } from '#lib/api.js';
	import ChatView from '#lib/components/ChatView.svelte';
	import ConsoleShell from '#lib/components/ConsoleShell.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import UploadWizard from '#lib/components/UploadWizard.svelte';
	import { t } from '#lib/i18n/index.svelte.js';
	import { requireRole } from '#lib/session.svelte.js';
	import { ask, choose, newConversation, setBooks, study } from '#lib/study.svelte.js';

	type ClassRow = { id: number; grade: number; section: string; medium: string; label: string; mine: boolean };
	type TeacherBook = Book & { status: string; page_count: number; class_ids: number[] };
	type Job = { id: number; status: string; filename: string; page_count: number; error: string | null };
	type Overview = {
		classes: ClassRow[];
		books: TeacherBook[];
		jobs: Job[];
		limits: { max_upload_mb: number; max_pages: number };
		subjects: string[];
		boards: string[];
	};
	type Tab = 'library' | 'upload' | 'try' | 'inbox' | 'approved' | 'insights';

	let tab = $state<Tab>('library');
	let data = $state<Overview | null>(null);
	let errorKey = $state('');
	let resumeJob = $state<Job | null>(null);
	let inbox = $state<any[]>([]);
	let approved = $state<any[]>([]);
	let activity = $state<{ days: number; min_group: number; rows: any[] } | null>(null);
	let editing = $state<Record<number, number[]>>({});
	let expanded = $state<Record<number, boolean>>({});

	const working = $derived(data?.jobs.some((job) => ['queued', 'ingesting'].includes(job.status)));
	const items = $derived([
		{ id: 'library' as Tab, icon: 'book', label: t('teacher.tab.books') },
		{ id: 'upload' as Tab, icon: 'upload', label: t('teacher.tab.upload') },
		{ id: 'try' as Tab, icon: 'sparkle', label: t('teacher.tab.try') },
		{ id: 'inbox' as Tab, icon: 'inbox', label: t('teacher.tab.unanswered'), count: inbox.length },
		{ id: 'approved' as Tab, icon: 'check', label: t('teacher.tab.approved') },
		{ id: 'insights' as Tab, icon: 'chart', label: t('teacher.tab.activity') }
	]);

	async function refresh(): Promise<void> {
		try {
			data = await api.get<Overview>('/api/teacher/overview');
			errorKey = '';
		} catch (error) {
			errorKey = error instanceof ApiError ? error.key : 'error.generic';
		}
	}

	async function open(next: Tab): Promise<void> {
		tab = next;
		try {
			if (next === 'inbox') inbox = await api.get('/api/teacher/unanswered');
			if (next === 'approved') approved = await api.get('/api/teacher/approved');
			if (next === 'insights') activity = await api.get('/api/teacher/activity');
			if (next === 'library' || next === 'try') await refresh();
			if (next === 'try' && data && (study.endpoint !== '/api/teacher/ask' || !study.loaded)) {
				setBooks(data.books, '/api/teacher/ask');
			}
		} catch (error) {
			errorKey = error instanceof ApiError ? error.key : 'error.generic';
		}
	}

	onMount(() => {
		requireRole('teacher', 'admin').then(async (me) => {
			if (!me) return;
			await refresh();
			inbox = await api.get<any[]>('/api/teacher/unanswered').catch(() => []);
		});
		const timer = setInterval(() => working && tab === 'library' && refresh(), 5000);
		return () => clearInterval(timer);
	});

	async function act(action: () => Promise<unknown>): Promise<void> {
		try {
			await action();
			await refresh();
		} catch (error) {
			alert(t(error instanceof ApiError ? error.key : 'error.generic'));
		}
	}

	async function answerIt(row: any): Promise<void> {
		await open('try');
		newConversation();
		choose(row.document_id, row.chapter_no);
		ask(row.question);
	}

	const classLabel = (id: number) => data?.classes.find((klass) => klass.id === id)?.label ?? '?';
	const notesState = (chapter: Book['chapters'][number]) => Object.values(chapter.notes ?? {})[0];
</script>

<ConsoleShell role={t('teacher.title')} {items} current={tab} onselect={open} title={items.find((item) => item.id === tab)?.label ?? ''}>
	{#if errorKey}<p class="error">{t(errorKey)}</p>{/if}

	{#if !data}
		<div class="stack"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:120px"></div></div>
	{:else if tab === 'library'}
		<div class="stack">
			{#if data.jobs.length}
				<section class="card stack">
					<h2 class="section-title"><Icon name="upload" size={20} />{t('teacher.jobs')}</h2>
					{#each data.jobs as job (job.id)}
						<div class="job">
							<div class="grow">
								<strong>{job.filename}</strong>
								{#if job.error}<p class="muted small">{t(job.error)}</p>{/if}
								{#if job.status === 'ingesting' || job.status === 'queued'}<div class="progress"><span></span></div>{/if}
							</div>
							<span class="badge" class:bad={job.status === 'failed'} class:accent={job.status === 'ingesting'}>{t(`teacher.job.${job.status}`)}</span>
							{#if job.status === 'awaiting_details'}
								<button class="btn small primary" onclick={() => ((resumeJob = job), (tab = 'upload'))}>{t('teacher.job.finish')}</button>
							{/if}
							{#if job.status === 'failed'}
								<button class="btn small" onclick={() => act(() => api.post(`/api/teacher/uploads/${job.id}/retry`))}>{t('teacher.job.retry')}</button>
							{/if}
							{#if job.status !== 'ingesting'}
								<button class="btn small ghost" onclick={() => act(() => api.del(`/api/teacher/uploads/${job.id}`))}>{t('teacher.job.cancel')}</button>
							{/if}
						</div>
					{/each}
				</section>
			{/if}

			{#if data.books.length === 0}
				<div class="empty card"><div class="art"><Icon name="book" size={28} /></div><p>{t('teacher.no_books')}</p>
					<button class="btn primary" onclick={() => (tab = 'upload')}><Icon name="upload" size={18} />{t('teacher.tab.upload')}</button></div>
			{/if}

			<div class="books">
				{#each data.books as book (book.id)}
					<article class="card book">
						<div class="book-head">
							<div class="cover" aria-hidden="true"><Icon name="book" size={24} /></div>
							<div class="grow">
								<h3>{book.title}</h3>
								<p class="muted small">{t('upload.grade')} {book.grade} · {t(`subject.${book.subject}`)} · {t(`medium.${book.medium}`)} · {t('teacher.pages', { n: book.page_count })}</p>
							</div>
							<span class="badge" class:ok={book.status === 'published'} class:warn={book.status !== 'published'}>
								{t(`teacher.status.${book.status}`)}
							</span>
						</div>

						<div class="row">
							<span class="muted small">{t('teacher.classes')}:</span>
							{#if editing[book.id]}
								{#each data.classes as klass (klass.id)}
									<label class="chip"><input type="checkbox" bind:group={editing[book.id]} value={klass.id} /> {klass.label}</label>
								{/each}
								<button class="btn small primary" onclick={() => act(async () => { await api.post(`/api/teacher/books/${book.id}/classes`, { class_ids: editing[book.id] }); delete editing[book.id]; })}>{t('teacher.save_classes')}</button>
							{:else}
								{#each book.class_ids as id (id)}<span class="badge accent">{classLabel(id)}</span>{:else}<span class="muted small">—</span>{/each}
								<button class="btn small ghost" onclick={() => (editing[book.id] = [...book.class_ids])} aria-label={t('teacher.classes')}><Icon name="pencil" size={16} /></button>
							{/if}
						</div>

						<button class="disclose" onclick={() => (expanded[book.id] = !expanded[book.id])} aria-expanded={!!expanded[book.id]}>
							<Icon name="list" size={18} />
							<span class="grow">{t('teacher.notes_title', { n: book.chapters.filter((c) => notesState(c)).length, total: book.chapters.length })}</span>
							<Icon name={expanded[book.id] ? 'chevronDown' : 'chevronRight'} size={18} />
						</button>
						{#if expanded[book.id]}
							<ul class="chapters">
								{#each book.chapters as chapter (chapter.no)}
									{@const state = notesState(chapter)}
									<li>
										<span class="num">{chapter.no}</span>
										<span class="grow">{chapter.title}</span>
										{#if state === 'approved'}
											<button class="badge ok as-button" onclick={() => act(() => api.post(`/api/teacher/notes/${book.id}/${chapter.no}`, { approved: false }))}><Icon name="check" size={14} />{t('teacher.notes_approved')}</button>
										{:else if state === 'draft'}
											<a class="btn small ghost" href={`/learn/${book.id}/${chapter.no}`} target="_blank"><Icon name="eye" size={16} /></a>
											<button class="btn small" onclick={() => act(() => api.post(`/api/teacher/notes/${book.id}/${chapter.no}`, { approved: true }))}>{t('teacher.notes_approve')}</button>
										{:else}
											<span class="badge">{t('teacher.notes_none')}</span>
										{/if}
									</li>
								{/each}
							</ul>
							<button class="btn small" onclick={() => act(() => api.post(`/api/teacher/notes/${book.id}/regenerate`, {}))}><Icon name="refresh" size={16} />{t('teacher.notes_regenerate')}</button>
						{/if}

						<div class="row book-actions">
							{#if book.status === 'published'}
								<button class="btn small" onclick={() => act(() => api.post(`/api/teacher/books/${book.id}/publish`, { published: false }))}>{t('teacher.unpublish')}</button>
							{:else}
								<button class="btn small primary" onclick={() => act(() => api.post(`/api/teacher/books/${book.id}/publish`, { published: true }))}>{t('teacher.publish')}</button>
							{/if}
							<button class="btn small" onclick={() => { open('try'); }}><Icon name="sparkle" size={16} />{t('teacher.tab.try')}</button>
							<span class="grow"></span>
							<button class="btn small danger" onclick={() => confirm(t('teacher.delete_confirm', { title: book.title })) && act(() => api.del(`/api/teacher/books/${book.id}`))}><Icon name="trash" size={16} />{t('teacher.delete')}</button>
						</div>
					</article>
				{/each}
			</div>
		</div>
	{:else if tab === 'upload'}
		<UploadWizard classes={data.classes} limits={data.limits} subjects={data.subjects} boards={data.boards} {resumeJob}
			ondone={() => ((resumeJob = null), open('library'))} />
	{:else if tab === 'try'}
		<p class="muted small try-note"><Icon name="eye" size={16} />{t('try.note')}</p>
		{#if data.books.length}<div class="try"><ChatView teacherMode /></div>{/if}
	{:else if tab === 'inbox'}
		<section class="card">
			<p class="muted small">{t('inbox.intro')}</p>
			{#if inbox.length === 0}
				<div class="empty"><div class="art"><Icon name="inbox" size={28} /></div><p>{t('unanswered.empty')}</p></div>
			{:else}
				<ul class="inbox">
					{#each inbox as row (row.id)}
						<li>
							<span class="times" title={t('inbox.times', { n: row.times_asked })}>{row.times_asked}×</span>
							<div class="grow">
								<p class="q" lang={row.language}>{row.question}</p>
								<p class="muted small">{row.class} · {row.chapter_no ? t('ask.chapter_short', { n: row.chapter_no }) : t('ask.whole_book')} · {t(`unanswered.reason.${row.reason}`)} · {(row.last_asked ?? row.created_at).slice(0, 10)}</p>
							</div>
							<button class="btn small" onclick={() => answerIt(row)}><Icon name="sparkle" size={16} />{t('inbox.answer')}</button>
							<button class="btn small ghost" aria-label={t('unanswered.dismiss')} onclick={async () => { await api.del(`/api/teacher/unanswered/${row.id}`); inbox = inbox.filter((item) => item.id !== row.id); }}><Icon name="check" size={16} /></button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{:else if tab === 'approved'}
		<section class="card">
			{#if approved.length === 0}
				<div class="empty"><div class="art"><Icon name="check" size={28} /></div><p>{t('approved.empty')}</p></div>
			{:else}
				<ul class="inbox">
					{#each approved as row (row.id)}
						<li>
							<Icon name="check" size={18} />
							<div class="grow"><p class="q" lang={row.language}>{row.question}</p>
								{#if row.status === 'needs_review'}<span class="badge warn">{t('approved.needs_review')}</span>{/if}</div>
							<button class="btn small danger" onclick={async () => { await api.post(`/api/teacher/approved/${row.id}/reject`); approved = approved.filter((item) => item.id !== row.id); }}>{t('approved.remove')}</button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{:else if tab === 'insights' && activity}
		{@const top = Math.max(1, ...activity.rows.map((row) => row.asked))}
		<section class="card stack">
			<p class="muted small">{t('activity.intro', { days: activity.days, min: activity.min_group })}</p>
			{#if activity.rows.length === 0}
				<div class="empty"><div class="art"><Icon name="chart" size={28} /></div><p>{t('activity.empty')}</p></div>
			{:else}
				{#each activity.rows as row, index (index)}
					<div class="insight">
						<div class="row"><span class="badge accent">{classLabel(row.class_id)}</span>
							<strong class="grow">{row.chapter_no ? `${t('ask.chapter_short', { n: row.chapter_no })} · ${row.chapter_title ?? ''}` : t('ask.whole_book')}</strong>
							<span class="muted small">{t('activity.asked')}: {row.asked}</span></div>
						<div class="bar"><span style={`width:${(100 * row.asked) / top}%`}></span><span class="miss" style={`width:${(100 * row.not_found) / top}%`}></span></div>
						<p class="muted small">{t('activity.not_found')}: {Math.round((100 * row.not_found) / row.asked)}% · {t('activity.malayalam')}: {Math.round((100 * row.in_malayalam) / row.asked)}%</p>
					</div>
				{/each}
			{/if}
		</section>
	{/if}
</ConsoleShell>

<style>
	.section-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 1rem;
		margin: 0;
	}
	.small {
		font-size: 0.85rem;
		margin: 0;
	}
	.job {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		padding-top: 10px;
		border-top: 1px solid var(--line);
	}
	.progress {
		height: 6px;
		border-radius: 6px;
		background: var(--surface-2);
		overflow: hidden;
		margin-top: 6px;
	}
	.progress span {
		display: block;
		width: 40%;
		height: 100%;
		background: var(--accent);
		animation: slide 1.4s ease-in-out infinite;
	}
	@keyframes slide {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(250%);
		}
	}
	.books {
		display: grid;
		gap: 14px;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr));
	}
	.book {
		display: grid;
		gap: 12px;
		align-content: start;
	}
	.book-head {
		display: flex;
		gap: 12px;
		align-items: flex-start;
	}
	.book-head h3 {
		margin: 0;
	}
	.cover {
		display: grid;
		place-items: center;
		width: 44px;
		height: 54px;
		border-radius: 8px 12px 12px 8px;
		background: linear-gradient(135deg, var(--accent), var(--accent-strong));
		color: #fff;
		flex-shrink: 0;
	}
	.disclose {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		min-height: 42px;
		padding: 0 10px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--surface-2);
		cursor: pointer;
		color: var(--text);
		font-weight: 600;
		text-align: left;
	}
	.chapters {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 4px;
	}
	.chapters li {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 40px;
		font-size: 0.9rem;
	}
	.num {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border-radius: 8px;
		background: var(--accent-soft);
		color: var(--accent-strong);
		font-weight: 800;
		font-size: 0.8rem;
	}
	.as-button {
		border: 0;
		cursor: pointer;
	}
	.book-actions {
		border-top: 1px solid var(--line);
		padding-top: 12px;
	}
	.try-note {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 4px;
	}
	.try {
		max-width: 820px;
	}
	.inbox {
		list-style: none;
		margin: 8px 0 0;
		padding: 0;
		display: grid;
	}
	.inbox li {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 4px;
		border-top: 1px solid var(--line);
	}
	.times {
		display: grid;
		place-items: center;
		min-width: 40px;
		height: 32px;
		border-radius: 10px;
		background: var(--warm-soft);
		color: var(--warm);
		font-weight: 800;
		font-size: 0.85rem;
	}
	.q {
		margin: 0;
		font-weight: 600;
	}
	.insight {
		display: grid;
		gap: 6px;
		padding-top: 12px;
		border-top: 1px solid var(--line);
	}
	.bar {
		position: relative;
		height: 12px;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.bar span {
		position: absolute;
		left: 0;
		top: 0;
		bottom: 0;
		background: var(--accent);
		border-radius: 999px;
	}
	.bar .miss {
		background: var(--warm);
	}
</style>
