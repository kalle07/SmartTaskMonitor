# tray.py
import threading
from threading import Event
from pystray import Icon, MenuItem, Menu
from PIL import Image, ImageDraw, ImageFont
#from functools import partial
import os
import sys
import time
import psutil
import pythoncom
import wmi
#import ctypes
import pynvml
from pynvml import *
# from pynvml import nvmlDeviceGetTemperature, nvmlDeviceGetTemperatureThreshold, NVML_TEMPERATURE_GPU, NVML_TEMPERATURE_THRESHOLD_GPU_MAX, nvmlInit, nvmlShutdown, nvmlDeviceGetHandleByIndex, nvmlDeviceGetUtilizationRates, nvmlDeviceGetMemoryInfo, nvmlDeviceGetCount, nvmlDeviceGetName
from difflib import get_close_matches
import subprocess  # Importieren Sie subprocess
import tempfile
import shutil




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


icons = {}
current_colors = {}
last_colors = {}
stop_events = {}
color_lock = threading.Lock()
icon_lock = threading.Lock()


COLOR_MAP = {
    "gray": (160, 160, 160, 255),
    "green": (0, 128, 0, 255),
    "red": (128, 0, 0, 255),
    "yellow": (220, 220, 0, 255)
}


def start_monitor_thread(target, *args, **kwargs):
    """Starts a daemon thread for a monitoring function that manages its own loop."""
    t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread_refs.append(t)
    t.start()

shutdown_event = Event()
thread_refs = []
shutdown_requested = threading.Event() 


def get_resource_path(relative_path: str) -> str:
    """Resolves resource paths for PyInstaller --onefile with fallback."""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))

    path = os.path.join(base_path, relative_path)
    if os.path.exists(path):
        return path

    # Fallback: Directory of the running executable
    exe_dir = os.path.abspath(os.path.dirname(sys.executable))
    path = os.path.join(exe_dir, relative_path)
    if os.path.exists(path):
        return path

    # Fallback: Current working directory
    path = os.path.abspath(relative_path)
    if os.path.exists(path):
        return path

    raise FileNotFoundError(f"Resource '{relative_path}' not found in any search path.")


try:
    font_path = get_resource_path("DePixelSchmal.otf")
except FileNotFoundError as e:
    print(f"[WARN] Font not found: {e}. Using fallback font.")
    font_path = None
    

def round_to_nearest_five(value):
    return int(round(value / 5.0) * 5)

def get_active_network_adapters():
    c = wmi.WMI()
    adapters = []
    for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
        if hasattr(nic, 'Description'):
            adapters.append(nic.Description)
    return adapters

def get_adapter_speeds():
    c = wmi.WMI()
    speeds = {}
    for nic in c.Win32_NetworkAdapter():
        if nic.NetEnabled and nic.Speed:
            speeds[nic.Name] = int(nic.Speed)  # Bits per second
    return speeds

def find_best_match(name, candidates):
    matches = get_close_matches(name, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None

def create_text_icon(text, color=(255, 255, 255, 255), bg_color=(0, 0, 0, 0)):
    size = 77
    image = Image.new("RGBA", (size, size), bg_color)
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype(font_path, 29)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font) if hasattr(draw, 'textbbox') else font.getsize(text)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    text_x = (size - text_w) // 2 - bbox[0]
    text_y = (size - text_h) // 2 - bbox[1]

    draw.text((text_x, text_y), text, font=font, fill=color)
    return image

def format_speed_custom(value_kb):
    units = ['kB/s', 'MB/s', 'GB/s']
    speed = value_kb
    unit_index = 0

    while speed >= 100 and unit_index < len(units) - 1:
        speed /= 1024
        unit_index += 1

    if speed < 10:
        display = f"{speed:.1f}"
    else:
        display = f"{min(round(speed), 99)}"

    return f"{display}\n{units[unit_index]}"

# drive icon
def get_color(read_active, write_active, read_mb=0, write_mb=0):
    if read_mb < 2 and write_mb < 2:
        return "gray"
    elif read_mb >= 2 and write_mb >= 2:
        ratio = read_mb / write_mb if write_mb != 0 else float('inf')
        if 1/5 <= ratio <= 5:
            return "yellow"
        elif write_mb > read_mb:
            return "red"
        else:
            return "green"
    elif write_mb >= 2:
        return "red"
    elif read_mb >= 2:
        return "green"
    return "gray"


