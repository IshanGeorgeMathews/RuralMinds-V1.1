<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api, ApiError, type Me } from '#lib/api.js';
	import Icon from '#lib/components/Icon.svelte';
	import Logo from '#lib/components/Logo.svelte';
	import { LANGUAGES, getLang, setLang, t, type Lang } from '#lib/i18n/index.svelte.js';
	import { homeFor, loadMe, session } from '#lib/session.svelte.js';

	let username = $state('');
	let password = $state('');
	let showPassword = $state(false);
	let errorKey = $state(page.url.searchParams.has('expired') ? 'auth.expired' : '');
	let sending = $state(false);

	// What makes RuralMinds trustworthy, in plain words (no numbers: those come from eval/).
	const TRUST = [
		{ icon: 'page', key: 'login.trust.book' },
		{ icon: 'wifi', key: 'login.trust.offline' },
		{ icon: 'check', key: 'login.trust.teacher' }
	];

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
	<aside class="brand">
		<Logo size={40} wordmark />
		<div class="pitch">
			<h2>{t('login.brand_title')}</h2>
			<p>{t('app.tagline')}</p>
		</div>
		<ul class="trust">
			{#each TRUST as item (item.key)}
				<li><span class="trust-icon"><Icon name={item.icon} size={18} /></span>{t(item.key)}</li>
			{/each}
		</ul>
		<p class="offline"><span class="status-dot"></span>{t('app.offline_badge')}</p>
	</aside>

	<section class="side">
		<header class="top">
			<span class="mobile-logo"><Logo size={32} wordmark /></span>
			<label class="language">
				<Icon name="globe" size={16} />
				<select value={getLang()} onchange={(event) => setLang(event.currentTarget.value as Lang)} aria-label={t('settings.app_language')}>
					{#each LANGUAGES as language (language.code)}<option value={language.code}>{language.label}</option>{/each}
				</select>
			</label>
		</header>

		<div class="form-wrap">
			<h1>{t('login.title')}</h1>
			<p class="muted lead">{t('login.help')}</p>

			<form onsubmit={submit}>
				<label class="field">
					<span>{t('login.username')}</span>
					<input bind:value={username} autocomplete="username" autocapitalize="none" spellcheck="false" required placeholder="8a-07" />
				</label>
				<label class="field">
					<span>{t('login.password')}</span>
					<div class="password">
						<input type={showPassword ? 'text' : 'password'} bind:value={password} autocomplete="current-password" required />
						<button type="button" class="reveal" onclick={() => (showPassword = !showPassword)} aria-label={t('login.show_password')} aria-pressed={showPassword}>
							<Icon name="eye" size={20} />
						</button>
					</div>
				</label>
				{#if errorKey}<p class="error" role="alert"><Icon name="alert" size={18} />{t(errorKey)}</p>{/if}
				<button class="btn primary block submit" disabled={sending || !username || !password}>
					{#if sending}<span class="spinner" aria-hidden="true"></span>{t('loading')}{:else}{t('login.submit')}{/if}
				</button>
			</form>

			<ul class="trust mobile-trust">
				{#each TRUST as item (item.key)}
					<li><span class="trust-icon"><Icon name={item.icon} size={16} /></span>{t(item.key)}</li>
				{/each}
			</ul>
		</div>

		<p class="admin-note"><Icon name="shield" size={14} />{t('login.admin_note')}</p>
	</section>
</main>

<style>
	.screen {
		min-height: 100dvh;
		display: grid;
		grid-template-columns: 1fr;
		background: var(--bg);
	}

	/* Brand panel: always ink, in both themes, so it reads as the product's "cover". */
	.brand {
		display: none;
		--text: #e8edeb;
		--muted: #9aa6a1;
		position: relative;
		overflow: hidden;
		flex-direction: column;
		justify-content: space-between;
		gap: 40px;
		padding: 40px 48px;
		color: var(--text);
		background:
			radial-gradient(70% 55% at 15% 100%, rgb(63 193 176 / 0.28), transparent 70%),
			radial-gradient(60% 50% at 100% 0%, rgb(63 193 176 / 0.12), transparent 70%),
			#0b1311;
	}
	.brand::before {
		/* faint ruled-paper texture: a quiet nod to the exercise book */
		content: '';
		position: absolute;
		inset: 0;
		background-image: linear-gradient(rgb(255 255 255 / 0.035) 1px, transparent 1px);
		background-size: 100% 36px;
		mask-image: linear-gradient(to bottom, transparent, #000 30%, #000 70%, transparent);
		pointer-events: none;
	}
	.brand > * {
		position: relative;
	}
	.pitch h2 {
		font-size: 2.4rem;
		line-height: 1.1;
		letter-spacing: -0.035em;
		font-weight: 720;
		max-width: 14ch;
		margin: 0 0 14px;
	}
	.pitch p {
		color: var(--muted);
		font-size: 1.05rem;
		max-width: 34ch;
		margin: 0;
	}
	.trust {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 14px;
	}
	.trust li {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 0.95rem;
	}
	.trust-icon {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		background: rgb(63 193 176 / 0.14);
		border: 1px solid rgb(63 193 176 / 0.25);
		color: #6fd6c8;
		flex-shrink: 0;
	}
	.offline {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		margin: 0;
		font-size: 0.85rem;
		color: var(--muted);
	}

	/* Form side */
	.side {
		display: flex;
		flex-direction: column;
		min-height: 100dvh;
		padding: 0 20px;
	}
	.top {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 16px 0;
	}
	.language {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-left: auto;
		padding-left: 12px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--surface);
		color: var(--muted);
	}
	.language select {
		width: auto;
		min-height: 36px;
		padding: 4px 10px 4px 2px;
		border: 0;
		box-shadow: none;
		background: transparent;
		color: var(--text);
		font-size: 0.88rem;
		font-weight: 600;
	}
	.form-wrap {
		flex: 1;
		width: 100%;
		max-width: 380px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 32px 0;
	}
	h1 {
		font-size: 1.9rem;
		margin: 0 0 6px;
	}
	.lead {
		margin: 0 0 28px;
	}
	form {
		display: grid;
		gap: 2px;
	}
	.password {
		position: relative;
	}
	.password input {
		padding-right: 52px;
	}
	.reveal {
		position: absolute;
		top: 50%;
		right: 4px;
		transform: translateY(-50%);
		display: grid;
		place-items: center;
		width: 42px;
		height: 40px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--faint);
		cursor: pointer;
	}
	.reveal:hover,
	.reveal[aria-pressed='true'] {
		color: var(--text);
		background: var(--surface-2);
	}
	.submit {
		min-height: 50px;
		margin-top: 6px;
		font-size: 1rem;
	}
	.mobile-trust {
		margin-top: 32px;
		padding-top: 22px;
		border-top: 1px solid var(--line);
		gap: 12px;
	}
	.mobile-trust li {
		font-size: 0.86rem;
		color: var(--muted);
	}
	.mobile-trust .trust-icon {
		width: 30px;
		height: 30px;
		border-radius: 9px;
		background: var(--accent-softer);
		border-color: var(--accent-soft);
		color: var(--accent-strong);
	}
	.admin-note {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		font-size: 0.8rem;
		color: var(--faint);
		margin: 0;
		padding: 16px 0 calc(16px + env(safe-area-inset-bottom));
	}

	@media (min-width: 900px) {
		.screen {
			grid-template-columns: minmax(380px, 0.9fr) 1fr;
		}
		.brand {
			display: flex;
			position: sticky;
			top: 0;
			height: 100dvh;
		}
		.mobile-logo,
		.mobile-trust {
			display: none;
		}
		.side {
			padding: 0 40px;
		}
		.top {
			padding: 24px 0;
		}
	}
</style>
