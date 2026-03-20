"""
ui/styles.py
Central QSS stylesheet for the Ryuk AI dashboard.
Import DASHBOARD_QSS and pass it to QMainWindow.setStyleSheet().
"""

DASHBOARD_QSS = """
/* ================================================================
   RYUK AI — Premium Obsidian & Azure Theme
   Color Tokens:
     Background   #0A0B10    Surface      #161821
     Surface+1    #1E202B    Surface+2    #262936
     Primary      #3D7BFF    Error        #FF4B4B
     Warning      #F59E0B    Success      #10B981
     Text High    #FFFFFF    Text Med     #94A3B8
     Outline      #232634    OutlineVar   #32364D
   ================================================================ */

QMainWindow, QWidget#centralwidget {
    background-color: #0A0B10;
}
QWidget {
    font-family: 'Outfit', 'Inter', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 14px;
    color: #FFFFFF;
    background-color: transparent;
}

/* === TOP COMMAND BAR === */
#TopBar {
    background-color: #0A0B10;
    border-bottom: 1px solid #232634;
}

/* === NAV RAIL === */
#NavRail {
    background-color: #0A0B10;
    border-right: 1px solid #232634;
}
#NavBtn {
    color: #64748B;
    background: transparent;
    border: none;
    border-radius: 8px;
    font-size: 18px;
}
#NavBtn:hover {
    color: #FFFFFF;
    background-color: rgba(255, 255, 255, 0.05);
}
#NavBtnActive {
    color: #3D7BFF;
    background-color: rgba(61, 123, 255, 0.1);
    border: 1px solid rgba(61, 123, 255, 0.2);
    border-radius: 8px;
}

/* === CONTENT AREAS === */
#ContentArea {
    background-color: #0A0B10;
}

#IntelPanel {
    background-color: #0A0B10;
    border-left: 1px solid #232634;
}

#IntelHeader {
    color: #94A3B8;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 2px;
    padding: 16px;
    border-bottom: 1px solid #232634;
}

/* === CARDS === */
#VideoCard {
    background-color: #161821;
    border: 1px solid #232634;
    border-radius: 12px;
}
#VideoCard:hover {
    border-color: #3D7BFF;
}

#PersonCard {
    background-color: #161821;
    border: 1px solid #232634;
    border-radius: 12px;
}

/* === INPUTS === */
QLineEdit {
    background-color: #0A0B10;
    border: 1px solid #232634;
    border-radius: 8px;
    padding: 12px 16px;
    color: #FFFFFF;
}
QLineEdit:focus {
    border-color: #3D7BFF;
}

QComboBox {
    background-color: #0A0B10;
    border: 1px solid #232634;
    border-radius: 8px;
    padding: 12px 16px;
    color: #FFFFFF;
}
QComboBox:focus {
    border-color: #3D7BFF;
}

/* === SCROLLBARS === */
QScrollBar:vertical {
    border: none; background: transparent;
    width: 6px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #232634;
    min-height: 20px; border-radius: 3px;
}
QScrollBar::handle:vertical:hover { background: #32364D; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* === ALERTS === */
#AlertBanner {
    background-color: #450A0A;
    border-bottom: 1px solid #991B1B;
}
#AlertLabel {
    color: #FCA5A5;
    font-weight: 700;
}
#AlertDismissBtn {
    color: #FCA5A5;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    padding: 4px 12px;
}
"""
