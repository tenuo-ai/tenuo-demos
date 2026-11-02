"""Run the installed CLI and real report handler in subprocesses."""
import json
import subprocess
import sys
from pathlib import Path


def test_cli_to_enforced_report_reader(tmp_path):
    source = Path(__file__).parent
    home = tmp_path / ".tenuo"
    warrant = home / "report.warrant"

    def cli(*args):
        result = subprocess.run([sys.executable, "-m", "tenuo.local_cli", "--home", str(home),
                                 "--json", *map(str, args)], text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    cli("init", "--dev")
    cli("warrant", "issue", "--template", source / "report.yaml", "--holder", "agent", "--out", warrant)
    assert cli("warrant", "verify", "--file", warrant)["valid"]
    decoded = cli("warrant", "show", "--file", warrant)
    assert "weekly" in decoded["warrant"]["capabilities"]["read_report"]["report"]
    result = subprocess.run([sys.executable, str(source / "run_demo.py"), "--home", str(home),
                             "--warrant", str(warrant)], text=True, capture_output=True, check=True)
    assert "ALLOW:" in result.stdout and "DENY:" in result.stdout
    assert "Handler calls: 1 (weekly only)" in result.stdout
