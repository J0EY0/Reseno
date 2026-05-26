type ControlledCallback<Args extends unknown[]> = {
  (...args: Args): void
  cancel: () => void
  flush: () => void
}

export function createThrottledCallback<Args extends unknown[]>(
  callback: (...args: Args) => void,
  waitMs: number,
): ControlledCallback<Args> {
  let lastRunAt = 0
  let latestArgs: Args | null = null
  let timer: number | null = null

  const run = (args: Args) => {
    lastRunAt = Date.now()
    latestArgs = null
    callback(...args)
  }

  const throttled = ((...args: Args) => {
    latestArgs = args

    const remaining = waitMs - (Date.now() - lastRunAt)

    if (remaining <= 0) {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }

      run(args)
      return
    }

    if (timer !== null) {
      return
    }

    timer = window.setTimeout(() => {
      timer = null

      if (latestArgs) {
        run(latestArgs)
      }
    }, remaining)
  }) as ControlledCallback<Args>

  throttled.cancel = () => {
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }

    latestArgs = null
  }

  throttled.flush = () => {
    if (!latestArgs) {
      return
    }

    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }

    run(latestArgs)
  }

  return throttled
}
