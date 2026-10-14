<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '#lib/api.js';
	import ConsoleShell from '#lib/components/ConsoleShell.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { t } from '#lib/i18n/index.svelte.js';
	import { requireRole } from '#lib/session.svelte.js';

	type Controls = {
		answering_enabled: boolean;
		allowed_languages: string[];
		disabled_classes: number[];
		max_students: number;
		max_teachers: number;
	};
	type ClassRow = { id: number; grade: number; section: string; medium: string; label: string; students: number };

	const TABS = ['overview', 'classes', 'accounts', 'settings'] as const;
	const ICONS = { overview: 'chart', classes: 'users', accounts: 'shield', settings: 'settings' };
	let tab = $state<(typeof TABS)[number]>('overview');
	let overview = $state<any>(null);
	let classes = $state<ClassRow[]>([]);
	let users = $state<any[]>([]);
	let controls = $state<Controls | null>(null);
	let errorKey = $state('');
	let notice = $state('');
	let restarting = $state(false);
	let slips = $state<{ username: string; password: string }[]>([]);
	let filters = $state({ role: '', class_id: '', enabled: '', q: '' });
	let newClass = $state({ grade: 8, section: 'A', medium: 'en' });
	let bulk = $state({ class_id: 0, count: 30 });
	let teacher = $state({ username: '', class_ids: [] as number[] });

	async function run(action: () => Promise<unknown>): Promise<void> {
		errorKey = '';
		try {
			await action();
		} catch (error) {
			errorKey = error instanceof ApiError ? error.key : 'error.generic';
		}
	}

	const loadOverview = () =>
		run(async () => {
			overview = await api.get('/api/admin/overview');
			controls = overview.controls;
		});
	const loadClasses = () => run(async () => (classes = await api.get('/api/admin/classes')));
	const loadUsers = () =>
		run(async () => {
			const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== ''));
			users = await api.get(`/api/admin/users?${query}`);
		});

	async function open(next: (typeof TABS)[number]): Promise<void> {
		tab = next;
		notice = '';
		if (next === 'overview' || next === 'settings') await loadOverview();
		await loadClasses();
		if (next === 'accounts') await loadUsers();
	}

	onMount(() => {
		requireRole('admin').then((me) => me && open('overview'));
	});

	async function saveControls(patch: Partial<Controls> = {}): Promise<void> {
		if (!controls) return;
		await run(async () => {
			controls = await api.post<Controls>('/api/admin/controls', { ...controls, ...patch });
			notice = t('settings.saved');
		});
	}

	async function restart(): Promise<void> {
		if (!confirm(t('admin.restart_confirm'))) return;
		restarting = true;
		await run(() => api.post('/api/admin/model/restart'));
		restarting = false;
		await loadOverview();
	}

	const createClass = () =>
		run(async () => {
			await api.post('/api/admin/classes', newClass);
			await loadClasses();
		});

	const createStudents = () =>
		run(async () => {
			const result = await api.post<{ accounts: { username: string; password: string }[] }>(
				'/api/admin/users/bulk',
				bulk
			);
			slips = result.accounts;
			notice = t('accounts.created');
			await loadUsers();
		});

	const createTeacher = () =>
		run(async () => {
			const result = await api.post<{ username: string; password: string }>('/api/admin/users', {
				username: teacher.username,
				role: 'teacher',
				class_ids: teacher.class_ids
			});
			slips = [result];
			notice = t('accounts.created');
			teacher = { username: '', class_ids: [] };
			await loadUsers();
		});

	const resetPassword = (user: any) =>
		run(async () => {
			const result = await api.post<{ username: string; password: string }>(`/api/admin/users/${user.id}/reset`);
			slips = [result];
			notice = t('accounts.new_password', { name: result.username, password: result.password });
		});

	const mb = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(bytes > 1e9 ? 0 : 1)} MB`;
	const seconds = (ms: number | null) => (ms === null ? '—' : `${(ms / 1000).toFixed(1)} s`);
	const maxDay = $derived(
		Math.max(1, ...(overview?.usage.by_day ?? []).map((day: any) => sumDay(day)))
	);
	function sumDay(day: Record<string, any>): number {
		return ['answered', 'refused', 'cached', 'error'].reduce((total, key) => total + (day[key] ?? 0), 0);
	}
</script>

<ConsoleShell role={t('admin.title')} items={TABS.map((id) => ({ id, icon: ICONS[id], label: t(`admin.tab.${id}`) }))} current={tab} onselect={open} title={t(`admin.tab.${tab}`)}>
	{#if errorKey}<p class="error no-print">{t(errorKey)}</p>{/if}
	{#if notice}<p class="badge ok notice no-print">{notice}</p>{/if}

	{#if tab === 'overview' && overview}
		{@const usage = overview.usage}
		{@const model = overview.model}
		<div class="stack">
			<section class="card stack">
				<div class="row">
					<h2 class="grow">{t('admin.model')}</h2>
					<span class="badge" class:ok={controls?.answering_enabled} class:bad={!controls?.answering_enabled}>
						{controls?.answering_enabled ? t('admin.answering_on') : t('admin.answering_off')}
					</span>
				</div>
				<p class="mono">{model.model ? String(model.model).split(/[\\/]/).pop() : '—'}</p>
				<div class="row">
					<span class="badge" class:ok={model.chat} class:bad={!model.chat}>{t('admin.model_chat')}: {model.chat ? t('admin.running') : t('admin.stopped')}</span>
					<span class="badge" class:ok={model.embed} class:bad={!model.embed}>{t('admin.model_embed')}: {model.embed ? t('admin.running') : t('admin.stopped')}</span>
					{#if model.slots}<span class="badge">{t('admin.busy_slots', { busy: model.busy_slots, slots: model.slots })}</span>{/if}
				</div>
				<div class="row">
					{#if controls?.answering_enabled}
						<button class="btn danger" onclick={() => saveControls({ answering_enabled: false })}>⏸ {t('admin.pause')}</button>
					{:else}
						<button class="btn primary" onclick={() => saveControls({ answering_enabled: true })}>▶ {t('admin.resume')}</button>
					{/if}
					<button class="btn" disabled={restarting} onclick={restart}>↻ {restarting ? t('admin.restarting') : t('admin.restart')}</button>
				</div>
				<p class="muted small">{t('settings.model_note')}</p>
			</section>

			<section class="tiles">
				<div class="card tile"><span>{t('admin.questions')}</span><strong>{usage.questions}</strong><small>{t('admin.last_days', { days: usage.days })}</small></div>
				<div class="card tile"><span>{t('admin.answered')}</span><strong>{usage.outcomes.answered ?? 0}</strong></div>
				<div class="card tile"><span>{t('admin.refused')}</span><strong>{usage.outcomes.refused ?? 0}</strong></div>
				<div class="card tile"><span>{t('admin.cached')}</span><strong>{usage.outcomes.cached ?? 0}</strong></div>
				<div class="card tile"><span>{t('admin.first_word')}</span><strong>{seconds(usage.first_word_ms.p50)}</strong><small>p95 {seconds(usage.first_word_ms.p95)}</small></div>
				<div class="card tile"><span>{t('admin.total_time')}</span><strong>{seconds(usage.total_ms.p50)}</strong><small>p95 {seconds(usage.total_ms.p95)}</small></div>
			</section>

			<section class="card stack">
				<h3>{t('admin.by_day')}</h3>
				{#if usage.by_day.length === 0}
					<p class="muted">{t('admin.no_data')}</p>
				{:else}
					<div class="bars">
						{#each usage.by_day as day (day.day)}
							<div class="bar-row">
								<span class="muted small">{day.day.slice(5)}</span>
								<div class="bar"><span style={`width:${(100 * sumDay(day)) / maxDay}%`}></span></div>
								<span class="small">{sumDay(day)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</section>

			<div class="two">
				<section class="card">
					<h3>{t('admin.by_language')}</h3>
					{#each Object.entries(usage.by_language) as [language, count] (language)}
						<p class="row"><span class="grow">{t(`medium.${language}`)}</span><strong>{count}</strong></p>
					{:else}<p class="muted">{t('admin.no_data')}</p>{/each}
				</section>
				<section class="card">
					<h3>{t('admin.by_class')}</h3>
					{#each Object.entries(usage.by_class) as [label, count] (label)}
						<p class="row"><span class="grow">{label === 'teacher' ? t('admin.teacher_tests') : label}</span><strong>{count}</strong></p>
					{:else}<p class="muted">{t('admin.no_data')}</p>{/each}
				</section>
				<section class="card">
					<h3>{t('admin.disk')}</h3>
					{#each Object.entries(overview.disk) as [name, bytes] (name)}
						<p class="row"><span class="grow">{name === 'free' ? t('admin.disk_free') : name}</span><strong>{mb(Number(bytes))}</strong></p>
					{/each}
				</section>
				<section class="card">
					<p class="row"><span class="grow">{t('admin.students')}</span><strong>{overview.accounts.student?.total ?? 0}</strong></p>
					<p class="row"><span class="grow">{t('admin.teachers')}</span><strong>{overview.accounts.teacher?.total ?? 0}</strong></p>
					<p class="row"><span class="grow">{t('admin.books')}</span><strong>{Object.values(overview.books).reduce((a: number, b) => a + Number(b), 0)}</strong></p>
					<p class="row"><span class="grow">{t('admin.unanswered')}</span><strong>{overview.unanswered}</strong></p>
				</section>
			</div>
		</div>
	{:else if tab === 'classes'}
		<div class="stack">
			<form class="card row" onsubmit={(event) => (event.preventDefault(), createClass())}>
				<label class="field"><span>{t('classes.grade')}</span><input type="number" min="1" max="12" bind:value={newClass.grade} /></label>
				<label class="field"><span>{t('classes.section')}</span><input bind:value={newClass.section} maxlength="4" /></label>
				<label class="field"><span>{t('classes.medium')}</span>
					<select bind:value={newClass.medium}><option value="en">{t('medium.en')}</option><option value="ml">{t('medium.ml')}</option></select></label>
				<button class="btn primary">＋ {t('classes.add')}</button>
			</form>
			{#each classes as klass (klass.id)}
				<div class="card row">
					<strong class="grow">{klass.label} · {t(`medium.${klass.medium}`)}</strong>
					<span class="muted">{t('classes.students', { n: klass.students })}</span>
					<button class="btn small danger" onclick={() => run(async () => { await api.del(`/api/admin/classes/${klass.id}`); await loadClasses(); })}>{t('classes.delete')}</button>
				</div>
			{/each}
		</div>
	{:else if tab === 'accounts'}
		<div class="stack">
			<p class="muted small no-print">🔒 {t('accounts.privacy')}</p>
			<div class="two no-print">
				<form class="card" onsubmit={(event) => (event.preventDefault(), createStudents())}>
					<h3>{t('accounts.bulk_title')}</h3>
					<label class="field"><span>{t('accounts.filter_class')}</span>
						<select bind:value={bulk.class_id} required>
							{#each classes as klass (klass.id)}<option value={klass.id}>{klass.label}</option>{/each}
						</select></label>
					<label class="field"><span>{t('accounts.bulk_count')}</span><input type="number" min="1" max="100" bind:value={bulk.count} /></label>
					<button class="btn primary" disabled={!bulk.class_id}>{t('accounts.bulk_submit')}</button>
				</form>
				<form class="card" onsubmit={(event) => (event.preventDefault(), createTeacher())}>
					<h3>{t('accounts.teacher_title')}</h3>
					<label class="field"><span>{t('login.username')}</span><input bind:value={teacher.username} required maxlength="32" /></label>
					<fieldset class="field"><span>{t('accounts.teacher_classes')}</span>
						<div class="row">{#each classes as klass (klass.id)}<label class="chip"><input type="checkbox" bind:group={teacher.class_ids} value={klass.id} /> {klass.label}</label>{/each}</div>
					</fieldset>
					<button class="btn primary">{t('accounts.teacher_submit')}</button>
				</form>
			</div>

			{#if slips.length}
				<section class="card stack">
					<div class="row no-print"><strong class="grow">{t('accounts.created')}</strong>
						<button class="btn" onclick={() => window.print()}>🖨 {t('accounts.print')}</button>
						<button class="btn ghost" onclick={() => (slips = [])}>{t('common.close')}</button></div>
					<div class="slips">
						{#each slips as slip (slip.username)}
							<div class="slip">
								<strong>RuralMinds</strong>
								<span>{t('accounts.slip_site')} http://{location.host}</span>
								<span>{t('login.username')}: <b class="mono">{slip.username}</b></span>
								<span>{t('login.password')}: <b class="mono">{slip.password}</b></span>
							</div>
						{/each}
					</div>
				</section>
			{/if}

			<section class="card stack no-print">
				<form class="row" onsubmit={(event) => (event.preventDefault(), loadUsers())}>
					<select bind:value={filters.role} aria-label={t('accounts.filter_role')} class="narrow">
						<option value="">{t('accounts.filter_role')}: {t('accounts.all')}</option>
						<option value="student">{t('accounts.role.student')}</option><option value="teacher">{t('accounts.role.teacher')}</option>
					</select>
					<select bind:value={filters.class_id} aria-label={t('accounts.filter_class')} class="narrow">
						<option value="">{t('accounts.filter_class')}: {t('accounts.all')}</option>
						{#each classes as klass (klass.id)}<option value={String(klass.id)}>{klass.label}</option>{/each}
					</select>
					<select bind:value={filters.enabled} aria-label={t('accounts.filter_status')} class="narrow">
						<option value="">{t('accounts.filter_status')}: {t('accounts.all')}</option>
						<option value="true">{t('accounts.enabled')}</option><option value="false">{t('accounts.disabled')}</option>
					</select>
					<input bind:value={filters.q} placeholder={t('accounts.search')} class="narrow" />
					<button class="btn">🔍</button>
				</form>
				<div class="table-scroll">
					<table>
						<thead><tr><th>{t('login.username')}</th><th>{t('accounts.filter_role')}</th><th>{t('accounts.filter_class')}</th><th>{t('accounts.last_login')}</th><th></th></tr></thead>
						<tbody>
							{#each users as user (user.id)}
								<tr class:off={!user.enabled}>
									<td class="mono">{user.username}</td>
									<td>{t(`accounts.role.${user.role}`)}</td>
									<td>{user.class ?? (user.class_ids ?? []).map((id: number) => classes.find((c) => c.id === id)?.label).join(', ')}</td>
									<td>{user.last_login_day ?? '—'}</td>
									<td class="row actions">
										<button class="btn small" onclick={() => resetPassword(user)}>{t('accounts.reset')}</button>
										<button class="btn small" onclick={() => run(async () => { await api.post(`/api/admin/users/${user.id}`, { enabled: !user.enabled }); await loadUsers(); })}>
											{user.enabled ? t('accounts.disable') : t('accounts.enable')}</button>
										<button class="btn small danger" onclick={() => confirm(t('accounts.delete_confirm', { name: user.username })) && run(async () => { await api.del(`/api/admin/users/${user.id}`); await loadUsers(); })}>✕</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		</div>
	{:else if tab === 'settings' && controls}
		<form class="card stack" onsubmit={(event) => (event.preventDefault(), saveControls())}>
			<label class="row"><input type="checkbox" bind:checked={controls.answering_enabled} /> {t('settings.answering')}</label>
			<fieldset class="field"><span>{t('settings.languages')}</span>
				<div class="row">
					{#each ['en', 'ml'] as language (language)}
						<label class="chip"><input type="checkbox" bind:group={controls.allowed_languages} value={language} /> {t(`medium.${language}`)}</label>
					{/each}
				</div>
			</fieldset>
			<fieldset class="field"><span>{t('settings.classes')}</span>
				<div class="row">
					{#each classes as klass (klass.id)}
						<label class="chip"><input type="checkbox" checked={!controls.disabled_classes.includes(klass.id)}
							onchange={(event) => {
								const allowed = event.currentTarget.checked;
								controls!.disabled_classes = allowed
									? controls!.disabled_classes.filter((id) => id !== klass.id)
									: [...controls!.disabled_classes, klass.id];
							}} /> {klass.label}</label>
					{/each}
				</div>
			</fieldset>
			<div class="two">
				<label class="field"><span>{t('settings.max_students')}</span><input type="number" min="1" max="5000" bind:value={controls.max_students} /></label>
				<label class="field"><span>{t('settings.max_teachers')}</span><input type="number" min="1" max="500" bind:value={controls.max_teachers} /></label>
			</div>
			<p class="muted small">{t('settings.model_note')}</p>
			<button class="btn primary">{t('settings.save')}</button>
		</form>
	{/if}
</ConsoleShell>

<style>
	main {
		padding-bottom: 40px;
	}
	.notice {
		display: inline-block;
		padding: 6px 12px;
		margin: 0 0 10px;
	}
	.mono {
		font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
	}
	.small {
		font-size: 0.85rem;
		margin: 0;
	}
	.tiles {
		display: grid;
		gap: 10px;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	}
	.tile {
		display: grid;
		gap: 2px;
	}
	.tile span,
	.tile small {
		color: var(--muted);
		font-size: 0.85rem;
	}
	.tile strong {
		font-size: 1.6rem;
	}
	.two {
		display: grid;
		gap: 14px;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
	}
	.two p.row {
		margin: 6px 0;
	}
	.bars {
		display: grid;
		gap: 6px;
	}
	.bar-row {
		display: grid;
		grid-template-columns: 48px 1fr 40px;
		gap: 8px;
		align-items: center;
	}
	.bar {
		height: 14px;
		background: var(--surface-2);
		border-radius: 999px;
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.narrow {
		width: auto;
		flex: 1 1 140px;
	}
	fieldset {
		border: 0;
		padding: 0;
		margin: 0 0 14px;
	}
	tr.off {
		opacity: 0.55;
	}
	.actions {
		flex-wrap: nowrap;
		gap: 4px;
	}
	.slips {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: 8px;
	}
	.slip {
		display: grid;
		gap: 2px;
		border: 1px dashed var(--line);
		border-radius: 10px;
		padding: 10px;
		font-size: 0.9rem;
		break-inside: avoid;
	}
	@media print {
		.slip {
			border-color: #000;
		}
		.card {
			border: 0;
			box-shadow: none;
		}
	}
</style>
