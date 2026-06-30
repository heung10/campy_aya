"""
Shared GUI styling.
"""


APP_STYLE = """
QWidget {
    background: #1b1d20;
    color: #d6dde8;
    font-size: 12px;
}

QMainWindow, QDialog {
    background: #1b1d20;
}

QLabel {
    color: #d6dde8;
}

QLabel[muted="true"] {
    color: #8a9099;
}

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #2a2d31;
    color: #f4f7fb;
    border: 1px solid #3b414a;
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: #406a95;
}

QPushButton {
    background: #2f3338;
    color: #f4f7fb;
    border: 1px solid #4a515d;
    border-radius: 3px;
    padding: 5px 10px;
    min-height: 20px;
}

QPushButton:hover {
    background: #39404a;
}

QPushButton:pressed {
    background: #22262b;
}

QPushButton:disabled {
    color: #727984;
    background: #25282d;
    border-color: #343941;
}

QCheckBox {
    spacing: 7px;
}

QTabWidget::pane {
    border: 1px solid #303640;
    top: -1px;
}

QTabBar::tab {
    background: #22252a;
    color: #b8c7da;
    border: 1px solid #303640;
    padding: 6px 14px;
}

QTabBar::tab:selected {
    background: #101216;
    color: #f4f7fb;
}

QTableWidget {
    background: #101216;
    alternate-background-color: #151a20;
    border: 1px solid #303640;
    gridline-color: #2d333d;
}

QHeaderView::section {
    background: #22252a;
    color: #b8c7da;
    border: 1px solid #303640;
    padding: 4px;
    font-weight: 600;
}

QGroupBox {
    border: 1px solid #303640;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 3px;
}
"""


CAMERA_TILE_STYLE = """
QFrame {
    background: #101216;
    border: 1px solid #303640;
    border-radius: 4px;
}
"""

