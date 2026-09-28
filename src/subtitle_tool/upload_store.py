"""管理流式上传、任务占用和可恢复输入，失败时保留可重试文件。
Manage streamed uploads, job claims, and retained inputs while preserving retryable files on failure.
"""
from __future__ import annotations

from email.parser import BytesHeaderParser
from email.message import Message
import os
from pathlib import Path
import shutil
import threading
import time
import uuid

from .media_preview import VIDEO_SUFFIXES
from .web_security import RequestError


class LimitedReader:
    def __init__(self, stream, length: int):
        self.stream, self.remaining = stream, length

    def read(self, size: int = 256 * 1024) -> bytes:
        if self.remaining <= 0:
            return b""
        data = self.stream.read(min(size, self.remaining))
        if not data:
            raise RequestError("上传中断，收到的文件不完整。")
        self.remaining -= len(data)
        return data

    def readline(self, limit: int = 16384) -> bytes:
        data = self.stream.readline(min(limit, self.remaining))
        self.remaining -= len(data)
        if not data or len(data) >= limit or not data.endswith(b"\n"):
            raise RequestError("上传表单头不完整或过长。")
        return data


class UploadStore:
    """管理临时上传；保留的任务输入归输出目录管理。
    Owns temporary uploads; retained inputs belong to a task's output directory.
    """

    def __init__(self, root: Path, reserve_bytes: int = 64 * 1024 ** 2):
        self.root = root.resolve()
        self.reserve_bytes = reserve_bytes
        self._claims: set[Path] = set()
        self._lock = threading.RLock()

    def _prepare(self, filename: str, length: int) -> Path:
        name = Path(filename.replace("\\", "/")).name.strip()
        if not name or Path(name).suffix.lower() not in VIDEO_SUFFIXES or len(name.encode("utf-8")) > 240:
            raise RequestError("请上传 MP4、MOV、MKV、M4V 或 WebM 视频文件。")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if shutil.disk_usage(self.root).free < length + self.reserve_bytes:
            raise RequestError("临时目录可用磁盘空间不足。", 507)
        directory = self.root / uuid.uuid4().hex
        directory.mkdir(mode=0o700)
        return directory / name

    def receive(self, stream, length: int, filename: str) -> Path:
        if length <= 0:
            raise RequestError("上传文件不能为空。")
        path = self._prepare(filename, length)
        try:
            reader = LimitedReader(stream, length)
            with path.open("xb") as output:
                while reader.remaining:
                    output.write(reader.read())
            return path
        except BaseException:
            shutil.rmtree(path.parent, ignore_errors=True)
            raise

    def receive_multipart(self, stream, length: int, content_type: str) -> Path:
        metadata = Message()
        metadata["content-type"] = content_type
        boundary = metadata.get_boundary()
        if not boundary or len(boundary) > 70 or not boundary.isascii() or any(ord(char) < 32 for char in boundary):
            raise RequestError("上传表单 boundary 无效。")
        marker = b"\r\n--" + boundary.encode("ascii")
        reader = LimitedReader(stream, length)
        if reader.readline() != b"--" + boundary.encode("ascii") + b"\r\n":
            raise RequestError("上传表单起始边界无效。")
        header = bytearray()
        while True:
            line = reader.readline()
            if line == b"\r\n":
                break
            header.extend(line)
            if len(header) > 16384:
                raise RequestError("上传表单头过长。")
        part = BytesHeaderParser().parsebytes(bytes(header))
        if part.get_param("name", header="content-disposition") != "video" or not part.get_filename():
            raise RequestError("上传表单需要一个 video 文件。")
        path = self._prepare(part.get_filename(), length)
        try:
            pending = b""
            complete = False
            with path.open("xb") as output:
                while reader.remaining:
                    pending += reader.read()
                    cursor = 0
                    while True:
                        index = pending.find(marker, cursor)
                        if index < 0 or len(pending) < index + len(marker) + 2:
                            break
                        suffix = pending[index + len(marker):index + len(marker) + 2]
                        if suffix == b"--":
                            output.write(pending[:index])
                            trailing = pending[index + len(marker) + 2:]
                            while reader.remaining:
                                trailing += reader.read()
                                if len(trailing) > 4096:
                                    raise RequestError("上传表单尾部无效。")
                            if trailing.strip():
                                raise RequestError("上传表单尾部无效。")
                            complete = True
                            break
                        if suffix == b"\r\n":
                            raise RequestError("每次只允许上传一个 video 文件。")
                        cursor = index + len(marker)
                    if complete:
                        break
                    # 保留可能跨数据块的边界及后缀，其余内容及时写盘以限制内存占用。
                    # Keep a possible cross-chunk boundary and suffix; flush the rest to bound memory use.
                    keep = len(marker) + 2
                    if len(pending) > keep:
                        output.write(pending[:-keep])
                        pending = pending[-keep:]
            if not complete or path.stat().st_size == 0:
                raise RequestError("上传文件为空或表单未完整传输。")
            return path
        except BaseException:
            shutil.rmtree(path.parent, ignore_errors=True)
            raise

    def owns(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.root)
            return len(relative.parts) == 2 and not path.is_symlink()
        except ValueError:
            return False

    def claim(self, path: Path) -> None:
        with self._lock:
            if self.owns(path):
                if not path.is_file():
                    raise RequestError("上传已过期，请重新上传视频。")
                if path.resolve() in self._claims:
                    raise RequestError("该上传已被任务使用，请重新上传。", 409)
                self._claims.add(path.resolve())

    def release(self, path: Path, *, delete: bool = True) -> None:
        with self._lock:
            if self.owns(path):
                self._claims.discard(path.resolve())
                if delete:
                    shutil.rmtree(path.parent, ignore_errors=True)

    def retain(self, path: Path, destination: Path, *, release_source: bool = True) -> Path:
        with self._lock:
            if not self.owns(path):
                return path
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / path.name
            try:
                os.link(path, target)
            except OSError:
                temporary = destination / ("." + path.name + ".part")
                try:
                    shutil.copyfile(path, temporary)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            # 调用方可延后释放，直到任务记录成功保存保留路径。
            # Callers may defer release until the retained path is successfully saved in the job record.
            if release_source:
                self.release(path)
            return target

    def cleanup(self, max_age_seconds: int = 86400) -> None:
        with self._lock:
            if not self.root.exists():
                return
            held = {path.parent for path in self._claims}
            cutoff = time.time() - max_age_seconds
            for directory in self.root.iterdir():
                if directory.is_symlink() or not directory.is_dir() or directory in held:
                    continue
                try:
                    if directory.stat().st_mtime < cutoff:
                        shutil.rmtree(directory)
                except FileNotFoundError:
                    continue
