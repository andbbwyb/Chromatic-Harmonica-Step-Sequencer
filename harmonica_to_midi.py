# -*- coding: utf-8 -*-
import sys, json, os, time
import numpy as np
import pyaudio
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QGridLayout, QTableWidget, QTableWidgetItem,
                               QCheckBox, QGroupBox, QMessageBox, QFileDialog, QSpinBox,
                               QScrollArea, QHeaderView, QAbstractItemView, QDialog, QSizePolicy,
                               QComboBox)
from PySide6.QtCore import Qt, QThread, Signal, QEvent, QUrl, QSize, QRect, QRectF, QPoint, QPointF
from PySide6.QtGui import QFont, QColor, QBrush, QPalette, QIcon, QPainter, QPen, QPaintEvent, QMouseEvent


NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def note_to_freq(note_str):
    name = note_str[:-1]
    octave = int(note_str[-1])
    semitones = NOTE_NAMES.index(name) + (octave - 4) * 12
    return 440.0 * (2 ** ((semitones - 9) / 12.0))


CHROMATIC_HOLES = {
    1:  { (True, False): ('C4',261.6),  (False, False): ('D4',293.7),
          (True, True):  ('C#4',277.2), (False, True):  ('D#4',311.1) },
    2:  { (True, False): ('E4',329.6),  (False, False): ('F4',349.2),
          (True, True):  ('F4',349.2),  (False, True):  ('F#4',370.0) },
    3:  { (True, False): ('G4',392.0),  (False, False): ('A4',440.0),
          (True, True):  ('G#4',415.3), (False, True):  ('A#4',466.2) },
    4:  { (True, False): ('C5',523.3),  (False, False): ('B4',493.9),
          (True, True):  ('C#5',554.4), (False, True):  ('C5',523.3) },
    5:  { (True, False): ('C5',523.3),  (False, False): ('D5',587.3),
          (True, True):  ('C#5',554.4), (False, True):  ('D#5',622.3) },
    6:  { (True, False): ('E5',659.3),  (False, False): ('F5',698.5),
          (True, True):  ('F5',698.5),  (False, True):  ('F#5',740.0) },
    7:  { (True, False): ('G5',784.0),  (False, False): ('A5',880.0),
          (True, True):  ('G#5',830.6), (False, True):  ('A#5',932.3) },
    8:  { (True, False): ('C6',1046.5), (False, False): ('B5',987.8),
          (True, True):  ('C#6',1108.7),(False, True):  ('C6',1046.5) },
    9:  { (True, False): ('C6',1046.5), (False, False): ('D6',1174.7),
          (True, True):  ('C#6',1108.7),(False, True):  ('D#6',1244.5) },
    10: { (True, False): ('E6',1318.5), (False, False): ('F6',1396.9),
          (True, True):  ('F6',1396.9), (False, True):  ('F#6',1480.0) },
    11: { (True, False): ('G6',1568.0), (False, False): ('A6',1760.0),
          (True, True):  ('G#6',1661.2),(False, True):  ('A#6',1864.7) },
    12: { (True, False): ('C7',2093.0), (False, False): ('D7',2349.3),
          (True, True):  ('C#7',2217.5),(False, True):  ('D#7',2489.0) },
}


