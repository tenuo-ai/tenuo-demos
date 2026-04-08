# Tenuo Demos

Open source demos showing how [Tenuo](https://tenuo.ai) protects AI agents with cryptographic capability tokens.

## Demos

| Demo | What it shows |
|------|--------------|
| [**Invoice Processing**](invoice-processing/) | A multi-agent pipeline processes invoices. A prompt injection redirects a payment to the wrong bank account. Traditional auth (OAuth, RBAC, policy engines) all approve. Tenuo blocks it. |
| [**Skyvern Prompt Injection**](skyvern-prompt-injection/) | An AI shopping agent browses an e-commerce store. A hidden prompt injection tricks it into buying a terrible product. Tenuo's warrant constraints block the bad purchase — the LLM is compromised but the outcome isn't. |

## What is Tenuo?

AI agents need access to production systems — databases, APIs, payment processors. Traditional authorization (OAuth scopes, RBAC roles, policy engines) answers **"is this agent allowed to do this?"** The answer is yes. The problem is that's the wrong question.

Tenuo issues **cryptographic capability tokens** that answer a different question: **"what should this agent be doing right now, with these specific arguments, for how long?"** The token carries per-argument constraints derived from the task context and is enforced in microseconds with no network round-trip.

- **Open source core**: [github.com/tenuo-ai/tenuo](https://github.com/tenuo-ai/tenuo)
- **Integrations**: LangGraph, LangChain, CrewAI, OpenAI, MCP, Google ADK, Temporal
- **Cloud dashboard**: [cloud.tenuo.ai](https://cloud.tenuo.ai)
- **Early access**: [tenuo.ai/early-access.html](https://tenuo.ai/early-access.html)

## License

MIT
