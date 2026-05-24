import sys
import os
import time
import requests
from bs4 import BeautifulSoup
import pygame
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QSlider, QPushButton, QFrame)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QFont, QIcon, QPainter, QColor, QLinearGradient, QPainterPath

# 対象のURLとコンポーネント
TARGET_URL = "https://status.vrchat.com/"
COMPONENT_MAP = {
    "ll3syftt0xwm": "認証 / ログイン",
    "fcb1zgxm9b3s": "ソーシャル / フレンドリスト",
    "6yydlg6mdf01": "SDKアセットのアップロード",
    "ftp7mrsh0fwm": "リアルタイムプレーヤーの状態変更"
}

STATUS_MAP = {
    "Operational": "正常",
    "Degraded Performance": "パフォーマンス低下",
    "Partial Outage": "部分的な停止",
    "Major Outage": "停止"
}

# --- スクレイピング用別スレッド ---
class ScraperThread(QThread):
    result_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def run(self):
        try:
            response = requests.get(TARGET_URL, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            scraped_data = {}
            for comp_id in COMPONENT_MAP.keys():
                component_div = soup.find(attrs={"data-component-id": comp_id})
                if component_div:
                    status_span = component_div.find('span', class_='component-status')
                    if status_span:
                        scraped_data[comp_id] = status_span.text.strip()
                        continue
                scraped_data[comp_id] = "取得失敗"
            
            self.result_signal.emit(scraped_data)
        except Exception as e:
            self.error_signal.emit("通信エラー")

# --- メインGUIクラス ---
class StatusMonitorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 音声の初期化
        pygame.mixer.init()
        self.notice_sound = "notice.mp3"
        
        # 状態管理
        self.previous_states = {}
        self.fetch_interval = 45
        self.next_fetch_time = time.time()
        self.is_fetching = False

        # フォントの読み込み
        self.font_family = "sans-serif"
        font_path = "Jigmo2.ttf"
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                self.font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
        
        self.init_ui()
        self.init_timer()
        self.force_fetch()

    def init_ui(self):
        self.setWindowTitle("VRChat Status Monitor")
        self.resize(500, 650)
        
        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))
            
        self.central_widget = CustomBackgroundWidget(self)
        self.setCentralWidget(self.central_widget)
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        # 1. タイトル
        title_label = QLabel("VRChat Server Status")
        title_label.setFont(QFont(self.font_family, 22))
        title_label.setStyleSheet("color: white; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setFixedHeight(40) # 高さを固定
        main_layout.addWidget(title_label)

        # 2. ステータス表示エリア
        self.status_labels = {}
        for comp_id, jp_name in COMPONENT_MAP.items():
            card = QFrame()
            card.setFixedHeight(60) # カードの高さを完全に固定してレイアウトの動きを防ぐ
            card.setStyleSheet("""
                QFrame {
                    background-color: rgba(20, 20, 25, 200);
                    border: 1px solid rgba(196, 181, 253, 50);
                    border-radius: 8px;
                }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(20, 0, 20, 0)
            
            name_lbl = QLabel(jp_name)
            name_lbl.setFont(QFont(self.font_family, 12))
            name_lbl.setStyleSheet("color: #E0E0E0; background: transparent; border: none;")
            
            status_lbl = QLabel("待機中...")
            status_lbl.setFont(QFont(self.font_family, 12))
            status_lbl.setAlignment(Qt.AlignCenter)
            # ラベルの枠サイズを固定し、文字が変わっても横幅が変動しないようにする
            status_lbl.setFixedSize(180, 30) 
            status_lbl.setStyleSheet("color: #93C5FD; background: transparent; border: none;")
            
            card_layout.addWidget(name_lbl)
            card_layout.addWidget(status_lbl, alignment=Qt.AlignRight)
            main_layout.addWidget(card)
            self.status_labels[comp_id] = status_lbl

        # 3. クールダウン表示エリア
        cooldown_layout = QHBoxLayout()
        self.cooldown_label = QLabel("00.00 s")
        
        # フォント設定: 数字を等幅（Monospace）として扱うようヒントを出す
        cd_font = QFont(self.font_family, 36)
        cd_font.setStyleHint(QFont.Monospace)
        cd_font.setFixedPitch(True)
        self.cooldown_label.setFont(cd_font)
        self.cooldown_label.setAlignment(Qt.AlignCenter)
        # 枠を固定して文字のガタつきによる全体への影響を遮断
        self.cooldown_label.setFixedSize(250, 60)
        self.cooldown_label.setStyleSheet("color: #C4B5FD; font-weight: bold;")
        cooldown_layout.addWidget(self.cooldown_label, alignment=Qt.AlignCenter)
        main_layout.addLayout(cooldown_layout)

        # 4. スライダーエリア
        slider_layout = QVBoxLayout()
        self.slider_val_label = QLabel(f"取得間隔: {self.fetch_interval} 秒")
        self.slider_val_label.setFont(QFont(self.font_family, 10))
        self.slider_val_label.setAlignment(Qt.AlignCenter)
        self.slider_val_label.setFixedSize(200, 20) # ラベル幅固定
        self.slider_val_label.setStyleSheet("color: white;")
        slider_layout.addWidget(self.slider_val_label, alignment=Qt.AlignCenter)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(1)
        self.slider.setMaximum(12)
        self.slider.setValue(self.fetch_interval // 5)
        self.slider.valueChanged.connect(self.on_slider_change)
        
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #1A1A1A;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #C4B5FD, stop:1 #93C5FD);
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 2px solid #93C5FD;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
        """)
        slider_layout.addWidget(self.slider)
        main_layout.addLayout(slider_layout)

        # 5. スキップボタン
        self.skip_btn = QPushButton("クールダウンスキップ")
        self.skip_btn.setFont(QFont(self.font_family, 12))
        self.skip_btn.setFixedHeight(50) # ボタンの高さ固定
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(self.force_fetch)
        
        self.skip_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: white;
                border: 2px solid;
                border-top-color: #C4B5FD;
                border-left-color: #C4B5FD;
                border-bottom-color: #93C5FD;
                border-right-color: #93C5FD;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(196, 181, 253, 50), stop:1 rgba(147, 197, 253, 50));
            }
            QPushButton:disabled {
                border-color: #333333;
                color: #555555;
            }
        """)
        main_layout.addWidget(self.skip_btn)
        main_layout.addStretch()

    def init_timer(self):
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_cooldown_display)
        # 30ms (約33fps) に調整し、文字の潰れや過度な描画負荷を防止
        self.ui_timer.start(30)

    def on_slider_change(self, val):
        self.fetch_interval = val * 5
        self.slider_val_label.setText(f"取得間隔: {self.fetch_interval} 秒")

    def update_cooldown_display(self):
        if self.is_fetching:
            self.cooldown_label.setText("Fetching...")
            return

        remaining = self.next_fetch_time - time.time()
        if remaining <= 0:
            self.cooldown_label.setText("00.00 s")
            self.trigger_scrape()
        else:
            self.cooldown_label.setText(f"{remaining:05.2f} s")

    def force_fetch(self):
        if not self.is_fetching:
            self.next_fetch_time = time.time()

    def trigger_scrape(self):
        self.is_fetching = True
        self.skip_btn.setEnabled(False)
        
        self.scraper_thread = ScraperThread()
        self.scraper_thread.result_signal.connect(self.handle_result)
        self.scraper_thread.error_signal.connect(self.handle_error)
        self.scraper_thread.start()

    def handle_result(self, current_states):
        for comp_id, raw_status in current_states.items():
            prev_status = self.previous_states.get(comp_id)
            jp_status = STATUS_MAP.get(raw_status, raw_status)
            
            if prev_status == "Major Outage" and raw_status == "Operational":
                self.play_audio()
                
            self.previous_states[comp_id] = raw_status
            
            if raw_status == "Operational":
                self.status_labels[comp_id].setStyleSheet("color: #93C5FD; background: transparent; border: none; font-weight: bold;")
            else:
                self.status_labels[comp_id].setStyleSheet("color: #C4B5FD; background: rgba(196, 181, 253, 30); border: none; font-weight: bold; border-radius: 4px;")
            self.status_labels[comp_id].setText(jp_status)

        self.reset_fetch_cycle()

    def handle_error(self, error_msg):
        for comp_id in COMPONENT_MAP.keys():
            self.status_labels[comp_id].setText("通信エラー")
            self.status_labels[comp_id].setStyleSheet("color: #555555; background: transparent; border: none;")
        self.reset_fetch_cycle()

    def reset_fetch_cycle(self):
        self.next_fetch_time = time.time() + self.fetch_interval
        self.is_fetching = False
        self.skip_btn.setEnabled(True)

    def play_audio(self):
        if os.path.exists(self.notice_sound):
            try:
                pygame.mixer.music.load(self.notice_sound)
                pygame.mixer.music.play()
            except Exception as e:
                print(f"音声再生エラー: {e}")

# --- 幾何学的な背景を描画するカスタムウィジェット ---
class CustomBackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("#08080A"))
        self.setPalette(palette)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(196, 181, 253, 15)) 
        gradient.setColorAt(1.0, QColor(147, 197, 253, 15)) 

        path1 = QPainterPath()
        path1.moveTo(0, 0)
        path1.lineTo(self.width() * 0.6, 0)
        path1.lineTo(0, self.height() * 0.4)
        path1.closeSubpath()
        painter.fillPath(path1, gradient)

        path2 = QPainterPath()
        path2.moveTo(self.width(), self.height())
        path2.lineTo(self.width() * 0.4, self.height())
        path2.lineTo(self.width(), self.height() * 0.6)
        path2.closeSubpath()
        painter.fillPath(path2, gradient)
        
        painter.setPen(QColor(196, 181, 253, 40))
        painter.drawLine(0, int(self.height() * 0.1), int(self.width() * 0.2), 0)
        painter.drawLine(int(self.width() * 0.8), self.height(), self.width(), int(self.height() * 0.9))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StatusMonitorGUI()
    window.show()
    sys.exit(app.exec_())