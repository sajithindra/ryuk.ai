"""
ui/styles.py
Centralized UI tokens, CSS injection, and theme definitions for Ryuk AI NiceGUI.
"""
from nicegui import ui

# User-defined Design Tokens
BG_COLOR = "#050608" # Near Black
SURFACE_COLOR = "rgba(16, 18, 27, 0.4)" # Glass Surface
PRIMARY_COLOR = "#00D1FF" # Cyber Cyan
ACCENT_COLOR = "#7000FF" # Deep Purple Accent
ERROR_COLOR = "#FF3333"
SUCCESS_COLOR = "#00FF94"
TEXT_HIGH = "#F0F2F5"
TEXT_MED = "#6B7280"
OUTLINE_COLOR = "rgba(255, 255, 255, 0.08)"
GLOW_COLOR = "0 0 30px rgba(0, 209, 255, 0.2)"

def inject_styles():
    """Injects global CSS into the page head."""
    ui.query('body').style(f'background-color: {BG_COLOR}; color: {TEXT_HIGH}; font-family: "Outfit", sans-serif; overflow: hidden;')
    
    ui.add_head_html(f"""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
            @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
            
            :root {{
                --primary: {PRIMARY_COLOR};
                --accent: {ACCENT_COLOR};
                --success: {SUCCESS_COLOR};
                --bg: {BG_COLOR};
                --surface: {SURFACE_COLOR};
                --outline: {OUTLINE_COLOR};
                --text: {TEXT_HIGH};
                --text-muted: {TEXT_MED};
            }}

            body {{
                background: radial-gradient(circle at 50% 0%, #11141d 0%, #050608 100%);
            }}

            .cyber-panel {{
                background: var(--surface) !important;
                backdrop-filter: blur(25px) saturate(180%);
                border: 1px solid var(--outline) !important;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.8);
                border-radius: 16px !important;
            }}
            
            .cyber-border-l {{ border-left: 3px solid var(--primary); }}
            
            .glow-text {{
                color: var(--text);
                text-shadow: 0 0 15px rgba(0, 209, 255, 0.5);
            }}
            
            .scroll-hidden::-webkit-scrollbar {{ display: none; }}
            
            .telemetry-bar {{
                background: rgba(5, 6, 8, 0.7);
                backdrop-filter: blur(10px);
                border-bottom: 1px solid var(--outline);
            }}
            
            .nav-icon-btn {{
                transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                color: var(--text-muted) !important;
            }}
            .nav-icon-btn:hover {{
                color: var(--primary) !important;
                background: rgba(0, 209, 255, 0.1) !important;
                transform: translateX(5px) scale(1.1);
            }}
            .nav-icon-btn.active {{
                color: var(--primary) !important;
                background: rgba(0, 209, 255, 0.15) !important;
                border: 1px solid rgba(0, 209, 255, 0.3) !important;
                box-shadow: 0 0 30px rgba(0, 209, 255, 0.3);
            }}
            .nav-icon-btn.active i {{ color: var(--primary) !important; }}

            .modern-nav {{
                background: rgba(10, 12, 18, 0.4) !important;
                backdrop-filter: blur(20px) saturate(180%);
                border: 1px solid rgba(255, 255, 255, 0.05) !important;
                border-radius: 24px !important;
                padding: 8px 16px !important;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5), inset 0 0 0 1px rgba(255, 255, 255, 0.05);
                transition: all 0.4s ease;
                z-index: 1000;
            }}

            .nav-pill {{
                border-radius: 16px !important;
                padding: 4px 12px !important;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
                color: rgba(255, 255, 255, 0.5) !important;
                font-size: 0.85rem !important;
                font-weight: 600 !important;
                text-transform: uppercase !important;
                letter-spacing: 1px !important;
            }}
            .nav-pill:hover {{
                background: rgba(0, 209, 255, 0.05) !important;
                color: var(--primary) !important;
                transform: translateY(-2px);
            }}
            .nav-pill.active {{
                background: rgba(0, 209, 255, 0.1) !important;
                color: var(--primary) !important;
                border: 1px solid rgba(0, 209, 255, 0.2) !important;
                box-shadow: 0 0 20px rgba(0, 209, 255, 0.15);
            }}

            .logo-glow {{
                filter: drop-shadow(0 0 8px rgba(0, 209, 255, 0.4));
                transition: all 0.5s ease;
            }}
            .logo-glow:hover {{
                filter: drop-shadow(0 0 15px rgba(0, 209, 255, 0.8)) hue-rotate(90deg);
                transform: scale(1.1);
            }}

            .cam-card {{
                position: relative;
                overflow: hidden;
                border-radius: 20px !important;
                border: 1px solid var(--outline) !important;
                background: rgba(16, 18, 27, 0.6) !important;
                transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
            }}
            .cam-card:hover {{
                border-color: var(--primary) !important;
                transform: translateY(-8px) scale(1.02);
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.9), 0 0 20px rgba(0, 209, 255, 0.2);
                z-index: 10;
            }}
            
            .intel-item {{
                border-left: 4px solid transparent;
                transition: all 0.3s ease;
                border-radius: 12px;
                background: rgba(255, 255, 255, 0.03);
                margin-bottom: 8px;
            }}
            .intel-item:hover {{
                background: rgba(255, 255, 255, 0.08);
                border-left-color: var(--primary);
                transform: scale(1.02);
            }}

            .cyber-btn {{
                border-radius: 12px !important;
                font-weight: 800 !important;
                letter-spacing: 2px !important;
                background: linear-gradient(135deg, var(--primary), var(--accent)) !important;
                box-shadow: 0 4px 15px rgba(0, 209, 255, 0.3) !important;
            }}
            .cyber-btn:hover {{
                filter: brightness(1.2);
                box-shadow: 0 8px 30px rgba(0, 209, 255, 0.5) !important;
            }}

            @keyframes pulse-glow {{
                0% {{ box-shadow: 0 0 5px rgba(0, 209, 255, 0.2); }}
                50% {{ box-shadow: 0 0 20px rgba(0, 209, 255, 0.5); }}
                100% {{ box-shadow: 0 0 5px rgba(0, 209, 255, 0.2); }}
            }}

            .active-ai-track {{
                animation: pulse-glow 2s infinite;
            }}

            .scanline {{
                width: 100%;
                height: 100px;
                z-index: 5;
                background: linear-gradient(0deg, rgba(0, 209, 255, 0) 0%, rgba(0, 209, 255, 0.1) 50%, rgba(0, 209, 255, 0) 100%);
                opacity: 0.1;
                position: absolute;
                bottom: 100%;
                animation: scanline 8s linear infinite;
                pointer-events: none;
            }}

            @keyframes scanline {{
                0% {{ bottom: 100%; }}
                100% {{ bottom: -100px; }}
            }}

            .health-pulse {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: {SUCCESS_COLOR};
                box-shadow: 0 0 10px {SUCCESS_COLOR};
                animation: health-pulse 2s infinite;
            }}

            .stat-box {{
                background: rgba(255,255,255,0.03);
                border-radius: 8px;
                padding: 8px 12px;
                border: 1px solid rgba(255,255,255,0.05);
            }}
            .stat-label {{
                font-size: 9px;
                font-weight: 800;
                letter-spacing: 1px;
                color: rgba(255,255,255,0.3);
                text-transform: uppercase;
            }}
            .stat-value {{
                font-family: 'JetBrains Mono', 'Roboto Mono', monospace;
                font-size: 13px;
                font-weight: 900;
            }}

            @keyframes health-pulse {{
                0% {{ transform: scale(1); opacity: 1; }}
                50% {{ transform: scale(1.5); opacity: 0.5; }}
                100% {{ transform: scale(1); opacity: 1; }}
            }}

            .id-card {{
                border-radius: 16px !important;
                background: rgba(255, 255, 255, 0.02) !important;
                border: 1px solid rgba(255, 255, 255, 0.05) !important;
                transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                overflow: hidden;
                backdrop-filter: blur(10px);
            }}
            .id-card:hover {{
                background: rgba(255, 255, 255, 0.06) !important;
                border_color: var(--primary) !important;
                transform: translateY(-5px);
                box-shadow: 0 15px 40px rgba(0, 0, 0, 0.6);
            }}
            .id-thumb-container {{
                position: relative;
                width: 100%;
                aspect-ratio: 1 / 1;
                overflow: hidden;
                border-radius: 12px;
                background: rgba(0,0,0,0.2);
            }}
            .id-card-btn {{
                transition: all 0.2s ease;
                opacity: 0.6;
            }}
            .id-card-btn:hover {{
                opacity: 1;
                transform: scale(1.1);
            }}

            .tactical-card {{
                background: rgba(15, 18, 26, 0.7) !important;
                backdrop-filter: blur(15px);
                border: 1px solid rgba(255, 255, 255, 0.08) !important;
                border-radius: 12px !important;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                overflow: hidden;
            }}
            .tactical-card:hover {{
                border-color: rgba(0, 209, 255, 0.3) !important;
                background: rgba(18, 22, 32, 0.8) !important;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            }}
            
            .tactical-header {{
                background: rgba(255, 255, 255, 0.03);
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                padding: 10px 14px;
            }}
            
            .status-dot {{
                width: 6px;
                height: 6px;
                border_radius: 50%;
                background: var(--primary);
                box-shadow: 0 0 10px var(--primary);
                animation: status-pulse 2s infinite;
            }}
            
            @keyframes status-pulse {{
                0% {{ opacity: 0.4; transform: scale(0.8); }}
                50% {{ opacity: 1; transform: scale(1.2); }}
                100% {{ opacity: 0.4; transform: scale(0.8); }}
            }}
        </style>
    """)

def get_threat_color(threat: str) -> str:
    """Returns the CSS color for a given threat level."""
    return 'red' if threat == 'High' else 'orange' if threat == 'Medium' else '#53DE53'
