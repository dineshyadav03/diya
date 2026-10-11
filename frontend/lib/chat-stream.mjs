// Reading a chat reply as it is written (docs/STREAMING_DESIGN.md). The API's POST /api/chat/stream answers with one JSON object per line:
//   {"type":"start","thread_id":7,"message_id":12}     the chat the message is in
//   {"type":"delta","text":"Hey "}                      the next piece of the reply
//   {"type":"reset"}                                    the text so far was only a preface to a tool: throw it away
//   {"type":"tool","name":"get_weather"}                a tool is running
//   {"type":"wait"}                                     still working (so a model that is slow to load does not look like a dead connection)
//   {"type":"done","thread_id":7,"answer":"...","tools_called":[],"message_id":12,"reading":false}   exactly what /api/chat returns
//   {"type":"error","status":503,"detail":"...","thread_id":7}     it could not be answered; the message was kept
// This file is browser code (nothing here knows an address or a token) and plain enough to be run under Node by the tests.

// Read `body` (a ReadableStream of bytes) to its end and return the `done` event. `handlers` may have onStart, onDelta, onReset, onTool and onWait, each given the event; and onError,
// given the error event (or, for a stream that simply ended too soon, { status: undefined }) just before this throws, so the caller can say why. Throws Error('chat stream failed') in
// both cases, and also for a line that is not JSON.
export async function readChatStream(body, handlers = {}) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finished = null
  const fail = (event) => {
    handlers.onError?.(event)
    throw new Error('chat stream failed')
  }
  const handle = (line) => {
    if (!line.trim()) return
    let event
    try {
      event = JSON.parse(line)
    } catch {
      fail({ status: undefined })
    }
    if (!event || typeof event !== 'object') fail({ status: undefined })
    if (event.type === 'start') handlers.onStart?.(event)
    else if (event.type === 'delta') {
      if (typeof event.text === 'string') handlers.onDelta?.(event.text)
    } else if (event.type === 'reset') handlers.onReset?.(event)
    else if (event.type === 'tool') handlers.onTool?.(event)
    else if (event.type === 'wait') handlers.onWait?.(event)
    else if (event.type === 'done') finished = event
    else if (event.type === 'error') fail(event)
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: !done })
    let newline
    while ((newline = buffer.indexOf('\n')) >= 0) {
      handle(buffer.slice(0, newline))
      buffer = buffer.slice(newline + 1)
    }
    if (done) break
  }
  handle(buffer)
  if (!finished) fail({ status: undefined })
  return finished
}
