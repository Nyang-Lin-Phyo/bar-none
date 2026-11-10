"""Theme for beatMatcher — colours & type from nyang-lin-phyo.github.io.

The site's dark palette is the default; ``LIGHT`` mirrors its
``[data-theme='light']`` tokens.  Tk cannot render alpha, so the site's
translucent tokens are pre-composited against the background into solid
hex values (``line``, ``glow``, ``surface``).

Typography follows the site: a light serif for display type
(Cormorant Garamond on the web, with OS staples as fallbacks) and a mono
face for UI text (DM Mono → Consolas → …).
"""

from __future__ import annotations

from tkinter import font as tkfont
from tkinter import ttk

DARK: dict[str, str] = {
    "bg": "#0d0b14",  # --bg
    "bg2": "#120f1e",  # --bg2
    "purple": "#d4b8ff",  # --purple
    "purple_dim": "#a87fe8",  # --purple-dim
    "text": "#ede8ff",  # --text
    "muted": "#9286b8",  # --muted
    "line": "#292535",  # --line  (rgba(201,184,240,.15) over --bg)
    "glow": "#1c1926",  # --glow  (rgba(201,184,240,.08) over --bg)
    "surface": "#121019",  # --surface (white 2% over --bg)
    "on_purple": "#0d0b14",  # text on a solid --purple fill (== --bg)
}

LIGHT: dict[str, str] = {
    "bg": "#f4f1fb",  # --bg
    "bg2": "#ece7f5",  # --bg2
    "purple": "#573bb5",  # --purple
    "purple_dim": "#6a52c4",  # --purple-dim
    "text": "#2b2340",  # --text
    "muted": "#5e5478",  # --muted
    "line": "#ccc4e0",  # --line  (rgba(86,62,145,.25) over --bg)
    "glow": "#e9e4f6",  # --glow  (rgba(87,59,181,.07) over --bg)
    "surface": "#efebf9",  # --surface (rgba(87,59,181,.03) over --bg)
    "on_purple": "#f4f1fb",  # text on a solid --purple fill (== --bg)
}

# Site fonts first, then fonts that ship with Windows / common Linux distros.
_SERIF_CANDIDATES = (
    "Cormorant Garamond",
    "Georgia",
    "DejaVu Serif",
    "Times New Roman",
)
_MONO_CANDIDATES = (
    "DM Mono",
    "Consolas",
    "DejaVu Sans Mono",
    "Courier New",
)


def pick_fonts(root: "tk.Misc") -> tuple[str, str]:
    """Return ``(serif, mono)`` families installed on this machine."""
    installed = {name.lower() for name in tkfont.families(root)}

    def pick(candidates: tuple[str, ...]) -> str:
        for name in candidates:
            if name.lower() in installed:
                return name
        return candidates[-1]

    return pick(_SERIF_CANDIDATES), pick(_MONO_CANDIDATES)


def init_style(style: ttk.Style) -> None:
    """Flat base theme that actually honours custom colours (cross-platform)."""
    style.theme_use("clam")


def apply(
    root: "tk.Misc",
    style: ttk.Style,
    palette: dict[str, str],
    serif: str,
    mono: str,
) -> None:
    """(Re)configure every ttk style and the combobox dropdown palette."""
    p = palette

    root.configure(bg=p["bg"])
    root.option_add("*TCombobox*Listbox.background", p["bg2"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["purple"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["on_purple"])
    root.option_add("*TCombobox*Listbox.font", (mono, 9))

    # ghost button — surface-coloured flat tag (site .tag / .demo-btn)
    style.configure(
        "TButton",
        background=p["bg2"],
        foreground=p["purple"],
        bordercolor=p["line"],
        lightcolor=p["bg2"],
        darkcolor=p["bg2"],
        focuscolor=p["bg2"],
        relief="flat",
        padding=(14, 7),
        font=(mono, 9),
    )
    style.map(
        "TButton",
        background=[("active", p["glow"]), ("pressed", p["glow"])],
        foreground=[("active", p["purple"])],
        bordercolor=[("active", p["purple_dim"])],
    )

    # primary action — solid purple fill (site .skip-link)
    style.configure(
        "Primary.TButton",
        background=p["purple"],
        foreground=p["on_purple"],
        bordercolor=p["purple"],
        lightcolor=p["purple"],
        darkcolor=p["purple"],
        focuscolor=p["purple"],
        relief="flat",
        padding=(18, 8),
        font=(mono, 10),
    )
    style.map(
        "Primary.TButton",
        background=[("active", p["purple_dim"]), ("pressed", p["purple_dim"])],
        foreground=[("active", p["on_purple"])],
    )

    # tiny bordered tag (theme toggle, top-right)
    style.configure(
        "Tag.TButton",
        background=p["bg2"],
        foreground=p["purple_dim"],
        bordercolor=p["line"],
        lightcolor=p["bg2"],
        darkcolor=p["bg2"],
        focuscolor=p["bg2"],
        relief="flat",
        padding=(10, 4),
        font=(mono, 8),
    )
    style.map(
        "Tag.TButton",
        background=[("active", p["glow"])],
        foreground=[("active", p["purple"])],
        bordercolor=[("active", p["purple_dim"])],
    )

    # text fields
    style.configure(
        "TEntry",
        fieldbackground=p["bg2"],
        foreground=p["text"],
        insertcolor=p["purple"],
        bordercolor=p["line"],
        lightcolor=p["line"],
        darkcolor=p["line"],
        padding=6,
        font=(mono, 9),
    )
    style.map(
        "TEntry",
        foreground=[("disabled", p["muted"])],
        fieldbackground=[("disabled", p["bg2"])],
    )

    # dropdowns
    style.configure(
        "TCombobox",
        fieldbackground=p["bg2"],
        background=p["bg2"],
        foreground=p["text"],
        arrowcolor=p["purple"],
        bordercolor=p["line"],
        lightcolor=p["line"],
        darkcolor=p["line"],
        padding=5,
        font=(mono, 9),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", p["bg2"])],
        foreground=[("readonly", p["text"])],
        selectbackground=[("readonly", p["bg2"])],
        selectforeground=[("readonly", p["text"])],
        bordercolor=[("active", p["purple_dim"])],
    )
