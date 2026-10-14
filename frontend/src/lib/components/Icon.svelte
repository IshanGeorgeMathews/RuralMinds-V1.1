<script lang="ts" module>
	// Simple line icons drawn for this app (24x24, 2px stroke). Bundled, never downloaded.
	const PATHS: Record<string, string> = {
		book: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5zM4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5',
		chat: 'M4 5h16v11H9l-5 4z',
		settings:
			'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1-2 2-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21h-3v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1-2-2 .1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3v-3h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1 2-2 .1.1a1.7 1.7 0 0 0 1.8.3H8a1.7 1.7 0 0 0 1-1.5V3h3v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1 2 2-.1.1a1.7 1.7 0 0 0-.3 1.8V8a1.7 1.7 0 0 0 1.5 1H21v3h-.1a1.7 1.7 0 0 0-1.5 1z',
		send: 'M4 12l16-8-6 16-3-7z',
		stop: 'M7 7h10v10H7z',
		plus: 'M12 5v14M5 12h14',
		chevronDown: 'M6 9l6 6 6-6',
		chevronRight: 'M9 6l6 6-6 6',
		chevronLeft: 'M15 6l-6 6 6 6',
		close: 'M6 6l12 12M18 6L6 18',
		check: 'M5 12l5 5 9-10',
		copy: 'M9 9h11v11H9zM5 15V4h11',
		upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
		inbox: 'M4 13l2-8h12l2 8v6H4zM4 13h5l1 2h4l1-2h5',
		chart: 'M4 20V10M10 20V4M16 20v-8M22 20H2',
		users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a6 6 0 0 1 12 0v1M16 3.5a4 4 0 0 1 0 7M22 21v-1a6 6 0 0 0-4-5.7',
		shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
		refresh: 'M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4',
		pause: 'M8 5h3v14H8zM13 5h3v14h-3z',
		play: 'M7 5l12 7-12 7z',
		trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
		lightbulb: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z',
		list: 'M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01',
		globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18',
		text: 'M4 7V5h16v2M12 5v14M9 19h6',
		moon: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z',
		logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11',
		page: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6',
		sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z',
		question: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01',
		story: 'M4 4h7a3 3 0 0 1 3 3v13a2.5 2.5 0 0 0-2.5-2.5H4zM20 4h-5a3 3 0 0 0-3 3v13a2.5 2.5 0 0 1 2.5-2.5H20z',
		quiz: 'M9 11l2 2 4-4M5 4h14v16H5z',
		simpler: 'M4 12h16M4 6h10M4 18h7',
		wifiOff: 'M2 2l20 20M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 5-2.8M19 13a10 10 0 0 0-2.4-1.8M2 8.8a15 15 0 0 1 4.2-2.6M12 20h.01',
		wifi: 'M5 13a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0M2 8.8a15 15 0 0 1 20 0M12 20h.01',
		home: 'M3 11l9-7 9 7v9h-6v-6H9v6H3z',
		pencil: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
		eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
		printer: 'M7 9V3h10v6M7 17H4v-7h16v7h-3M7 14h10v7H7z',
		search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5',
		server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
		alert: 'M12 3l10 18H2zM12 10v4M12 18h.01'
	};
	export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
	let { name, size = 22, label = '' }: { name: string; size?: number; label?: string } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	role={label ? 'img' : undefined}
	aria-label={label || undefined}
	aria-hidden={label ? undefined : 'true'}
>
	<path d={PATHS[name] ?? PATHS.question} />
</svg>
