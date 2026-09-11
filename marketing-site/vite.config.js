import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import { routes } from './src/site.mjs'

const staticRoutes = {
  name: 'static-page-routes',
  configurePreviewServer(server) {
    server.middlewares.use((req, res, next) => {
      const url = new URL(req.url, 'http://localhost')
      const path = url.pathname.replace(/\/$/, '') || '/'
      if (routes.includes(path) && path !== '/') req.url = `${path}/index.html${url.search}`
      next()
    })
  },
}

export default defineConfig({
  plugins: [tailwindcss(), staticRoutes],
  server: { host: '127.0.0.1', headers: { 'X-Robots-Tag': 'noindex, nofollow' } },
  preview: { host: '127.0.0.1', headers: { 'X-Robots-Tag': 'noindex, nofollow' } },
})
