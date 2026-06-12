class EditorPanel:
    def __init__(self, ctk, parent, app):
        self.ctk = ctk
        self.app = app
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._build()

    def _build(self):
        ctk = self.ctk
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        left = self._editor_column("参考文案", 0)
        right = self._editor_column("SRT 预览 / 编辑", 1)

        ctk.CTkLabel(left, textvariable=self.app.text_path_var, anchor="w").grid(row=1, column=0, columnspan=4, sticky="ew", padx=12, pady=(0, 6))
        ctk.CTkButton(left, text="选择文稿", width=100, command=self.app.on_browse_text).grid(row=2, column=0, sticky="ew", padx=(12, 6), pady=(0, 8))
        ctk.CTkButton(left, text="清空", width=90, command=self.app.on_clear_text).grid(row=2, column=1, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkButton(left, text="优化文案", width=110, command=self.app.on_optimize_text).grid(row=2, column=2, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkButton(left, text="保存文案", width=110, command=self.app.on_save_reference_text).grid(row=2, column=3, sticky="ew", padx=(6, 12), pady=(0, 8))
        self.app.text_editor = ctk.CTkTextbox(left, wrap="word")
        self.app.text_editor.grid(row=3, column=0, columnspan=4, sticky="nsew", padx=12, pady=(0, 12))

        ctk.CTkLabel(right, textvariable=self.app.srt_path_var, anchor="w").grid(row=1, column=0, columnspan=5, sticky="ew", padx=12, pady=(0, 6))
        ctk.CTkButton(right, text="选择 SRT", width=100, command=self.app.on_browse_srt).grid(row=2, column=0, sticky="ew", padx=(12, 6), pady=(0, 8))
        ctk.CTkButton(right, text="刷新预览", width=100, command=self.app.on_reload_srt_preview).grid(row=2, column=1, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkButton(right, text="保存 SRT", width=100, command=self.app.on_save_srt_preview).grid(row=2, column=2, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkButton(right, text="校对", width=90, command=self.app.on_convert_srt).grid(row=2, column=3, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkButton(right, text="翻译", width=90, command=self.app.on_translate).grid(row=2, column=4, sticky="ew", padx=(6, 12), pady=(0, 8))
        self.app.preview_box = ctk.CTkTextbox(right, wrap="word")
        self.app.preview_box.grid(row=3, column=0, columnspan=5, sticky="nsew", padx=12, pady=(0, 12))

    def _editor_column(self, title, column):
        ctk = self.ctk
        frame = ctk.CTkFrame(self.frame, corner_radius=10)
        frame.grid(row=0, column=column, sticky="nsew", padx=(12, 6) if column == 0 else (6, 12), pady=12)
        frame.grid_columnconfigure(tuple(range(5)), weight=1)
        frame.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(frame, text=title, anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=5, sticky="ew", padx=12, pady=(10, 6))
        return frame