def _set_icon_color(key, color):
    with icon_lock:
        icon_data = icons.get(key)
        if icon_data:
            icon = icon_data["icon"]
            label = icon_data["label"]
            new_icon = create_icon(COLOR_MAP.get(color, (128, 128, 128)), label)
            try:
                icon.icon = new_icon
            except Exception as e:
                print(f"[WARN] Could not update icon for {key}: {e}")
            finally:
                with color_lock:
                    last_colors[key] = color

# Drive letter ICONS
def create_icon(color_rgb, label):
    size = 77
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.ellipse((0, 0, size, size), fill=color_rgb)

    try:
        font = ImageFont.truetype(font_path, 55)
    except Exception:
        font = ImageFont.load_default()

    if hasattr(draw, 'textbbox'):
        bbox = draw.textbbox((0, 0), label, font=font)
    else:
        width, height = font.getsize(label)
        bbox = (0, 0, width, height)

    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) / 2
    text_y = (size - text_h) / 2 - bbox[1]

    brightness = sum(color_rgb) / 3
    text_color = (0, 0, 0, 255) if brightness > 130 else (255, 255, 255, 255)

    draw.text((text_x, text_y), label, font=font, fill=text_color)
    return image
    
def update_tray_color(key, color):
    with color_lock:
        old_color = current_colors.get(key)
        if old_color == color:
            return
        current_colors[key] = color



def _icon_updater(key, stop_event):
    while not stop_event.is_set():
        with color_lock:
            color = current_colors.get(key, "gray")
            last_color = last_colors.get(key)

        if color != last_color:
            try:
                _set_icon_color(key, color)
            except Exception as e:
                print(f"[WARN] Icon update failed for {key}: {e}")

        stop_event.wait(0.2)



# gradient color bar ICON: cpu, ram, gpu, vram, temp
def get_gradient_color(percent):
    """
    Gibt eine Farbe für den gegebenen Prozentwert aus einem Regenbogenverlauf zurück:
    0% -> grün, 50% -> gelb, 100% -> rot
    """
    if percent <= 50:
        # Grün → Gelb
        ratio = percent / 50.0
        r = int(COLOR_MAP["green"][0] + ratio * (COLOR_MAP["yellow"][0] - COLOR_MAP["green"][0]))
        g = int(COLOR_MAP["green"][1] + ratio * (COLOR_MAP["yellow"][1] - COLOR_MAP["green"][1]))
        b = int(COLOR_MAP["green"][2] + ratio * (COLOR_MAP["yellow"][2] - COLOR_MAP["green"][2]))
    else:
        # Gelb → Rot
        ratio = (percent - 50) / 50.0
        r = int(COLOR_MAP["yellow"][0] + ratio * (COLOR_MAP["red"][0] - COLOR_MAP["yellow"][0]))
        g = int(COLOR_MAP["yellow"][1] + ratio * (COLOR_MAP["red"][1] - COLOR_MAP["yellow"][1]))
        b = int(COLOR_MAP["yellow"][2] + ratio * (COLOR_MAP["red"][2] - COLOR_MAP["yellow"][2]))

    return (r, g, b, 255)


def create_bar_icon(percent, label, color=None):
    """
    Erstellt ein Balken-Icon mit Regenbogen-Farbverlauf.
    0% → unten grün, 50% → mitte gelb, 100% → oben rot
    """
    size = 77
    margin = 4
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Balkengröße
    bar_width = size - 2 * margin
    bar_height = int((percent / 100.0) * size)
    bar_x0 = margin
    bar_x1 = size - margin
    bar_y_bottom = size - 1
    bar_y_top = bar_y_bottom - bar_height + 1

    # Farbverlauf zeichnen
    for i in range(bar_height):
        rel_percent = (i / bar_height) * percent
        line_color = get_gradient_color(rel_percent)
        y = bar_y_bottom - i
        draw.line([(bar_x0, y), (bar_x1, y)], fill=line_color)

    # Label zeichnen
    try:
        font = ImageFont.truetype(font_path, 30)
    except:
        font = ImageFont.load_default()

    draw.text((2, 2), label, font=font, fill=(255, 255, 255, 255))

    return image



