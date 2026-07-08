# gui.py

import wx

class MainFrame(wx.Frame):

    MAX_WIDTH = 1000
    MAX_HEIGHT = 1000
    MIN_WIDTH = 300
    MIN_HEIGHT = 200

    def __init__(self, *args, hardware_info=None, result_queue=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hardware_info = hardware_info or {}
        self.result_queue = result_queue
        self._submitted = False

        self.selected_components = {
            'cpu': True,
            'ram': True,
            'gpu': True,
            'network': True,
            'drives': []
        }

        # EVT_CLOSE binden
        self.Bind(wx.EVT_CLOSE, self.on_close)

        # Checkboxen speichern: Dictionary mit Kategorie als Key und Liste von Checkboxes als Value
        self.checkboxes = {}

        self.panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(self.panel, label="Window will self-close in 10 sec")
        vbox.Add(info, 0, wx.ALL, 10)

        auto_close_info = wx.StaticText(
            self.panel,
            label="Drive monitoring (read/write) every second\nThreshold 2MB"
        )
        vbox.Add(auto_close_info, 0, wx.LEFT | wx.BOTTOM, 10)

        tray_info = wx.StaticText(
            self.panel,
            label="(Hover over tray icon to see further information)"
        )
        vbox.Add(tray_info, 0, wx.LEFT | wx.BOTTOM, 10)

        # CPU-Info: eine Checkbox mit zusammengesetzten Infos
        if hardware_info.get('cpu_info'):
            cpu_info = hardware_info['cpu_info']
            cpu_label = (f"CPU Info: Logical cores: {cpu_info.get('logical_cores')}, "
                         f"Physical cores: {cpu_info.get('physical_cores')}, "
                         f"Frequency: {cpu_info.get('frequency', 'N/A')} MHz")
            checkbox = wx.CheckBox(self.panel, label=cpu_label)
            checkbox.SetValue(True)
            vbox.Add(checkbox, 0, wx.LEFT | wx.BOTTOM, 10)
            self.checkboxes['cpu'] = [checkbox]

        # RAM-Info: eine Checkbox mit zusammengesetzten Infos
        if hardware_info.get('ram_info'):
            ram_info = hardware_info['ram_info']
            ram_label = (f"RAM Info: Total: {ram_info.get('total_gb', 'N/A')} GB, "
                         f"Available: {ram_info.get('available_gb', 'N/A')} GB")
            checkbox = wx.CheckBox(self.panel, label=ram_label)
            checkbox.SetValue(True)
            vbox.Add(checkbox, 0, wx.LEFT | wx.BOTTOM, 10)
            self.checkboxes['ram'] = [checkbox]

        # GPU-Info
        if hardware_info.get('gpu_info'):
            self.add_section(vbox, "GPU Info:", [
                f"{gpu['name']} ({gpu['memory_total_mb']} MB VRAM / MaxTemp: {gpu['max_temp']} °C)"
                for gpu in hardware_info['gpu_info']
            ], category="gpu")

        # Netzwerkadapter
        if hardware_info.get('network_adapters'):
            self.add_section(vbox, "Active Network Adapters:", hardware_info['network_adapters'], category="network")

        # Drive-Info
        if hardware_info.get('drive_map'):
            self.add_drive_section(vbox)

        # Submit Button
        self.submit_button = wx.Button(self.panel, label="Submit and Close (10)")
        self.submit_button.Bind(wx.EVT_BUTTON, self.on_submit)
        vbox.Add(self.submit_button, 0, wx.ALL | wx.CENTER, 10)

        self.panel.SetSizer(vbox)
        self.panel.Layout()
        self.submit_button.SetFocus()
        self.SetDefaultItem(self.submit_button)

        best_size = self.panel.GetBestSize()
        width = min(max(best_size.width, self.MIN_WIDTH), self.MAX_WIDTH)
        height = min(max(best_size.height, self.MIN_HEIGHT), self.MAX_HEIGHT)
        self.SetClientSize((width, height))
        self.SetPosition((200,100))
        self.SetTitle("SmartTaskTool by Sevenof9")

        self.countdown_timer = 10
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_countdown, self.timer)
        self.timer.Start(1000)  # Update every second

    def update_countdown(self, event):
        self.countdown_timer -= 1
        if self.countdown_timer <= 0:
            self.submit_values()
            self.timer.Stop()
        else:
            self.submit_button.SetLabel(f"Submit and Close ({self.countdown_timer})")

    def add_drive_section(self, vbox):
        drive_map = self.hardware_info.get('drive_map', {})
        vbox.Add(wx.StaticText(self.panel, label="Detected Drives:"), 0, wx.LEFT | wx.TOP, 10)
        for dev in sorted(drive_map.keys()):
            parts = drive_map[dev]
            for part_info in sorted(parts, key=lambda x: x['letter']):
                letter = part_info.get('letter', 'N/A')
                label = part_info.get('label', 'N/A')
                checkbox_label = f"{dev} - {letter} ({label})"
                checkbox = wx.CheckBox(self.panel, label=checkbox_label)
                checkbox.SetValue(True)
                vbox.Add(checkbox, 0, wx.LEFT | wx.BOTTOM, 10)

                if 'drives' not in self.checkboxes:
                    self.checkboxes['drives'] = []
                self.checkboxes['drives'].append((dev, letter, checkbox))

    def submit_values(self):
        if self._submitted:
            return
        self._submitted = True
        selected_components = {
            'cpu': False,
            'ram': False,
            'gpu': False,
            'network': False,
            'drives': []
        }

        checkbox_categories = ['cpu', 'ram', 'gpu', 'network']
        for category in checkbox_categories:
            if category in self.checkboxes:
                selected_components[category] = any(checkbox.GetValue() for checkbox in self.checkboxes[category])

        if 'drives' in self.checkboxes:
            for dev, part, checkbox in self.checkboxes['drives']:
                if checkbox.GetValue():
                    selected_components['drives'].append((dev, part))

        # Hardwareinfo ergänzen
        selected_components['cpu_info'] = self.hardware_info.get('cpu_info', {})
        selected_components['ram_info'] = self.hardware_info.get('ram_info', {})
        selected_components['gpu_info'] = self.hardware_info.get('gpu_info', [])
        selected_components['network_adapters'] = self.hardware_info.get('network_adapters', [])
        selected_components['drive_map'] = self.hardware_info.get('drive_map', {})

        print("[DEBUG] Auswahl:", selected_components)
        if self.result_queue:
            self.result_queue.put(selected_components)
        self.Close()

    def on_submit(self, event):
        print("[DEBUG] Submit-Button geklickt")
        self.submit_values()

    def add_section(self, vbox, title, items, category):
        vbox.Add(wx.StaticText(self.panel, label=title), 0, wx.LEFT | wx.TOP, 10)
        for item in items:
            checkbox = wx.CheckBox(self.panel, label=item)
            checkbox.SetValue(True)
            vbox.Add(checkbox, 0, wx.LEFT | wx.BOTTOM, 10)

            if category not in self.checkboxes:
                self.checkboxes[category] = []

            if category == "drives":
                # Assuming dev and part are extracted from item
                parts = item.split(":")
                if len(parts) == 2:
                    dev, part = parts
                    self.checkboxes[category].append((dev.strip(), part.strip(), checkbox))
            else:
                self.checkboxes[category].append(checkbox)

    
    def on_close(self, event):
        print("[DEBUG] Fenster wird geschlossen")

        if hasattr(self, 'timer') and self.timer.IsRunning():
            self.timer.Stop()

        if self.result_queue:
            # Leere Auswahl übermitteln
            selected_components = {
                'cpu': False,
                'ram': False,
                'gpu': False,
                'network': False,
                'drives': [],
                'cpu_info': self.hardware_info.get('cpu_info', {}),
                'ram_info': self.hardware_info.get('ram_info', {}),
                'gpu_info': self.hardware_info.get('gpu_info', []),
                'network_adapters': self.hardware_info.get('network_adapters', []),
                'drive_map': self.hardware_info.get('drive_map', {})
            }
            self.result_queue.put(selected_components)

        # Let wx handle the frame destruction & main loop exit naturally
        event.Skip()
        #old
        #self.Destroy()

        #app = wx.GetApp()
        #if app:
        #    app.ExitMainLoop()





if __name__ == "__main__":
    app = wx.App(False)

    # Layout
    hardware_info = {
        'cpu_info': {
            'logical_cores': 8,
            'physical_cores': 4,
            'frequency': 3200,
        },
        'ram_info': {
            'total_gb': 16,
            'available_gb': 10
        },
        'gpu_info': [
            {'name': 'NVIDIA GTX 1080', 'memory_total_mb': 8192, 'max_temp': 84}
        ],
        'network_adapters': ['Ethernet', 'Wi-Fi'],
        'drive_map': {
            'Disk0': [{'letter': 'C:', 'label': 'System'}, {'letter': 'D:', 'label': 'Recovery'}],
            'Disk1': [{'letter': 'E:', 'label': 'Data'}]
        }


    }

    frame = MainFrame(None, hardware_info=hardware_info)
    frame.Show()
    app.MainLoop()
