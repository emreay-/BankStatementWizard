import weakref
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Tuple, cast

import urwid
import urwid.raw_display

from .file_selector import FileSelector

__all__ = ["run_ui"]


class SwitchingPadding(urwid.Padding):
    def padding_values(self, size, focus):
        max_columns = size[0]
        width, ignore = self.original_widget.pack(size, focus=focus)
        self.align = "left" if max_columns > width else "right"
        return urwid.Padding.padding_values(self, size, focus)


PALETTE = [
    ("body", "white", "", "standout"),
    ("header", "white", "dark red", "bold"),
    ("button normal", "light gray", "dark blue", "standout"),
    ("button select", "white", "dark green"),
    ("button disabled", "dark gray", "dark blue"),
    ("edit", "light gray", "dark blue"),
    ("title", "white", "black"),
    ("chars", "light gray", "black"),
    ("exit", "white", "dark blue")
]


@dataclass
class TopMenuButton:
    widget: urwid.Widget
    key_short_cut: str

    def __getattr__(self, name) -> urwid.Widget:
        w = self.widget
        while True:
            if isinstance(w, urwid.PopUpLauncher) and name == "pop_up_launcher":
                break
            if isinstance(w, urwid.Button) and name == "button":
                break
            if hasattr(w, "original_widget"):
                w = w.original_widget
            else:
                raise ValueError(f"Cannot get {name} attribute for {self.__class__.__name__}")
        return w

    def set_pop_up_callback(self, callback: Callable) -> "TopMenuButton":
        urwid.connect_signal(self.button, "click", lambda w: self.pop_up_launcher.open_pop_up())
        self.pop_up_launcher.callback = callback
        return self

    def set_button_callback(self, callback: Callable) -> "TopMenuButton":
        urwid.connect_signal(self.button, "click", callback)
        return self

    def activate(self):
        self.button.mouse_event(None, "mouse press", 1, 4, 0, True)

    @staticmethod
    def from_label_and_key(label: str, key: str) -> "TopMenuButton":
        label = f"{label} ({key.title()})"
        button = urwid.Button(label)
        button = urwid.AttrMap(button, "button normal", "button select")
        return TopMenuButton(widget=button, key_short_cut=key)


class PopUpMixin:
    def attach(self, launcher: urwid.PopUpLauncher):
        urwid.connect_signal(self, 'close', lambda button: launcher.close_pop_up())

    def launch(self, launcher: urwid.PopUpLauncher):
        self.attach(launcher)
        return self


def create_line_box(*widgets) -> urwid.LineBox:
    body = list(widgets)
    return urwid.LineBox(urwid.ListBox(urwid.SimpleFocusListWalker(body)))


def create_box(*widgets) -> urwid.Filler:
    body = list(widgets)
    return urwid.Filler(urwid.Pile(body))


def create_overlay(widget: urwid.Widget, background: str = " ", **kwargs):
    _kwargs = dict(align="center", width=("relative", 80), valign="middle",
                   height=("relative", 80), min_width=24, min_height=8)
    _kwargs.update(kwargs)
    return urwid.Overlay(widget, urwid.SolidFill(background), **_kwargs)


class StatementsMenu:
    def __init__(self, parent: weakref.ref):
        self.parent = parent

    def launch(self, _: urwid.Widget):
        add_statement_button = urwid.Button("Add Statement", self._add_statement)
        remove_statement_button = urwid.Button("Remove Statement")
        done_button = urwid.Button("Done", lambda _: self._reset_loop_widget())
        self._set_loop_widget(
            create_overlay(create_line_box(urwid.Text("Statements Menu"), urwid.Divider("_", 0, 1),
                                           add_statement_button, remove_statement_button, done_button)))

    def _add_statement(self, _):
        statement_type_button = urwid.Button("Statement Type")
        browse_button = urwid.Button("Browse", self._browse_statement)
        done_button = urwid.Button("Done", lambda i: self.launch(i))
        self._set_loop_widget(
            create_overlay(create_line_box(urwid.Text("Add Statement"), urwid.Divider("_", 0, 1),
                                           statement_type_button, browse_button, done_button))
        )

    def _browse_statement(self, _):
        def _cb(path: str):
            self._reset_loop_widget()
        browser = FileSelector(on_selected=_cb)
        self._set_loop_widget(create_overlay(browser.view))

    def _set_loop_widget(self, widget: urwid.Widget):
        self.parent().loop.widget = widget

    def _reset_loop_widget(self):
        parent = self.parent()
        parent.loop.widget = parent.main_view


class PopUpWrapper(urwid.PopUpLauncher):
    def __init__(self, parent):
        super().__init__(parent)
        self.callback: Optional[Callable[["PopUpWrapper"], urwid.Widget]] = None
        self.parameters: Dict = {'left': 0, 'top': 1, 'overlay_width': 32, 'overlay_height': 7}

    def create_pop_up(self):
        if not self.callback:
            raise ValueError(f"Pop up wrapped was not set")
        return self.callback(self)

    def get_pop_up_parameters(self):
        return self.parameters