class AudioEngine:
    def __init__(self):
        old_out = sys.stderr
        sys.stderr = open(os.devnull, 'w')
        try:
            self.p = pyaudio.PyAudio()
        finally:
            sys.stderr.close()
            sys.stderr = old_out
        self.stream = None

    def _ensure_stream(self):
        if self.stream is None:
            self.stream = self.p.open(format=pyaudio.paFloat32, channels=1, rate=44100,
                                      output=True, frames_per_buffer=512)

    def play_note(self, freq, duration=0.3, volume=0.25):
        self._ensure_stream()
        if freq <= 0:
            return
        samples = int(44100 * duration)
        t = np.arange(samples) / 44100.0
        wave = np.zeros(samples)
        harmonics = [1.0, 2.0, 3.0, 4.0, 5.0]
        gains = [1.0, 0.4, 0.2, 0.05, 0.03]
        for h, g in zip(harmonics, gains):
            wave += g * np.sin(2 * np.pi * freq * h * t)
        wave = wave / np.max(np.abs(wave)) * volume
        fade_len = min(int(44100 * 0.015), samples // 6)
        wave[:fade_len] *= np.linspace(0, 1, fade_len)
        wave[-fade_len:] *= np.linspace(1, 0, fade_len)
        self.stream.write(wave.astype(np.float32).tobytes())

    def close(self):
        if self.stream:
            self.stream.close()
        self.p.terminate()


class PlaybackThread(QThread):
    finished = Signal()
    step_playing = Signal(int, list)

    def __init__(self, steps, hole_data, durations, parent=None):
        super().__init__(parent)
        self.durations = durations
        self.freq_steps = []
        self.note_steps = []
        for step in steps:
            freqs = []
            notes = []
            for hole, blow, slide_state in step:
                key = (True, slide_state) if blow else (False, slide_state)
                note_name, freq = hole_data[hole][key]
                freqs.append(freq)
                notes.append(note_name)
            self.freq_steps.append(freqs)
            self.note_steps.append(notes)
        self.audio = AudioEngine()

    def run(self):
        for idx in range(len(self.freq_steps)):
            if self.isInterruptionRequested():
                break
            self.step_playing.emit(idx, self.note_steps[idx])
            dur = self.durations[idx] if idx < len(self.durations) else 0.3
            any_note = bool(self.freq_steps[idx])
            if any_note:
                for freq in self.freq_steps[idx]:
                    self.audio.play_note(freq, duration=dur * 0.9)
                time.sleep(dur * 0.1)
            else:
                time.sleep(dur)
        self.audio.close()
        self.finished.emit()


class ChromaticHeader(QHeaderView):
    MARGIN = 3
    rangeColClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.op_mode = 'normal'
        self.delete_marks = set()
        self.range_start_col = -1
        self.range_end_col = -1
        self.setMinimumHeight(30)

    def _sec_rect(self, idx):
        x = self.sectionViewportPosition(idx)
        return QRect(x, 0, self.sectionSize(idx), self.height())

    def set_op_mode(self, mode):
        self.op_mode = mode
        self.delete_marks.clear()
        self.viewport().update()

    def set_range_markers(self, start, end):
        self.range_start_col = start
        self.range_end_col = end
        self.viewport().update()

    def clear_range_markers(self):
        self.range_start_col = -1
        self.range_end_col = -1
        self.viewport().update()

    def paintSection(self, painter, rect, logical_index):
        is_range = False
        if self.op_mode != 'normal' and self.op_mode != 'delete':
            if self.range_start_col >= 0 and self.range_start_col == logical_index:
                painter.fillRect(rect, QColor('#1a6b3c'))
                is_range = True
            elif self.range_end_col >= 0 and self.range_end_col == logical_index:
                painter.fillRect(rect, QColor('#8e44ad'))
                is_range = True
            elif self.range_start_col >= 0 and self.range_end_col >= 0:
                lo = min(self.range_start_col, self.range_end_col)
                hi = max(self.range_start_col, self.range_end_col)
                if lo <= logical_index <= hi:
                    painter.fillRect(rect, QColor('#1e4d2b'))
                    is_range = True

        if not is_range:
            painter.fillRect(rect, QColor('#1a252f'))

        painter.setPen(QColor('#2c3e50'))
        painter.drawRect(rect)

        if self.op_mode == 'delete':
            cb = QRect(rect.x() + self.MARGIN, rect.y() + self.MARGIN, 16, 16)
            if logical_index in self.delete_marks:
                painter.setBrush(QColor('#e74c3c'))
                painter.setPen(Qt.NoPen)
                painter.drawRect(cb)
                painter.setPen(Qt.white)
                f = QFont('Arial', 10, QFont.Bold)
                painter.setFont(f)
                painter.drawText(cb, Qt.AlignCenter, '\u2713')
            else:
                painter.setBrush(QColor('#2c3e50'))
                painter.setPen(QColor('#7f8c8d'))
                painter.drawRect(cb)

            label_rect = QRect(rect.x() + 16 + self.MARGIN * 2, rect.y(),
                               rect.width() - 16 - self.MARGIN * 2, rect.height())
            painter.setPen(QColor('#ecf0f1'))
            painter.drawText(label_rect, Qt.AlignCenter, str(logical_index + 1))
        else:
            painter.setPen(QColor('#ecf0f1'))
            painter.drawText(rect, Qt.AlignCenter, str(logical_index + 1))

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        logical = self.logicalIndexAt(pos)
        if logical < 0:
            super().mousePressEvent(event)
            return

        if self.op_mode == 'delete':
            vr = self._sec_rect(logical)
            cb = QRect(vr.x() + self.MARGIN, vr.y() + self.MARGIN, 16, 16)
            if cb.contains(pos):
                if logical in self.delete_marks:
                    self.delete_marks.discard(logical)
                else:
                    self.delete_marks.add(logical)
                self.viewport().update()
                return

        if self.op_mode == 'range_select':
            self.rangeColClicked.emit(logical)
            return

        super().mousePressEvent(event)


class HarmonicaStepSequencer(QMainWindow):
    CELL_BLOW = QColor(80, 35, 35)
    CELL_DRAW = QColor(30, 50, 95)
    CELL_PLAYING = QColor(120, 95, 25)
    MAX_RANGES = 20

    def __init__(self):
        super().__init__()
        self.audio = AudioEngine()
        self.slide_active = False
        self.steps = []
        self.playback_thread = None
        self.last_col = 0
        self._insert_btns = []
        self.ranges = {}
        self._range_counter = 0
        self._range_pending_start = None
        self.NOTE_TO_CN = {
            'C': 'do', 'C#': 'do#', 'D': 're', 'D#': 're#',
            'E': 'mi', 'F': 'fa', 'F#': 'fa#',
            'G': 'sol', 'G#': 'sol#', 'A': 'la', 'A#': 'la#', 'B': 'si'
        }
        self.init_ui()

    def note_to_cn(self, note_str):
        name = note_str[:-1]
        octave = int(note_str[-1])
        base = self.NOTE_TO_CN[name]
        if octave > 4:
            return base + '*' * (octave - 4)
        elif octave < 4:
            return base + '_' * (4 - octave)
        return base

    def init_ui(self):
        self.setWindowTitle('半音阶口琴步进扒谱器')
        self.setMinimumSize(1200, 680)
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel('\U0001f3b5 半音阶12孔口琴步进扒谱器')
        tf = QFont('Microsoft YaHei', 14, QFont.Bold)
        title.setFont(tf)
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        ctrl = QHBoxLayout()
        self.slide_cb = QCheckBox('推键 Slide (升半音)')
        self.slide_cb.setFont(QFont('Microsoft YaHei', 10, QFont.Bold))
        self.slide_cb.toggled.connect(self.toggle_slide)
        ctrl.addWidget(self.slide_cb)
        ctrl.addSpacing(10)

        ctrl.addWidget(QLabel('基础时值(ms):'))
        self.base_unit_spin = QSpinBox()
        self.base_unit_spin.setRange(50, 2000)
        self.base_unit_spin.setValue(200)
        self.base_unit_spin.setSuffix(' ms')
        self.base_unit_spin.setFixedWidth(80)
        self.base_unit_spin.setFont(QFont('Arial', 10, QFont.Bold))
        self.base_unit_spin.setToolTip('列宽44px时的音符时长，列越宽音越长')
        ctrl.addWidget(self.base_unit_spin)

        ctrl.addSpacing(6)
        ctrl.addWidget(QLabel('每拍几格:'))
        self.div_spin = QSpinBox()
        self.div_spin.setRange(1, 8)
        self.div_spin.setValue(2)
        self.div_spin.setFixedWidth(50)
        ctrl.addWidget(self.div_spin)

        ctrl.addSpacing(10)
        add_step_btn = QPushButton('\u2795 加一拍')
        add_step_btn.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        add_step_btn.setStyleSheet('background:#2ecc71; color:white; padding:4px 10px; border-radius:4px;')
        add_step_btn.clicked.connect(self.add_step)
        ctrl.addWidget(add_step_btn)

        del_step_btn = QPushButton('\u2796 删一拍')
        del_step_btn.setStyleSheet('background:#e74c3c; color:white; padding:4px 10px; border-radius:4px;')
        del_step_btn.clicked.connect(self.delete_last_step)
        ctrl.addWidget(del_step_btn)

        ctrl.addSpacing(10)
        self.insert_mode_btn = QPushButton('\u2194 插入拍')
        self.insert_mode_btn.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        self.insert_mode_btn.setStyleSheet('background:#8e44ad; color:white; padding:4px 10px; border-radius:4px;')
        self.insert_mode_btn.clicked.connect(self.enter_insert_mode)
        ctrl.addWidget(self.insert_mode_btn)

        ctrl.addSpacing(4)
        self.del_mode_btn = QPushButton('\u2610 删除多选')
        self.del_mode_btn.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        self.del_mode_btn.setStyleSheet('background:#c0392b; color:white; padding:4px 10px; border-radius:4px;')
        self.del_mode_btn.clicked.connect(self.enter_delete_mode)
        ctrl.addWidget(self.del_mode_btn)

        ctrl.addSpacing(6)
        self.mode_cancel_btn = QPushButton('取消')
        self.mode_cancel_btn.setFont(QFont('Microsoft YaHei', 9))
        self.mode_cancel_btn.setStyleSheet('background:#7f8c8d; color:white; padding:4px 14px; border-radius:4px;')
        self.mode_cancel_btn.clicked.connect(self.cancel_current_mode)
        self.mode_cancel_btn.hide()
        ctrl.addWidget(self.mode_cancel_btn)

        ctrl.addSpacing(10)
        ctrl.addWidget(QLabel('区间:'))
        self.range_combo = QComboBox()
        self.range_combo.setFont(QFont('Microsoft YaHei', 9))
        self.range_combo.setStyleSheet(
            'QComboBox{background:#34495e; color:#ecf0f1; border:1px solid #3d4f5e;'
            'border-radius:3px; padding:2px 6px; min-width:80px;}'
            'QComboBox::drop-down{border:none; width:20px;}'
            'QComboBox QAbstractItemView{background:#2c3e50; color:#ecf0f1; selection-background-color:#3498db;}')
        self.range_combo.addItem('全部', -1)
        self.range_combo.setFixedWidth(110)
        ctrl.addWidget(self.range_combo)

        self.range_new_btn = QPushButton('新建')
        self.range_new_btn.setFont(QFont('Microsoft YaHei', 9))
        self.range_new_btn.setStyleSheet('background:#3498db; color:white; padding:3px 10px; border-radius:3px;')
        self.range_new_btn.clicked.connect(self.start_range_selection)
        ctrl.addWidget(self.range_new_btn)

        self.range_del_btn = QPushButton('删除')
        self.range_del_btn.setFont(QFont('Microsoft YaHei', 9))
        self.range_del_btn.setStyleSheet('background:#7f8c8d; color:white; padding:3px 10px; border-radius:3px;')
        self.range_del_btn.clicked.connect(self.delete_selected_range)
        ctrl.addWidget(self.range_del_btn)

        self.range_info_label = QLabel('')
        self.range_info_label.setStyleSheet('color:#7f8c8d; font-size:10px;')
        ctrl.addWidget(self.range_info_label)

        ctrl.addStretch()

        ref_html = '''
        <div style="font-size:12px; color:#e0e0e0; font-family:Microsoft YaHei,sans-serif;
                    background:#1a252f; border:1px solid #3d4f5e; border-radius:6px; padding:6px 8px;">
        <div style="font-weight:bold; text-align:center; margin-bottom:5px; color:#ecf0f1; font-size:13px; letter-spacing:1px;">
            唱名对照
        </div>
        <table style="border-collapse:collapse;">
        <tr style="background:#2c3e50;">
            <th style="padding:2px 8px;font-weight:bold;">孔</th>
            <th style="padding:2px 8px;font-weight:bold;color:#ff6b6b;">吹</th>
            <th style="padding:2px 8px;font-weight:bold;color:#f39c12;">吹推</th>
            <th style="padding:2px 8px;font-weight:bold;color:#54a0ff;">吸</th>
            <th style="padding:2px 8px;font-weight:bold;color:#a29bfe;">吸推</th>
        </tr>'''
        for h in range(1, 13):
            bn, _ = CHROMATIC_HOLES[h][(True, False)]
            bs, _ = CHROMATIC_HOLES[h][(True, True)]
            dn, _ = CHROMATIC_HOLES[h][(False, False)]
            ds, _ = CHROMATIC_HOLES[h][(False, True)]
            bg = '#1e2d3d' if h % 2 == 0 else '#1a252f'
            ref_html += (f'<tr style="background:{bg};">'
                f'<td style="padding:1px 8px;text-align:center;">{h}</td>'
                f'<td style="padding:1px 8px;color:#ff6b6b;">{self.note_to_cn(bn)}</td>'
                f'<td style="padding:1px 8px;color:#f39c12;">{self.note_to_cn(bs)}</td>'
                f'<td style="padding:1px 8px;color:#54a0ff;">{self.note_to_cn(dn)}</td>'
                f'<td style="padding:1px 8px;color:#a29bfe;">{self.note_to_cn(ds)}</td></tr>')
        ref_html += '''
        </table>
        <div style="font-size:10px; color:#7f8c8d; text-align:center; margin-top:4px; border-top:1px solid #2c3e50; padding-top:3px;">
            <span style="color:#b0b0b0;">*</span>=高八度
            <span style="color:#b0b0b0;">_</span>=低八度
            <span style="color:#b0b0b0;">#</span>=升半音(推键)
        </div>
        </div>'''
        ref_label = QLabel(ref_html)
        ref_label.setToolTip(
            '符号说明\n'
            'do re mi fa sol la si = 基本唱名\n'
            '# 跟在后面 = 升半音（推键效果）\n'
            '* 跟在后面 = 高八度\n'
            '_ 跟在后面 = 低八度\n'
            '\u26a0 12孔C调最低音C4(do)，无低八度音')
        ctrl.addWidget(ref_label)

        main_layout.addLayout(ctrl)
        tip = QLabel('\U0001f4a1 左键=吹音 | 右键=吸音 | 滚轮中键=清空 | 拉宽列=延长音')
        tip.setStyleSheet('color:#b0b0b0; font-size:10px;')
        tip.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(tip)

        content = QHBoxLayout()
        content.setSpacing(6)

        left_panel = QGroupBox('口琴对照表')
        left_panel.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        left_panel.setFixedWidth(240)
        lv = QVBoxLayout(left_panel)
        lv.setSpacing(1)
        self.hole_labels = {}
        for hole in range(1, 13):
            row = QHBoxLayout()
            row.setSpacing(4)
            hl = QLabel(f'孔 {hole:2d}:')
            hl.setFixedWidth(40)
            hl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            hl.setStyleSheet('font-weight:bold;')
            row.addWidget(hl)

            blow_name, blow_freq = CHROMATIC_HOLES[hole][(True, False)]
            draw_name, draw_freq = CHROMATIC_HOLES[hole][(False, False)]

            blow_lbl = QLabel(f'吹 {blow_name}')
            blow_lbl.setStyleSheet(
                'background:#ff6b6b; color:white; font-weight:bold; padding:3px 6px; border-radius:3px;')
            blow_lbl.setAlignment(Qt.AlignCenter)
            blow_lbl.setFixedWidth(70)
            row.addWidget(blow_lbl)

            draw_lbl = QLabel(f'吸 {draw_name}')
            draw_lbl.setStyleSheet(
                'background:#54a0ff; color:white; font-weight:bold; padding:3px 6px; border-radius:3px;')
            draw_lbl.setAlignment(Qt.AlignCenter)
            draw_lbl.setFixedWidth(70)
            row.addWidget(draw_lbl)

            test_btn = QPushButton('\u25b6')
            test_btn.setFixedSize(28, 26)
            test_btn.setStyleSheet(
                'background:#5a6a7a; color:white; border-radius:4px; font-size:11px;')
            test_btn.clicked.connect(lambda checked, h=hole: self.test_hole_sound(h))
            row.addWidget(test_btn)
            lv.addLayout(row)
        lv.addStretch()
        content.addWidget(left_panel)

        right_panel = QGroupBox('拍子编辑区 (左键=吹 \u00b7 右键=吸 \u00b7 滚轮中键=清空)')
        right_panel.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
        rv = QVBoxLayout(right_panel)
        rv.setContentsMargins(4, 8, 4, 4)

        self.table = QTableWidget()
        self.table.setFont(QFont('Arial', 10))
        self.table.setColumnCount(16)
        self.table.setHorizontalHeaderLabels(
            [f'{i}' for i in range(1, 17)])
        self.table.horizontalHeader().setDefaultSectionSize(52)
        self.table.horizontalHeader().setMinimumSectionSize(44)
        self.table.horizontalHeader().setMaximumSectionSize(200)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        custom_header = ChromaticHeader(self.table)
        custom_header.rangeColClicked.connect(self._on_range_col_clicked)
        self.table.setHorizontalHeader(custom_header)

        self.table.setRowCount(12)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.verticalHeader().setMinimumSectionSize(28)
        self.table.verticalHeader().setMaximumSectionSize(40)

        hole_labels = []
        for h in range(1, 13):
            bn = CHROMATIC_HOLES[h][(True, False)][0]
            dn = CHROMATIC_HOLES[h][(False, False)][0]
            hole_labels.append(f'{h}\n{bn}|{dn}')
        self.table.setVerticalHeaderLabels(hole_labels)

        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setContextMenuPolicy(Qt.NoContextMenu)

        self.table.viewport().installEventFilter(self)

        rv.addWidget(self.table)

        content.addWidget(right_panel)
        main_layout.addLayout(content, 1)

        btn_row = QHBoxLayout()
        self.record_btn = QPushButton('\U0001f534  开始录制')
        self.record_btn.setFont(QFont('Microsoft YaHei', 10, QFont.Bold))
        self.record_btn.setMinimumHeight(34)
        self.record_btn.setStyleSheet(
            'QPushButton{background:#e74c3c; color:white; border-radius:5px; padding:5px 16px;}'
            'QPushButton:hover{background:#c0392b;}')
        self.record_btn.clicked.connect(self.toggle_recording)
        btn_row.addWidget(self.record_btn)

        self.play_btn = QPushButton('\u25b6  回放')
        self.play_btn.setFont(QFont('Microsoft YaHei', 10, QFont.Bold))
        self.play_btn.setMinimumHeight(34)
        self.play_btn.setStyleSheet(
            'QPushButton{background:#2ecc71; color:white; border-radius:5px; padding:5px 16px;}'
            'QPushButton:hover{background:#27ae60;}')
        self.play_btn.clicked.connect(self.playback)
        btn_row.addWidget(self.play_btn)

        clear_btn = QPushButton('\U0001f5d1  清空')
        clear_btn.setFont(QFont('Microsoft YaHei', 10))
        clear_btn.setMinimumHeight(34)
        clear_btn.setStyleSheet(
            'QPushButton{background:#e67e22; color:white; border-radius:5px; padding:5px 16px;}'
            'QPushButton:hover{background:#d35400;}')
        clear_btn.clicked.connect(self.clear_all)
        btn_row.addWidget(clear_btn)

        export_btn = QPushButton('\U0001f4be  导出MIDI')
        export_btn.setFont(QFont('Microsoft YaHei', 10))
        export_btn.setMinimumHeight(34)
        export_btn.setStyleSheet(
            'QPushButton{background:#34495e; color:white; border-radius:5px; padding:5px 16px;}'
            'QPushButton:hover{background:#2c3e50;}')
        export_btn.clicked.connect(self.export_midi)
        btn_row.addWidget(export_btn)

        reset_w_btn = QPushButton('\u2194 恢复列宽')
        reset_w_btn.setFont(QFont('Microsoft YaHei', 10))
        reset_w_btn.setMinimumHeight(34)
        reset_w_btn.setStyleSheet(
            'QPushButton{background:#5a6a7a; color:white; border-radius:5px; padding:5px 12px;}'
            'QPushButton:hover{background:#4a5a6a;}')
        reset_w_btn.clicked.connect(self.reset_column_widths)
        btn_row.addWidget(reset_w_btn)

        btn_row.addStretch()
        status_label = QLabel('状态: 就绪')
        self.status_label = status_label
        status_label.setStyleSheet('color:#b0b0b0; font-size:10px;')
        btn_row.addWidget(status_label)
        main_layout.addLayout(btn_row)

        self.setStyleSheet('''
            QMainWindow{background:#1e272e;}
            QGroupBox{color:#ecf0f1; border:2px solid #3d4f5e; border-radius:8px;
                      margin-top:6px; padding-top:14px; font-weight:bold;}
            QGroupBox::title{subcontrol-origin:margin; left:10px; color:#ecf0f1;}
            QTableWidget{gridline-color:#2c3e50; background:#2c3e50; color:#ecf0f1;
                         border:1px solid #3d4f5e; border-radius:4px;}
            QTableWidget::item{border:1px solid #34495e; color:#ecf0f1;}
            QHeaderView::section{background:#1a252f; color:#ecf0f1; font-weight:bold;
                                 padding:2px; border:1px solid #2c3e50;}
            QLabel{color:#ecf0f1;}
            QCheckBox{color:#ecf0f1; spacing:6px;}
            QSpinBox{background:#34495e; color:#ecf0f1; border:1px solid #3d4f5e;
                     border-radius:3px; padding:2px 4px;}
            QSpinBox::up-button{subcontrol-origin:border; subcontrol-position:top right;
                                width:16px; background:#2c3e50; border-left:1px solid #3d4f5e;
                                border-bottom:1px solid #3d4f5e;}
            QSpinBox::down-button{subcontrol-origin:border; subcontrol-position:bottom right;
                                  width:16px; background:#2c3e50; border-left:1px solid #3d4f5e;}
            QPushButton{color:#ecf0f1;}
        ''')

        self.refresh_grid_display()
        self.status_label.setText('状态: 就绪 | 左键=吹 \u00b7 右键=吸 \u00b7 滚轮中键=清空')

    def enter_insert_mode(self):
        self._insert_start_cols = self.table.columnCount()
        self.insert_mode_btn.setText('完成 ✓')
        self.insert_mode_btn.setStyleSheet('background:#8e44ad; color:white; padding:4px 10px; border-radius:4px;')
        self.insert_mode_btn.clicked.disconnect()
        self.insert_mode_btn.clicked.connect(self.exit_insert_mode)
        self.mode_cancel_btn.show()
        self.del_mode_btn.setEnabled(False)
        self._create_insert_btns()
        header = self.table.horizontalHeader()
        header.sectionResized.connect(self._reposition_insert_btns)
        self.table.horizontalScrollBar().valueChanged.connect(self._reposition_insert_btns)
        self.status_label.setText('状态: ↔ 点击表头缝隙顶部的 + 按钮插入新拍')

    def _create_insert_btns(self):
        for b in self._insert_btns:
            b.deleteLater()
        self._insert_btns.clear()
        header = self.table.horizontalHeader()
        cols = self.table.columnCount()
        if cols < 2:
            return
        for i in range(cols - 1):
            gap = header.sectionViewportPosition(i) + header.sectionSize(i)
            btn = QPushButton('+', header)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                'QPushButton{background:#2ecc71; color:white; font-weight:bold; font-size:16px;'
                'border:none; border-radius:12px;}'
                'QPushButton:hover{background:#27ae60;}'
                'QPushButton:pressed{background:#1e8449;}')
            btn.move(gap - 12, 0)
            btn.raise_()
            btn.show()
            btn.clicked.connect(lambda checked, pos=i+1: self.insert_column_at(pos))
            self._insert_btns.append(btn)

    def _reposition_insert_btns(self, *args):
        header = self.table.horizontalHeader()
        for i, btn in enumerate(self._insert_btns):
            gap = header.sectionViewportPosition(i) + header.sectionSize(i)
            btn.move(gap - 12, 0)
            btn.raise_()

    def exit_insert_mode(self):
        for b in self._insert_btns:
            b.deleteLater()
        self._insert_btns.clear()
        try:
            self.table.horizontalHeader().sectionResized.disconnect(self._reposition_insert_btns)
        except:
            pass
        try:
            self.table.horizontalScrollBar().valueChanged.disconnect(self._reposition_insert_btns)
        except:
            pass
        self.insert_mode_btn.setText('\u2194 插入拍')
        self.insert_mode_btn.setStyleSheet('background:#8e44ad; color:white; padding:4px 10px; border-radius:4px;')
        self.insert_mode_btn.clicked.disconnect()
        self.insert_mode_btn.clicked.connect(self.enter_insert_mode)
        self.mode_cancel_btn.hide()
        self.del_mode_btn.setEnabled(True)
        self._reindex_headers()
        self.status_label.setText('状态: 就绪')

    def enter_delete_mode(self):
        cols = self.table.columnCount()
        if cols <= 1:
            QMessageBox.information(self, '提示', '至少保留1拍，不能删除')
            return
        self.del_mode_btn.setText('确认删除 \u2713')
        self.del_mode_btn.setStyleSheet('background:#27ae60; color:white; padding:4px 10px; border-radius:4px;')
        self.del_mode_btn.clicked.disconnect()
        self.del_mode_btn.clicked.connect(self.execute_delete)
        self.mode_cancel_btn.show()
        self.insert_mode_btn.setEnabled(False)
        header = self.table.horizontalHeader()
        if isinstance(header, ChromaticHeader):
            header.set_op_mode('delete')
        self.status_label.setText('状态: \u2610 点击列左上角小框勾选，再点确认删除')

    def exit_delete_mode(self):
        self.del_mode_btn.setText('\u2610 删除多选')
        self.del_mode_btn.setStyleSheet('background:#c0392b; color:white; padding:4px 10px; border-radius:4px;')
        self.del_mode_btn.clicked.disconnect()
        self.del_mode_btn.clicked.connect(self.enter_delete_mode)
        self.mode_cancel_btn.hide()
        self.insert_mode_btn.setEnabled(True)
        header = self.table.horizontalHeader()
        if isinstance(header, ChromaticHeader):
            header.set_op_mode('normal')
        self.status_label.setText('状态: 就绪')

    def insert_column_at(self, position):
        self.table.insertColumn(position)
        self._reindex_headers()
        self.status_label.setText(f'状态: 已插入第 {position+1} 拍')
        self._create_insert_btns()

    def execute_delete(self):
        if self.table.columnCount() <= 1:
            QMessageBox.warning(self, '错误', '不能删除所有节拍，至少保留1拍')
            return
        header = self.table.horizontalHeader()
        if not isinstance(header, ChromaticHeader):
            self.cancel_current_mode()
            return
        to_delete = sorted(header.delete_marks, reverse=True)
        if not to_delete:
            self.cancel_current_mode()
            return
        for i in to_delete:
            self.table.removeColumn(i)
        self.status_label.setText(f'状态: 已删除 {len(to_delete)} 拍')
        self.exit_delete_mode()

    def cancel_current_mode(self):
        if self._insert_btns:
            while self.table.columnCount() > self._insert_start_cols:
                self.table.removeColumn(self._insert_start_cols)
            self.exit_insert_mode()
            self.status_label.setText('状态: 已取消插入')
            return
        header = self.table.horizontalHeader()
        if isinstance(header, ChromaticHeader) and header.op_mode == 'delete':
            self.exit_delete_mode()
        if isinstance(header, ChromaticHeader) and header.op_mode == 'range_select':
            self._exit_range_selection()
            self.status_label.setText('状态: 已取消新建区间')

    def _reindex_headers(self):
        headers = [str(i + 1) for i in range(self.table.columnCount())]
        self.table.setHorizontalHeaderLabels(headers)

    def reset_column_widths(self):
        header = self.table.horizontalHeader()
        default_w = header.defaultSectionSize()
        for i in range(self.table.columnCount()):
            header.resizeSection(i, default_w)
        self.status_label.setText('状态: 已恢复所有列宽为默认大小')

    def toggle_slide(self, checked):
        self.slide_active = checked
        hole_labels = []
        for h in range(1, 13):
            bn = CHROMATIC_HOLES[h][(True, self.slide_active)][0]
            dn = CHROMATIC_HOLES[h][(False, self.slide_active)][0]
            hole_labels.append(f'{h}\n{bn}|{dn}')
        self.table.setVerticalHeaderLabels(hole_labels)
        self.status_label.setText(f'推键{"已开启" if self.slide_active else "已关闭"}')

    def test_hole_sound(self, hole):
        blow_note, blow_freq = CHROMATIC_HOLES[hole][(True, self.slide_active)]
        draw_note, draw_freq = CHROMATIC_HOLES[hole][(False, self.slide_active)]
        self.audio.play_note(blow_freq, duration=0.2)
        self.status_label.setText(f'孔{hole}: 吹={blow_note} / 吸={draw_note}')

    def get_cell_type(self, row, col):
        item = self.table.item(row, col)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        if isinstance(data, tuple):
            return data[0]
        return data

    def set_cell_type(self, row, col, cell_type):
        hole = row + 1
        if cell_type == 'blow':
            note_name, freq = CHROMATIC_HOLES[hole][(True, self.slide_active)]
            self.audio.play_note(freq, duration=0.2)
            item = QTableWidgetItem('吹')
            item.setBackground(self.CELL_BLOW)
            item.setForeground(QColor('#ecf0f1'))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(QFont('Arial', 9, QFont.Bold))
            item.setData(Qt.UserRole, ('blow', self.slide_active))
            item.setData(Qt.ToolTipRole, f'孔{hole} 吹={note_name}')
            self.table.setItem(row, col, item)
        elif cell_type == 'draw':
            note_name, freq = CHROMATIC_HOLES[hole][(False, self.slide_active)]
            self.audio.play_note(freq, duration=0.2)
            item = QTableWidgetItem('吸')
            item.setBackground(self.CELL_DRAW)
            item.setForeground(QColor('#ecf0f1'))
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(QFont('Arial', 9, QFont.Bold))
            item.setData(Qt.UserRole, ('draw', self.slide_active))
            item.setData(Qt.ToolTipRole, f'孔{hole} 吸={note_name}')
            self.table.setItem(row, col, item)
        else:
            self.table.setItem(row, col, None)

    def eventFilter(self, obj, event):
        if obj != self.table.viewport():
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonPress:
            pos = event.position().toPoint()
            item = self.table.indexAt(pos)
            if item.isValid():
                row, col = item.row(), item.column()
                self.last_col = col
                if event.button() == Qt.LeftButton:
                    self.set_cell_type(row, col, 'blow')
                    return True
                elif event.button() == Qt.RightButton:
                    self.set_cell_type(row, col, 'draw')
                    return True
                elif event.button() == Qt.MiddleButton:
                    self.set_cell_type(row, col, None)
                    return True

        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.MiddleButton:
            pos = event.position().toPoint()
            item = self.table.indexAt(pos)
            if item.isValid():
                row, col = item.row(), item.column()
                self.set_cell_type(row, col, None)
                return True

        return super().eventFilter(obj, event)

    def refresh_grid_display(self):
        pass

    def add_step(self):
        self.table.setColumnCount(self.table.columnCount() + 1)
        self._reindex_headers()
        self.status_label.setText(f'状态: 已加第 {self.table.columnCount()} 拍')

    def delete_last_step(self):
        c = self.table.columnCount()
        if c > 1:
            self.table.setColumnCount(c - 1)
            self._reindex_headers()
            self.status_label.setText(f'状态: 已删最后1拍')

    def get_steps_from_grid(self):
        steps = []
        hole_data = CHROMATIC_HOLES
        for col in range(self.table.columnCount()):
            step = []
            for row in range(12):
                item = self.table.item(row, col)
                if item is None:
                    continue
                data = item.data(Qt.UserRole)
                if isinstance(data, tuple):
                    cell_type, slide_state = data
                elif isinstance(data, str):
                    cell_type = data
                    slide_state = self.slide_active
                else:
                    continue
                if cell_type == 'blow':
                    step.append((row + 1, True, slide_state))
                elif cell_type == 'draw':
                    step.append((row + 1, False, slide_state))
            steps.append(step)
        return steps, hole_data

    def _col_duration(self, col_idx):
        header = self.table.horizontalHeader()
        if col_idx < 0 or col_idx >= self.table.columnCount():
            return 0.3
        w = header.sectionSize(col_idx)
        min_w = header.minimumSectionSize()
        base_s = self.base_unit_spin.value() / 1000.0
        ratio = w / min_w
        return base_s * ratio

    def _get_durations_for_steps(self, steps):
        header = self.table.horizontalHeader()
        min_w = header.minimumSectionSize()
        base_s = self.base_unit_spin.value() / 1000.0
        durations = []
        for col in range(len(steps)):
            if steps[col]:
                w = header.sectionSize(col)
                ratio = w / min_w
                durations.append(base_s * ratio)
            else:
                durations.append(base_s)
        return durations

    def start_range_selection(self):
        if len(self.ranges) >= self.MAX_RANGES:
            QMessageBox.information(self, '提示', f'最多{self.MAX_RANGES}个区间')
            return
        self._range_pending_start = None
        header = self.table.horizontalHeader()
        if isinstance(header, ChromaticHeader):
            header.set_op_mode('range_select')
            header.clear_range_markers()
        self.mode_cancel_btn.show()
        self.range_new_btn.setEnabled(False)
        self.status_label.setText('状态: 点击任意一列设为区间起点')

    def _exit_range_selection(self):
        self._range_pending_start = None
        header = self.table.horizontalHeader()
        if isinstance(header, ChromaticHeader):
            header.set_op_mode('normal')
            header.clear_range_markers()
        self.mode_cancel_btn.hide()
        self.range_new_btn.setEnabled(True)

    def _on_range_col_clicked(self, col):
        if self._range_pending_start is None:
            self._range_pending_start = col
            header = self.table.horizontalHeader()
            if isinstance(header, ChromaticHeader):
                header.set_range_markers(col, -1)
            self.status_label.setText(f'状态: 起点=第{col+1}拍，再点击另一列设为终点')
        else:
            start = self._range_pending_start
            end = col
            lo = min(start, end)
            hi = max(start, end)
            if lo == hi:
                self.status_label.setText('状态: 起点和终点不能是同一列，请重新点击')
                self._range_pending_start = None
                if isinstance(header, ChromaticHeader):
                    header.clear_range_markers()
                return
            rid = self._range_counter + 1
            self.ranges[rid] = {'start': lo, 'end': hi}
            self._range_counter = rid
            self._update_range_combo()
            self._exit_range_selection()
            self.status_label.setText(f'状态: 已新建区间{rid} (第{lo+1}拍 ~ 第{hi+1}拍)')

    def _update_range_combo(self):
        current_val = self.range_combo.currentData()
        self.range_combo.blockSignals(True)
        self.range_combo.clear()
        self.range_combo.addItem('全部', -1)
        sorted_ids = sorted(self.ranges.keys())
        for rid in sorted_ids:
            r = self.ranges[rid]
            label = f'区间{rid}: {r["start"]+1}~{r["end"]+1}'
            self.range_combo.addItem(label, rid)
        idx = self.range_combo.findData(current_val)
        if idx >= 0:
            self.range_combo.setCurrentIndex(idx)
        self.range_combo.blockSignals(False)
        if self.ranges:
            self.range_info_label.setText(f'共{len(self.ranges)}个区间')
        else:
            self.range_info_label.setText('')

    def delete_selected_range(self):
        rid = self.range_combo.currentData()
        if rid is None or rid == -1:
            QMessageBox.information(self, '提示', '请先在区间下拉框中选择要删除的区间')
            return
        del self.ranges[rid]
        self._update_range_combo()
        header = self.table.horizontalHeader()
        if isinstance(header, ChromaticHeader):
            header.clear_range_markers()
        self.status_label.setText(f'状态: 已删除区间{rid}')

    def _get_playback_range(self):
        rid = self.range_combo.currentData()
        if rid is None or rid == -1:
            return None
        r = self.ranges.get(rid)
        if r is None:
            return None
        return (r['start'], r['end'])

    def toggle_recording(self):
        self.clear_all()
        if self.record_btn.text().startswith('\U0001f534'):
            self.record_btn.setText('\u23fa  录制中...')
            self.record_btn.setStyleSheet(
                'QPushButton{background:#c0392b; color:white; border-radius:5px; padding:5px 16px; font-weight:bold;}')
            self.status_label.setText('状态: \u23fa 录制中...点击单元格输入音符')
        else:
            self.record_btn.setText('\U0001f534  开始录制')
            self.record_btn.setStyleSheet(
                'QPushButton{background:#e74c3c; color:white; border-radius:5px; padding:5px 16px;}'
                'QPushButton:hover{background:#c0392b;}')
            total = sum(1 for r in range(12) for c in range(self.table.columnCount())
                        if self.get_cell_type(r, c) is not None)
            self.status_label.setText(f'状态: 录制完成，共 {total} 个音符')

    def playback(self):
        steps, hole_data = self.get_steps_from_grid()
        pbrange = self._get_playback_range()
        if pbrange is not None:
            pstart, pend = pbrange
            if pstart >= len(steps):
                QMessageBox.information(self, '提示', '区间起始超出节拍总数')
                return
            steps = steps[pstart:pend+1]
            if not steps:
                QMessageBox.information(self, '提示', '区间内没有节拍')
                return

        total_notes = sum(len(s) for s in steps)
        if total_notes == 0:
            QMessageBox.information(self, '提示', '没有音符，先点击单元格输入吧')
            return

        self.play_btn.setEnabled(False)
        self.record_btn.setEnabled(False)
        durations = self._get_durations_for_steps(steps)
        self.playback_thread = PlaybackThread(steps, hole_data, durations)
        self.playback_thread.step_playing.connect(self.highlight_step)
        self.playback_thread.finished.connect(self.playback_finished)
        self.playback_thread.start()
        if pbrange is not None:
            self.status_label.setText(f'状态: \u25b6 区间回放中...')
        else:
            self.status_label.setText('状态: \u25b6 回放中...')

    def highlight_step(self, step_idx, note_names):
        notes_str = ' '.join(note_names) if note_names else '(休止)'
        self.status_label.setText(f'\u25b6 第{step_idx+1}拍: {notes_str}')
        for row in range(12):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                cell_data = item.data(Qt.UserRole)
                cell_type = cell_data[0] if isinstance(cell_data, tuple) else cell_data
                if col == step_idx:
                    if cell_type == 'blow':
                        item.setBackground(QColor(180, 120, 40))
                    elif cell_type == 'draw':
                        item.setBackground(QColor(100, 130, 60))
                else:
                    if cell_type == 'blow':
                        item.setBackground(self.CELL_BLOW)
                    elif cell_type == 'draw':
                        item.setBackground(self.CELL_DRAW)

    def playback_finished(self):
        self.play_btn.setEnabled(True)
        self.record_btn.setEnabled(True)
        for row in range(12):
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                cell_data = item.data(Qt.UserRole)
                cell_type = cell_data[0] if isinstance(cell_data, tuple) else cell_data
                if cell_type == 'blow':
                    item.setBackground(self.CELL_BLOW)
                elif cell_type == 'draw':
                    item.setBackground(self.CELL_DRAW)
        self.status_label.setText('状态: 回放完成')

    def clear_all(self):
        for row in range(12):
            for col in range(self.table.columnCount()):
                self.table.setItem(row, col, None)
        self.status_label.setText('状态: 已清空')

    def export_midi(self):
        steps, hole_data = self.get_steps_from_grid()
        total_notes = sum(len(s) for s in steps)
        if total_notes == 0:
            QMessageBox.information(self, '提示', '没有音符可导出')
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, '导出 MIDI', 'my_song.mid', 'MIDI 文件 (*.mid)')
        if not file_path:
            return

        try:
            from music21 import stream, note, tempo, meter, duration
            base_s = self.base_unit_spin.value() / 1000.0
            sub = self.div_spin.value()

            s = stream.Score()
            p = stream.Part()
            bpm = 60.0 / base_s
            s.append(tempo.MetronomeMark(number=bpm))
            s.append(meter.TimeSignature('4/4'))
            s.append(p)

            for step in steps:
                if not step:
                    r = note.Rest()
                    r.duration = duration.Duration(base_s / sub)
                    p.append(r)
                else:
                    for hole, blow, slide_state in step:
                        key = (True, slide_state) if blow else (False, slide_state)
                        note_name, _ = hole_data[hole][key]
                        midi_note = note.Note(note_name)
                        midi_note.duration = duration.Duration(base_s / sub)
                        p.append(midi_note)

            s.write('midi', fp=file_path)
            QMessageBox.information(self, '导出成功',
                f'已导出 {total_notes} 个音符到:\n{file_path}')
            self.status_label.setText(f'状态: 已导出 {file_path}')
        except Exception as e:
            QMessageBox.warning(self, '导出失败', str(e))

    def closeEvent(self, event):
        self.audio.close()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = HarmonicaStepSequencer()
    window.show()
    sys.exit(app.exec())