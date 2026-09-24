"""Platform-specific application data and DaVinci Resolve paths."""

import os
import sys


def app_support_dir():
    if os.name == "nt":
        base_dir = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    elif sys.platform == "darwin":
        base_dir = os.path.expanduser("~/Library/Application Support")
    else:
        base_dir = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base_dir, "SubtitleAgent")


APP_SUPPORT_DIR = app_support_dir()


def _running_resolve_library():
    """Return fusionscript.dll beside a running Resolve.exe, if accessible."""
    if os.name != "nt":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        process_ids = (wintypes.DWORD * 4096)()
        bytes_needed = wintypes.DWORD()
        psapi.EnumProcesses.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        psapi.EnumProcesses.restype = wintypes.BOOL
        if not psapi.EnumProcesses(
            process_ids,
            ctypes.sizeof(process_ids),
            ctypes.byref(bytes_needed),
        ):
            return None

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        process_count = min(bytes_needed.value // ctypes.sizeof(wintypes.DWORD), len(process_ids))
        for process_id in process_ids[:process_count]:
            handle = kernel32.OpenProcess(0x1000, False, process_id)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                continue
            try:
                image_path = ctypes.create_unicode_buffer(32768)
                image_path_size = wintypes.DWORD(len(image_path))
                if not kernel32.QueryFullProcessImageNameW(
                    handle, 0, image_path, ctypes.byref(image_path_size)
                ):
                    continue
                if os.path.basename(image_path.value).casefold() != "resolve.exe":
                    continue
                library = os.path.join(os.path.dirname(image_path.value), "fusionscript.dll")
                if os.path.isfile(library):
                    return library
            finally:
                kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return None
    return None


def _windows_resolve_library():
    running_library = _running_resolve_library()
    if running_library:
        return running_library

    roots = []
    for value in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if value:
            roots.append(value)

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        drive_mask = kernel32.GetLogicalDrives()
        kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetDriveTypeW.restype = ctypes.c_uint
        for index in range(26):
            if not drive_mask & (1 << index):
                continue
            drive_root = "%s:\\" % chr(ord("A") + index)
            if kernel32.GetDriveTypeW(drive_root) == 3:  # DRIVE_FIXED
                roots.extend(
                    [
                        os.path.join(drive_root, "Program Files"),
                        os.path.join(drive_root, "Program Files (x86)"),
                        drive_root,
                    ]
                )
    except (AttributeError, OSError):
        pass

    seen = set()
    for root in roots:
        for relative_path in (
            os.path.join("Blackmagic Design", "DaVinci Resolve", "fusionscript.dll"),
            os.path.join("Blackmagic Design", "DaVinci Resolve Studio", "fusionscript.dll"),
        ):
            library = os.path.join(root, relative_path)
            normalized = os.path.normcase(os.path.abspath(library))
            if normalized not in seen and os.path.isfile(library):
                return library
            seen.add(normalized)

    return None


def default_resolve_paths():
    if os.name == "nt":
        api_root = os.path.join(
            os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
            "Blackmagic Design",
            "DaVinci Resolve",
            "Support",
            "Developer",
            "Scripting",
        )
        library = _windows_resolve_library() or os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "Blackmagic Design",
            "DaVinci Resolve",
            "fusionscript.dll",
        )
    elif sys.platform == "darwin":
        api_root = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        library = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    else:
        api_root = ""
        library = ""
    return api_root, library


_RESOLVE_DLL_DIRECTORY_HANDLES = []


def configure_resolve_environment(env=None):
    """Set Resolve defaults, preserving explicit environment overrides."""
    target_env = os.environ if env is None else env
    default_api_root, default_library = default_resolve_paths()
    api_root = target_env.get("RESOLVE_SCRIPT_API") or default_api_root
    library_override = target_env.get("RESOLVE_SCRIPT_LIB")
    library = (
        library_override
        if library_override and os.path.isfile(library_override)
        else default_library
    )

    if api_root:
        target_env["RESOLVE_SCRIPT_API"] = api_root
        module_dir = os.path.join(api_root, "Modules")
        paths = [path for path in target_env.get("PYTHONPATH", "").split(os.pathsep) if path]
        normalized_paths = {os.path.normcase(os.path.abspath(path)) for path in paths}
        if os.path.normcase(os.path.abspath(module_dir)) not in normalized_paths:
            target_env["PYTHONPATH"] = os.pathsep.join([module_dir] + paths)

    if library:
        target_env["RESOLVE_SCRIPT_LIB"] = library
        if os.name == "nt":
            library_dir = os.path.dirname(library)
            if os.path.isdir(library_dir):
                path_entries = [path for path in target_env.get("PATH", "").split(os.pathsep) if path]
                normalized_entries = {os.path.normcase(os.path.abspath(path)) for path in path_entries}
                if os.path.normcase(os.path.abspath(library_dir)) not in normalized_entries:
                    target_env["PATH"] = os.pathsep.join([library_dir] + path_entries)
                if env is None:
                    _RESOLVE_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(library_dir))

    return api_root, library
