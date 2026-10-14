<script lang="ts" generics="T extends string">
	import type { Snippet } from 'svelte';
	import { LANGUAGES, getLang, setLang, t, type Lang } from '#lib/i18n/index.svelte.js';
	import { logout, session } from '#lib/session.svelte.js';
	import Icon from './Icon.svelte';
	import Logo from './Logo.svelte';

	// Teacher and admin layout: a sidebar on laptops, a scrolling tab strip on phones.
	let {
		role,
		items,
		current,
		onselect,
		title,
		subtitle = '',
		actions,
		children
	}: {
		role: string;
		items: { id: T; icon: string; label: string; count?: number }[];
		current: T;
		onselect: (id: T) => void;
		title: string;
		subtitle?: string;
		actions?: Snippet;
		children: Snippet;
	} = $props();
</script>

<div class="console">
	<aside class="side no-print">
		<div class="brand">
			<Logo size={32} />
			<div><strong>{t('app.name')}</strong><span>{role}</span></div>
		</div>
		<nav aria-label={role}>
			{#each items as item (item.id)}
				<button class="nav" aria-current={item.id === current ? 'page' : undefined} onclick={() => onselect(item.id)}>
					<Icon name={item.icon} size={19} />
					<span class="grow">{item.label}</span>
					{#if item.count}<span class="count tabular">{item.count}</span>{/if}
				</button>
			{/each}
		</nav>
		<div class="foot">
			<p class="offline"><span class="status-dot"></span>{t('app.offline_badge')}</p>
			<div class="me">
				<span class="avatar" aria-hidden="true">{(session.me?.username ?? '?').slice(0, 2).toUpperCase()}</span>
				<span class="grow"><strong>{session.me?.username}</strong><small>{role}</small></span>
				<button class="btn ghost small icon" onclick={logout} aria-label={t('logout')} title={t('logout')}><Icon name="logout" size={18} /></button>
			</div>
			<label class="language">
				<Icon name="globe" size={16} />
				<select value={getLang()} onchange={(event) => setLang(event.currentTarget.value as Lang)} aria-label={t('settings.app_language')}>
					{#each LANGUAGES as language (language.code)}<option value={language.code}>{language.label}</option>{/each}
				</select>
			</label>
		</div>
	</aside>
	<div class="content">
		<header class="top no-print">
			<div class="grow">
				<p class="eyebrow">{role}</p>
				<h1>{title}</h1>
				{#if subtitle}<p class="muted subtitle">{subtitle}</p>{/if}
			</div>
			{#if actions}<div class="actions">{@render actions()}</div>{/if}
			<button class="btn ghost small icon mobile-logout" onclick={logout} aria-label={t('logout')}><Icon name="logout" size={18} /></button>
		</header>
		<main>{@render children()}</main>
	</div>
</div>

<style>
	.console {
		min-height: 100dvh;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
	}
	.side {
		position: sticky;
		top: 0;
		z-index: 10;
		background: color-mix(in srgb, var(--surface) 92%, transparent);
		backdrop-filter: saturate(1.4) blur(14px);
		-webkit-backdrop-filter: saturate(1.4) blur(14px);
		border-bottom: 1px solid var(--line);
		padding: 10px 12px 8px;
		display: grid;
		gap: 8px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.brand div {
		display: grid;
		line-height: 1.2;
	}
	.brand strong {
		font-weight: 700;
		letter-spacing: -0.02em;
	}
	.brand div span {
		font-size: 0.76rem;
		color: var(--muted);
	}
	nav {
		display: flex;
		gap: 4px;
		min-width: 0;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.nav {
		display: flex;
		align-items: center;
		gap: 9px;
		min-height: 38px;
		padding: 0 12px;
		border: 0;
		border-radius: 9px;
		background: transparent;
		color: var(--muted);
		font-weight: 550;
		font-size: 0.92rem;
		cursor: pointer;
		white-space: nowrap;
		text-align: left;
		transition:
			background 0.15s,
			color 0.15s;
	}
	.nav:hover {
		background: var(--surface-2);
		color: var(--text);
	}
	.nav[aria-current='page'] {
		background: var(--surface-2);
		color: var(--text);
		font-weight: 650;
		box-shadow: inset 0 0 0 1px var(--line);
	}
	.nav[aria-current='page'] :global(svg) {
		color: var(--accent-strong);
	}
	.count {
		min-width: 22px;
		padding: 1px 7px;
		border-radius: 999px;
		background: var(--warm);
		color: #fff;
		font-size: 0.72rem;
		font-weight: 700;
		text-align: center;
	}
	.foot {
		display: none;
	}
	.content {
		min-width: 0;
	}
	.top {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 12px;
		padding: 20px 16px 6px;
	}
	.top h1 {
		margin: 2px 0 0;
		font-size: 1.6rem;
	}
	.subtitle {
		margin: 4px 0 0;
		font-size: 0.92rem;
	}
	.actions {
		display: flex;
		gap: 8px;
		align-items: center;
		min-width: 0;
	}
	.actions :global(.btn) {
		white-space: normal;
		text-align: center;
	}
	main {
		padding: 14px 16px 48px;
	}
	@media (min-width: 900px) {
		.console {
			grid-template-columns: 256px minmax(0, 1fr);
		}
		.side {
			height: 100dvh;
			border-bottom: 0;
			border-right: 1px solid var(--line);
			background: var(--surface);
			padding: 20px 12px 14px;
			grid-template-rows: auto 1fr auto;
			gap: 22px;
		}
		.brand {
			padding: 0 8px;
		}
		nav {
			flex-direction: column;
			overflow: visible;
			gap: 2px;
		}
		.nav {
			min-height: 40px;
			padding: 0 10px;
		}
		.foot {
			display: grid;
			gap: 10px;
		}
		.offline {
			display: flex;
			align-items: center;
			gap: 10px;
			margin: 0;
			padding: 8px 12px;
			border-radius: 10px;
			background: var(--bg);
			border: 1px solid var(--line);
			font-size: 0.8rem;
			font-weight: 600;
			color: var(--muted);
		}
		.me {
			display: flex;
			align-items: center;
			gap: 10px;
			padding: 10px 4px 0 8px;
			border-top: 1px solid var(--line);
		}
		.me strong {
			display: block;
			font-size: 0.9rem;
			font-weight: 650;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		.me small {
			display: block;
			color: var(--muted);
			font-size: 0.76rem;
		}
		.avatar {
			display: grid;
			place-items: center;
			width: 34px;
			height: 34px;
			border-radius: 50%;
			background: var(--accent-soft);
			color: var(--accent-strong);
			font-size: 0.76rem;
			font-weight: 700;
			flex-shrink: 0;
		}
		.language {
			display: flex;
			align-items: center;
			gap: 6px;
			padding-left: 10px;
			border: 1px solid var(--line);
			border-radius: 10px;
			color: var(--muted);
		}
		.language select {
			min-height: 36px;
			border: 0;
			box-shadow: none;
			background: transparent;
			padding: 4px 8px 4px 0;
			font-size: 0.86rem;
		}
		.mobile-logout {
			display: none;
		}
		.top {
			padding: 32px 40px 8px;
		}
		.top h1 {
			font-size: 1.85rem;
		}
		main {
			padding: 16px 40px 56px;
			max-width: 1200px;
		}
	}
</style>
