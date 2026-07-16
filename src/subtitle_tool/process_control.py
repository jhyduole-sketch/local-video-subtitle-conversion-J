from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable

from .errors import CancellationError, ProcessTimeoutError


CancelCheck = Callable[[], bool]
LineCallback = Callable[[str], None]
HeartbeatCallback = Callable[[float], None]


def timeout_seconds_from_env(name: str, default: float, minimum: float = 1.0) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return max(minimum, float(value))
    except ValueError:
        return default


def run_process(
    command: list[str],
    cancel_check: CancelCheck | None = None,
    timeout_seconds: float | None = None,
    heartbeat_interval_seconds: float | None = None,
    heartbeat_callback: HeartbeatCallback | None = None,
    operation_name: str | None = None,
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
    started_at = time.monotonic()
    last_heartbeat_at = started_at
    while True:
        if cancel_check and cancel_check():
            _terminate_process_group(process)
            raise CancellationError("Task was cancelled by user.")
        now = time.monotonic()
        if timeout_seconds is not None and now - started_at >= timeout_seconds:
            _terminate_process_group(process)
            raise _process_timeout_error(operation_name, timeout_seconds, inactivity=False)
        if (
            heartbeat_callback is not None
            and heartbeat_interval_seconds is not None
            and heartbeat_interval_seconds > 0
            and now - last_heartbeat_at >= heartbeat_interval_seconds
        ):
            heartbeat_callback(now - started_at)
            last_heartbeat_at = now
        try:
            stdout, stderr = process.communicate(
                timeout=_poll_timeout(
                    started_at,
                    last_heartbeat_at,
                    timeout_seconds,
                    heartbeat_interval_seconds,
                )
            )
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
    timeout_seconds: float | None = None,
    inactivity_timeout_seconds: float | None = None,
    heartbeat_interval_seconds: float | None = None,
    heartbeat_callback: HeartbeatCallback | None = None,
    operation_name: str | None = None,
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
    started_at = time.monotonic()
    last_activity_at = started_at
    last_heartbeat_at = started_at
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")

    try:
        while selector.get_map():
            if cancel_check and cancel_check():
                _terminate_process_group(process)
                raise CancellationError("Task was cancelled by user.")
            now = time.monotonic()
            if timeout_seconds is not None and now - started_at >= timeout_seconds:
                _terminate_process_group(process)
                raise _process_timeout_error(operation_name, timeout_seconds, inactivity=False)
            if (
                inactivity_timeout_seconds is not None
                and now - last_activity_at >= inactivity_timeout_seconds
            ):
                _terminate_process_group(process)
                raise _process_timeout_error(
                    operation_name, inactivity_timeout_seconds, inactivity=True
                )
            if (
                heartbeat_callback is not None
                and heartbeat_interval_seconds is not None
                and heartbeat_interval_seconds > 0
                and now - last_heartbeat_at >= heartbeat_interval_seconds
            ):
                heartbeat_callback(now - started_at)
                last_heartbeat_at = now
            wait_seconds = _stream_poll_timeout(
                started_at,
                last_activity_at,
                last_heartbeat_at,
                timeout_seconds,
                inactivity_timeout_seconds,
                heartbeat_interval_seconds,
            )
            for key, _ in selector.select(timeout=wait_seconds):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                last_activity_at = time.monotonic()
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


def _poll_timeout(
    started_at: float,
    last_heartbeat_at: float,
    timeout_seconds: float | None,
    heartbeat_interval_seconds: float | None,
) -> float:
    now = time.monotonic()
    waits = [0.2]
    if timeout_seconds is not None:
        waits.append(max(0.01, timeout_seconds - (now - started_at)))
    if heartbeat_interval_seconds is not None and heartbeat_interval_seconds > 0:
        waits.append(max(0.01, heartbeat_interval_seconds - (now - last_heartbeat_at)))
    return min(waits)


def _stream_poll_timeout(
    started_at: float,
    last_activity_at: float,
    last_heartbeat_at: float,
    timeout_seconds: float | None,
    inactivity_timeout_seconds: float | None,
    heartbeat_interval_seconds: float | None,
) -> float:
    now = time.monotonic()
    waits = [0.2]
    if timeout_seconds is not None:
        waits.append(max(0.01, timeout_seconds - (now - started_at)))
    if inactivity_timeout_seconds is not None:
        waits.append(max(0.01, inactivity_timeout_seconds - (now - last_activity_at)))
    if heartbeat_interval_seconds is not None and heartbeat_interval_seconds > 0:
        waits.append(max(0.01, heartbeat_interval_seconds - (now - last_heartbeat_at)))
    return min(waits)


def _process_timeout_error(
    operation_name: str | None, seconds: float, *, inactivity: bool
) -> ProcessTimeoutError:
    operation = operation_name or "外部程序"
    duration = _format_limit_seconds(seconds)
    if inactivity:
        return ProcessTimeoutError(
            f"{operation}长时间没有进度（{duration}），进程已停止。"
            "请检查输入文件、磁盘空间，或改用稳定模式后重试。"
        )
    return ProcessTimeoutError(
        f"{operation}运行超时（已超过 {duration}），进程已停止。"
        "请缩短视频、检查网络，或调大超时设置后重试。"
    )


def _format_limit_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:g} 秒"
    return f"{seconds / 60:g} 分钟"


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
