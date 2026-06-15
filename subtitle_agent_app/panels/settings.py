class FormFields:
    def __init__(self, ctk, app):
        self.ctk = ctk
        self.app = app
        self.vars = {}

    def add_entry(self, parent, row, label, key, show=None):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=8)
        value = ctk.StringVar(value=str(self.app.config.get(key, "")))
        entry = ctk.CTkEntry(parent, textvariable=value, show=show)
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=8)
        self.vars[key] = value
        return entry

    def add_combo(self, parent, row, label, key, values):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=8)
        combo = ctk.CTkComboBox(parent, values=list(values))
        combo.set(str(self.app.config.get(key, values[0])))
        combo.grid(row=row, column=1, sticky="ew", padx=(0, 12), pady=8)
        self.vars[key] = combo
        return combo

    def add_switch(self, parent, row, label, key):
        ctk = self.ctk
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=8)
        switch = ctk.CTkSwitch(parent, text="enable")
        if bool(self.app.config.get(key, False)):
            switch.select()
        else:
            switch.deselect()
        switch.grid(row=row, column=1, sticky="w", padx=(0, 12), pady=8)
        self.vars[key] = switch
        return switch

    def add_text(self, parent, row, label, key, height=120):
        ctk = self.ctk
        parent.grid_rowconfigure(row, weight=1)
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="nw", padx=12, pady=8)
        text = ctk.CTkTextbox(parent, height=height, wrap="word")
        text.insert("1.0", str(self.app.config.get(key, "")))
        text.grid(row=row, column=1, sticky="nsew", padx=(0, 12), pady=8)
        self.vars[key] = text
        return text

    def apply_values(self, cfg):
        for key, widget in self.vars.items():
            value = cfg.get(key, "")
            if isinstance(widget, self.ctk.CTkComboBox):
                widget.set(str(value))
            elif isinstance(widget, self.ctk.CTkSwitch):
                widget.select() if bool(value) else widget.deselect()
            elif isinstance(widget, self.ctk.CTkTextbox):
                widget.delete("1.0", "end")
                widget.insert("1.0", str(value))
            else:
                widget.set(str(value))

    def read_values(self, cfg):
        updated = dict(cfg)
        for key, widget in self.vars.items():
            if isinstance(widget, self.ctk.CTkComboBox):
                updated[key] = widget.get().strip()
            elif isinstance(widget, self.ctk.CTkSwitch):
                updated[key] = bool(widget.get())
            elif isinstance(widget, self.ctk.CTkTextbox):
                updated[key] = widget.get("1.0", "end").strip()
            else:
                updated[key] = widget.get().strip()
        return updated


class LLMSettingsFields(FormFields):
    def build(self, parent, row_offset=0):
        self.add_entry(parent, row_offset + 0, "DashScope API Key", "dashscope_api_key", show="*")
        self.add_entry(parent, row_offset + 1, "llm_model", "llm_model")
        self.add_entry(parent, row_offset + 2, "llm_base_url", "llm_base_url")
        self.add_switch(parent, row_offset + 3, "thinking", "llm_enable_thinking")


class SettingsPanel:
    def __init__(self, ctk, parent, app):
        self.ctk = ctk
        self.app = app
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.fields = FormFields(ctk, app)
        self.llm_fields = LLMSettingsFields(ctk, app)
        self._build()

    def _build(self):
        ctk = self.ctk
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        tabs = ctk.CTkTabview(self.frame)
        tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.tabs = tabs
        for name in ("识别", "LLM", "提示词"):
            tabs.add(name)
            tabs.tab(name).grid_columnconfigure(1, weight=1)

        self.fields.add_entry(tabs.tab("识别"), 0, "输出目录", "custom_output_dir")
        self.fields.add_combo(tabs.tab("识别"), 1, "默认语言", "default_lang", ["zh", "en", "yue", "ja", "ko"])
        self.fields.add_combo(tabs.tab("识别"), 2, "目标语言", "target_lang", ["zh-cn", "zh-tw", "zh-hk", "en", "ja", "ko"])
        self.fields.add_combo(tabs.tab("识别"), 3, "region", "region", ["cn", "intl"])
        self.fields.add_entry(tabs.tab("识别"), 4, "max_words", "default_max_words")
        self.fields.add_entry(tabs.tab("识别"), 5, "max_chars", "default_max_chars")
        self.fields.add_entry(tabs.tab("识别"), 6, "chars_per_line", "default_chars_per_line")
        self.fields.add_entry(tabs.tab("识别"), 7, "强制对齐模型目录", "align_model_dir")
        self.fields.add_combo(tabs.tab("识别"), 8, "对齐语言", "align_language", ["zh-cn", "zh-tw", "zh-hk", "en", "ja", "ko"])
        self.fields.add_switch(tabs.tab("识别"), 9, "CJK 罗马化", "align_romanize")
        self.fields.add_entry(tabs.tab("识别"), 10, "对齐线程数", "align_threads")
        self.fields.add_entry(tabs.tab("识别"), 11, "对齐 batch_size", "align_batch_size")
        self.llm_fields.build(tabs.tab("LLM"))
        self.fields.add_text(tabs.tab("提示词"), 0, "校对提示词", "llm_proofread_prompt", height=150)
        self.fields.add_text(tabs.tab("提示词"), 1, "翻译提示词（可使用 {target_lang}）", "llm_translate_prompt", height=150)
        self.fields.add_text(tabs.tab("提示词"), 2, "文案优化提示词", "llm_optimize_prompt", height=150)

        actions = ctk.CTkFrame(self.frame, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="e", padx=12, pady=(0, 12))
        ctk.CTkButton(actions, text="保存设置", width=120, command=self.save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="重新载入", width=120, command=self.reload).pack(side="left")

    def values(self):
        cfg = dict(self.app.config)
        cfg["output_dir_mode"] = "custom"
        cfg = self.fields.read_values(cfg)
        cfg = self.llm_fields.read_values(cfg)
        return cfg

    def save(self):
        self.app.save_config_and_refresh(self.values())

    def reload(self):
        self.fields.apply_values(self.app.config)
        self.llm_fields.apply_values(self.app.config)
