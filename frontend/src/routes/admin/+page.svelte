<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '#lib/api.js';
	import ConsoleShell from '#lib/components/ConsoleShell.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { confirmAction } from '#lib/feedback.svelte.js';
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
	// The laptop's Wi-Fi address; this page's own host is localhost, which a phone can't reach.
	let phoneUrl = $state('');
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
			phoneUrl = overview.phone_urls?.[0] ?? `http://${location.host}`;
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
		if (!(await confirmAction(t('admin.restart_confirm'), { confirmLabel: t('admin.restart') }))) return;
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
	<!-- Stays on screen (not a toast): it can carry a one-time password. -->
	{#if notice}<p class="notice no-print" role="status"><Icon name="check" size={18} /><span class="grow">{notice}</span>
		<button class="btn ghost small icon" onclick={() => (notice = '')} aria-label={t('common.close')}><Icon name="close" size={16} /></button></p>{/if}

	{#if tab === 'overview' && overview}
		{@const usage = overview.usage}
		{@const model = overview.model}
		{@const on = !!controls?.answering_enabled}
		<div class="stack">
			<section class="card status" class:paused={!on}>
				<div class="status-main">
					<span class="status-icon"><Icon name={on ? 'play' : 'pause'} size={22} /></span>
					<div class="grow">
						<p class="eyebrow">{t('admin.model')}</p>
						<h2>{on ? t('admin.answering_on') : t('admin.answering_off')}</h2>
						<p class="mono model-file">{model.model ? String(model.model).split(/[\\/]/).pop() : '—'}</p>
					</div>
					<div class="row status-actions">
						{#if on}
							<button class="btn danger" onclick={() => saveControls({ answering_enabled: false })}><Icon name="pause" size={18} />{t('admin.pause')}</button>
						{:else}
							<button class="btn accent" onclick={() => saveControls({ answering_enabled: true })}><Icon name="play" size={18} />{t('admin.resume')}</button>
						{/if}
						<button class="btn" disabled={restarting} onclick={restart}>
							{#if restarting}<span class="spinner"></span>{:else}<Icon name="refresh" size={18} />{/if}
							{restarting ? t('admin.restarting') : t('admin.restart')}
						</button>
					</div>
				</div>
				<div class="services">
					<span><span class="status-dot" class:off={!model.chat}></span>{t('admin.model_chat')}: {model.chat ? t('admin.running') : t('admin.stopped')}</span>
					<span><span class="status-dot" class:off={!model.embed}></span>{t('admin.model_embed')}: {model.embed ? t('admin.running') : t('admin.stopped')}</span>
					{#if model.slots}<span class="tabular"><Icon name="server" size={15} />{t('admin.busy_slots', { busy: model.busy_slots, slots: model.slots })}</span>{/if}
					{#each overview.phone_urls ?? [] as url (url)}<span><Icon name="globe" size={15} />{t('accounts.slip_site')} <b class="mono">{url}</b></span>{/each}
				</div>
				<p class="muted small">{t('settings.model_note')}</p>
			</section>

			<!-- Measured from this server's own answer log, not claimed. -->
			<section class="tiles">
				<div class="kpi"><span>{t('admin.questions')}</span><strong>{usage.questions}</strong><small>{t('admin.last_days', { days: usage.days })}</small></div>
				<div class="kpi"><span>{t('admin.answered')}</span><strong>{usage.outcomes.answered ?? 0}</strong></div>
				<div class="kpi"><span>{t('admin.refused')}</span><strong>{usage.outcomes.refused ?? 0}</strong></div>
				<div class="kpi"><span>{t('admin.cached')}</span><strong>{usage.outcomes.cached ?? 0}</strong></div>
				<div class="kpi"><span>{t('admin.first_word')}</span><strong>{seconds(usage.first_word_ms.p50)}</strong><small>p95 {seconds(usage.first_word_ms.p95)}</small></div>
				<div class="kpi"><span>{t('admin.total_time')}</span><strong>{seconds(usage.total_ms.p50)}</strong><small>p95 {seconds(usage.total_ms.p95)}</small></div>
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
					<ul class="facts">
						{#each Object.entries(usage.by_language) as [language, count] (language)}
							<li><span class="grow">{t(`medium.${language}`)}</span><strong>{count}</strong></li>
						{:else}<li class="muted">{t('admin.no_data')}</li>{/each}
					</ul>
				</section>
				<section class="card">
					<h3>{t('admin.by_class')}</h3>
					<ul class="facts">
						{#each Object.entries(usage.by_class) as [label, count] (label)}
							<li><span class="grow">{label === 'teacher' ? t('admin.teacher_tests') : label}</span><strong>{count}</strong></li>
						{:else}<li class="muted">{t('admin.no_data')}</li>{/each}
					</ul>
				</section>
				<section class="card">
					<h3>{t('admin.disk')}</h3>
					<ul class="facts">
						{#each Object.entries(overview.disk) as [name, bytes] (name)}
							<li><span class="grow">{name === 'free' ? t('admin.disk_free') : name}</span><strong>{mb(Number(bytes))}</strong></li>
						{/each}
					</ul>
				</section>
				<section class="card">
					<h3>{t('admin.tab.accounts')}</h3>
					<ul class="facts">
						<li><span class="grow">{t('admin.students')}</span><strong>{overview.accounts.student?.total ?? 0}</strong></li>
						<li><span class="grow">{t('admin.teachers')}</span><strong>{overview.accounts.teacher?.total ?? 0}</strong></li>
						<li><span class="grow">{t('admin.books')}</span><strong>{Object.values(overview.books).reduce((a: number, b) => a + Number(b), 0)}</strong></li>
						<li><span class="grow">{t('admin.unanswered')}</span><strong>{overview.unanswered}</strong></li>
					</ul>
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
				<button class="btn primary"><Icon name="plus" size={18} />{t('classes.add')}</button>
			</form>
			{#if classes.length}
				<ul class="list-group">
					{#each classes as klass (klass.id)}
						<li class="class-row">
							<span class="class-tag">{klass.label}</span>
							<span class="grow">
								<strong>{t(`medium.${klass.medium}`)}</strong>
								<small class="muted tabular">{t('classes.students', { n: klass.students })}</small>
							</span>
							<button class="btn small danger" onclick={() => run(async () => { await api.del(`/api/admin/classes/${klass.id}`); await loadClasses(); })}><Icon name="trash" size={15} />{t('classes.delete')}</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{:else if tab === 'accounts'}
		<div class="stack">
			<p class="muted small no-print privacy"><Icon name="shield" size={16} />{t('accounts.privacy')}</p>
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
						<button class="btn" onclick={() => window.print()}><Icon name="printer" size={18} />{t('accounts.print')}</button>
						<button class="btn ghost" onclick={() => (slips = [])}>{t('common.close')}</button></div>
					<div class="slips">
						{#each slips as slip (slip.username)}
							<div class="slip">
								<strong>RuralMinds</strong>
								<span>{t('accounts.slip_site')} {phoneUrl}</span>
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
					<button class="btn icon" aria-label={t('accounts.search')}><Icon name="search" size={18} /></button>
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
										<button class="btn small danger" onclick={async () => (await confirmAction(t('accounts.delete_confirm', { name: user.username }), { danger: true, confirmLabel: t('accounts.delete') })) && run(async () => { await api.del(`/api/admin/users/${user.id}`); await loadUsers(); })} aria-label={t('accounts.delete')}><Icon name="trash" size={16} /></button>
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
			<label class="switch-row">
				<span class="grow"><strong>{t('settings.answering')}</strong></span>
				<input class="switch" type="checkbox" role="switch" bind:checked={controls.answering_enabled} />
			</label>
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
	.notice {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 6px 6px 6px 14px;
		margin: 0 0 14px;
		border-radius: 12px;
		background: var(--ok-soft);
		border: 1px solid color-mix(in srgb, var(--ok) 25%, transparent);
		color: var(--text);
		font-weight: 550;
	}
	.notice > :global(svg:first-child) {
		color: var(--ok);
	}
	.small {
		font-size: 0.85rem;
		margin: 0;
	}

	/* Answering status: the one control that matters during a demo. */
	.status {
		display: grid;
		gap: 14px;
		padding: 20px;
		border-color: color-mix(in srgb, var(--ok) 30%, var(--line));
		background:
			radial-gradient(60% 120% at 0% 0%, color-mix(in srgb, var(--ok) 9%, transparent), transparent 70%),
			var(--surface);
	}
	.status.paused {
		border-color: color-mix(in srgb, var(--danger) 35%, var(--line));
		background:
			radial-gradient(60% 120% at 0% 0%, color-mix(in srgb, var(--danger) 9%, transparent), transparent 70%),
			var(--surface);
	}
	.status-main {
		display: flex;
		align-items: flex-start;
		gap: 14px;
		flex-wrap: wrap;
	}
	.status-icon {
		display: grid;
		place-items: center;
		width: 48px;
		height: 48px;
		border-radius: 14px;
		background: var(--ok-soft);
		color: var(--ok);
		flex-shrink: 0;
	}
	.paused .status-icon {
		background: var(--danger-soft);
		color: var(--danger);
	}
	.status h2 {
		margin: 2px 0 2px;
		font-size: 1.35rem;
	}
	.model-file {
		margin: 0;
		font-size: 0.82rem;
		color: var(--muted);
		overflow-wrap: anywhere;
	}
	.status-actions {
		gap: 8px;
	}
	.services {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 20px;
		padding-top: 12px;
		border-top: 1px solid var(--line);
		font-size: 0.86rem;
		font-weight: 550;
	}
	.services > span {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.services :global(svg) {
		color: var(--muted);
	}

	.tiles {
		display: grid;
		gap: 10px;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
	}
	.two {
		display: grid;
		gap: 14px;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
	}
	.two h3,
	.stack > h3 {
		font-size: 0.76rem;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--muted);
		margin: 0 0 6px;
	}
	.facts {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.facts li {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 9px 0;
		font-size: 0.94rem;
	}
	.facts li + li {
		border-top: 1px solid var(--line);
	}
	.facts strong {
		font-variant-numeric: tabular-nums;
		font-weight: 650;
	}
	.bars {
		display: grid;
		gap: 8px;
	}
	.bar-row {
		display: grid;
		grid-template-columns: 52px 1fr 40px;
		gap: 10px;
		align-items: center;
		font-variant-numeric: tabular-nums;
	}
	.bar-row > :last-child {
		text-align: right;
		font-weight: 600;
	}
	.bar {
		height: 10px;
		background: var(--surface-2);
		border-radius: 999px;
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 70%, var(--primary)));
	}

	.class-row {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 12px 14px;
	}
	.class-row strong {
		display: block;
		font-weight: 600;
	}
	.class-row small {
		display: block;
		font-size: 0.82rem;
	}
	.class-tag {
		display: grid;
		place-items: center;
		min-width: 48px;
		height: 40px;
		padding: 0 8px;
		border-radius: 10px;
		background: var(--accent-softer);
		border: 1px solid var(--accent-soft);
		color: var(--accent-strong);
		font-weight: 700;
	}

	.switch-row {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 4px 0 14px;
		border-bottom: 1px solid var(--line);
		cursor: pointer;
	}
	.switch {
		appearance: none;
		position: relative;
		width: 46px !important;
		height: 28px !important;
		border-radius: 999px;
		background: var(--surface-3);
		border: 1px solid var(--line-strong);
		cursor: pointer;
		transition: background 0.15s;
		flex-shrink: 0;
	}
	.switch::after {
		content: '';
		position: absolute;
		top: 2px;
		left: 2px;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: #fff;
		box-shadow: 0 1px 3px rgb(0 0 0 / 0.25);
		transition: transform 0.18s;
	}
	.switch:checked {
		background: var(--accent);
		border-color: var(--accent);
	}
	.switch:checked::after {
		transform: translateX(18px);
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
	.privacy {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		padding: 10px 14px;
		border-radius: 12px;
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.privacy :global(svg) {
		color: var(--accent-strong);
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
		border: 1px dashed var(--line-strong);
		border-radius: 10px;
		padding: 12px;
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
