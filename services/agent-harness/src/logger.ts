/**
 * Logger for the MCP evaluation server
 *
 * Console output is unconditional. The log FILE is opt-in via HARNESS_LOG_FILE.
 *
 * Why the file sink is off by default
 * -----------------------------------
 * createLogFile() used to run in the Logger constructor, which runs at module
 * load, so every server start minted a fresh logs/server_<timestamp>.log that
 * was never rotated, capped, or pruned. `npm run dev` is `tsx watch`, which
 * restarts the process on every file change, so an editing session left one
 * file per restart (13 were created in 23 seconds on 2026-09-06).
 *
 * Combined with verbose() below -- which wrote the entire accumulated
 * messages[] on every LLM call, so turn N logged all N turns and the file grew
 * O(n^2) in turns -- that reached 1.8 GB across 31 files, one of them 734 MB
 * from 1108 lines.
 *
 * Nothing reads these files. run_all.sh already redirects the harness's stdout
 * to $LOGDIR/harness.log, and `make run-harness` prints to the terminal, so the
 * console stream is the durable record either way.
 *
 * To get file logging back for a debugging session:
 *   HARNESS_LOG_FILE=1                  info/warn/error to file
 *   HARNESS_LOG_FILE=1 LOG_LEVEL=debug  the above plus full verbose payloads
 *
 * verbose() needs both switches on purpose: it is the one that grows
 * quadratically, so it should never come back on by accident.
 */

import * as fs from 'fs'
import * as path from 'path'

type LogLevel = 'info' | 'warn' | 'error' | 'debug'

const FILE_LOGGING = /^(1|true|yes|on)$/i.test(process.env.HARNESS_LOG_FILE ?? '')

let fileStream: fs.WriteStream | null = null
let fileSinkDisabled = false

/**
 * Open the log file on first write rather than at import.
 *
 * Lazy on purpose: a process that imports the logger but never logs (a helper
 * module pulled in by a script, say) leaves no file behind at all.
 */
function getFileStream(): fs.WriteStream | null {
  if (!FILE_LOGGING || fileSinkDisabled) return null
  if (fileStream) return fileStream
  try {
    const logsDir = path.join(process.cwd(), 'logs')
    if (!fs.existsSync(logsDir)) {
      fs.mkdirSync(logsDir, { recursive: true })
    }
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const logPath = path.join(logsDir, `server_${timestamp}.log`)
    console.log(`[LOGGER] Writing server logs to: ${logPath}`)
    fileStream = fs.createWriteStream(logPath, { flags: 'a' })
    return fileStream
  } catch (err) {
    // A logging failure must never take the eval server down with it. Disable
    // the sink, say so once, and carry on writing to the console.
    fileSinkDisabled = true
    console.warn('[LOGGER] file logging disabled (could not open log file):', err)
    return null
  }
}

class Logger {
  constructor(private level: LogLevel = 'info') {}

  private log(level: LogLevel, message: string, meta?: any) {
    const timestamp = new Date().toISOString()
    const logMessage = `[${timestamp}] [${level.toUpperCase()}] ${message}`

    // Write to console (compact for readability)
    if (meta) {
      console.log(logMessage, meta)
    } else {
      console.log(logMessage)
    }

    // Write to file (full detail) -- no-op unless HARNESS_LOG_FILE is set
    const stream = getFileStream()
    if (stream) {
      const fileLine = meta
        ? `${logMessage} ${JSON.stringify(meta)}\n`
        : `${logMessage}\n`
      stream.write(fileLine)
    }
  }

  info(message: string, meta?: any) {
    this.log('info', message, meta)
  }

  warn(message: string, meta?: any) {
    this.log('warn', message, meta)
  }

  error(message: string, meta?: any) {
    this.log('error', message, meta)
  }

  debug(message: string, meta?: any) {
    if (this.level === 'debug') {
      this.log('debug', message, meta)
    }
  }

  /**
   * Write to the log file only (skip console). Use for large payloads.
   *
   * Requires HARNESS_LOG_FILE *and* LOG_LEVEL=debug -- see the header note on
   * quadratic growth. Callers pass the object itself, not a pre-stringified
   * one: this method serialises exactly once.
   */
  verbose(message: string, meta?: any) {
    if (this.level !== 'debug') return
    const stream = getFileStream()
    if (!stream) return
    const timestamp = new Date().toISOString()
    const logMessage = `[${timestamp}] [VERBOSE] ${message}`
    const fileLine = meta
      ? `${logMessage} ${JSON.stringify(meta)}\n`
      : `${logMessage}\n`
    stream.write(fileLine)
  }

  /** True when a log file is actually being written. Used for the startup banner. */
  get fileLoggingEnabled(): boolean {
    return FILE_LOGGING
  }
}

export const logger = new Logger(
  (process.env.LOG_LEVEL as LogLevel) || 'info'
)
