import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { _electron, type ElectronApplication, type Page } from '@playwright/test'
import { expect, test } from '@playwright/test'

/**
 * E2E smoke tests for the built Hermes desktop app.
 *
 * These tests launch the real packaged Electron binary (produced by
 * `npm run pack` → `electron-builder --dir`) with:
 *   - HERMES_DESKTOP_BOOT_FAKE=1      — simulates boot progress without
 *                                       spawning a real Hermes backend
 *   - HERMES_DESKTOP_USER_DATA_DIR    — isolated electron userData
 *   - HERMES_DESKTOP_IGNORE_EXISTING=1 — forces the bootstrap path
 *   - HERMES_HOME                     — isolated throwaway directory
 *   - All credential env vars stripped
 *
 * The binary path is resolved per-platform to match electron-builder's
 * output layout.  On Windows CI the app is built with `npm run pack`
 * before these tests run.
 */

const DESKTOP_ROOT = path.resolve(import.meta.dirname, '..')
const RELEASE_ROOT = path.join(DESKTOP_ROOT, 'release')

const BINARY_PATH: string = (() => {
  const downloadsExe = path.join(os.homedir(), 'Downloads', 'Hermes-Setup.exe')

  if (fs.existsSync(downloadsExe)) {
    return downloadsExe
  }

  const platform = process.platform

  if (platform === 'darwin') {
    const arch = process.arch === 'arm64' ? 'arm64' : 'x64'

    return path.join(RELEASE_ROOT, `mac-${arch}`, 'Hermes.app', 'Contents', 'MacOS', 'Hermes')
  }

  if (platform === 'win32') {
    return path.join(RELEASE_ROOT, 'win-unpacked', 'Hermes.exe')
  }

  return path.join(RELEASE_ROOT, 'linux-unpacked', 'hermes')
})()

// Credential-suffix filter — matches test-desktop.mjs's isCredentialEnvVar.
const CREDENTIAL_SUFFIXES: string[] = [
  '_API_KEY',
  '_TOKEN',
  '_SECRET',
  '_PASSWORD',
  '_CREDENTIALS',
  '_ACCESS_KEY',
  '_PRIVATE_KEY',
  '_OAUTH_TOKEN',
]

const CREDENTIAL_NAMES = new Set([
  'ANTHROPIC_BASE_URL',
  'ANTHROPIC_TOKEN',
  'AWS_ACCESS_KEY_ID',
  'AWS_SECRET_ACCESS_KEY',
  'AWS_SESSION_TOKEN',
  'CUSTOM_API_KEY',
  'GEMINI_BASE_URL',
  'OPENAI_BASE_URL',
  'OPENROUTER_BASE_URL',
  'OLLAMA_BASE_URL',
  'GROQ_BASE_URL',
  'XAI_BASE_URL',
])

function isCredentialEnvVar(name: string): boolean {
  if (CREDENTIAL_NAMES.has(name)) {return true}

  return CREDENTIAL_SUFFIXES.some((suffix) => name.endsWith(suffix))
}

function buildSandboxEnv(): { env: Record<string, string>; sandbox: string } {
  const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-e2e-'))
  const userDataDir = path.join(sandbox, 'electron-user-data')
  const hermesHome = path.join(sandbox, 'hermes-home')
  fs.mkdirSync(userDataDir, { recursive: true })
  fs.mkdirSync(hermesHome, { recursive: true })

  // Strip credentials, inject sandboxed env.
  const env: Record<string, string> = {}

  for (const [key, value] of Object.entries(process.env)) {
    if (!value) {continue}

    if (isCredentialEnvVar(key)) {continue}
    env[key] = value
  }

  // Fake boot: simulates progress steps without spawning the real backend.
  env.HERMES_DESKTOP_BOOT_FAKE = '1'
  env.HERMES_DESKTOP_BOOT_FAKE_STEP_MS = '120'
  // Force bootstrap path even if a hermes install exists on the runner.
  env.HERMES_DESKTOP_IGNORE_EXISTING = '1'
  // Isolate electron's userData and HERMES_HOME to the sandbox.
  env.HERMES_DESKTOP_USER_DATA_DIR = userDataDir
  env.HERMES_HOME = hermesHome
  // Clear any dev-server override — we want the packaged renderer, not vite.
  delete env.HERMES_DESKTOP_DEV_SERVER
  delete env.HERMES_DESKTOP_HERMES
  delete env.HERMES_DESKTOP_HERMES_ROOT

  return { env, sandbox }
}

let app: ElectronApplication
let page: Page
let sandbox: string

test.beforeAll(async () => {
  test.skip(
    !fs.existsSync(BINARY_PATH),
    `Built app binary not found: ${BINARY_PATH}. Run 'npm run pack' first.`
  )

  const { env, sandbox: dir } = buildSandboxEnv()
  sandbox = dir

  app = await _electron.launch({
    executablePath: BINARY_PATH,
    args: ['--disable-gpu', '--no-sandbox', '--disable-software-rasterizer'],
    env,
  })

  page = await app.firstWindow()
})

test.afterAll(async () => {
  await app?.close().catch(() => undefined)

  try {
    if (sandbox) {fs.rmSync(sandbox, { recursive: true, force: true })}
  } catch {
    // best-effort cleanup
  }
})

test('window opens with the Hermes title', async () => {
  // The main.cjs sets the window title to APP_NAME ('Hermes') during
  // createBrowserWindow.  Verify it before anything else.
  const title = await page.title()
  expect(title).toContain('Hermes')
})

test('renderer loads and shows DOM content', async () => {
  // Wait for the React root to mount.  The app renders into #root
  // (see src/main.tsx).  Give it a generous timeout for cold boot on CI.
  await page.waitForSelector('#root', { state: 'attached', timeout: 30_000 })

  // The root should have children after React hydrates — the boot overlay
  // or the main app shell.
  const childCount = await page.locator('#root > *').count()
  expect(childCount).toBeGreaterThan(0)
})

test('boot progress overlay fades out or shows error state', async () => {
  // With BOOT_FAKE mode the app simulates boot progress steps.  Without a
  // real backend, boot will eventually fail — the app shows a
  // BootFailureOverlay.  Either outcome (success → overlay disappears,
  // failure → error overlay renders) proves the renderer is working.
  //
  // Wait for one of:
  //   (a) the boot overlay disappears (renderer.ready), OR
  //   (b) an error message becomes visible (boot failure path)
  //
  // Use a waitForFunction so we don't depend on specific CSS selectors
  // that might change between refactors.
  await page.waitForFunction(
    () => {
      const root = document.getElementById('root')

      if (!root) {return false}
      const text = root.textContent ?? ''

      // Error path: boot failure overlay renders an error message.
      if (text.includes('error') || text.includes('Error') || text.includes('failed')) {
        return true
      }

      // Success path: overlay disappears and the app renders.  Look for
      // a chat input, sidebar, or settings gear as indicators.
      // If there's no "boot" / "starting" / "installing" text visible,
      // boot has completed (either to the main UI or to onboarding).
      const bootIndicators = ['starting', 'resolving', 'spawning', 'waiting', 'installing']
      const lower = text.toLowerCase()

      return !bootIndicators.some((word) => lower.includes(word))
    },
    { timeout: 60_000 }
  )
})

test('can capture a screenshot for the CI artifact', async () => {
  // This doubles as both a sanity check (page is renderable) and a
  // useful CI artifact — the screenshot is attached to the test report.
  const screenshot = await page.screenshot()
  expect(screenshot.byteLength).toBeGreaterThan(0)
})
