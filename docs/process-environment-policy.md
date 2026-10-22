# Optional parent-environment policy for language server processes

By default all multilspy adapters retain the original behavior: a language
server inherits its embedding process's environment. Embedding clients can
choose a restricted parent-key allowlist via the **generic** configuration:

```python
config = MultilspyConfig(
    code_language=Language.PYTHON,
    python_server="pyright",
    server_binary="/host-approved/bin/pyright-langserver",
    inherited_environment_keys=("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR"),
)
```

`inherited_environment_keys=None` retains legacy unrestricted inheritance.
An empty tuple inherits **no** parent values; a nonempty tuple inherits only
listed variables actually present. Adapter-supplied `ProcessLaunchInfo.env`
is still applied as explicit overrides. Bad key names, duplicate names,
non-tuples and more than 64 keys fail before subprocess creation. The policy
is implemented in common `LanguageServerHandler` for all adapters: it does
not introduce a Pyright-specific protocol client or new JSON-RPC behavior.

This is **credential hygiene**, not an OS sandbox. For example, omitting
`HOME` does not prevent a program discovering home via user database APIs;
allowing `PATH` does not constrain the paths that subprocesses may execute.
The embedding application still needs its own filesystem, external read,
network, child process and resource limits before labelling any provider safe
for execution against untrusted workspaces. Process-session independence is
also not security isolation.
