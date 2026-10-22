"""P3.3 generic process-launch env hygiene (not a sandbox).

All tests use synthetic keys only. The normal default remains full inheritance
for every existing adapter; an explicit tuple is a new opt-in host policy.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from multilspy import LanguageServer
from multilspy.lsp_protocol_handler.server import LanguageServerHandler, ProcessLaunchInfo
from multilspy.multilspy_config import Language, MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

_MARKER = "BINNACLE_P33_SYNTHETIC_NOT_A_CREDENTIAL"


def _handler(tmp_path, *, keys=None, overrides=None):
    info = ProcessLaunchInfo(
        cmd=[sys.executable],
        cwd=str(tmp_path),
        inherited_environment_keys=keys,
        env=overrides or {},
    )
    return LanguageServerHandler(info)


def test_default_retains_parent_environment_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv(_MARKER, "synthetic-marker-only")
    handler = _handler(tmp_path)
    exported = handler._process_environment()
    assert exported[_MARKER] == "synthetic-marker-only"
    assert exported["PATH"] == os.environ["PATH"]
    assert handler.process_launch_info.inherited_environment_keys is None


def test_empty_tuple_inherits_nothing_from_parent(tmp_path, monkeypatch):
    monkeypatch.setenv(_MARKER, "synthetic-marker-only")
    assert _handler(tmp_path, keys=())._process_environment() == {}


def test_allowlist_passes_only_listed_existing_values(tmp_path, monkeypatch):
    monkeypatch.setenv(_MARKER, "not-forwarded")
    monkeypatch.setenv("PYRIGHT_P33_ALLOWED", "synthetic")
    handler = _handler(
        tmp_path, keys=("PYRIGHT_P33_ALLOWED", "DOES_NOT_EXIST_ANYWHERE_2233")
    )
    assert handler._process_environment() == {"PYRIGHT_P33_ALLOWED": "synthetic"}


def test_explicit_adapter_override_takes_priority_over_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("PYRIGHT_P33_ALLOWED", "from-parent")
    monkeypatch.setenv(_MARKER, "not-forwarded")
    handler = _handler(
        tmp_path,
        keys=("PYRIGHT_P33_ALLOWED",),
        overrides={"PYRIGHT_P33_ALLOWED": "from-provider", "LSP_ONLY": "yes"},
    )
    assert handler._process_environment() == {
        "PYRIGHT_P33_ALLOWED": "from-provider", "LSP_ONLY": "yes"
    }


@pytest.mark.parametrize("bad_keys", [
    ["PATH"], "PATH", (1,), (None,), ("",), ("A-B",),
    ("A", "A"), ("INVALID=NAME",), ("A\x00B",),
    tuple(f"K_{i}" for i in range(65)),
])
def test_bad_allowlist_fails_before_process_spawn(tmp_path, bad_keys):
    handler = _handler(tmp_path, keys=bad_keys)
    with pytest.raises(ValueError, match="invalid_parent_environment_allowlist"):
        handler._process_environment()
    assert handler.process is None


def test_config_field_from_dict_accepts_explicit_allowlist():
    config = MultilspyConfig.from_dict({
        "code_language": Language.PYTHON,
        "python_server": "pyright",
        "inherited_environment_keys": ("PATH", "LANG"),
    })
    assert config.inherited_environment_keys == ("PATH", "LANG")
    assert MultilspyConfig(code_language=Language.PYTHON).inherited_environment_keys is None


@pytest.mark.asyncio
async def test_real_python_child_does_not_receive_parent_synthetic_marker(tmp_path, monkeypatch):
    marker_file = tmp_path / "result.txt"
    monkeypatch.setenv(_MARKER, "sensitive-looking-but-synthetic")
    info = ProcessLaunchInfo(
        cmd=[
            sys.executable, "-c",
            "import os,sys;open(sys.argv[1],'w').write('present' if "
            "os.getenv(sys.argv[2]) else 'absent')",
            str(marker_file), _MARKER,
        ],
        cwd=str(tmp_path),
        inherited_environment_keys=(),
    )
    client = LanguageServerHandler(info)
    process = await asyncio.create_subprocess_exec(
        *info.cmd, cwd=info.cwd, env=client._process_environment()
    )
    await asyncio.wait_for(process.wait(), 3)
    assert process.returncode == 0
    assert marker_file.read_text() == "absent"


@pytest.mark.asyncio
async def test_generic_language_server_config_reaches_native_pyright_launch(tmp_path, monkeypatch):
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    if not binary:
        pytest.skip("explicit real Pyright acceptance opt-in required")
    monkeypatch.setenv(_MARKER, "not-a-secret")
    config = MultilspyConfig(
        code_language=Language.PYTHON,
        python_server="pyright",
        server_binary=binary,
        inherited_environment_keys=("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"),
    )
    language_server = LanguageServer.create(config, MultilspyLogger(), str(tmp_path))
    assert type(language_server).__name__ == "PyrightServer"
    assert _MARKER not in language_server.server._process_environment()
    assert language_server.server.process_launch_info.inherited_environment_keys is not None
    # The actual Binnacle integration exercises the start->LSP->stop flow;
    # this verifies propagation through the genuine upstream Pyright adapter.


@pytest.mark.asyncio
async def test_real_pyright_definition_with_minimal_parent_env(tmp_path, monkeypatch):
    """Real language server runs with no synthetic parent secret inherited."""
    binary = os.getenv("PYRIGHT_LSP_TEST_BIN")
    if not binary:
        pytest.skip("set PYRIGHT_LSP_TEST_BIN for native Pyright opt-in")
    project = tmp_path / "audit"
    project.mkdir()
    (project / "lib.py").write_text(
        "def greet(name: str) -> str:\n    return name.upper()\n",
        encoding="utf-8",
    )
    (project / "app.py").write_text(
        "from lib import greet\nanswer = greet('Ada')\n", encoding="utf-8"
    )
    marker_value = "not-a-secret-unit-test"
    monkeypatch.setenv(_MARKER, marker_value)
    config = MultilspyConfig(
        code_language=Language.PYTHON,
        python_server="pyright",
        server_binary=binary,
        inherited_environment_keys=("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR"),
    )
    server = LanguageServer.create(config, MultilspyLogger(), str(project))
    assert _MARKER not in server.server._process_environment()
    from asyncio import create_subprocess_exec as real_spawn
    observed = []

    async def inspect_launch(*args, **kwargs):
        if "--stdio" in args:
            passed = kwargs.get("env")
            observed.append(
                isinstance(passed, dict) and _MARKER not in passed
            )
        return await real_spawn(*args, **kwargs)

    async def exercise():
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(asyncio, "create_subprocess_exec", inspect_launch)
            async with server.start_server():
                with server.open_file("app.py"), server.open_file("lib.py"):
                    answer = await asyncio.wait_for(
                        server.request_definition("app.py", 1, 9), timeout=9
                    )
                    assert answer and answer[0]["relativePath"] == "lib.py"
    await asyncio.wait_for(exercise(), 30)
    assert observed == [True]
    assert server.server.process is None
