"""
Application entry point for the campy GUI.
"""

from __future__ import print_function

import sys
import multiprocessing as mp

from PyQt5.QtWidgets import QApplication

from .main_window import MainWindow


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    mp.freeze_support()

    if args and args[0] == "--acquire":
        if len(args) < 2:
            raise SystemExit("--acquire requires a config path.")
        sys.argv = ["campy-acquire", args[1]]
        from campy.campy import Main
        return Main()

    app = QApplication.instance() or QApplication(sys.argv[:1] + args)
    initial_config = args[0] if args else None
    window = MainWindow(initial_config=initial_config)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