def _on_quit(icon_inst=None, item=None):
    print("[INFO] Beenden eingeleitet...")

    # 1. Stop-Flag setzen und Threads sauber beenden
    shutdown_event.set()
    for t in thread_refs:
        if t.is_alive():
            t.join(timeout=2.1)
    print("[INFO] Alle Threads beendet.")

    # 2. Tray-Icons stoppen
    stop_all_tray_icons()
    print("[INFO] Alle Trays beendet.")
    
    # 3. NVIDIA NVML sauber beenden
    try:
        pynvml.nvmlShutdown()
    except Exception:
        pass
    print("[INFO] Nvidia shut down.")

    # 4. Release CLR/Pythonnet to unload LHM DLL handles
    try:
        import clr
        clr.Cleanup()
    except Exception:
        pass
    print("[INFO] CLR released.")


    time.sleep(0.1)
    shutdown_requested.set()


def _on_restart(icon_inst=None, item=None):
    print("[INFO] Neustart eingeleitet...")

    # 1. Stop-Flag setzen und Threads sauber beenden
    shutdown_event.set()
    for t in thread_refs:
        t.join(timeout=2.1)
    print("[INFO] Alle Threads beendet.")

    # 2. Tray-Icons stoppen
    stop_all_tray_icons()

    # 3. pynvml sauber beenden
    try:
        pynvml.nvmlShutdown()
    except Exception:
        pass

    time.sleep(0.1)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    startdir_path = os.path.join(base_dir, "startdir.txt")
    print("[INFO] Start Folder lesen")
    try:
        with open(startdir_path, "r", encoding="utf-8") as f:
            executable_path = f.readline().strip()
        if not os.path.isfile(executable_path):
            raise FileNotFoundError(f"EXE nicht gefunden: {executable_path}")
    except Exception as e:
        print(f"[ERROR] Fehler beim Lesen der startdir.txt: {e}")
        if icon_inst:
            icon_inst.stop()
        return

    exe_dir = os.path.dirname(executable_path)
    
    time.sleep(0.1)
    try:
        print(f"[INFO] Starte EXE erneut (via subprocess.Popen): {executable_path}")

        env = os.environ.copy()
        env["RESTART_COUNT"] = str(int(env.get("RESTART_COUNT", "0")) + 1)
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1" 

        subprocess.Popen(
            [executable_path],
            cwd=exe_dir,
            env=env,
            close_fds=True,
            shell=False
        )

        print(f"[INFO] EXE gestartet!")
    except Exception as e:
        print(f"[ERROR] Fehler beim Start via Popen: {e}")
        return
    print("[INFO] Old Instance EXIT")
    time.sleep(0.5)
    shutdown_requested.set()




def stop_all_tray_icons():
    for icon in icons.values():
        try:
            if icon["icon"].visible:
                icon["icon"].visible = False
                icon["icon"].stop()
        except Exception as e:
            print(f"[WARN] Icon-Stop fehlgeschlagen: {e}")
    time.sleep(0.1) 
    for event in stop_events.values():
        event.set()

def update_tray_tooltip(key, tooltip_text):
    icon_data = icons.get(key)
    if icon_data:
        icon = icon_data["icon"]
        try:
            icon.title = tooltip_text[:127]
        except Exception as e:
            print(f"[WARN] Tooltip konnte nicht gesetzt werden für {key}: {e}")

def update_net_icons(adapter_name, send_kb, recv_kb, selected_components):
    menu = Menu(
        MenuItem("Restart", lambda icon_inst, item: _on_restart(icon_inst, item)),
        MenuItem("Exit", lambda icon_inst, item: _on_quit(icon_inst, item))
    )


    def update_icon(direction, value_kb):
        if not selected_components['network']:
            return

        if value_kb < 10:
            value_kb = 0

        key = f"NET_{adapter_name}, Direction: {direction}"
        text_with_linebreak = f"{'U ' if direction == 'SEND' else 'D '}{format_speed_custom(value_kb)}"
        speed_parts = format_speed_custom(value_kb).split("\n")
        text_no_linebreak = f"{speed_parts[0]} {speed_parts[1]}" if len(speed_parts) == 2 else format_speed_custom(value_kb)

        image = create_text_icon(text_with_linebreak)
        if key not in icons:
            icon = Icon(key, image, menu=menu)
            icons[key] = {"icon": icon, "label": key}
            print(f"Created Network icon {key}")
            icon.run_detached()
        else:
            icons[key]["icon"].icon = image
            # Set tooltip using the update_tray_tooltip function
            tooltip = f"{adapter_name} {'Upload' if direction == 'SEND' else 'Download'}: {text_no_linebreak}"
            tooltip = tooltip[:127] # falls percpu=True (tooltips max128 zeichen)
            update_tray_tooltip(key, tooltip)

    update_icon("SEND", send_kb)
    update_icon("RECV", recv_kb)


