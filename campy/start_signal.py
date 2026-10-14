"""Cancellable Enter wait without a background thread holding stdin's lock."""
import os
import sys
import time


def _read_available(stream):
    """Return one input byte, b'' for EOF, or None when no input is ready."""
    fd = stream.fileno()
    if os.name == 'nt':
        import msvcrt
        if stream.isatty():
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char == '\x03':
                raise KeyboardInterrupt
            return char.encode('utf-8')

        # select() cannot poll Windows anonymous pipes (GUI subprocess stdin).
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
        get_type = kernel.GetFileType
        get_type.argtypes = [wintypes.HANDLE]
        get_type.restype = wintypes.DWORD
        if get_type(handle) == 3:  # FILE_TYPE_PIPE
            available = wintypes.DWORD()
            peek = kernel.PeekNamedPipe
            peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            peek.restype = wintypes.BOOL
            if not peek(handle, None, 0, None, ctypes.byref(available), None):
                error = ctypes.get_last_error()
                if error in (109, 232):  # broken / closing pipe
                    return b''
                raise ctypes.WinError(error)
            if not available.value:
                return None
    else:
        import select
        if not select.select([fd], [], [], 0)[0]:
            return None
    return os.read(fd, 1)


def wait_for_start(cancelled, stream=None):
    """Accept Enter from console or GUI pipe, checking cancellation every 50 ms."""
    stream = sys.stdin if stream is None else stream
    while not cancelled():
        value = _read_available(stream)
        if value == b'':
            return False
        if value in (b'\n', b'\r'):
            return not cancelled()
        time.sleep(.05)
    return False
