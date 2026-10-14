<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api, ApiError, type Me } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';
	import { LANGUAGES, getLang, setLang, t, type Lang } from '#lib/i18n/index.svelte.js';
	import { homeFor, loadMe, session } from '#lib/session.svelte.js';

	let username = $state('');
	let password = $state('');
	let showPassword = $state(false);
	let errorKey = $state(page.url.searchParams.has('expired') ? 'auth.expired' : '');
	let sending = $state(false);

	onMount(async () => {
		try {
			const me = await loadMe();
			if (me) await goto(homeFor(me), { replaceState: true });
		} catch {
			// offline: stay on the form; signing in shows the message
		}
	});

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		errorKey = '';
		sending = true;
		try {
			const me = await api.post<Me>('/api/login', { username: username.trim(), password });
			session.me = me;
			session.loaded = true;
			await goto(homeFor(me), { replaceState: true });
		} catch (error) {
			errorKey = error instanceof ApiError ? error.key : 'error.generic';
			password = '';
		} finally {
			sending = false;
		}
	}
</script>

<main class="screen">
	<label class="language">
		<Icon name="globe" size={18} />
		<select value={getLang()} onchange={(event) => setLang(event.currentTarget.value as Lang)} aria-label={t('settings.app_language')}>
			{#each LANGUAGES as language (language.code)}<option value={language.code}>{language.label}</option>{/each}
		</select>
	</label>

	<section class="panel">
		<div class="hero">
			<span class="logo" aria-hidden="true">R</span>
			<h1>{t('app.name')}</h1>
			<p>{t('app.tagline')}</p>
			<span class="offline"><Icon name="wifi" size={16} />{t('app.offline_badge')}</span>
		</div>

		<form class="card" onsubmit={submit}>
			<h2>{t('login.title')}</h2>
			<label class="field">
				<span>{t('login.username')}</span>
				<input bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" required placeholder="8a-07" />
			</label>
			<label class="field">
				<span>{t('login.password')}</span>
				<div class="password">
					<input type={showPassword ? 'text' : 'password'} bind:value={password} autocomplete="current-password" required />
					<button type="button" class="btn ghost icon" onclick={() => (showPassword = !showPassword)} aria-label={t('login.show_password')} aria-pressed={showPassword}>
						<Icon name="eye" size={20} />
					</button>
				</div>
			</label>
			{#if errorKey}<p class="error" role="alert">{t(errorKey)}</p>{/if}
			<button class="btn primary block" disabled={sending || !username || !password}>
				{sending ? t('loading') : t('login.submit')}
			</button>
			<p class="muted help">{t('login.help')}</p>
		</form>
		<p class="muted admin-note"><Icon name="shield" size={14} />{t('login.admin_note')}</p>
	</section>
</main>

<style>
	.screen {
		min-height: 100dvh;
		display: grid;
		place-items: center;
		padding: 56px 16px 24px;
		background:
			radial-gradient(90% 60% at 50% 0%, color-mix(in srgb, var(--accent) 26%, transparent), transparent 70%),
			var(--bg);
	}
	.language {
		position: absolute;
		top: 12px;
		right: 16px;
		display: flex;
		align-items: center;
		gap: 6px;
		color: var(--muted);
	}
	.language select {
		width: auto;
		min-height: 38px;
		padding: 4px 10px;
		border-radius: 999px;
	}
	.panel {
		width: 100%;
		max-width: 400px;
		display: grid;
		gap: 18px;
	}
	.hero {
		display: grid;
		justify-items: center;
		text-align: center;
		gap: 6px;
	}
	.hero h1 {
		margin: 8px 0 0;
		font-size: 2rem;
	}
	.hero p {
		margin: 0;
		color: var(--muted);
		max-width: 30ch;
	}
	.logo {
		display: grid;
		place-items: center;
		width: 64px;
		height: 64px;
		border-radius: 20px;
		background: linear-gradient(135deg, var(--accent), var(--accent-strong));
		color: #fff;
		font-size: 2rem;
		font-weight: 800;
		box-shadow: var(--shadow-lg);
	}
	.offline {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-top: 4px;
		padding: 4px 12px;
		border-radius: 999px;
		background: var(--accent-soft);
		color: var(--accent-strong);
		font-size: 0.82rem;
		font-weight: 700;
	}
	form {
		display: grid;
		gap: 2px;
		padding: 22px 20px;
		border-radius: var(--radius-lg);
	}
	form h2 {
		margin-bottom: 12px;
	}
	.password {
		display: flex;
		gap: 6px;
	}
	.help {
		margin: 12px 0 0;
		text-align: center;
		font-size: 0.85rem;
	}
	.admin-note {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		font-size: 0.8rem;
		margin: 0;
	}
</style>
