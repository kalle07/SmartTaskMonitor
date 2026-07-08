# hardware.py
import psutil
import wmi
import pynvml
import threading
import time
import clr
import os
import sys




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


def safe_call(func, name):
    try:
        return func()
    except Exception as e:
        print(f"[WARN] {name} konnte nicht geladen werden: {e}")
        return None


def get_physical_drives_with_partitions_and_labels():
    c = wmi.WMI()
    drive_map = {}

    for disk in c.Win32_DiskDrive():
        disk_id = disk.DeviceID.split("\\")[-1].upper()
        if disk_id not in drive_map:
            drive_map[disk_id] = []

        partitions = disk.associators("Win32_DiskDriveToDiskPartition")
        for partition in partitions:
            logical_disks = partition.associators("Win32_LogicalDiskToPartition")
            for logical_disk in logical_disks:
                letter = logical_disk.DeviceID.upper().strip()
                volume_name = logical_disk.VolumeName or "Kein Name"
                if not any(d["letter"] == letter for d in drive_map[disk_id]):
                    drive_map[disk_id].append({
                        "letter": letter,
                        "label": volume_name
                    })
    print("[DEBUG] Drive Info:", drive_map)
    return drive_map



def get_cpu_info():
    cpu_freq = psutil.cpu_freq()
    cpu_info = {
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "frequency": round(cpu_freq.max) if cpu_freq else None,
    }
    return cpu_info


def get_ram_info():
    mem = psutil.virtual_memory()
    ram_info = {
        "total_gb": round(mem.total / (1024 ** 3)),
        "available_gb": round(mem.available / (1024 ** 3)),
    }
    print("[DEBUG] RAM Info:", ram_info)
    return ram_info



def get_gpu_info():
    """Returns (gpu_info_list, nvidia_available_flag)"""
    gpu_info = []
    nvidia_available = False
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count > 0:
            nvidia_available = True
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name_raw = pynvml.nvmlDeviceGetName(handle)
                name = name_raw.decode() if isinstance(name_raw, bytes) else name_raw
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                try:
                    max_temp = pynvml.nvmlDeviceGetTemperatureThreshold(handle, pynvml.NVML_TEMPERATURE_THRESHOLD_GPU_MAX)
                except Exception:
                    max_temp = 90
                gpu_info.append({
                    "name": name,
                    "memory_total_mb": int(mem_info.total / 1024**2),
                    "max_temp": max_temp
                })
    except Exception as e:
        print(f"[WARN] NVIDIA detection failed: {e}")
    finally:
        try: pynvml.nvmlShutdown()
        except: pass
    return gpu_info, nvidia_available



def get_amd_gpu_info() -> tuple[list[dict], bool]:
    """Returns (amd_gpu_info_list, amd_available_flag)"""
    amd_gpus = []
    amd_available = False
    try:
        # ✅ CLR already loaded in main.py; direct import is sufficient
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

        for hardware in hw.Hardware:
            if "Amd" in hardware.HardwareType.ToString():
                amd_available = True
                hardware.Update()
                name = hardware.Name
                temp = load = mem_used = mem_total = None
                for sensor in hardware.Sensors:
                    s_name = sensor.Name.lower()
                    s_type = sensor.SensorType.ToString()
                    val = sensor.Value
                    if s_type == "Temperature" and "core" in s_name: temp = val
                    elif s_type == "Load" and ("core" in s_name or "gpu" in s_name): load = val
                    elif "memory used" in s_name: mem_used = val
                    elif "memory total" in s_name: mem_total = val

                amd_gpus.append({
                    "name": name,
                    "memory_total_mb": int(mem_total) if mem_total else 0,
                    "max_temp": 100,
                    "current_temp": temp,
                    "load": load,
                    "memory_used_mb": mem_used
                })
        hw.Close()
    except ImportError:
        print("[WARN] pythonnet not installed. AMD detection skipped.")
    except Exception as e:
        print(f"[WARN] AMD detection failed: {e}")
    return amd_gpus, amd_available


def get_network_adapters():
    c = wmi.WMI()
    adapters = []
    for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
        if hasattr(nic, 'Description'):
            adapters.append(nic.Description)
    print("[DEBUG] Network Adapters:", adapters)
    return adapters


def detect_hardware(dll_path: str) -> dict:
    drive_map = safe_call(get_physical_drives_with_partitions_and_labels, "Laufwerke") or {}
    cpu_info = safe_call(get_cpu_info, "CPU") or {}
    ram_info = safe_call(get_ram_info, "RAM") or {}
    network_adapters = safe_call(get_network_adapters, "Netzwerkadapter") or []
    
    gpu_info, nvidia_available = get_gpu_info()
    amd_gpu_info, amd_available = get_amd_gpu_info()
    gpu_info.extend(amd_gpu_info)

    return {
        'cpu_info': cpu_info,
        'ram_info': ram_info,
        'gpu_info': gpu_info,
        'network_adapters': network_adapters,
        'drive_map': drive_map,
        '_nvidia_available': nvidia_available,
        '_amd_available': amd_available
    }



def main():
    print("[INFO] Starte Hardware-Erkennung...\n")
    hardware_info = detect_hardware()

    # Optional: Ausgabe der erkannten Hardware (kann auskommentiert werden)
    #for key, value in hardware_info.items():
    #    print(f"[RESULT] {key}: {value}")

    print("\n[INFO] Warte 5 Sekunden...")
    time.sleep(5)
    print("[INFO] Hardware Erkennung beendet.")

if __name__ == "__main__":
    main()

