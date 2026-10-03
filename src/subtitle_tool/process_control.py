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
    capture_limit_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_process_streaming(
        command, cancel_check=cancel_check, timeout_seconds=timeout_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        heartbeat_callback=heartbeat_callback, operation_name=operation_name,
        capture_limit_bytes=capture_limit_bytes,
    )


def run_process_streaming(
    command: list[str],
    cancel_check: CancelCheck | None = None,
    stdout_line_callback: LineCallback | None = None,
    timeout_seconds: float | None = None,
    inactivity_timeout_seconds: float | None = None,
    heartbeat_interval_seconds: float | None = None,
    heartbeat_callback: HeartbeatCallback | None = None,
    operation_name: str | None = None,
    capture_limit_bytes: int | None = 1024 * 1024,
) -> subprocess.CompletedProcess[str]:
    if capture_limit_bytes is not None and capture_limit_bytes < 0:
        raise ValueError("capture_limit_bytes must be non-negative")
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
    try:
        if process.stdout is not None:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        # 管道关闭不代表进程退出；等待期间仍执行取消、超时和心跳检查。
        # Closed pipes do not mean process exit; keep cancellation, timeout and heartbeat checks active.
        while selector.get_map() or process.poll() is None:
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
            if not selector.get_map():
                time.sleep(wait_seconds)
                continue
            for key, _ in selector.select(timeout=wait_seconds):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                last_activity_at = time.monotonic()
                if key.data == "stdout":
                    _append_capture(stdout_bytes, chunk, capture_limit_bytes)
                    if stdout_line_callback is None:
                        continue
                    stdout_line_buffer.extend(chunk)
                    while b"\n" in stdout_line_buffer:
                        raw_line, _, remainder = stdout_line_buffer.partition(b"\n")
                        stdout_line_buffer = bytearray(remainder)
                        if stdout_line_callback is not None:
                            stdout_line_callback(
                                raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                            )
                    # 异常长的无换行进度行直接拒绝，避免缓冲区无限增长。
                    # Reject malformed newline-free progress records instead of unbounded buffering.
                    if len(stdout_line_buffer) > 1024 * 1024:
                        raise ValueError("Subprocess progress line exceeds 1 MiB")
                else:
                    _append_capture(stderr_bytes, chunk, capture_limit_bytes)
        process.wait()
    except BaseException:
        # 回调和读取错误也必须终止并回收子进程，不能只关闭管道。
        # Callback and read failures must terminate and reap the child, not only close pipes.
        _terminate_process_group(process)
        raise
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


def _append_capture(buffer: bytearray, chunk: bytes, limit: int | None) -> None:
    buffer.extend(chunk)
    if limit is not None and len(buffer) > limit:
        del buffer[:len(buffer) - limit]


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


def _terminate_process_group(process: subprocess.Popen) -> None:
    # 父进程退出后同组子孙仍可能存活；不能用 poll() 跳过整个进程组。
    # Descendants may survive their leader; poll() must not skip process-group cleanup.
    def send(sig: int) -> None:
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            if process.poll() is None:
                process.send_signal(sig)

    deadline = time.monotonic() + 1.0
    send(signal.SIGTERM)
    try:
        process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass
    # 即使后代关闭了输出管道，也给它们有限时间退出，再强制终止。
    # Give descendants a bounded grace period even when they closed their output pipes.
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    send(signal.SIGKILL)
    process.communicate()
