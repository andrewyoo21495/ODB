"""ECAD Checklist GUI - A graphical front-end for main.py check."""

from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path


class ChecklistGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ECAD Checklist")
        self.root.geometry("700x520")
        self.root.minsize(600, 450)

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # --- Title ---
        title = tk.Label(
            self.root, text="ECAD Checklist", font=("Arial", 16, "bold"),
        )
        title.pack(pady=(15, 10))

        # --- ODB file browse ---
        file_frame = tk.Frame(self.root)
        file_frame.pack(fill=tk.X, **pad)

        tk.Label(file_frame, text="ODB File:", width=10, anchor="w").pack(side=tk.LEFT)
        self.file_var = tk.StringVar()
        self.file_var.trace_add("write", self._on_file_changed)
        tk.Entry(file_frame, textvariable=self.file_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5),
        )
        tk.Button(file_frame, text="Browse", command=self._browse_file).pack(side=tk.LEFT)

        # --- Output path browse ---
        out_frame = tk.Frame(self.root)
        out_frame.pack(fill=tk.X, **pad)

        tk.Label(out_frame, text="Output:", width=10, anchor="w").pack(side=tk.LEFT)
        self.out_var = tk.StringVar()
        tk.Entry(out_frame, textvariable=self.out_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5),
        )
        tk.Button(out_frame, text="Browse", command=self._browse_output).pack(side=tk.LEFT)

        # --- Report format selection ---
        fmt_frame = tk.Frame(self.root)
        fmt_frame.pack(fill=tk.X, **pad)

        tk.Label(fmt_frame, text="Format:", width=10, anchor="w").pack(side=tk.LEFT)
        self.fmt_var = tk.StringVar(value="excel")
        fmt_combo = ttk.Combobox(
            fmt_frame, textvariable=self.fmt_var, state="readonly",
            values=["excel", "html", "excel html"],
            width=15,
        )
        fmt_combo.pack(side=tk.LEFT, padx=(0, 5))
        fmt_combo.bind("<<ComboboxSelected>>", self._on_file_changed)

        # --- Run button ---
        self.run_btn = tk.Button(
            self.root, text="Run Checklist", font=("Arial", 11, "bold"),
            command=self._run_checklist,
        )
        self.run_btn.pack(pady=10)

        # --- Result / log window ---
        log_frame = tk.LabelFrame(self.root, text="Execution Log")
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select ODB File",
            filetypes=[
                ("ODB++ files", "*.tgz *.zip *.tar *.gz"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.file_var.set(path)

    def _on_file_changed(self, *_args):
        odb_path = self.file_var.get().strip()
        if odb_path:
            parent = Path(odb_path).parent
            odb_name = Path(odb_path).name
            fmt = self.fmt_var.get().strip()
            ext = ".html" if fmt == "html" else ".xlsx"
            self.out_var.set(str(parent / f"[CKL_report]{odb_name}{ext}"))

    def _browse_output(self):
        fmt = self.fmt_var.get().strip()
        if fmt == "html":
            default_ext = ".html"
            filetypes = [("HTML files", "*.html"), ("All files", "*.*")]
        else:
            default_ext = ".xlsx"
            filetypes = [("Excel files", "*.xlsx"), ("HTML files", "*.html"),
                         ("All files", "*.*")]
        path = filedialog.asksaveasfilename(
            title="Select Output Location",
            defaultextension=default_ext,
            filetypes=filetypes,
        )
        if path:
            self.out_var.set(path)

    def _run_checklist(self):
        odb_path = self.file_var.get().strip()
        if not odb_path:
            self._log("ERROR: Please select an ODB file first.\n")
            return

        output_path = self.out_var.get().strip()
        self.run_btn.configure(state=tk.DISABLED, text="Running...")
        self._log_clear()
        self._log(f"Starting checklist for: {odb_path}\n")
        if output_path:
            self._log(f"Output: {output_path}\n")
        self._log("-" * 50 + "\n")

        thread = threading.Thread(
            target=self._execute, args=(odb_path, output_path), daemon=True,
        )
        thread.start()

    def _execute(self, odb_path: str, output_path: str):
        cmd = [sys.executable, "-u", "main.py", "check", odb_path]
        if output_path:
            cmd += ["--output", output_path]
        fmt = self.fmt_var.get().strip()
        if fmt:
            cmd += ["--format"] + fmt.split()

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path(__file__).parent),
            )
            for line in process.stdout:
                self.root.after(0, self._log, line)
            process.wait()

            if process.returncode == 0:
                self.root.after(0, self._log, "\nChecklist completed successfully.\n")
            else:
                self.root.after(
                    0, self._log,
                    f"\nProcess exited with code {process.returncode}.\n",
                )
        except Exception as exc:
            self.root.after(0, self._log, f"\nERROR: {exc}\n")
        finally:
            self.root.after(0, self._finish)

    def _finish(self):
        self.run_btn.configure(state=tk.NORMAL, text="Run Checklist")

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _log(self, text: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _log_clear(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    ChecklistGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
