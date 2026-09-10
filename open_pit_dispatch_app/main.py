# -*- coding: utf-8 -*-

import sys

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.theme import APP_QSS


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenPit Competition Dispatch Center")
    app.setStyleSheet(APP_QSS)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
