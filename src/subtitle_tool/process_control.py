from __future__ import annotations

import os
import selectors
import signal
import subprocess
from collections.abc import Callable

from .errors import CancellationError


CancelCheck = Callable[[], bool]
LineCallback = Callable[[str], None]


def run_process(
    command: list[str], cancel_check: CancelCheck | None = None
) -> subprocess.CompletedProcess[str]:
    if cancel_check and cancel_check():
        raise CancellationError("Task was cancelled by user.")

    process = subprocess.Popen(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    while True:
        if cancel_check and cancel_check():
            _terminate_process_group(process)
            raise CancellationError("Task was cancelled by user.")
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            return subprocess.CompletedProcess(
                args=command,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired:
            continue


def run_process_streaming(
    command: list[str],
    cancel_check: CancelCheck | None = None,
    stdout_line_callback: LineCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    if cancel_check and cancel_check():
        raise CancellationError("Task was cancelled by user.")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    stdout_bytes = bytearray()
    stderr_bytes = bytearray()
    stdout_line_buffer = bytearray()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")

    try:
        while selector.get_map():
            if cancel_check and cancel_check():
                _terminate_process_group(process)
                raise CancellationError("Task was cancelled by user.")
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stdout":
                    stdout_bytes.extend(chunk)
                    stdout_line_buffer.extend(chunk)
                    while b"\n" in stdout_line_buffer:
                        raw_line, _, remainder = stdout_line_buffer.partition(b"\n")
                        stdout_line_buffer = bytearray(remainder)
                        if stdout_line_callback is not None:
                            stdout_line_callback(
                                raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                            )
                else:
                    stderr_bytes.extend(chunk)
        process.wait()
    finally:
        selector.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    if stdout_line_buffer and stdout_line_callback is not None:
        stdout_line_callback(stdout_line_buffer.decode("utf-8", errors="replace"))
    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.communicate(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        process.kill()
    process.communicate()
