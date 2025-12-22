# SmartTaskTool
Tray-Icons for Task-Bar: Drives, CPU, GPU, Network
=> only windows! (only Nvidia atm)

exe file on huggingface or right side -> "releases":
https://huggingface.co/kalle07/SmartTaskTool

* Read / Write - Detection on your Hard Drives<br>
* CPU - Usage<br>
* RAM - Usage<br>
* GPU - Usage (all only nvidia)<br>
* VRAM - Usage<br>
* GPU Temperature<br>
* Network - download/upload<br>
-> Update once per second<br>

My Icons look like this: (depending on hard drives/partitions, Network, GPU)<br>
<img width="720" height="224" alt="grafik" src="https://github.com/user-attachments/assets/77123810-4938-452a-a4cf-7a6ba2eabcc2" />
<br><br>
At start you can choose:<br>
<img width="481" height="569" alt="grafik" src="https://github.com/user-attachments/assets/2e35330b-75a3-4070-a4c2-10a11db5585d" />
<br>
<br>
SmartTaskTool is a Windows-only utility designed to monitor various hardware parameters on your system. It tracks disk read/write activity, CPU usage, RAM usage, and GPU information (limited to Nvidia GPUs), including VRAM usage and GPU temperature. The tool also monitors network activity (download/upload rates) across all connected network adapters. The software updates its metrics once per second and displays them in the system tray with icons that indicate the status of your hardware (e.g., color-coded for disk activity).
<br><br>

Python (4 files, start main) or exe.
I use psutil, wmi and pynvml.
Iam not a coder so its a co-work of Ai and my brain ;)

GPU should be work with multi GPUs if nvidia, AMD has no python lib for windows. 
Network should be work with all connected network adapters (in tray-icon no name, but with mouse hover over you will see).
On start you will see a GUI, you have 10 secons to choose hardware.
<br>

Further work:
* Iam on it to implement to save a config-file for reuse 
* Iam on implement AMD GPU (need help with librehardware, I have all I need only how looks like the list, would be nice if you can help)
<br>

Hints:<br>
Drive threshold 2MB/s (this means that only larger actions are displayed)<br>
red - writing | green - reading | yellow - <read/write><br>
Network start at 0.1kB/s up to GB/s<br>
Mouse hover - You see a little more detail, but it is not updated<br>
If you put in autostart, try to delay start 5 to 10sec<br>
mause "right click" - EXIT or Restart<br>
<br>

<b>=> All at your own risk !!!</b>