BIG_TEXT_FONT = urwid.font.HalfBlock5x4Font()


class BankStatementWizardApp:
    def __init__(self):
        self.main_view: Optional[urwid.Widget] = None

        self.header: Optional[urwid.Widget] = None

        self.title_text: Optional[urwid.Widget] = None
        self.title: Optional[urwid.Widget] = None

        self.exit_text: Optional[urwid.Widget] = None
        self.exit_view: Optional[urwid.Widget] = None

        self.statements_menu_button: Optional[TopMenuButton] = None
        self.filter_menu_button: Optional[TopMenuButton] = None
        self.plot_menu_button: Optional[TopMenuButton] = None
        self.export_menu_button: Optional[TopMenuButton] = None
        self.search_button: Optional[TopMenuButton] = None
        self.go_to_button: Optional[TopMenuButton] = None
        self.done_button: Optional[TopMenuButton] = None
        self.top_menu_columns: Optional[urwid.Widget] = None

        self.setup()
        self.loop = urwid.MainLoop(self.main_view, PALETTE, unhandled_input=self.unhandled_input, pop_ups=True)
        self.is_quitting: bool = False

    def setup(self):
        self.create_title_widgets()
        self.create_top_menu_widgets()
        self.create_main_view_widgets()
        self.create_exit_view_widgets()

    def unhandled_input(self, key):
        if self.is_quitting:
            if key == "enter":
                raise urwid.ExitMainLoop()
            if key == "esc":
                self.is_quitting = False
                self.loop.widget = self.main_view
                return True
        else:
            if key == "esc":
                self.is_quitting = True
                self.loop.widget = self.exit_view
                return True

        for button in self.menu_buttons:
            if key == button.key_short_cut:
                button.activate()

    def run(self):
        self.loop.run()

    @property
    def menu_buttons(self) -> Tuple[TopMenuButton]:
        return cast(Tuple[TopMenuButton], (
            self.statements_menu_button,
            self.filter_menu_button,
            self.plot_menu_button,
            self.export_menu_button,
            self.search_button,
            self.go_to_button,
            self.done_button,
        ))

    def create_title_widgets(self):
        self.title_text = urwid.BigText("Bank Statement Wizard", BIG_TEXT_FONT)
        self.title = SwitchingPadding(self.title_text, "center", None)
        self.title = urwid.Filler(self.title, "middle")
        self.title = urwid.BoxAdapter(self.title, 7)
        self.title = urwid.AttrMap(self.title, "title")

    def create_header_widgets(self):
        self.header = urwid.Text("Press ESC to exit")
        self.header = urwid.AttrWrap(self.header, "header")

    def create_main_view_widgets(self):
        self.main_view = urwid.ListBox(
            urwid.SimpleListWalker([self.title, self.top_menu_columns]))
        self.main_view = urwid.Frame(header=self.header, body=self.main_view)
        self.main_view = urwid.AttrWrap(self.main_view, "body")

    def create_exit_view_widgets(self):
        self.exit_text = urwid.BigText(("exit", " Quit? [ESC to cancel] "), BIG_TEXT_FONT)
        self.exit_view = urwid.Overlay(self.exit_text, self.main_view, "center", None, "middle", None)

    def create_top_menu_widgets(self):
        self.statements_menu_button = TopMenuButton.from_label_and_key("Statements Menu", "f2")
        statements_menu = StatementsMenu(parent=weakref.ref(self))
        self.statements_menu_button.set_button_callback(statements_menu.launch)

        self.filter_menu_button = TopMenuButton.from_label_and_key("Filter Menu", "f3")
        self.plot_menu_button = TopMenuButton.from_label_and_key("Plot Menu", "f4")
        self.export_menu_button = TopMenuButton.from_label_and_key("Export Menu", "f5")
        self.search_button = TopMenuButton.from_label_and_key("Search", "f6")
        self.go_to_button = TopMenuButton.from_label_and_key("Go To...", "f7")
        self.done_button = TopMenuButton.from_label_and_key("Done", "f8")
        self.top_menu_columns = urwid.Columns([i.widget for i in self.menu_buttons])
        self.top_menu_columns = urwid.AttrMap(self.top_menu_columns, "button normal")

    def set_frame(self):
        if self.main_view:
            try:
                self.main_view = urwid.ListBox(
                    urwid.SimpleListWalker([self.title, self.top_menu_columns, *self.main_view.body]))
            except AttributeError:
                pass
        else:
            self.main_view = urwid.ListBox(
                urwid.SimpleListWalker([self.title, self.top_menu_columns]))


def run_ui():
    BankStatementWizardApp().run()