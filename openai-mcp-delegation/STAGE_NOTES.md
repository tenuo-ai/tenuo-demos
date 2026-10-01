# Stage notes

Target: a short builder demo, not a survey of authorization systems.

## Narrative

1. **Begin with the workflow builders already write.** An operator asks an
   orchestrator to investigate checkout latency. The orchestrator uses a worker;
   the worker calls operations tools over MCP.
2. **Establish the first boundary before delegation.** A model choosing a tool is
   not an authorization decision. The MCP server must decide whether this task
   may invoke this tool with these arguments.
3. **State the threat assumption.** Assume the worker may be confused,
   prompt-injected, or compromised. No theatrical injection is needed.
4. **Introduce delegation.** The orchestrator may roll back production, but an
   investigation worker needs only reads. Its child warrant is an attenuation,
   not a copy of the orchestrator's credentials.
5. **Run the four cases.** Narrate what reaches the handler and what does not.
6. **End on the reusable rule.** Carry authority with the task; narrow it at
   every handoff; verify at the tool boundary.

## Suggested demo order

```bash
uv run incident-demo baseline
uv run incident-demo agent
uv run incident-demo cases
```

If model or venue networking is unreliable, show the architecture and go
directly to `cases`. The security path remains live.

## Points to make while code is open

- `authority.py`: the parent includes rollback; the child names only reads.
- `mcp_client.py`: the holder signs the exact tool name and arguments.
- `ops_server.py`: verification runs as middleware, not as a prompt instruction.
- `scenarios.py`: a denial is followed by a state read, so the result is more
  than a printed error message.

## Avoid side quests

- Do not frame this as criticism of GitHub, OAuth, or MCP.
- Do not spend the opening on warrant encoding or cryptography.
- Do not make prompt injection the spectacle; it is part of the threat model.
- Do not lead with delegation. First establish why tool calls need task-level
  authorization at all.
