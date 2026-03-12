"""
ui/styles.py
Central QSS stylesheet for the Ryuk AI dashboard.
Import DASHBOARD_QSS and pass it to QMainWindow.setStyleSheet().
"""

DASHBOARD_QSS = """
/* ================================================================
   RYUK AI — Professional Minimalist Theme
   Color Tokens:
     Background   #0F111A    Surface      #1A1D2B
     Surface+1    #24293D    Surface+2    #2D334A
     Primary      #3B82F6    Error        #EF4444
     Warning      #F59E0B    Success      #10B981
     Text High    #F8FAFC    Text Med     #94A3B8
     Outline      #2E3352    OutlineVar   #404875
   ================================================================ */

QMainWindow, QWidget#centralwidget {
    background-color: #0F111A;
}
QWidget {
    font-family: 'Inter', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 14px;
    color: #F8FAFC;
    background-color: transparent;
}

/* === TOP COMMAND BAR === */
#TopBar {
    background-color: #0F111A;
    border-bottom: 1px solid #1E293B;
}

/* === NAV RAIL === */
#NavRail {
    background-color: #0F111A;
    border-right: 1px solid #1E293B;
}
#NavBtn {
    color: #64748B;
    background: transparent;
    border: none;
    border-radius: 8px;
    font-size: 18px;
}
#NavBtn:hover {
    color: #94A3B8;
    background-color: rgba(255, 255, 255, 0.03);
}
#NavBtnActive {
    color: #3B82F6;
    background-color: rgba(59, 130, 246, 0.1);
    border: none;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 600;
}

/* === CONTENT AREAS === */
#ContentArea {
    background-color: #0F111A;
}

#IntelPanel {
    background-color: #0F111A;
    border-left: 1px solid #1E293B;
}

#IntelHeader {
    color: #94A3B8;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 1px;
    padding: 16px;
    border-bottom: 1px solid #1E293B;
}

/* === CARDS === */
#VideoCard {
    background-color: #1A1D2B;
    border: 1px solid #2D3748;
    border-radius: 12px;
}
#VideoCard:hover {
    border-color: #3B82F6;
}

#PersonCard {
    background-color: #1A1D2B;
    border: 1px solid #2D3748;
    border-radius: 12px;
}

/* === INPUTS === */
QLineEdit {
    background-color: #0F111A;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 10px 14px;
    color: #F8FAFC;
}
QLineEdit:focus {
    border-color: #3B82F6;
}

QComboBox {
    background-color: #0F111A;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 10px 14px;
    color: #F8FAFC;
}
QComboBox:focus {
    border-color: #3B82F6;
}

/* === SCROLLBARS === */
QScrollBar:vertical {
    border: none; background: transparent;
    width: 4px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px; border-radius: 2px;
}
QScrollBar::handle:vertical:hover { background: #475569; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* === ALERTS === */
#AlertBanner {
    background-color: #450A0A;
    border-bottom: 1px solid #991B1B;
}
#AlertLabel {
    color: #FCA5A5;
    font-weight: 600;
}
#AlertDismissBtn {
    color: #FCA5A5;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    padding: 4px 12px;
}
"""
