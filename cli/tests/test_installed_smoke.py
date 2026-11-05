"""Installation failures keep the subprocess evidence used to diagnose them."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('output,error', [('安装中\n', None), (b'download\n', b'network error\n')])
def test_timeout_preserves_partial_output_without_masking_failure(tmp_path, monkeypatch, output, error):
    script = Path(__file__).parents[1] / 'scripts/smoke_installed.py'
    spec = importlib.util.spec_from_file_location('installed_smoke', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('pip', 1, output=output, stderr=error)

    monkeypatch.setattr(module.subprocess, 'run', timeout)
    log = tmp_path / 'install.log'
    with pytest.raises(RuntimeError, match='Timed out'):
        module.execute(['pip'], tmp_path, {}, log, timeout=1)
    expected = (output.encode('utf-8') if isinstance(output, str) else output) + (error or b'')
    assert log.read_bytes() == expected
