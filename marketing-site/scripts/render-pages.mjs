import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { page, routes, escape } from '../src/site.mjs'

const template = await readFile('dist/index.html', 'utf8')
for (const route of [...routes, '/404']) {
  const p = page(route)
  const html = template.replace(/<title>.*?<\/title>/s, `<title>${escape(p.title)}</title>`)
    .replace(/<meta name="description" content="[^"]*"\s*\/?>/, `<meta name="description" content="${escape(p.description)}">`)
    .replace('<div id="root"></div>', `<div id="root">${p.html}</div>`)
  const dir = route === '/' ? 'dist' : join('dist', route.slice(1))
  await mkdir(dir, {recursive:true})
  await writeFile(join(dir, 'index.html'), html)
}
console.log(`Rendered ${routes.length} pages plus 404; noindex enabled; no public domain configured.`)