def sort_selected_drives(drive_selections, device_map):
    items = [(dev, part) for dev, parts in device_map.items() for part in parts]
    
    # Zugriff auf 'letter' für Sortierung
    sorted_items = sorted(items, key=lambda x: x[1]['letter'].upper(), reverse=True)
    
    # Auch drive_selections sortieren anhand des zweiten Elements (Laufwerksbuchstabe)
    return sorted(drive_selections, key=lambda x: x[1].upper(), reverse=True)


def start_drive_icons(hardware_info, device_map, drive_selections):
    print("Starting tray icons for selected drives...")
    menu = Menu(
        MenuItem("Restart", lambda icon_inst, item: _on_restart(icon_inst, item)),
        MenuItem("Exit", lambda icon_inst, item: _on_quit(icon_inst, item))
    )


    sorted_drive_selections = sort_selected_drives(drive_selections, device_map)

    for index, (dev, part) in enumerate(sorted_drive_selections):
        icon_label = part.strip(":")
        icon_key = f"{dev}_{part}"
        icon_title = f"{index}_SmartTaskTool_{icon_label}"

        image = create_icon(COLOR_MAP["gray"], icon_label)
        icon = Icon(icon_title, image, menu=menu)
        icons[icon_key] = {"icon": icon, "label": icon_label}
        current_colors[icon_key] = "gray"
        last_colors[icon_key] = None
        stop_event = threading.Event()
        stop_events[icon_key] = stop_event

        icon.run_detached()

        threading.Thread(target=_icon_updater, args=(icon_key, stop_event), daemon=True).start()
        time.sleep(0.2)

    print("Started Icons:")
    for key, value in icons.items():
        print(f"  {key}: {value}")


