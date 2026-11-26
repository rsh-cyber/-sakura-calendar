"""Read the Windows desktop process identity for the current Sakura launch."""

from __future__ import annotations

import ctypes
import ntpath
import os
from collections.abc import Callable, Mapping
from ctypes import wintypes
from pathlib import Path


_ProcessInfo = tuple[int, str]


def windows_host_boot_id(sakura_dir: Path) -> str | None:
    """Identify the Sakura desktop ancestor of this runner, if verifiable."""
    if os.name != "nt":
        return None
    return _find_host_boot_id(
        os.fspath(sakura_dir / "sakura.exe"),
        os.getpid(),
        _read_parent_pids(),
        _read_process,
    )


def _path_key(path: str) -> str:
    normalized = ntpath.normcase(ntpath.normpath(path))
    if normalized.startswith("\\\\?\\unc\\"):
        return "\\\\" + normalized[8:]
    return normalized.removeprefix("\\\\?\\")


def _find_host_boot_id(
    host_executable: str,
    pid: int,
    parents: Mapping[int, int],
    read_process: Callable[[int], _ProcessInfo | None],
) -> str | None:
    current = read_process(pid)
    if current is None:
        return None

    expected_path = _path_key(host_executable)
    child_created = current[0]
    while parent_pid := parents.get(pid):
        parent = read_process(parent_pid)
        if parent is None:
            return None
        created, executable = parent
        # A more recent process with the same PID is not the original parent.
        if not 0 < created < child_created:
            return None
        if _path_key(executable) == expected_path:
            return f"sakura-win:{parent_pid}:{created}"
        pid, child_created = parent_pid, created
    return None


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _read_parent_pids() -> dict[int, int]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for function in (kernel.Process32FirstW, kernel.Process32NextW):
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, ctypes.c_void_p(-1).value):
        return {}

    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            return {}
        parents = {}
        while True:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                return parents if ctypes.get_last_error() == 18 else {}  # ERROR_NO_MORE_FILES
    finally:
        kernel.CloseHandle(snapshot)


def _read_process(pid: int) -> _ProcessInfo | None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None

    try:
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time),
        ):
            return None
        size = wintypes.DWORD(32768)
        name = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return None
        filetime = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return filetime, name.value
    finally:
        kernel.CloseHandle(handle)
