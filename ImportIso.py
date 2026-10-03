import os
import shutil
import subprocess
import threading
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    ROOT_CLASS = TkinterDnD.Tk
    HAS_DND = True
except ImportError:
    ROOT_CLASS = tk.Tk
    HAS_DND = False


def find_7z():
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.exists(p):
            return p
    return shutil.which("7z")


def find_oscdimg():
    found = shutil.which("oscdimg")
    if found:
        return found
    for pf in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        for arch in ("amd64", "x86", "arm64"):
            p = os.path.join(
                pf, "Windows Kits", "10", "Assessment and Deployment Kit",
                "Deployment Tools", arch, "Oscdimg", "oscdimg.exe",
            )
            if os.path.exists(p):
                return p
    return None


def human(size):
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class App(ROOT_CLASS):
    def __init__(self):
        super().__init__()
        self.title("ISO Editor")
        self.geometry("1000x620")
        self.iso_path = None
        self.work_dir = None
        self.sevenzip = find_7z()
        self.oscdimg = find_oscdimg()
        self.build_ui()

    def build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        self.drop = tk.Label(
            top, text="ISO dosyasını buraya sürükle bırak\n(ya da tıkla ve seç)",
            relief="groove", bd=2, height=4, bg="#eef3fb", font=("Segoe UI", 11),
            cursor="hand2",
        )
        self.drop.pack(fill="x")
        self.drop.bind("<Button-1>", lambda e: self.pick_iso())
        if HAS_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self.on_drop)
        else:
            self.drop.config(text="tkinterdnd2 yüklü değil (pip install tkinterdnd2)\nŞimdilik tıkla ve seç")

        main = ttk.PanedWindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(main)
        main.add(left, weight=3)
        cols = ("size",)
        self.tree = ttk.Treeview(left, columns=cols, selectmode="browse")
        self.tree.heading("#0", text="Dosya / Klasör")
        self.tree.heading("size", text="Boyut")
        self.tree.column("size", width=100, anchor="e")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        right = ttk.Frame(main, padding=(8, 0))
        main.add(right, weight=1)
        ttk.Label(right, text="ISO Bilgisi", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.info = tk.Text(right, width=34, height=14, state="disabled", wrap="word")
        self.info.pack(fill="x", pady=4)

        self.btn_extract = ttk.Button(right, text="1) Dosyaları çıkar (düzenlemeye başla)",
                                      command=self.extract, state="disabled")
        self.btn_extract.pack(fill="x", pady=2)
        self.btn_add = ttk.Button(right, text="Dosya ekle / değiştir", command=self.add_file, state="disabled")
        self.btn_add.pack(fill="x", pady=2)
        self.btn_del = ttk.Button(right, text="Seçileni sil", command=self.delete_selected, state="disabled")
        self.btn_del.pack(fill="x", pady=2)
        self.btn_save = ttk.Button(right, text="2) ISO olarak kaydet", command=self.save_iso, state="disabled")
        self.btn_save.pack(fill="x", pady=(10, 2))

        self.status = tk.StringVar(value="Hazır.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def set_info(self, text):
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.config(state="disabled")

    def on_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if paths:
            self.load_iso(paths[0])

    def pick_iso(self):
        p = filedialog.askopenfilename(filetypes=[("ISO dosyası", "*.iso")])
        if p:
            self.load_iso(p)

    def load_iso(self, path):
        if not path.lower().endswith(".iso"):
            messagebox.showwarning("ISO Editor", "Lütfen bir .iso dosyası seç.")
            return
        if not self.sevenzip:
            messagebox.showerror("ISO Editor", "7-Zip bulunamadı. https://www.7-zip.org adresinden kur.")
            return
        self.iso_path = path
        self.work_dir = None
        self.status.set("ISO okunuyor...")
        threading.Thread(target=self._list_iso, daemon=True).start()

    def _list_iso(self):
        try:
            out = subprocess.run(
                [self.sevenzip, "l", "-slt", self.iso_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            ).stdout
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Hata", str(e)))
            return

        entries = []
        in_files = False
        cur = {}
        for line in out.splitlines():
            if line.startswith("----------"):
                in_files = True
                continue
            if not in_files:
                continue
            if not line.strip():
                if "Path" in cur:
                    entries.append(cur)
                cur = {}
                continue
            if " = " in line:
                k, v = line.split(" = ", 1)
                cur[k.strip()] = v.strip()
        if "Path" in cur:
            entries.append(cur)
        self.after(0, lambda: self._show_listing(entries))

    def _show_listing(self, entries):
        self.tree.delete(*self.tree.get_children())
        nodes = {"": ""}
        total = 0
        files = 0
        names = set()
        for e in sorted(entries, key=lambda x: x["Path"].lower()):
            path = e["Path"].replace("\\", "/")
            is_dir = e.get("Folder") == "+"
            parts = path.split("/")
            parent = ""
            for i, part in enumerate(parts):
                key = "/".join(parts[: i + 1])
                if key not in nodes:
                    last = i == len(parts) - 1
                    size = "" if (is_dir or not last) else human(e.get("Size", 0) or 0)
                    nodes[key] = self.tree.insert(nodes[parent], "end", text=part, values=(size,))
                parent = key
            if not is_dir:
                files += 1
                total += int(e.get("Size", 0) or 0)
                names.add(path.lower())

        has_wim = "sources/install.wim" in names
        has_esd = "sources/install.esd" in names
        has_bios = "boot/etfsboot.com" in names
        has_efi = "efi/microsoft/boot/efisys.bin" in names
        text = (
            f"Dosya: {os.path.basename(self.iso_path)}\n"
            f"ISO boyutu: {human(os.path.getsize(self.iso_path))}\n"
            f"İçerik: {files} dosya, {human(total)}\n\n"
            f"install.wim: {'var' if has_wim else 'yok'}\n"
            f"install.esd: {'var' if has_esd else 'yok'}\n"
            f"BIOS boot (etfsboot.com): {'var' if has_bios else 'yok'}\n"
            f"UEFI boot (efisys.bin): {'var' if has_efi else 'yok'}\n"
        )
        self.set_info(text)
        self.btn_extract.config(state="normal")
        self.btn_add.config(state="disabled")
        self.btn_del.config(state="disabled")
        self.btn_save.config(state="disabled")
        self.status.set("ISO okundu. Düzenlemek için 'Dosyaları çıkar'a bas.")

    def extract(self):
        base = filedialog.askdirectory(title="Çalışma klasörünü seç (boş yer olan bir sürücü)")
        if not base:
            return
        self.work_dir = tempfile.mkdtemp(prefix="iso_work_", dir=base)
        self.btn_extract.config(state="disabled")
        self.status.set("Dosyalar çıkarılıyor, biraz sürebilir...")
        threading.Thread(target=self._extract_thread, daemon=True).start()

    def _extract_thread(self):
        r = subprocess.run(
            [self.sevenzip, "x", self.iso_path, f"-o{self.work_dir}", "-y"],
            capture_output=True, text=True, errors="replace",
        )
        self.after(0, lambda: self._extract_done(r.returncode))

    def _extract_done(self, code):
        if code != 0:
            messagebox.showerror("Hata", "Çıkarma başarısız oldu.")
            self.btn_extract.config(state="normal")
            return
        self.refresh_tree_from_disk()
        for b in (self.btn_add, self.btn_del, self.btn_save):
            b.config(state="normal")
        self.status.set(f"Çıkarıldı: {self.work_dir}  — artık düzenleyebilirsin.")

    def refresh_tree_from_disk(self):
        self.tree.delete(*self.tree.get_children())

        def walk(folder, parent):
            for name in sorted(os.listdir(folder), key=str.lower):
                full = os.path.join(folder, name)
                if os.path.isdir(full):
                    node = self.tree.insert(parent, "end", text=name, values=("",), open=False)
                    walk(full, node)
                else:
                    self.tree.insert(parent, "end", text=name, values=(human(os.path.getsize(full)),))

        walk(self.work_dir, "")

    def selected_disk_path(self):
        sel = self.tree.selection()
        if not sel:
            return None
        parts = []
        node = sel[0]
        while node:
            parts.append(self.tree.item(node, "text"))
            node = self.tree.parent(node)
        return os.path.join(self.work_dir, *reversed(parts))

    def add_file(self):
        target = self.selected_disk_path() or self.work_dir
        if os.path.isfile(target):
            target = os.path.dirname(target)
        files = filedialog.askopenfilenames(title="Eklenecek / üzerine yazılacak dosyalar")
        for f in files:
            shutil.copy2(f, target)
        if files:
            self.refresh_tree_from_disk()
            self.status.set(f"{len(files)} dosya {os.path.relpath(target, self.work_dir)} içine kopyalandı.")

    def delete_selected(self):
        p = self.selected_disk_path()
        if not p:
            return
        if not messagebox.askyesno("Sil", f"Silinsin mi?\n{os.path.relpath(p, self.work_dir)}"):
            return
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
        self.refresh_tree_from_disk()
        self.status.set("Silindi.")

    def save_iso(self):
        if not self.oscdimg:
            messagebox.showerror(
                "oscdimg yok",
                "ISO oluşturmak için Windows ADK içindeki 'Deployment Tools' kurulu olmalı.\n"
                "Microsoft sitesinden Windows ADK'yı indirip sadece Deployment Tools'u seç.",
            )
            return
        out = filedialog.asksaveasfilename(defaultextension=".iso", filetypes=[("ISO", "*.iso")])
        if not out:
            return
        bios = os.path.join(self.work_dir, "boot", "etfsboot.com")
        efi = os.path.join(self.work_dir, "efi", "microsoft", "boot", "efisys.bin")
        if not (os.path.exists(bios) and os.path.exists(efi)):
            messagebox.showerror("Hata", "Boot dosyaları (etfsboot.com / efisys.bin) bulunamadı.")
            return
        cmd = [
            self.oscdimg, "-m", "-o", "-u2", "-udfver102",
            f"-bootdata:2#p0,e,b{bios}#pEF,e,b{efi}",
            self.work_dir, out,
        ]
        self.status.set("ISO oluşturuluyor...")
        threading.Thread(target=self._save_thread, args=(cmd, out), daemon=True).start()

    def _save_thread(self, cmd, out):
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode == 0:
            self.after(0, lambda: (self.status.set(f"Kaydedildi: {out}"),
                                   messagebox.showinfo("Bitti", f"ISO kaydedildi:\n{out}")))
        else:
            self.after(0, lambda: messagebox.showerror("Hata", r.stdout[-800:] + r.stderr[-800:]))


if __name__ == "__main__":
    App().mainloop()