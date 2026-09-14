# AI development log

Tool: Codex, used interactively to interpret the brief, write the script and tests, and review behavior.

This log records the actual conversation prompts and the relevant assignment context. It does not invent a separate prompt history.

## Parallel fetching and error handling

Initial user prompt (formatting normalized):

> we have an assignment for an ai intern role at yellow.ai First, tell me what you understood from the pdf. mention all the givens and requirements. then discuss what tech stack we can use, and the plan of action

The attached assignment supplied these instructions as task context:

> You must trigger these API calls concurrently (e.g., Promise.all in JS or asyncio.gather in Python), not one by one.

> Your script must handle the InvalidCity123 case. The error for that city should be logged, but the script must not crash—it should finish processing the other valid cities.

Implementation prompt after discussing and accepting the Python approach:

> Great start the work and build this end to end

Result: a shared `httpx.AsyncClient`, `asyncio.gather` over per-order tasks, and local handling of HTTP failures, timeouts, connection errors, and malformed responses. HTTP request URLs and exception strings containing keys are not logged. Successful results are saved even if another city fails.

Validation: a synchronization-barrier test proves that all four requests enter the transport before any can complete. Separate tests cover a failed city alongside a successful delayed order, network failures, response validation, and persistence.

## Weather-aware apology

User prompt:

> Sounds good, how are you going to do the apology

Result: an AI-assisted deterministic function uses the first name, city, and weather description. The user accepted this approach before implementation. The function is called only for the three delay conditions. Missing descriptions use a neutral condition-based fallback without inventing severity.

No runtime LLM is called. The PDF asks for an AI tool to help write the function; the implementation follows that interpretation. No customer messages are sent externally.