def start_tray_monitoring(hardware_info: dict, selected_components: dict, dll_path: str) -> None:
    """Starts background monitoring threads and system tray icons."""
    if not isinstance(selected_components, dict):
        raise ValueError("selected_components muss ein Dictionary sein")

    expected_keys = ['cpu', 'ram', 'gpu', 'network', 'drives']
    for key in expected_keys:
        if key not in selected_components:
            raise KeyError(f"selected_components fehlt: '{key}'")
        value = selected_components[key]
        if key == 'drives':
            if not isinstance(value, list):
                raise TypeError(f"'{key}' muss eine Liste sein.")
            if not all(isinstance(item, tuple) and len(item) == 2 for item in value):
                raise ValueError(f"Jedes Element in '{key}' muss ein Tuple mit zwei Elementen sein.")
        else:
            if not isinstance(value, bool):
                raise TypeError(f"'{key}' muss ein Boolean sein.")

    print("Starting tray monitoring...")

    menu = Menu(
        MenuItem("Restart", lambda icon_inst, item: _on_restart(icon_inst, item)),
        MenuItem("Exit", lambda icon_inst, item: _on_quit(icon_inst, item))
    )

    def update_cpu(percent):  # Dummy-Wert, tatsächliche Auswertung erfolgt kontrolliert
        if not selected_components['cpu']:
            return

        # CPU-Werte kontrolliert ermitteln
        try:
            logical = psutil.cpu_count(logical=True)
            physical = psutil.cpu_count(logical=False)
            cpu_percentages = psutil.cpu_percent(interval=None, percpu=True)

            num_cores = logical if logical else physical
            core_usages = cpu_percentages[:num_cores]

            if not core_usages:
                raise ValueError("Keine CPU-Werte erhalten.")

            avg_cpu_percent = sum(core_usages) / len(core_usages)
            percent = round_to_nearest_five(avg_cpu_percent)
        except Exception as e:
            print(f"[ERROR] CPU-Auswertung fehlgeschlagen: {e}")
            percent = 0
            core_usages = []
            num_cores = 0

        # Icon-Update
        image = create_bar_icon(percent, "CPU")
        key = "CPU_USAGE"
        if key not in icons:
            icon = Icon(key, image, menu=menu)
            icons[key] = {"icon": icon, "label": "CPU"}
            print(f"Created CPU icon")
            threading.Thread(target=icon.run, daemon=True).start()
        else:
            icons[key]["icon"].icon = image

        # Tooltip
        try:
            cores_str = " | ".join([f"{int(p)}%" for p in core_usages])
            tooltip = f"{num_cores} Cores: {cores_str}"
            tooltip = tooltip[:127]
            update_tray_tooltip(key, tooltip)
        except Exception:
            tooltip = f"CPU {percent}%"

        #icons[key]["icon"].title = tooltip


    def update_ram(percent):
        if not selected_components['ram']:
            return
        percent = round_to_nearest_five(percent)
        image = create_bar_icon(percent, "RAM")
        key = "RAM_USAGE"
        if key not in icons:
            icon = Icon(key, image, menu=menu)
            icons[key] = {"icon": icon, "label": "RAM"}
            print(f"Created RAM icon")
            threading.Thread(target=icon.run, daemon=True).start()
        else:
            icons[key]["icon"].icon = image

        try:
            mem = psutil.virtual_memory()
            used_gb = round(mem.used / (1024 ** 3))
            total_gb = round(mem.total / (1024 ** 3))
            tooltip = f"RAM {used_gb} / {total_gb} GB"
            update_tray_tooltip(key, tooltip)
        except Exception:
            tooltip = f"RAM: {percent}%"
        #icons[key]["icon"].title = tooltip


    gpu_info_list = hardware_info.get('gpu_info', [])
    gpu_names = {i: gpu['name'] for i, gpu in enumerate(gpu_info_list)}


    def update_gpu_sensor_data(gpu_idx, gpu_name, util, mem_used, mem_total, temp, max_temp):
        """Unified GPU sensor updater for both NVIDIA and AMD."""
        if not selected_components['gpu']:
            return

        gpu_key = str(gpu_idx)
        # Consistent labels: GPU0, VR0, T0, etc.
        label_temp = f"T{gpu_key}"
        label_vram = f"VR{gpu_key}"
        label_gpu = f"GPU{gpu_key}"

        # Icon registry keys
        key_temp = f"GPU_{gpu_key}_TEMP"
        key_vram = f"GPU_{gpu_key}_VRAM"
        key_gpu = f"GPU_{gpu_key}_LOAD"

        # === Temperatur ===
        temp_rounded = round(temp)
        clamped = max(30, min(temp, max_temp))
        pct = round((clamped - 30) / (max_temp - 30) * 100) if max_temp > 30 else 0
        image_temp = create_bar_icon(pct, label_temp)

        if key_temp not in icons:
            try:
                icon = Icon(key_temp, image_temp, menu=menu)
                icons[key_temp] = {"icon": icon, "label": label_temp}
                print(f"Created GPU temp icon for {gpu_key}")
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e:
                print(f"Error creating GPU temp icon: {e}")
        else:
            icons[key_temp]["icon"].icon = image_temp

        # Tooltip: Full GPU name + metric
        tooltip_temp = f"{gpu_name}\n{label_temp}: {temp_rounded} °C / {max_temp} °C"
        update_tray_tooltip(key_temp, tooltip_temp[:127])
        time.sleep(0.01)

        # === VRAM ===
        vram_util = round_to_nearest_five(mem_used / mem_total * 100) if mem_total > 0 else 0
        image_vram = create_bar_icon(vram_util, label_vram)

        if key_vram not in icons:
            try:
                icon = Icon(key_vram, image_vram, menu=menu)
                icons[key_vram] = {"icon": icon, "label": label_vram}
                print(f"Created GPU VRAM icon for {gpu_key}")
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e:
                print(f"Error creating GPU VRAM icon: {e}")
        else:
            icons[key_vram]["icon"].icon = image_vram

        used_gb = round(mem_used / (1024**3))
        total_gb = round(mem_total / (1024**3))
        tooltip_vram = f"{gpu_name}\n{label_vram}: {used_gb}/{total_gb} GB"
        update_tray_tooltip(key_vram, tooltip_vram[:127])
        time.sleep(0.01)

        # === Load ===
        image_gpu = create_bar_icon(round(util), label_gpu)

        if key_gpu not in icons:
            try:
                icon = Icon(key_gpu, image_gpu, menu=menu)
                icons[key_gpu] = {"icon": icon, "label": label_gpu}
                print(f"Created GPU load icon for {gpu_key}")
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e:
                print(f"Error creating GPU load icon: {e}")
        else:
            icons[key_gpu]["icon"].icon = image_gpu

        tooltip_gpu = f"{gpu_name}\n{label_gpu}: {round(util)}%"
        update_tray_tooltip(key_gpu, tooltip_gpu[:127])


    def update_amd_gpu_sensor_data(gpu_idx: int, gpu_name: str, util: float, mem_used_mb: float, mem_total_mb: float, temp: float, max_temp: float) -> None:
        """AMD-specific sensor updater. Explicitly handles MB-to-GB conversion."""
        if not selected_components['gpu']:
            return

        gpu_key = str(gpu_idx)
        label_temp = f"T{gpu_key}"
        label_vram = f"VR{gpu_key}"
        label_gpu = f"GPU{gpu_key}"

        key_temp = f"GPU_{gpu_key}_TEMP"
        key_vram = f"GPU_{gpu_key}_VRAM"
        key_gpu = f"GPU_{gpu_key}_LOAD"

        # === Temperatur ===
        temp_rounded = round(temp)
        clamped = max(30, min(temp, max_temp))
        pct = round((clamped - 30) / (max_temp - 30) * 100) if max_temp > 30 else 0
        image_temp = create_bar_icon(pct, label_temp)

        if key_temp not in icons:
            try:
                icon = Icon(key_temp, image_temp, menu=menu)
                icons[key_temp] = {"icon": icon, "label": label_temp}
                print(f"[INFO] Created AMD GPU temp icon for {gpu_key}")
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e:
                print(f"[WARN] Error creating AMD GPU temp icon: {e}")
        else:
            icons[key_temp]["icon"].icon = image_temp

        tooltip_temp = f"{gpu_name}\n{label_temp}: {temp_rounded} °C / {max_temp} °C"
        update_tray_tooltip(key_temp, tooltip_temp[:127])
        time.sleep(0.01)

        # === VRAM ===
        # LibreHardwareMonitor reports memory in MB. Convert to GB.
        mem_used_gb = mem_used_mb / 1024.0
        mem_total_gb = mem_total_mb / 1024.0
        vram_util = round_to_nearest_five(mem_used_gb / mem_total_gb * 100) if mem_total_gb > 0 else 0
        image_vram = create_bar_icon(vram_util, label_vram)

        if key_vram not in icons:
            try:
                icon = Icon(key_vram, image_vram, menu=menu)
                icons[key_vram] = {"icon": icon, "label": label_vram}
                print(f"[INFO] Created AMD GPU VRAM icon for {gpu_key}")
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e:
                print(f"[WARN] Error creating AMD GPU VRAM icon: {e}")
        else:
            icons[key_vram]["icon"].icon = image_vram

        used_gb = round(mem_used_gb)
        total_gb = round(mem_total_gb)
        tooltip_vram = f"{gpu_name}\n{label_vram}: {used_gb}/{total_gb} GB"
        update_tray_tooltip(key_vram, tooltip_vram[:127])
        time.sleep(0.01)

        # === Load ===
        image_gpu = create_bar_icon(round(util), label_gpu)

        if key_gpu not in icons:
            try:
                icon = Icon(key_gpu, image_gpu, menu=menu)
                icons[key_gpu] = {"icon": icon, "label": label_gpu}
                print(f"[INFO] Created AMD GPU load icon for {gpu_key}")
                threading.Thread(target=icon.run, daemon=True).start()
            except Exception as e:
                print(f"[WARN] Error creating AMD GPU load icon: {e}")
        else:
            icons[key_gpu]["icon"].icon = image_gpu

        tooltip_gpu = f"{gpu_name}\n{label_gpu}: {round(util)}%"
        update_tray_tooltip(key_gpu, tooltip_gpu[:127])



    def gpu_monitor():
        """NVIDIA monitoring loop with safe init & early exit."""
        try:
            pynvml.nvmlInit()
        except pynvml.NVMLError as e:
            print(f"[WARN] NVML not available. NVIDIA monitoring skipped.")
            return
        except Exception as e:
            print(f"[WARN] NVML init failed: {e}")
            return

        nvidia_data = []
        try:
            for idx in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                try:
                    max_temp = pynvml.nvmlDeviceGetTemperatureThreshold(handle, pynvml.NVML_TEMPERATURE_THRESHOLD_GPU_MAX)
                except pynvml.NVMLError:
                    max_temp = 90
                nvidia_data.append((idx, handle, max_temp))
        except pynvml.NVMLError as e:
            print(f"[WARN] Failed to fetch NVIDIA GPU data: {e}")
            pynvml.nvmlShutdown()
            return

        if not nvidia_data:
            print("[INFO] NVIDIA monitoring skipped: No NVIDIA GPUs found.")
            pynvml.nvmlShutdown()
            return

        try:
            while not shutdown_event.is_set():
                for idx, handle, max_temp in nvidia_data:
                    try:
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                        gpu_name = gpu_names.get(idx, f"GPU {idx}")
                        update_gpu_sensor_data(idx, gpu_name, util, mem.used, mem.total, temp, max_temp)
                    except pynvml.NVMLError as e:
                        print(f"[WARN] GPU{idx} sensor error: {e}")
                    time.sleep(0.05)
                time.sleep(0.4)
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass          



    def amd_gpu_monitor():
        """AMD monitoring loop with safe clr/DLL handling & early exit."""
        hw = None  # Prevent UnboundLocalError in finally
        try:
            # ✅ DLL path is already resolved & CLR loaded in main.py
            from LibreHardwareMonitor import Hardware as LHM_Hardware

            hw = LHM_Hardware.Computer()
            hw.IsGpuEnabled = True
            hw.IsCpuEnabled = False
            hw.IsMemoryEnabled = False
            hw.IsMotherboardEnabled = False
            hw.IsStorageEnabled = False
            hw.IsNetworkEnabled = False
            hw.IsControllerEnabled = False
            hw.Open()

            amd_hws = []
            for hardware in hw.Hardware:
                if "Amd" in hardware.HardwareType.ToString():
                    idx = next((i for i, name in gpu_names.items() if name == hardware.Name), None)
                    if idx is not None:
                        amd_hws.append((idx, hardware))

            if not amd_hws:
                print("[INFO] AMD monitoring skipped: No AMD GPUs found.")
                hw.Close()
                return

            while not shutdown_event.is_set():
                for idx, hardware in amd_hws:
                    hardware.Update()
                    temp = None
                    load = None
                    mem_used = None
                    mem_total = None
                    
                    for sensor in hardware.Sensors:
                        s_name = sensor.Name.lower()
                        s_type = sensor.SensorType.ToString()
                        val = sensor.Value
                        if s_type == "Temperature" and "core" in s_name:
                            temp = val
                        elif s_type == "Load" and ("core" in s_name or "gpu" in s_name):
                            load = val
                        elif "GPU Memory Used" in s_name:
                            mem_used = val
                        elif "GPU Memory Total" in s_name:
                            mem_total = val

                    if selected_components['gpu'] and temp is not None:
                        update_amd_gpu_sensor_data(
                            idx, gpu_names[idx],
                            load or 0.0,
                            mem_used or 0.0,
                            mem_total or 0.0,
                            temp or 0.0,
                            100.0  # Fallback max_temp for AMD
                        )
                        time.sleep(0.01)
                time.sleep(0.5)
        except ImportError:
            print("[WARN] pythonnet not installed. AMD monitoring skipped.")
        except Exception as e:
            print(f"[WARN] AMD monitoring failed: {e}")
        finally:
            if hw is not None:
                try:
                    hw.Close()
                except Exception:
                    pass





    def cpu_monitor():
        while not shutdown_event.is_set():
            try:
                update_cpu(psutil.cpu_percent(interval=None))
            except Exception as e:
                print(f"[ERROR] CPU Monitoring Fehler: {e}")
            time.sleep(0.5)

    def ram_monitor():
        while not shutdown_event.is_set():
            try:
                mem = psutil.virtual_memory()
                update_ram(mem.percent)
            except Exception as e:
                print(f"[ERROR] RAM Monitoring Fehler: {e}")
            time.sleep(0.5)

    def wmi_monitor(poll_interval=2):
        # if polinterval change -> set MB/s and kb/s
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        c = wmi.WMI(namespace="root\\CIMV2")
        prev_disk_counters = {}
        prev_net_stats = {}
        speeds = get_adapter_speeds()

        active_adapters = get_active_network_adapters()
        adapter_map = {active: find_best_match(active, list(speeds.keys())) for active in active_adapters}

        try:
            next_time = time.perf_counter()
            while not shutdown_event.is_set():
            #while True:
                try:

                    # Drives
                    perf_logical_disks = {
                        disk.Name.upper(): disk
                        for disk in c.Win32_PerfRawData_PerfDisk_LogicalDisk()
                    }

                    for dev, part in selected_components.get('drives', []):
                        if not selected_components['drives']:
                            continue

                        perf_disk = perf_logical_disks.get(part)
                        if not perf_disk:
                            continue

                        read_bytes = int(perf_disk.DiskReadBytesPerSec)
                        write_bytes = int(perf_disk.DiskWriteBytesPerSec)
                        prev_read, prev_write = prev_disk_counters.get(part, (0, 0))
                        read_diff = max(0, read_bytes - prev_read)
                        write_diff = max(0, write_bytes - prev_write)
                        prev_disk_counters[part] = (read_bytes, write_bytes)

                        mb_read = read_diff / 1024 / 1024 / 1
                        mb_write = write_diff / 1024 / 1024 / 1

                        key = f"{dev}_{part}"
                        color = get_color(mb_read > 2.0, mb_write > 2.0, mb_read, mb_write)

                        update_tray_color(key, color)
                        update_tray_tooltip(key, f"{part} R {int(mb_read)} MB/s | W {int(mb_write)} MB/s")

                    # Network
                    
                    perf_net_ifaces = c.Win32_PerfRawData_Tcpip_NetworkInterface()

                    for iface in perf_net_ifaces:
                        iface_name = getattr(iface, 'Name', None)
                        if not iface_name:
                            continue

                        adapter_name = find_best_match(iface_name, list(adapter_map.keys()))
                        if not adapter_name or not selected_components['network']:
                            continue

                        send_raw = int(iface.BytesSentPersec)
                        recv_raw = int(iface.BytesReceivedPerSec)

                        #print(f"Raw Network Data - Send: {send_raw}, Recv: {recv_raw}")

                        prev_send, prev_recv = prev_net_stats.get(adapter_name, (0, 0))
                        send_diff = max(0, send_raw - prev_send)
                        recv_diff = max(0, recv_raw - prev_recv)

                        #print(f"Network Diff Data - Send: {send_diff}, Recv: {recv_diff}")

                        prev_net_stats[adapter_name] = (send_raw, recv_raw)

                        # Convert bytes to KB
                        send_kb = send_diff / 1024 / 1
                        recv_kb = recv_diff / 1024 / 1

                        #print(f"Converted Network Data - Send: {send_kb} KB/s, Recv: {recv_kb} KB/s")

                        update_net_icons(adapter_name, send_kb, recv_kb, selected_components)

                except Exception as e:
                    print(f"[ERROR] Unified WMI Monitor: {e}")

                next_time += poll_interval
                time.sleep(max(0, next_time - time.perf_counter()))

        finally:
            pythoncom.CoUninitialize()


    # The timer is absolutely essential for determining the order in which the icons are created on the taskbar.

    # ✅ Check availability flags BEFORE starting threads
    nvidia_available = hardware_info.get('_nvidia_available', False)
    amd_available = hardware_info.get('_amd_available', False)

    if selected_components['cpu']:
        start_monitor_thread(cpu_monitor)
        time.sleep(0.3)

    if selected_components['ram']:
        start_monitor_thread(ram_monitor)
        time.sleep(0.3)
        
    if selected_components['gpu'] and nvidia_available:
        start_monitor_thread(gpu_monitor)
        time.sleep(0.3)

    if selected_components['gpu'] and amd_available:
        start_monitor_thread(amd_gpu_monitor)
        time.sleep(0.3)

    if selected_components['network']:
        start_monitor_thread(wmi_monitor)
        time.sleep(2)

    # Start tray icons for drives based on user selection
    if selected_components['drives']:
        device_map = hardware_info.get('drive_map', {})
        drive_selections = selected_components['drives']
        time.sleep(0.3)
        start_drive_icons(hardware_info, device_map, drive_selections)


    print("All tray monitoring components started.")


