class ResultDialog:
    def __init__(self, ctk, parent, title, stream_to_result=False):
        self.ctk = ctk
        self.window = ctk.CTkToplevel(parent)
        self.window.title(title)
        self.window.geometry("1080x620")
        self.window.minsize(900, 520)
        self.stream_to_result = bool(stream_to_result)
        self.apply_callback = None
        self.save_callback = None
        self.window.protocol("WM_DELETE_WINDOW", self.close_dialog)

        self.window.grid_columnconfigure(0, weight=1)
        self.window.grid_rowconfigure(2, weight=1)

        self.stage_label = ctk.CTkLabel(self.window, text="初始化任务", anchor="w", font=ctk.CTkFont(size=16, weight="bold"))
        self.stage_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))

        self.reasoning_label = ctk.CTkLabel(self.window, text="思维链文本长度：0 字符", anchor="w")
        self.reasoning_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        panes = ctk.CTkFrame(self.window)
        panes.grid(row=2, column=0, sticky="nsew", padx=12, pady=0)
        panes.grid_columnconfigure(0, weight=1)
        panes.grid_columnconfigure(1, weight=2)
        panes.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(panes, text="状态", anchor="w").grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=(8, 4))
        ctk.CTkLabel(panes, text="输出结果", anchor="w").grid(row=0, column=1, sticky="ew", padx=(4, 8), pady=(8, 4))

        self.log_box = ctk.CTkTextbox(panes, wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))

        self.result_box = ctk.CTkTextbox(panes, wrap="word")
        self.result_box.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))

        actions = ctk.CTkFrame(self.window, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="e", padx=12, pady=12)

        self.apply_button = ctk.CTkButton(actions, text="应用结果（等待生成）", command=self.apply_dialog)
        self.apply_button.pack(side="left", padx=(0, 8))

        self.close_button = ctk.CTkButton(actions, text="关闭", fg_color="#4b5563", hover_color="#374151", command=self.close_dialog)
        self.close_button.pack(side="left")

        self.window.transient(parent)
        self.window.lift()
        self.window.focus_force()

    def after(self, delay, callback):
        self.window.after(delay, callback)

    def destroy(self):
        self.window.destroy()

    def _append_text(self, widget, text):
        widget.insert("end", text)
        widget.see("end")

    def append_status(self, message):
        self.after(0, lambda: self._append_status_ui(message))

    def _append_status_ui(self, message):
        self.stage_label.configure(text=message)
        self._append_text(self.log_box, message + "\n")

    def append_output(self, text):
        self.after(0, lambda: self._append_output_ui(text))

    def _append_output_ui(self, text):
        target = self.result_box if self.stream_to_result else self.log_box
        self._append_text(target, text)

    def update_reasoning(self, message):
        self.after(0, lambda: self.reasoning_label.configure(text=message))

    def finish(self, success, message):
        prefix = "完成" if success else "失败"
        self.append_status("%s：%s" % (prefix, message))

    def set_result(self, text, apply_callback=None, save_callback=None):
        def _update():
            self.result_box.delete("1.0", "end")
            self.result_box.insert("1.0", text or "")
            self.apply_callback = apply_callback
            self.save_callback = save_callback
            self.apply_button.configure(text="应用结果" if apply_callback else "应用结果（无可应用内容）")

        self.after(0, _update)

    def get_result_text(self):
        return self.result_box.get("1.0", "end").strip()

    def save_result(self):
        if self.save_callback:
            self.save_callback(self.get_result_text())

    def close_dialog(self):
        try:
            self.save_result()
        finally:
            self.destroy()

    def apply_dialog(self):
        if not self.apply_callback:
            self.append_status("结果还未生成，暂不能应用")
            return
        self.save_result()
        self.apply_callback(self.get_result_text())
        self.destroy()
