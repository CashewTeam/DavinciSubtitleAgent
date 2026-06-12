class WorkbenchPanel:
    def __init__(self, ctk, parent, app):
        self.ctk = ctk
        self.app = app
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._build()

    def _build(self):
        ctk = self.ctk
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)

        material = ctk.CTkFrame(self.frame, corner_radius=10)
        material.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        material.grid_columnconfigure(1, weight=1)
        material.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(material, text="工作台", anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=6, sticky="ew", padx=12, pady=(10, 6))
        body = ctk.CTkFrame(material, fg_color="transparent")
        body.grid(row=1, column=0, columnspan=6, sticky="ew", padx=12, pady=(0, 12))
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(5, weight=1)

        self._row_with_entry(body, 0, "输出目录", self.app.output_dir_var, [("选择目录", self.app.on_browse_output_dir)], extra_label="前缀", extra_var=self.app.output_prefix_var)
        self._row_with_entry(body, 1, "WAV 文件", self.app.wav_path_var, [("选择 WAV", self.app.on_browse_wav), ("清空 WAV", self.app.on_clear_wav)])
        self._row_with_entry(body, 2, "参考文稿", self.app.text_path_var, [("选择文稿", self.app.on_browse_text), ("清空文稿", self.app.on_clear_text)])
        self._row_with_entry(body, 3, "SRT 文件", self.app.srt_path_var, [("选择 SRT", self.app.on_browse_srt), ("打开编辑", lambda: self.app.show_page("editor"))])
        self._row_two_entries(body, 4, "原始 SRT", self.app.raw_srt_var, "处理后 SRT", self.app.processed_srt_var)

        actions = ctk.CTkFrame(self.frame, corner_radius=10)
        actions.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        actions.grid_columnconfigure(1, weight=1)
        actions.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(actions, text="执行", anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=7, sticky="ew", padx=12, pady=(10, 6))
        ctk.CTkLabel(actions, text="当前模式").grid(row=1, column=0, sticky="w", padx=(12, 8), pady=(0, 10))
        self.app.mode_combo = ctk.CTkComboBox(actions, values=[label for _, label, _ in self.app.mode_specs], state="readonly", command=lambda _: self.app.on_mode_changed())
        self.app.mode_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(0, 10))
        ctk.CTkButton(actions, text="开始识别", width=110, command=self.app.on_generate).grid(row=1, column=2, padx=(0, 8), pady=(0, 10))
        ctk.CTkButton(actions, text="导出时间线字幕", width=140, command=self.app.on_export_srt).grid(row=1, column=3, padx=(0, 8), pady=(0, 10))
        ctk.CTkButton(actions, text="校对", width=90, command=self.app.on_convert_srt).grid(row=1, column=4, padx=(0, 8), pady=(0, 10))
        ctk.CTkButton(actions, text="翻译", width=90, command=self.app.on_translate).grid(row=1, column=5, padx=(0, 8), pady=(0, 10))
        ctk.CTkButton(actions, text="导入 SRT 到时间线", width=150, command=self.app.on_import_srt).grid(row=1, column=6, padx=(0, 12), pady=(0, 10))

        ctk.CTkLabel(actions, text="日志", anchor="w").grid(row=2, column=0, columnspan=7, sticky="ew", padx=12, pady=(0, 4))
        self.app.log_box = ctk.CTkTextbox(actions, wrap="word", height=260)
        self.app.log_box.grid(row=3, column=0, columnspan=7, sticky="nsew", padx=12, pady=(0, 12))

    def _row_with_entry(self, parent, row, label, var, buttons, extra_label=None, extra_var=None):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        entry = ctk.CTkEntry(parent, textvariable=var)
        entry.grid(row=row, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=6)
        button_col = 4
        for text, command in buttons:
            ctk.CTkButton(parent, text=text, width=110, command=command).grid(row=row, column=button_col, padx=(0, 8), pady=6, sticky="ew")
            button_col += 1
        if extra_label and extra_var is not None:
            ctk.CTkLabel(parent, text=extra_label).grid(row=row, column=4, sticky="w", padx=(0, 8), pady=6)
            ctk.CTkEntry(parent, textvariable=extra_var).grid(row=row, column=5, sticky="ew", pady=6)

    def _row_two_entries(self, parent, row, left_label, left_var, right_label, right_var):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=left_label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        left = ctk.CTkEntry(parent, textvariable=left_var)
        left.configure(state="readonly")
        left.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6)
        ctk.CTkLabel(parent, text=right_label).grid(row=row, column=3, sticky="w", padx=(0, 8), pady=6)
        right = ctk.CTkEntry(parent, textvariable=right_var)
        right.configure(state="readonly")
        right.grid(row=row, column=4, columnspan=2, sticky="ew", pady=6)

