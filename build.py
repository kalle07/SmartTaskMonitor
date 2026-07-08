# build.py
import PyInstaller.__main__
import shutil
import os

APP_NAME = 'SmartTaskMonitor_by_Sevenof9'
DLL_NAME = 'LibreHardwareMonitorLib.dll'

for folder in ['build', 'dist', '__pycache__']:
    if os.path.exists(folder):
        shutil.rmtree(folder)

opts = [
    'main.py',
    f'--name={APP_NAME}',
    '--onefile', # dev mode
    #'--console', # dev mode
    '--noconsole', # user mode
    '--windowed', # user mode
    '--clean',
    '--log-level=WARN',
    '--add-data=DePixelSchmal.otf;.',
    f'--add-data={DLL_NAME};.', #  dll inside
    #'--add-data=gui.py;.',
    #'--add-data=hardware.py;.', 
    #'--add-data=tray.py;.',      
]

hidden_imports = [
    'win32com', 'pythoncom', 'pystray', 'pystray._win32', 'pystray._base',
    'wmi', 'pynvml', 'PIL', 'wx', 'difflib', 'psutil', 'clr', 'pythonnet',
    'clr_loader', 'LibreHardwareMonitor'
]
for imp in hidden_imports:
    opts.append(f'--hidden-import={imp}')

PyInstaller.__main__.run(opts)

# Copy DLL next to EXE for convenient testing/deployment
dist_exe = os.path.join('dist', f'{APP_NAME}.exe')
dll_src = os.path.abspath(DLL_NAME)
dll_dst = os.path.join(os.path.dirname(dist_exe), DLL_NAME)

if os.path.exists(dll_src):
    shutil.copy2(dll_src, dll_dst)
    print(f"[OK] {DLL_NAME} copied to dist/ as fallback.")
else:
    print(f"[WARN] {DLL_NAME} not found in source dir. Fallback copy skipped.")
