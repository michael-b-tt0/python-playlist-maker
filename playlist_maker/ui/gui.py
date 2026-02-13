# playlist_maker/ui/gui.py

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, font
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import threading
import queue
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# Ensure script dir is in path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from ..app import main as pm_main
    from ..core import constants as pm_constants
except ImportError as e:
    logging.critical(f"GUI: CRITICAL IMPORT ERROR: {e}", exc_info=True)
    sys.exit(1)

class TkinterLogHandler(logging.Handler):
    def __init__(self, text_widget: scrolledtext.ScrolledText):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue()
        self.text_widget.tag_config("INFO", foreground="white")
        self.text_widget.tag_config("WARNING", foreground="orange")
        self.text_widget.tag_config("ERROR", foreground="red")
        self.text_widget.tag_config("DEBUG", foreground="gray")
        self.text_widget.after(100, self.poll_log_queue)

    def emit(self, record):
        self.queue.put(record)

    def poll_log_queue(self):
        try:
            while True:
                record = self.queue.get(block=False)
                msg = self.format(record)
                self.text_widget.configure(state='normal')
                self.text_widget.insert(tk.END, msg + "\n", (record.levelname,))
                self.text_widget.see(tk.END)
                self.text_widget.configure(state='disabled')
        except queue.Empty:
            pass
        finally:
            self.text_widget.after(100, self.poll_log_queue)

