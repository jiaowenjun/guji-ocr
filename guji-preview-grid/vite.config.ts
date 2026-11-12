import fs from 'node:fs'
import path from 'node:path'
import { execFile } from 'node:child_process'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, type Plugin, type Connect, type ViteDevServer } from 'vite'

const ANNOTATIONS_DIR = path.resolve(__dirname, '../kangxi-gold/annotations')
const REPO = path.resolve(__dirname, '..')
const PAGE_TOOL = path.join(REPO, 'scripts', 'kangxi_page_tool.py')

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

// 「添加新页」/页标签：桥接 scripts/kangxi_page_tool.py（数据优先 sqlite，缺则由
// 爬取脚本增量补抓）。子进程最长 10 分钟（含站点限速），stdout 末行是 JSON。
function datasetPageTool(): Plugin {
  // 此处 connect 类型的 res 即 NextHandleFunction 的第二参（有 statusCode/setHeader/end）
  const run = (args: string[], res: { statusCode: number; setHeader(k: string, v: string): void; end(body: string): void }) => {
    execFile(
      'python3',
      [PAGE_TOOL, ...args],
      { cwd: REPO, timeout: 600_000, maxBuffer: 16 * 1024 * 1024 },
      (err, stdout) => {
        const lastLine = stdout.trim().split('\n').pop() ?? ''
        let payload: unknown
        try {
          payload = JSON.parse(lastLine)
        } catch {
          payload = { ok: false, error: err ? String(err.message) : `输出无法解析：${lastLine.slice(0, 200)}` }
        }
        const ok = !err && (payload as { ok?: boolean }).ok !== false
        res.statusCode = ok ? 200 : 400
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify(payload))
      },
    )
  }
  const handle: Connect.NextHandleFunction = (req, res, next) => {
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
      let args: string[] | null = null
      try {
        const { action, page, status } = JSON.parse(body) as {
          action?: unknown
          page?: unknown
          status?: unknown
        }
        const pageOk = /^\d{1,4}$/.test(String(page))
        if (action === 'add' && pageOk) {
          args = ['add', '--page', String(page)]
        } else if (action === 'status' && pageOk && typeof status === 'string' && /^[a-z]+$/.test(status)) {
          args = ['status', '--page', String(page), '--to', status]
        }
      } catch {
        args = null
      }
      if (!args) {
        res.statusCode = 400
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify({ ok: false, error: '请求体应为 { action: add|status, page, status? }' }))
        return
      }
      run(args, res)
    })
  }
  return {
    name: 'dataset-page-tool',
    apply: 'serve',
    configureServer(server: ViteDevServer) {
      // 单挂载点：Connect 会剥离挂载前缀，多端点靠 body.action 区分
      server.middlewares.use('/dataset/page-tool', handle)
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
    datasetPageTool(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
