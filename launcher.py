# launcher.py
import subprocess, sys, webbrowser, threading, time
from pathlib import Path

ICON_ON  = None  # You can load a .ico if you want
ICON_OFF = None

class Launcher:
    def __init__(self):
        self.proc = None
        self.cmd = [sys.executable, "-m", "uvicorn", "combined_app:app", "--host", "127.0.0.1", "--port", "5000"]
        # add --reload for dev, remove for prod

    def start(self, icon=None, item=None):
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(self.cmd, cwd=str(Path(__file__).parent))
        # give it a second to bind
        threading.Thread(target=self._wait_and_open, daemon=True).start()

    def _wait_and_open(self):
        time.sleep(1.5)
        try:
            webbrowser.open("http://127.0.0.1:5000/")
        except Exception:
            pass

    def stop(self, icon=None, item=None):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self.proc = None

    def open_dashboard(self, icon=None, item=None):
        webbrowser.open("http://127.0.0.1:5000/")

    def quit(self, icon, item):
        self.stop()
        icon.stop()

L = Launcher()

# ---- System tray UI (pystray) ----
import pystray
from pystray import MenuItem as Item, Menu

def setup(icon):
    icon.visible = True

menu = Menu(
    Item('Start', L.start),
    Item('Open Dashboard', L.open_dashboard),
    Item('Stop', L.stop),
    Item('Quit', L.quit)
)

icon = pystray.Icon("AI Advisor", ICON_ON, "AI Advisor", menu)
icon.run(setup)