class PlaylistMakerGUI:
    def __init__(self, root: ttk.Window):
        self.root = root
        self.root.title("Deepmind Playlist Maker (Folder Mode)")
        self.root.geometry("900x700")
        
        # Data
        self.folder_paths: List[str] = []

        # Style
        self.style = ttk.Style(theme="cyborg")
        
        # Main Layout
        # Main Layout
        main_frame = ttk.Frame(self.root, padding="10") # Keep padding here if it works for Frame, or change? The user error was on LabelFrame. 
        # Wait, user error stack trace:
        # File "J:\python\python-playlist-maker\playlist_maker\ui\gui.py", line 73, in __init__
        # folder_frame = ttk.LabelFrame(main_frame, text="Album Folders", padding=10)
        # So I definitely need to change LabelFrame.
        
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Folder Selection Area ---
        folder_frame = ttk.LabelFrame(main_frame, text="Album Folders") # Remove padding arg from constructor
        folder_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10), padx=10, ipadx=5, ipady=5) # Apply spacing via pack/internal

        # Listbox with Scrollbar
        list_frame = ttk.Frame(folder_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10) # Add padding to inner frame pack
        
        self.folder_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=10, bg="#2b2b2b", fg="white", borderwidth=0)
        self.folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.folder_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_listbox.config(yscrollcommand=scrollbar.set)

        # Buttons for Folders
        btn_frame = ttk.Frame(folder_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10), padx=10) # Padding for button frame
        
        ttk.Button(btn_frame, text="Add Folder(s)", command=self.add_folders, style="success.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_selected_folders, style="danger.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Clear All", command=self.clear_all_folders, style="warning.TButton").pack(side=tk.LEFT, padx=5)

        # --- Options Area ---
        options_frame = ttk.LabelFrame(main_frame, text="Options") # Remove padding
        options_frame.pack(fill=tk.X, pady=(0, 10))

        # Inner frame for options content to manage padding
        options_inner = ttk.Frame(options_frame)
        options_inner.pack(fill=tk.X, padx=10, pady=10)

        # Match Threshold
        ttk.Label(options_inner, text="Fuzzy Match Threshold:").pack(side=tk.LEFT, padx=5)
        self.threshold_var = tk.IntVar(value=80)
        self.threshold_scale = ttk.Scale(options_inner, from_=50, to=100, variable=self.threshold_var, length=200, orient=tk.HORIZONTAL)
        self.threshold_scale.pack(side=tk.LEFT, padx=5)
        ttk.Label(options_inner, textvariable=self.threshold_var).pack(side=tk.LEFT, padx=5)

        # Output Directory (Optional override)
        ttk.Label(options_inner, text="Output Dir:").pack(side=tk.LEFT, padx=(20, 5))
        self.output_dir_var = tk.StringVar(value=pm_constants.DEFAULT_OUTPUT_DIR)
        ttk.Entry(options_inner, textvariable=self.output_dir_var, width=30).pack(side=tk.LEFT, padx=5)
        ttk.Button(options_inner, text="Browse...", command=self.browse_output).pack(side=tk.LEFT, padx=5)

        # --- Action Area ---
        action_frame = ttk.Frame(main_frame) # Remove padding
        action_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.generate_btn = ttk.Button(action_frame, text="GENERATE PLAYLIST", command=self.start_generation, style="primary.TButton", width=30)
        self.generate_btn.pack(pady=10) # Padding on pack

        # --- Log Area ---
        log_frame = ttk.LabelFrame(main_frame, text="Log Output") # Remove padding
        log_frame.pack(fill=tk.BOTH, expand=True)

        # Inner frame for log to manage padding
        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_inner, state='disabled', bg="#1e1e1e", fg="white", font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Setup Logging
        self.setup_logging()

    def setup_logging(self):
        handler = TkinterLogHandler(self.log_text)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def add_folders(self):
        selected_paths: List[str] = []
        try:
            # Use native Tk chooser with multi-select when supported by the platform/Tk build.
            folders = self.root.tk.call(
                "tk_chooseDirectory",
                "-title",
                "Select Album Folder(s)",
                "-mustexist",
                "1",
                "-multiple",
                "1",
            )
            if folders:
                selected_paths = [os.path.normpath(p) for p in self.root.tk.splitlist(folders)]
        except tk.TclError:
            # Fallback for Tk builds that do not support -multiple.
            folder = filedialog.askdirectory(title="Select Album Folder", mustexist=True)
            if folder:
                selected_paths = [os.path.normpath(folder)]

        for path in selected_paths:
            if path not in self.folder_paths:
                self.folder_paths.append(path)
                self.folder_listbox.insert(tk.END, path)

    def remove_selected_folders(self):
        selection = self.folder_listbox.curselection()
        for index in reversed(selection):
            path = self.folder_listbox.get(index)
            self.folder_paths.remove(path)
            self.folder_listbox.delete(index)

    def clear_all_folders(self):
        self.folder_paths.clear()
        self.folder_listbox.delete(0, tk.END)

    def browse_output(self):
        d = filedialog.askdirectory()
        if d: self.output_dir_var.set(d)

    def start_generation(self):
        if not self.folder_paths:
            messagebox.showwarning("No Folders", "Please add at least one album folder.")
            return

        self.generate_btn.config(state=tk.DISABLED, text="Processing...")
        
        # Prepare arguments for app.main
        argv = ["--folders"] + self.folder_paths
        argv += ["--output-dir", self.output_dir_var.get()]
        argv += ["--threshold", str(self.threshold_var.get())]
        
        thread = threading.Thread(target=self.run_process, args=(argv,), daemon=True)
        thread.start()

    def run_process(self, argv):
        try:
            result = pm_main(argv, clean_log_handlers=False)
            if result.get("success"):
                self.root.after(0, lambda: messagebox.showinfo("Success", f"Playlist generated!\nSaved to: {result.get('playlist_path')}"))
            else:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed: {result.get('error')}"))
        except Exception as e:
            logging.error(f"GUI Error: {e}", exc_info=True)
            err_msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", f"An unexpected error occurred: {err_msg}"))
        finally:
            self.root.after(0, lambda: self.generate_btn.config(state=tk.NORMAL, text="GENERATE PLAYLIST"))

if __name__ == "__main__":
    root = ttk.Window(themename="cyborg")
    app = PlaylistMakerGUI(root)
    root.mainloop()
