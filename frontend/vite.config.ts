import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// vite-plugin-pwa is not used: browsers only register a service worker over HTTPS (or on
// localhost), and phones reach the school server over plain HTTP on the LAN.
// It comes back with the HTTPS option (SYSTEM_DESIGN C8).
export default defineConfig({
	plugins: [
		sveltekit({
			// Single-page app: FastAPI serves index.html for every non-API path.
			adapter: adapter({ fallback: 'index.html' }),
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			}
		})
	],
	server: {
		// `npm run dev` talks to the API on this machine.
		proxy: { '/api': 'http://127.0.0.1:8000' }
	}
});
