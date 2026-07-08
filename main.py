# main.py
import wx
import sys
import threading
import queue
import time
import os
from gui import MainFrame
from tray import start_tray_monitoring, shutdown_requested
from hardware import detect_hardware
import pythoncom
import clr


DLL_NAME = "LibreHardwareMonitorLib.dll"

def get_dll_path() -> str:
    """Resolves DLL path: checks next to executable first, then falls back to bundled _MEIPASS."""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    external_path = os.path.join(base_dir, DLL_NAME)
    if os.path.exists(external_path):
        print(f"[INFO] Using external DLL: {external_path}")
        return external_path

    if hasattr(sys, '_MEIPASS'):
        bundled_path = os.path.join(sys._MEIPASS, DLL_NAME)
        if os.path.exists(bundled_path):
            print(f"[INFO] Using bundled DLL: {bundled_path}")
            return bundled_path

    raise FileNotFoundError(f"{DLL_NAME} not found next to executable or in bundled resources.")


def init_clr_and_com(dll_path: str) -> None:
    """Initialize COM and .NET runtime exactly once on the main thread."""
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    try:
        clr.AddReference(dll_path)
        print("[INFO] CLR & COM initialized successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize CLR/COM: {e}")
        sys.exit(1)


# Prozesspriorität direkt beim Start setzen
if sys.platform == "win32":
    import psutil
    try:
        p = psutil.Process(os.getpid())
        p.nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception as e:
        print(f"[WARN] Konnte Prozesspriorität nicht setzen: {e}")


def start_gui_and_get_selection(hardware_info, result_queue):
    class App(wx.App):
        def OnInit(self):
            self.frame = MainFrame(None, hardware_info=hardware_info, result_queue=result_queue)
            self.frame.Show()
            return True

    app = App(False)
    app.MainLoop()


def save_exe_dir_to_meipass():
    try:
        # Ermittlung des MEIPASS-Pfads (nur wenn als .exe via PyInstaller gestartet)
        if hasattr(sys, '_MEIPASS'):
            meipass_dir = sys._MEIPASS
        else:
            print("[WARN] Kein MEIPASS gefunden (nicht als EXE gestartet). Überspringe Speichern.")
            return

        # Pfad zur laufenden .exe
        if getattr(sys, 'frozen', False):
            #exe_dir = os.path.dirname(sys.executable)
            exe_path = sys.executable  # <- vollständiger Pfad zur exe inkl. Dateiname
        else:
            #exe_dir = os.path.dirname(os.path.abspath(__file__))
            exe_path = os.path.abspath(__file__)  # <- vollständiger Pfad zur .py Datei

        # Zieldatei im MEIPASS-Verzeichnis
        output_file = os.path.join(meipass_dir, "startdir.txt")

        with open(output_file, "w", encoding="utf-8") as f:
            #f.write(f"Startverzeichnis: {exe_dir}\n")
            f.write(f"{exe_path}\n")

        print(f"[INFO] Startverzeichnis und Startdatei gespeichert in MEIPASS: {output_file}")
    except Exception as e:
        print(f"[ERROR] Fehler beim Schreiben der startdir.txt: {e}")


if __name__ == "__main__":
    try:
        time.sleep(0.1)
        save_exe_dir_to_meipass()
        
        dll_path = get_dll_path()
        init_clr_and_com(dll_path)

        print("[DEBUG] Starte hardware.py...")
        # ✅ Pass dll_path to hardware module
        hardware_info = detect_hardware(dll_path)
        print("[DEBUG] hardware.py exit...")

        result_queue = queue.Queue()
        start_gui_and_get_selection(hardware_info, result_queue)
        print("[INFO] GUI beendet.")

        try:
            selected_components = result_queue.get(timeout=11)
            tray_should_start = any([
                selected_components.get('cpu'),
                selected_components.get('ram'),
                selected_components.get('gpu'),
                selected_components.get('network'),
                bool(selected_components.get('drives'))
            ])
        except queue.Empty:
            print("[WARN] Keine Rückgabe durch GUI. Traymonitor wird nicht gestartet.")
            tray_should_start = False

        if tray_should_start:
            print("[INFO] Auswahl empfangen:", selected_components)
            time.sleep(1)

            # ✅ Pass dll_path to tray module
            tray_thread = threading.Thread(
                target=start_tray_monitoring,
                args=(hardware_info, selected_components, dll_path),
                daemon=False
            )
            tray_thread.start()

            while not shutdown_requested.wait(timeout=0.1):
                pass

            print("[INFO] Tray-Exit wurde erkannt – beende main.py.")
            if tray_thread.is_alive():
                tray_thread.join(timeout=3.0)

            pythoncom.CoUninitialize()
            try:
                import clr
                clr.Cleanup()
            except Exception:
                pass

            time.sleep(0.5)
            os._exit(0)  # ✅ Cleaner for IDE execution

        else:
            print("[INFO] Programm wird beendet, da keine Auswahl getroffen wurde.")
            os._exit(0)

    except KeyboardInterrupt:
        print("[INFO] Manuell beendet.")
        os._exit(0)
    except Exception as e:
        print(f"[ERROR] Unerwarteter Fehler: {e}", file=sys.stderr)
        os._exit(1)
