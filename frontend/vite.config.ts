import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
	plugins: [
		VitePWA({
			registerType: 'autoUpdate',
			strategies: 'generateSW',
			devOptions: { enabled: false },
			workbox: { navigateFallback: '/index.html' },
			manifest: {
				name: 'RuralMinds',
				short_name: 'RuralMinds',
				start_url: '/',
				display: 'standalone',
				background_color: '#ffffff',
				icons: []
			}
		}),
		sveltekit({
			adapter: adapter({ fallback: 'index.html' }),
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			}
		})
	]
});
