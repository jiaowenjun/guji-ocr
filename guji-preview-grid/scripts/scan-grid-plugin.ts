import { execFile } from 'node:child_process'
import path from 'node:path'
import type { Plugin } from 'vite'

/** 独立测量原图；不读取草稿占格，不写标注，不依赖预先导出的 OCR 数据集。 */
export function scanGridPlugin(repo: string): Plugin {
  return {
    name: 'dataset-scan-grid',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/dataset/scan-grid', (req, res, next) => {
        if (req.method !== 'POST') return next()
        let body = ''
        let tooLarge = false
        req.setEncoding('utf8')
        req.on('data', (chunk: string) => {
          if (tooLarge) return
          body += chunk
          if (body.length > 65536) {
            tooLarge = true
            res.writeHead(413, { 'content-type': 'application/json' })
            res.end(JSON.stringify({ ok: false, error: '字格行位请求过大' }))
          }
        })
        req.on('end', () => {
          if (tooLarge) return
          const child = execFile('python3', [path.join(repo, 'tools/dataset/scan_grid.py')],
            { cwd: repo, timeout: 30_000, maxBuffer: 1024 * 1024 }, (error, stdout) => {
              if (res.destroyed) return
              let result: { ok?: boolean; error?: string }
              try {
                result = JSON.parse(stdout)
              } catch {
                result = { ok: false, error: error?.message ?? '原图字格定位结果无法解析' }
              }
              res.writeHead(!error && result.ok ? 200 : 400, {
                'content-type': 'application/json', 'cache-control': 'no-store',
              })
              res.end(JSON.stringify(result))
            })
          // 切页、关闭开关或继续编辑时终止过期计算。
          res.on('close', () => { if (!res.writableEnded) child.kill() })
          child.stdin?.on('error', () => { /* 进程启动失败/退出由 execFile 回调报告。 */ })
          child.stdin?.end(body)
        })
      })
    },
  }
}
