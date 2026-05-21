import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version?: string }
const buildTime = new Date().toISOString()

const getPackageName = (id: string): string | null => {
  const normalizedId = id.split(path.sep).join('/')
  const marker = '/node_modules/'
  const markerIndex = normalizedId.lastIndexOf(marker)
  if (markerIndex === -1) {
    return null
  }

  const packagePath = normalizedId.slice(markerIndex + marker.length)
  const [firstPart, secondPart] = packagePath.split('/')
  if (!firstPart) {
    return null
  }
  return firstPart.startsWith('@') && secondPart ? `${firstPart}/${secondPart}` : firstPart
}

const markdownPackages = new Set([
  'bail',
  'ccount',
  'character-entities',
  'character-entities-html4',
  'character-entities-legacy',
  'comma-separated-tokens',
  'decode-named-character-reference',
  'dequal',
  'devlop',
  'entities',
  'extend',
  'hast-util-whitespace',
  'html-url-attributes',
  'longest-streak',
  'markdown-table',
  'property-information',
  'react-markdown',
  'remark-gfm',
  'space-separated-tokens',
  'stringify-entities',
  'trim-lines',
  'trough',
  'unified',
  'vfile',
  'vfile-message',
  'zwitch',
])

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_PACKAGE_VERSION__: JSON.stringify(packageJson.version ?? '0.0.0'),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  server: {
    host: '0.0.0.0',  // 允许公网访问
    port: 5173,       // 默认端口
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 打包输出到项目根目录的 static 文件夹
    outDir: path.resolve(__dirname, '../../static'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          const packageName = getPackageName(id)
          if (!packageName) {
            return undefined
          }

          if (packageName === 'react' || packageName === 'react-dom' || packageName === 'scheduler') {
            return 'vendor-react'
          }
          if (packageName === 'react-router' || packageName === 'react-router-dom') {
            return 'vendor-router'
          }
          if (packageName === 'recharts' || packageName.startsWith('d3-')) {
            return 'vendor-charts'
          }
          if (
            packageName === 'motion'
            || packageName === 'motion-dom'
            || packageName === 'motion-utils'
            || packageName === 'framer-motion'
          ) {
            return 'vendor-motion'
          }
          if (
            packageName.startsWith('micromark')
            || packageName.startsWith('mdast-')
            || packageName.startsWith('hast-')
            || packageName.startsWith('unist-')
            || markdownPackages.has(packageName)
          ) {
            return 'vendor-markdown'
          }
          if (packageName === 'lucide-react' || packageName === '@remixicon/react') {
            return 'vendor-icons'
          }
          return undefined
        },
      },
    },
  },
})
