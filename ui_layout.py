"""Layout shell primitives for the 2026 overhaul (Phase 3).

Non-breaking: new components, not yet wired into ui.py. Integration is a
separate, test-guarded step.
"""
import customtkinter as ctk

from ui_theme import UITheme


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, palette=None, width=220, **kw):
        palette = palette or {}
        super().__init__(
            master, width=width, corner_radius=0,
            fg_color=palette.get("sidebar", UITheme.SIDEBAR_BG),
            **kw,
        )
        self._palette = palette
        self.pack_propagate(False)

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self.configure(fg_color=self._palette.get("sidebar", UITheme.SIDEBAR_BG))


class TopBar(ctk.CTkFrame):
    def __init__(self, master, palette=None, height=56, **kw):
        palette = palette or {}
        super().__init__(
            master, height=height, corner_radius=0,
            fg_color=palette.get("surface", UITheme.SURFACE_BG),
            **kw,
        )
        self._palette = palette
        self.pack_propagate(False)

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self.configure(fg_color=self._palette.get("surface", UITheme.SURFACE_BG))


class ContentArea(ctk.CTkFrame):
    def __init__(self, master, palette=None, **kw):
        palette = palette or {}
        super().__init__(
            master, corner_radius=0,
            fg_color=palette.get("bg", UITheme.BG_COLOR),
            **kw,
        )
        self._palette = palette

    def apply_palette(self, palette):
        self._palette = palette or self._palette
        self.configure(fg_color=self._palette.get("bg", UITheme.BG_COLOR))
