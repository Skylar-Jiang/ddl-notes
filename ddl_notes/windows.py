"""Small Windows integration layer. All tray callbacks send queue messages only."""
import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from threading import Thread


def enable_dpi_awareness():
    if os.name == 'nt':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            ctypes.windll.user32.SetProcessDPIAware()


def startup_command():
    if getattr(sys, 'frozen', False):
        args = [str(Path(sys.executable).resolve()), '--startup']
    else:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        args = [str(pythonw if pythonw.exists() else Path(sys.executable).resolve()),
                str(Path(__file__).resolve().parents[1] / 'run.py'), '--startup']
    return subprocess.list2cmdline(args)


class Startup:
    KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

    def __init__(self, name='DDLNotes'):
        self.name = name

    def command(self):
        if os.name != 'nt':
            return ''
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
                return winreg.QueryValueEx(key, self.name)[0]
        except FileNotFoundError:
            return ''

    def enabled(self):
        return bool(self.command())

    def enable(self):
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY) as key:
            winreg.SetValueEx(key, self.name, 0, winreg.REG_SZ, startup_command())

    def disable(self):
        if os.name != 'nt':
            return
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self.name)
        except FileNotFoundError:
            pass


class InstanceGuard:
    def __init__(self, name='DDLNotes'):
        self.name = 'Local\\' + name
        self.mutex = None
        self.event = None
        if os.name == 'nt':
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            self.kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            self.kernel.CreateEventW.restype = wintypes.HANDLE
            for name in ('SetEvent', 'ResetEvent', 'CloseHandle'):
                getattr(self.kernel, name).argtypes = [wintypes.HANDLE]
            self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    def acquire(self):
        if os.name != 'nt':
            return True
        self.mutex = self.kernel.CreateMutexW(None, False, self.name)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        existing = ctypes.get_last_error() == 183
        self.event = self.kernel.CreateEventW(None, True, False, self.name + '-Show')
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        if existing:
            self.kernel.SetEvent(self.event)
        return not existing

    def show_requested(self):
        if self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0:
            self.kernel.ResetEvent(self.event)
            return True
        return False

    def close(self):
        for name in ('mutex', 'event'):
            handle = getattr(self, name)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


def window_handle(window):
    user = ctypes.windll.user32
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    return user.GetParent(window.winfo_id()) or window.winfo_id()


def style_window(window, dark=False, tool=False):
    """Keep native resize/minimize/taskbar behavior; remove only the caption."""
    if os.name != 'nt':
        return
    window.update_idletasks()
    hwnd = window_handle(window)
    user = ctypes.windll.user32
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    before = wintypes.RECT()
    user.GetClientRect(hwnd, ctypes.byref(before))
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    style = user.GetWindowLongW(hwnd, -16)
    user.SetWindowLongW(hwnd, -16, style & ~0x00C00000)  # WS_CAPTION
    if tool:
        ex = user.GetWindowLongW(hwnd, -20)
        user.SetWindowLongW(hwnd, -20, (ex | 0x80) & ~0x40000)
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)
    client, outer = wintypes.RECT(), wintypes.RECT()
    user.GetClientRect(hwnd, ctypes.byref(client))
    user.GetWindowRect(hwnd, ctypes.byref(outer))
    # Removing a caption changes non-client metrics. Keep the requested client size stable.
    if (client.right, client.bottom) != (before.right, before.bottom):
        user.SetWindowPos(hwnd, None, 0, 0,
                          outer.right-outer.left + before.right-client.right,
                          outer.bottom-outer.top + before.bottom-client.bottom,
                          0x0002 | 0x0004 | 0x0010)
    try:
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD]
        for attribute, value in ((33, 2), (20, int(dark))):
            number = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))
    except OSError:
        logging.exception('Cannot apply DWM appearance')


def screen_bounds(window):
    if os.name == 'nt':
        user = ctypes.windll.user32
        left, top = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
        return left, top, left+user.GetSystemMetrics(78), top+user.GetSystemMetrics(79)
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


def move_window(window, x, y):
    if os.name == 'nt':
        user = ctypes.windll.user32
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos(window_handle(window), None, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0010)
    else:
        window.geometry(f'{x:+d}{y:+d}')


def tray_image():
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((5, 5, 59, 59), radius=14, fill='#E7DDF5', outline='#A598BB', width=2)
    draw.line((19, 24, 25, 30, 36, 18), fill='#716086', width=4)
    draw.line((19, 40, 46, 40), fill='#9C8DAE', width=3)
    draw.line((19, 48, 39, 48), fill='#9C8DAE', width=3)
    return image


class Tray:
    def __init__(self, queue):
        self.queue = queue
        self.icon = None
        self.thread = None
        self.ready = False

    def start(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem('打开 DDL Notes', lambda *_: self.queue.put('show'), default=True),
            pystray.MenuItem('添加任务', lambda *_: self.queue.put('add')),
            pystray.MenuItem('设置', lambda *_: self.queue.put('settings')),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出 DDL Notes', lambda *_: self.queue.put('quit')))
        self.icon = pystray.Icon('DDLNotes', tray_image(), 'DDL Notes · 安静记住每个截止时间', menu)

        def setup(icon):
            icon.visible = True
            self.queue.put('tray_ready')

        def run():
            try:
                self.icon.run(setup=setup)
            except Exception:
                logging.exception('Tray failed')
                self.queue.put('tray_failed')

        self.thread = Thread(target=run, name='DDLNotes-tray', daemon=True)
        self.thread.start()

    def stop(self):
        if self.icon:
            self.icon.stop()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
