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
     Primary      #3B82F6    Error        #EF4444
     Warning      #F59E0B    Success      #10B981
     Text High    #F8FAFC    Text Med     #94A3B8
     Outline      #232634    OutlineVar   #32364D
   ================================================================ */

QMainWindow, QWidget#centralwidget {
    background-color: #0A0B10;
}
QWidget {
    font-family: 'Outfit', 'Inter', 'Segoe UI', 'Roboto', sans-serif;
    font-size: 14px;
    color: #F8FAFC;
    background-color: transparent;
}

/* === TOP COMMAND BAR === */
#TopBar {
    background-color: #0A0B10;
    border-bottom: 1px solid #232634;
}
#Logo {
    color: #3B82F6;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 2px;
}
#PageTitle {
    color: #94A3B8;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
#Clock {
    color: #64748B;
    font-size: 11px;
}
#StatusLabel {
    font-size: 10px;
    font-weight: 600;
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
    color: #F8FAFC;
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
#EmptyGridLabel {
    color: #475569;
    font-size: 14px;
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
#PersonCard[threat="High"]   { border-left: 3px solid #EF4444; }
#PersonCard[threat="Medium"] { border-left: 3px solid #F59E0B; }
#PersonCard[threat="Low"]    { border-left: 3px solid #3B82F6; }

#PersonPhoto {
    border-radius: 24px;
    background: #0A0B10;
}
#PersonPhoto[threat="High"]   { border: 1px solid #EF4444; }
#PersonPhoto[threat="Medium"] { border: 1px solid #F59E0B; }
#PersonPhoto[threat="Low"]    { border: 1px solid #3B82F6; }

#IdentifiedSub {
    color: #64748B;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}
#IdentifiedName {
    color: #F8FAFC;
    font-weight: 600;
    font-size: 14px;
}
#ThreatBadge {
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
}
#AttributeLabel {
    color: #64748B;
    font-weight: 600;
    font-size: 10px;
}
#AttributeValue {
    color: #CBD5E1;
    font-size: 12px;
}
#DossierView {
    background-color: #0A0B10;
    border: 1px solid #232634;
    border-radius: 8px;
    padding: 10px;
    color: #CBD5E1;
    font-size: 13px;
}

/* === FORMS & ENROLLMENT === */
#EnrollmentHeader {
    color: #F8FAFC;
    font-size: 18px;
    font-weight: 700;
}
#EnrollmentSub {
    color: #64748B;
    font-size: 12px;
}
#PhotoPreview {
    background: #161821;
    border: 1px dashed #32364D;
    border-radius: 12px;
    color: #32364D;
    font-size: 40px;
}
#PhotoPreview[hasImage="true"] {
    border: 1px solid #3B82F6;
    background: #0A0B10;
}
#EnrollForm {
    background: #161821;
    border: 1px solid #232634;
    border-radius: 12px;
}
#FormSectionHeader {
    color: #475569;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
#ActionBtn {
    background-color: #3B82F6;
    color: #FFFFFF;
    font-weight: 700;
    font-size: 13px;
    border-radius: 8px;
    border: none;
}
#ActionBtn:hover {
    background-color: #2563EB;
}
#ActionBtn:disabled {
    background-color: #1E293B;
    color: #475569;
}
#SecondaryBtn {
    background: #161821;
    border: 1px solid #232634;
    color: #94A3B8;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
}
#SecondaryBtn:hover {
    border-color: #3B82F6;
    color: #3B82F6;
}

/* === CENTRAL INTELLIGENCE === */
#CIHeader {
    color: #F8FAFC;
    font-size: 18px;
    font-weight: 700;
}
#CountBadge {
    color: #10B981;
    background: rgba(16, 185, 129, 0.1);
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 10px;
    font-weight: 600;
}
#ProfileThumb {
    border-radius: 20px;
    background: #0A0B10;
    border: 1px solid #232634;
}
#ProfileName {
    color: #F8FAFC;
    font-weight: 600;
    font-size: 13px;
}
#ProfileMeta {
    color: #64748B;
    font-size: 10px;
}
#RowActionBtn {
    background: #1E202B;
    border: 1px solid #232634;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
}
#RowActionBtn:hover {
    background: rgba(255, 255, 255, 0.05);
}

/* === SYSTEM DIALOGS === */
QDialog, QMainWindow#EditProfileDialog, QMainWindow#ActivityReportDialog {
    background-color: #0A0B10;
}
#DialogHeader {
    color: #F8FAFC;
    font-size: 16px;
    font-weight: 700;
}
#DialogPhoto {
    background-color: #161821;
    border: 1px solid #232634;
    border-radius: 45px;
}
#DialogLabel {
    color: #475569;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

/* === ACTIVITY LOGS === */
#LogTime {
    color: #3B82F6;
    font-weight: 600;
    font-size: 11px;
}
#LogAction {
    color: #F8FAFC;
    font-size: 12px;
}
#LogMeta {
    color: #475569;
    font-size: 10px;
}

/* === THREAT LEVELS === */
#ThreatBadge[threat="High"] {
    color: #EF4444;
    background: rgba(239, 68, 68, 0.1);
}
#ThreatBadge[threat="Medium"] {
    color: #F59E0B;
    background: rgba(245, 158, 11, 0.1);
}
#ThreatBadge[threat="Low"] {
    color: #10B981;
    background: rgba(16, 185, 129, 0.1);
}

/* === HEALTH & STATUS === */
#HealthLabel[status="online"], #StatusLabel[status="online"] {
    color: #10B981;
}
#HealthLabel[status="offline"], #StatusLabel[status="offline"] {
    color: #EF4444;
}

/* === INPUTS === */
QLineEdit {
    background-color: #0A0B10;
    border: 1px solid #232634;
    border-radius: 8px;
    padding: 12px 16px;
    color: #F8FAFC;
}
QLineEdit:focus {
    border-color: #3B82F6;
}

QComboBox {
    background-color: #0A0B10;
    border: 1px solid #232634;
    border-radius: 8px;
    padding: 12px 16px;
    color: #F8FAFC;
}
QComboBox:focus {
    border-color: #3B82F6;
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

