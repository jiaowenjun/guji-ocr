import fs from 'node:fs'
import path from 'node:path'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, type Plugin, type Connect, type ViteDevServer } from 'vite'

const ANNOTATIONS_DIR = path.resolve(__dirname, '../kangxi-gold/annotations')

// 数据集对照页的保存回写：POST /dataset/save { page, content }
// 仅 dev 生效（configureServer 只在 dev server 运行）；写回目标限定在
// kangxi-gold/annotations/ 内已存在的 NNNN.gj，且内容首行必须仍是 @同页码。
function datasetSave(): Plugin {
  const handler: Connect.NextHandleFunction = (req, res, next) => {
    if (req.method !== 'POST') {
      next()
      return
    }
    let body = ''
    req.setEncoding('utf8')
    req.on('data', (chunk: string) => {
      body += chunk
    })
    req.on('end', () => {
      const send = (status: number, payload: unknown) => {
        res.statusCode = status
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify(payload))
      }
      try {
        const { page, content } = JSON.parse(body) as { page?: unknown; content?: unknown }
        const stem = /^\d{3,4}$/.test(String(page)) ? String(page).padStart(4, '0') : ''
        const file = stem ? path.join(ANNOTATIONS_DIR, `${stem}.gj`) : ''
        if (!file || path.dirname(file) !== ANNOTATIONS_DIR || !fs.existsSync(file)) {
          throw new Error(`页码不在数据集内：${String(page)}`)
        }
        const text = String(content ?? '')
        const firstLine = text.split('\n').map((l) => l.trim()).find((l) => l.length > 0) ?? ''
        if (firstLine !== `@${Number(stem)}`) {
          throw new Error(`内容首行应为 @${Number(stem)}，实际是 ${firstLine.slice(0, 20) || '(空)'}`)
        }
        fs.writeFileSync(file, text, 'utf8')
        send(200, { ok: true, path: file })
      } catch (err) {
        send(400, { ok: false, error: err instanceof Error ? err.message : String(err) })
      }
    })
  }

  return {
    name: 'dataset-save',
    apply: 'serve',
    configureServer(server: ViteDevServer) {
      server.middlewares.use('/dataset/save', handler)
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
    datasetSave(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
