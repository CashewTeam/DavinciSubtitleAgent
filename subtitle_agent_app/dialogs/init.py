from ..panels.settings import LLMSettingsFields


class InitDialog:
    def __init__(self, ctk, parent, app):
        self.ctk = ctk
        self.app = app
        self.window = ctk.CTkToplevel(parent)
        self.window.title("%s 初始化" % app.root.title())
        self.window.geometry("980x760")
        self.window.minsize(860, 680)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.transient(parent)
        self.window.lift()
        self.window.focus_force()

        self.status_labels = {}
        self.llm_fields = LLMSettingsFields(ctk, app)

        self.window.grid_columnconfigure(0, weight=1)
        self.window.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self.window, text="初始化", anchor="w", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        status = ctk.CTkFrame(self.window)
        status.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        status.grid_columnconfigure(1, weight=1)
        self.status_frame = status
        self._add_status_row(status, 0, "Homebrew")
        self._add_status_row(status, 1, "ffmpeg")
        self._add_status_row(status, 2, "强制对齐模型")
        self._add_status_row(status, 3, "模型目录")

        body = ctk.CTkFrame(self.window)
        body.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(1, weight=1)

        actions = ctk.CTkFrame(body)
        actions.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(actions, text="环境准备", anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        ctk.CTkButton(actions, text="重新检查", command=self.app.on_init_check).grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        ctk.CTkButton(actions, text="安装 ffmpeg", command=self.app.on_init_install_ffmpeg).grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        ctk.CTkButton(actions, text="下载推荐模型", command=self.app.on_init_download_model).grid(row=3, column=0, sticky="ew", padx=12, pady=6)

        llm = ctk.CTkFrame(body)
        llm.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(6, 0), pady=0)
        llm.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(llm, text="LLM 配置", anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 8))
        self.llm_fields.build(llm, row_offset=1)
        ctk.CTkButton(llm, text="保存 LLM 配置", command=self.app.on_init_save_llm).grid(row=5, column=0, columnspan=2, sticky="e", padx=12, pady=(8, 12))

        ctk.CTkLabel(body, text="初始化日志", anchor="w").grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(8, 4))
        self.log_box = ctk.CTkTextbox(body, wrap="word")
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))
        body.grid_rowconfigure(2, weight=1)

        footer = ctk.CTkFrame(self.window, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="e", padx=12, pady=(0, 12))
        ctk.CTkButton(footer, text="关闭", fg_color="#4b5563", hover_color="#374151", command=self.close).pack(side="left")

    def _add_status_row(self, parent, row, label):
        self.ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=6)
        value = self.ctk.CTkLabel(parent, text="-", anchor="w")
        value.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=6)
        self.status_labels[label] = value

    def append_log(self, message):
        def _append():
            self.log_box.insert("end", str(message) + "\n")
            self.log_box.see("end")
        self.window.after(0, _append)

    def set_status(self, mapping):
        def _update():
            for key, value in mapping.items():
                if key in self.status_labels:
                    self.status_labels[key].configure(text=str(value))
        self.window.after(0, _update)

    def refresh_llm_fields(self):
        self.llm_fields.apply_values(self.app.config)

    def llm_values(self):
        return self.llm_fields.read_values(dict(self.app.config))

    def close(self):
        self.app.init_dialog = None
        self.window.destroy()
