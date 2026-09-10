# -*- coding: utf-8 -*-

APP_QSS = r"""
QMainWindow, QDialog {
    background: #07110f;
    color: #edf5ef;
}
QWidget {
    color: #edf5ef;
    font-family: "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
}
QFrame#Panel {
    background: #0d1a17;
    border: 1px solid rgba(174, 213, 191, 45);
    border-radius: 10px;
}
QLabel#Title {
    font-size: 24px;
    font-weight: 800;
    color: #edf5ef;
}
QLabel#SectionTitle {
    font-size: 17px;
    font-weight: 800;
    color: #edf5ef;
}
QLabel#Eyebrow {
    color: #5ac7a1;
    font-size: 10px;
    font-weight: 700;
}
QLabel#Muted {
    color: #8ca499;
    font-size: 11px;
}
QLabel#Alert {
    background: #401513;
    color: #ffd4d1;
    border: 1px solid #a53d38;
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 700;
}
QPushButton {
    min-height: 32px;
    padding: 3px 12px;
    border: 1px solid rgba(174, 213, 191, 55);
    border-radius: 7px;
    background: #11231e;
    color: #edf5ef;
}
QPushButton:hover {
    border-color: #5ac7a1;
    background: #153029;
}
QPushButton#Primary {
    background: #a8e063;
    color: #07110f;
    border: none;
    font-weight: 800;
}
QPushButton#Danger {
    background: #351413;
    color: #ff8f8a;
    border: 1px solid #843a36;
    font-weight: 700;
}
QPushButton#Nav {
    min-height: 38px;
    font-weight: 700;
}
QPushButton#Nav:checked {
    background: #1a352b;
    color: #a8e063;
    border-color: #5ac7a1;
}
QComboBox, QSpinBox {
    min-height: 32px;
    padding: 0 8px;
    border: 1px solid rgba(174, 213, 191, 45);
    border-radius: 6px;
    background: #091713;
    selection-background-color: #1f493b;
}
QTabWidget::pane {
    border: 1px solid rgba(174, 213, 191, 35);
    background: #091512;
}
QTabBar::tab {
    background: #0d1a17;
    padding: 8px 18px;
    margin-right: 2px;
    border: 1px solid rgba(174, 213, 191, 30);
}
QTabBar::tab:selected {
    color: #a8e063;
    background: #142a23;
}
QTableWidget {
    background: #091512;
    alternate-background-color: #0d1d18;
    gridline-color: rgba(174, 213, 191, 28);
    border: 1px solid rgba(174, 213, 191, 35);
    selection-background-color: #214638;
}
QHeaderView::section {
    background: #11231e;
    color: #a9beb4;
    padding: 7px;
    border: 0;
    border-right: 1px solid rgba(174, 213, 191, 30);
    font-weight: 700;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    width: 11px;
    background: #07110f;
}
QScrollBar::handle:vertical {
    min-height: 30px;
    background: #315347;
    border-radius: 5px;
}
QScrollBar:horizontal {
    height: 11px;
    background: #07110f;
}
QScrollBar::handle:horizontal {
    min-width: 30px;
    background: #315347;
    border-radius: 5px;
}
QSplitter::handle {
    background: rgba(174, 213, 191, 25);
}
"""
