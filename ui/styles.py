"""
ui/styles.py
Central QSS stylesheet for the Ryuk AI dashboard.
Import DASHBOARD_QSS and pass it to QMainWindow.setStyleSheet().
"""

DASHBOARD_QSS = """
/* ================================================================
   RYUK AI — Dark Command-Center Theme
   Color Tokens:
     Background   #080A0F    Surface      #111420
     Surface+1    #1C2030    Surface+2    #232840
     Primary      #00E5FF    Error        #FF5370
     Warning      #FFB74D    Success      #00E5C8
     OnSurface    #E2E5F1    Muted        #6B7299
     Outline      #2E3352    OutlineVar   #404875
   ================================================================ */

QMainWindow, QWidget#centralwidget {
    background-color: #080A0F;
}
QWidget {
    font-family: 'Roboto', 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 14px;
    color: #E2E5F1;
    background-color: transparent;
}

/* === TOP COMMAND BAR === */
#TopBar {
    background-color: #080A0F;
    border-bottom: 1px solid #1A1E2E;
}

/* === NAV RAIL (icon strip) === */
#NavRail {
    background-color: #0D0F14;
    border-right: 1px solid #1A1E2E;
}
#NavBtn {
    color: #3A4068;
    background: transparent;
    border: none;
    border-radius: 12px;
    font-size: 18px;
    font-weight: 600;
}
#NavBtn:hover {
    color: #9099C0;
    background-color: rgba(0, 229, 255, 0.06);
}
#NavBtnActive {
    color: #00E5FF;
    background-color: rgba(0, 229, 255, 0.13);
    border: none;
    border-radius: 12px;
    font-size: 18px;
    font-weight: 700;
}
#NavBtnActive:hover {
    background-color: rgba(0, 229, 255, 0.20);
}

/* === SURFACE / CONTENT AREAS === */
#ContentArea {
    background-color: #080A0F;
}

/* === VIDEO STREAM CARD === */
#VideoCard {
    background-color: #111420;
    border: 1px solid #2E3352;
    border-radius: 16px;
}
#VideoCard:hover {
    border-color: rgba(0, 229, 255, 0.25);
}

/* === MATERIAL OUTLINED TEXT FIELD === */
QLineEdit {
    background-color: #1C2030;
    border: 1.5px solid #3A4068;
    border-radius: 8px;
    padding: 13px 16px;
    color: #E2E5F1;
    font-size: 14px;
    selection-background-color: rgba(0, 229, 255, 0.25);
}
QLineEdit:hover  { border-color: #6B7299; background-color: #202438; }
QLineEdit:focus  { border-color: #00E5FF; border-width: 2px; background-color: #1E2640; color: #FFFFFF; }
QLineEdit:disabled { background-color: rgba(28, 32, 48, 0.5); border-color: #2E3352; color: #6B7299; }

/* === MATERIAL COMBO BOX === */
QComboBox {
    background-color: #1C2030;
    border: 1.5px solid #3A4068;
    border-radius: 8px;
    padding: 13px 16px;
    color: #E2E5F1;
    font-size: 14px;
}
QComboBox:hover  { border-color: #6B7299; }
QComboBox:focus  { border-color: #00E5FF; border-width: 2px; }
QComboBox::drop-down { border: none; width: 32px; }
QComboBox::down-arrow { width: 12px; height: 12px; }
QComboBox QAbstractItemView {
    background-color: #232840;
    border: 1px solid #3A4068;
    border-radius: 8px;
    color: #E2E5F1;
    selection-background-color: rgba(0, 229, 255, 0.15);
    padding: 4px;
}

/* === LABELS === */
QLabel { color: #E2E5F1; background: transparent; }

/* === SCROLL AREAS === */
QScrollArea { border: none; background: transparent; }

QScrollBar:vertical {
    border: none; background: transparent;
    width: 5px; margin: 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(107, 114, 153, 0.4);
    min-height: 24px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: rgba(0, 229, 255, 0.5); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    border: none; background: transparent;
    height: 5px; margin: 0 4px;
}
QScrollBar::handle:horizontal {
    background: rgba(107, 114, 153, 0.4);
    min-width: 24px; border-radius: 3px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* === MESSAGE BOX === */
QMessageBox { background-color: #1C2030; color: #E2E5F1; }
QMessageBox QPushButton {
    background-color: rgba(0, 229, 255, 0.12);
    color: #00E5FF;
    border: 1px solid rgba(0, 229, 255, 0.3);
    border-radius: 20px;
    padding: 8px 24px;
    font-weight: 600;
    min-width: 80px;
}
QMessageBox QPushButton:hover { background-color: rgba(0, 229, 255, 0.22); }

/* === TOOL TIPS === */
QToolTip {
    background-color: #232840;
    color: #E2E5F1;
    border: 1px solid #3A4068;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}
"""
