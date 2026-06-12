class SettingsPanel:
    def __init__(self, ctk, parent, app):
        self.ctk = ctk
        self.app = app
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.vars = {}
        self._build()

    def _build(self):
        ctk = self.ctk
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        tabs = ctk.CTkTabview(self.frame)
        tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.tabs = tabs
        for name in ("输出", "识别", "LLM", "提示词"):
            tabs.add(name)
            tabs.tab(name).grid_columnconfigure(1, weight=1)

        self._add_entry(tabs.tab("输出"), 0, "输出目录", "custom_output_dir")
        self._add_combo(tabs.tab("识别"), 0, "默认语言", "default_lang", ["zh", "en", "yue", "ja", "ko"])
        self._add_combo(tabs.tab("识别"), 1, "目标语言", "target_lang", ["zh-cn", "zh-tw", "zh-hk", "en", "ja", "ko"])
        self._add_combo(tabs.tab("识别"), 2, "region", "region", ["cn", "intl"])
        self._add_entry(tabs.tab("识别"), 3, "max_words", "default_max_words")
        self._add_entry(tabs.tab("识别"), 4, "max_chars", "default_max_chars")
        self._add_entry(tabs.tab("识别"), 5, "chars_per_line", "default_chars_per_line")
        self._add_entry(tabs.tab("LLM"), 0, "DashScope API Key", "dashscope_api_key", show="*")
        self._add_entry(tabs.tab("LLM"), 1, "llm_model", "llm_model")
        self._add_entry(tabs.tab("LLM"), 2, "llm_base_url", "llm_base_url")
        self._add_switch(tabs.tab("LLM"), 3, "thinking", "llm_enable_thinking")
        self._add_text(tabs.tab("提示词"), 0, "校对提示词", "llm_proofread_prompt", height=150)
        self._add_text(tabs.tab("提示词"), 1, "翻译提示词（可使用 {target_lang}）", "llm_translate_prompt", height=150)
        self._add_text(tabs.tab("提示词"), 2, "文案优化提示词", "llm_optimize_prompt", height=150)

        actions = ctk.CTkFrame(self.frame, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="e", padx=12, pady=(0, 12))
        ctk.CTkButton(actions, text="保存设置", width=120, command=self.save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="重新载入", width=120, command=self.reload).pack(side="left")

    def _add_entry(self, parent, row, label, key, show=None):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=8)
        value = ctk.StringVar(value=str(self.app.config.get(key, "")))
        entry = ctk.CTkEntry(parent, textvariable=value, show=show)
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=8)
        self.vars[key] = value

    def _add_combo(self, parent, row, label, key, values):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=8)
        combo = ctk.CTkComboBox(parent, values=list(values))
        combo.set(str(self.app.config.get(key, values[0])))
        combo.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=8)
        self.vars[key] = combo

    def _add_switch(self, parent, row, label, key):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=8)
        switch = ctk.CTkSwitch(parent, text="enable")
        if bool(self.app.config.get(key, False)):
            switch.select()
        else:
            switch.deselect()
        switch.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=8)
        self.vars[key] = switch

    def _add_text(self, parent, row, label, key, height=120):
        ctk = self.ctk
        parent.grid_rowconfigure(row, weight=1)
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="nw", padx=12, pady=8)
        text = ctk.CTkTextbox(parent, height=height, wrap="word")
        text.insert("1.0", str(self.app.config.get(key, "")))
        text.grid(row=row, column=1, sticky="nsew", padx=(0, 12), pady=8)
        self.vars[key] = text

    def values(self):
        cfg = dict(self.app.config)
        cfg["output_dir_mode"] = "custom"
        for key, widget in self.vars.items():
            if isinstance(widget, self.ctk.CTkComboBox):
                cfg[key] = widget.get().strip()
            elif isinstance(widget, self.ctk.CTkSwitch):
                cfg[key] = bool(widget.get())
            elif isinstance(widget, self.ctk.CTkTextbox):
                cfg[key] = widget.get("1.0", "end").strip()
            else:
                cfg[key] = widget.get().strip()
        return cfg

    def save(self):
        self.app.save_config_and_refresh(self.values())

    def reload(self):
        for key, widget in self.vars.items():
            value = self.app.config.get(key, "")
            if isinstance(widget, self.ctk.CTkComboBox):
                widget.set(str(value))
            elif isinstance(widget, self.ctk.CTkSwitch):
                widget.select() if bool(value) else widget.deselect()
            elif isinstance(widget, self.ctk.CTkTextbox):
                widget.delete("1.0", "end")
                widget.insert("1.0", str(value))
            else:
                widget.set(str(value))
