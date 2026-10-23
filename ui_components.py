"""Themed UI primitives for the 2026 overhaul (Phase 2).

Pure-ish: widgets are created here but all colours come from the active
palette passed in. Every primitive accepts ``palette`` (dict) and re-themes
via ``apply_palette``.
"""
import customtkinter as ctk

from ui_theme import UITheme


class Card(ctk.CTkFrame):
    def __init__(self, master, palette=None, radius=None, **kw):
        palette = palette or {}
        super().__init__(
            master,
            corner_radius=radius or UITheme.RADIUS_LG,
            fg_color=palette.get("surface", UITheme.SURFACE_BG),
            border_color=palette.get("hover", UITheme.SIDEBAR_HOVER),
            border_width=UITheme.BORDER_W,
            **kw,
        )
        self._palette = palette

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self.configure(
            fg_color=self._palette.get("surface", UITheme.SURFACE_BG),
            border_color=self._palette.get("hover", UITheme.SIDEBAR_HOVER),
        )


class PrimaryButton(ctk.CTkButton):
    def __init__(self, master, palette=None, text="", **kw):
        palette = palette or {}
        accent = palette.get("accent", UITheme.COLOR_ACCENT)
        from ui_theme import _on_color
        fg = _on_color(accent, palette.get("text", "#ffffff"), palette.get("bg", "#000000"))
        super().__init__(
            master, text=text,
            corner_radius=UITheme.RADIUS_MD,
            fg_color=accent,
            hover_color=palette.get("accent_hover", accent),
            text_color=fg,
            height=UITheme.BTN_H,
            **kw,
        )
        self._palette = palette

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        accent = self._palette.get("accent", UITheme.COLOR_ACCENT)
        from ui_theme import _on_color
        self.configure(
            fg_color=accent,
            hover_color=self._palette.get("accent_hover", accent),
            text_color=_on_color(accent, self._palette.get("text", "#ffffff"),
                                 self._palette.get("bg", "#000000")),
        )


class GhostButton(ctk.CTkButton):
    def __init__(self, master, palette=None, text="", **kw):
        palette = palette or {}
        super().__init__(
            master, text=text,
            corner_radius=UITheme.RADIUS_MD,
            fg_color="transparent",
            hover_color=palette.get("hover", UITheme.SIDEBAR_HOVER),
            text_color=palette.get("text", "#ecf0f1"),
            height=UITheme.BTN_H,
            border_width=UITheme.BORDER_W,
            border_color=palette.get("hover", UITheme.SIDEBAR_HOVER),
            **kw,
        )
        self._palette = palette

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self.configure(
            hover_color=self._palette.get("hover", UITheme.SIDEBAR_HOVER),
            text_color=self._palette.get("text", "#ecf0f1"),
            border_color=self._palette.get("hover", UITheme.SIDEBAR_HOVER),
        )


class ThemedEntry(ctk.CTkEntry):
    def __init__(self, master, palette=None, **kw):
        palette = palette or {}
        super().__init__(
            master,
            corner_radius=UITheme.RADIUS_FIELD,
            fg_color=palette.get("field", palette.get("surface", UITheme.SURFACE_BG)),
            text_color=palette.get("text", "#ecf0f1"),
            placeholder_text_color=palette.get("sub", UITheme.COLOR_GRAY),
            border_color=palette.get("hover", UITheme.SIDEBAR_HOVER),
            border_width=UITheme.BORDER_W,
            height=UITheme.INPUT_H,
            **kw,
        )
        self._palette = palette

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self.configure(
            fg_color=self._palette.get("field", self._palette.get("surface", UITheme.SURFACE_BG)),
            text_color=self._palette.get("text", "#ecf0f1"),
            placeholder_text_color=self._palette.get("sub", UITheme.COLOR_GRAY),
            border_color=self._palette.get("hover", UITheme.SIDEBAR_HOVER),
        )


class EmptyState(ctk.CTkFrame):
    def __init__(self, master, palette=None, title="", subtitle="", **kw):
        palette = palette or {}
        super().__init__(master, fg_color="transparent", **kw)
        self._palette = palette
        self._title = ctk.CTkLabel(self, text=title, font=UITheme.F(16, "bold"),
                                    text_color=palette.get("text", "#ecf0f1"))
        self._title.pack(pady=(UITheme.SPACE_5, UITheme.SPACE_2))
        self._sub = ctk.CTkLabel(self, text=subtitle, font=UITheme.F(12),
                                  text_color=palette.get("sub", UITheme.COLOR_GRAY),
                                  wraplength=420, justify="center")
        self._sub.pack(pady=(0, UITheme.SPACE_5))

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self._title.configure(text_color=self._palette.get("text", "#ecf0f1"))
        self._sub.configure(text_color=self._palette.get("sub", UITheme.COLOR_GRAY))
"""Extra primitives (Phase 2b)."""
import customtkinter as ctk

from ui_theme import UITheme


class SectionHeader(ctk.CTkFrame):
    def __init__(self, master, palette=None, title="", subtitle="", **kw):
        palette = palette or {}
        super().__init__(master, fg_color="transparent", **kw)
        self._palette = palette
        ctk.CTkLabel(self, text=title, font=UITheme.F(UITheme.TYPE_TITLE, "bold"),
                     text_color=palette.get("text", "#ecf0f1"),
                     anchor="w").pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=UITheme.F(UITheme.TYPE_CAPTION),
                         text_color=palette.get("sub", UITheme.COLOR_GRAY),
                         anchor="w").pack(anchor="w", pady=(2, 0))

    def apply_palette(self, palette):
        self._palette = palette or self._palette


class Toast(ctk.CTkFrame):
    def __init__(self, master, palette=None, message="", kind="info", **kw):
        palette = palette or {}
        from ui_theme import status_color
        color = status_color(palette, kind)
        super().__init__(master, corner_radius=UITheme.RADIUS_MD,
                         fg_color=palette.get("surface", UITheme.SURFACE_BG),
                         border_color=color, border_width=2, **kw)
        self._palette = palette
        ctk.CTkLabel(self, text=message, font=UITheme.F(UITheme.TYPE_BODY),
                     text_color=palette.get("text", "#ecf0f1"),
                     wraplength=320, justify="left").pack(padx=UITheme.SPACE_3,
                                                          pady=UITheme.SPACE_2)

