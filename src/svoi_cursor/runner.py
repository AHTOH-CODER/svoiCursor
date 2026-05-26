from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot


@dataclass(frozen=True)
class RunResult:
    command: str
    output: str
    exit_code: int


class CodeRunner(QObject):
    finished = Signal(object)

    def __init__(self, path: Path, cwd: Path) -> None:
        super().__init__()
        self.path = path
        self.cwd = cwd

    @Slot()
    def run(self) -> None:
        self.finished.emit(run_file(self.path, self.cwd))


def run_file(path: Path, cwd: Path) -> RunResult:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _run([_python_executable(), str(path)], cwd)
    if suffix == ".go":
        return _run(["go", "run", str(path)], cwd)
    if suffix == ".c":
        return _compile_and_run("gcc", path, cwd)
    if suffix in {".cpp", ".cc", ".cxx"}:
        return _compile_and_run("g++", path, cwd)

    return RunResult(
        command=f"run {path.name}",
        output=f"Unsupported file type: {suffix or path.name}",
        exit_code=1,
    )


def _compile_and_run(compiler: str, path: Path, cwd: Path) -> RunResult:
    if shutil.which(compiler) is None:
        return RunResult(
            command=f"{compiler} {path.name}",
            output=(
                f"Compiler '{compiler}' was not found in PATH.\n"
                "Install it and restart the terminal, then run the file again."
            ),
            exit_code=1,
        )

    with tempfile.TemporaryDirectory(prefix="svoi_cursor_") as temp_dir:
        exe_path = Path(temp_dir) / ("program.exe" if os.name == "nt" else "program")
        compile_result = _run([compiler, str(path), "-o", str(exe_path)], cwd)
        if compile_result.exit_code != 0:
            return compile_result
        run_result = _run([str(exe_path)], cwd)
        return RunResult(
            command=f"{compile_result.command}\n{run_result.command}",
            output=run_result.output,
            exit_code=run_result.exit_code,
        )


def _run(command: list[str], cwd: Path) -> RunResult:
    command_text = " ".join(_quote(part) for part in command)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as error:
        return RunResult(command=command_text, output=str(error), exit_code=1)
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + (error.stderr or "")
        return RunResult(
            command=command_text,
            output=f"{output}\nProcess timed out after 60 seconds.".strip(),
            exit_code=1,
        )

    output = (completed.stdout or "") + (completed.stderr or "")
    return RunResult(command=command_text, output=output.strip(), exit_code=completed.returncode)


def _python_executable() -> str:
    return os.environ.get("PYTHON", "python")


def _quote(value: str) -> str:
    if " " in value:
        return f'"{value}"'
    return value
