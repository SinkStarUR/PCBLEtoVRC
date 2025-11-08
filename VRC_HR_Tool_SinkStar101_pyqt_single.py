import asyncio
import time
import sys
from bleak import BleakScanner, BleakClient
from pythonosc.udp_client import SimpleUDPClient
import configparser

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLabel, QPushButton, QTextEdit, QGroupBox,
                             QProgressBar, QSpinBox, QDoubleSpinBox, QLineEdit,
                             QCheckBox, QComboBox, QTabWidget, QFormLayout)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QPalette, QColor

class HeartRateWorker(QThread):
    """工作线程，用于运行异步的心率监测代码"""
    
    # 定义信号
    status_update = pyqtSignal(str)
    heart_rate_update = pyqtSignal(int, float)
    connection_status = pyqtSignal(bool)
    device_found = pyqtSignal(str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.client = None
        
        # 从配置中读取参数
        self.osc_ip = config.get('DATABASE', 'osc_ip')
        self.osc_port = config.getint('DATABASE', 'osc_port')
        self.osc_int = config.get('DATABASE', 'osc_int')
        self.osc_float = config.get('DATABASE', 'osc_float')
        self.hr_min = config.getint('DATABASE', 'hr_min')
        self.hr_max = config.getint('DATABASE', 'hr_max')
        self.osc_bool = config.get('DATABASE', 'osc_bool')
        self.dev_name = config.get('DATABASE', 'device_name')
        self.obs_mode = config.getint('DATABASE', 'obs_mode')
        
        self.target_device_names = [self.dev_name]
        self.xiaomi_heartrate_char_uuid = "00002a37-0000-1000-8000-00805f9b34fb"
        
        # 初始化OSC客户端
        self.osc_client = SimpleUDPClient(self.osc_ip, self.osc_port)
    
    def stop(self):
        """停止工作线程"""
        self.running = False
        if self.client:
            # 这里需要处理异步关闭，简化处理
            pass
    
    def send_osc(self, heart_rate):
        """发送OSC数据"""
        percent = heart_rate
        percent_f = min(heart_rate / self.hr_max, self.hr_min)
        self.osc_client.send_message(self.osc_bool, True)
        self.osc_client.send_message(self.osc_int, percent)
        self.osc_client.send_message(self.osc_float, percent_f)
        return f"心率整数值: {heart_rate}; 心率浮点值: {percent_f:.2f}"
    
    def notification_handler(self, sender, data):
        """处理心率通知"""
        if len(data) >= 2:
            heart_rate = data[1]
            vrc_status = self.send_osc(heart_rate)
            
            # 发送信号更新UI
            self.heart_rate_update.emit(heart_rate, min(heart_rate / self.hr_max, self.hr_min))
            
            status_text = f"实时心率 -> {vrc_status}"
            if self.obs_mode == 1:
                status_text += ",正在输出txt."
                with open("rate.txt", "w", encoding="utf-8") as frate:
                    frate.write(f"{heart_rate}")
            
            self.status_update.emit(status_text)
    
    async def find_target_device_async(self):
        """异步查找设备"""
        scan = 1
        self.status_update.emit("开始扫描蓝牙心率设备，共5次。")
        
        while scan <= 5 and self.running:
            self.status_update.emit(f"正在扫描蓝牙设备...第{scan}次")
            devices = await BleakScanner.discover()
            
            for device in devices:
                if device.name and self.running:
                    for target_name in self.target_device_names:
                        if target_name in device.name:
                            self.device_found.emit(f"成功找到目标设备: {device.name} ({device.address})")
                            return device
            
            self.status_update.emit(f"第{scan}次扫描结束，未找到指定设备，开始下一次扫描。")
            await asyncio.sleep(1)
            scan += 1
        
        return None
    
    async def main_loop_async(self):
        """异步主循环"""
        device = await self.find_target_device_async()
        
        if not device:
            self.status_update.emit(f"错误：扫描结束，未找到名称包含 {self.target_device_names} 的设备。")
            self.connection_status.emit(False)
            return
        
        self.connection_status.emit(True)
        
        while self.running:
            try:
                async with BleakClient(device.address) as client:
                    self.client = client
                    if client.is_connected:
                        self.status_update.emit("设备连接成功！正在监听心率...")
                        self.status_update.emit(f"正在向 OSC 地址 {self.osc_ip}:{self.osc_port} 发送当前心率。")
                        
                        await client.start_notify(self.xiaomi_heartrate_char_uuid, self.notification_handler)
                        
                        while client.is_connected and self.running:
                            await asyncio.sleep(1)
            except Exception as e:
                self.status_update.emit(f"连接断开或发生错误: {e}")
                self.connection_status.emit(False)
                if self.running:
                    self.status_update.emit("将在5秒后尝试重新连接...")
                    await asyncio.sleep(5)
    
    def run(self):
        """线程运行函数"""
        self.running = True
        
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self.main_loop_async())
        except Exception as e:
            self.status_update.emit(f"线程运行异常: {e}")
        finally:
            loop.close()
            self.osc_client.send_message(self.osc_bool, False)
            self.status_update.emit("心率监测已停止")


class HeartRateMonitorGUI(QMainWindow):
    """心率监测器GUI主窗口"""
    
    def __init__(self):
        super().__init__()
        
        # 读取配置文件
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        
        # 初始化工作线程
        self.worker = None
        
        # 初始化UI
        self.init_ui()
        
        # 设置定时器用于更新UI
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)  # 每100ms更新一次
        
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("VRC心率OSC工具")
        self.setGeometry(100, 100, 500, 600)
        
        # 设置主窗口部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 创建标签页
        tabs = QTabWidget()
        main_layout.addWidget(tabs)
        
        # 状态监控标签页
        status_tab = QWidget()
        status_layout = QVBoxLayout(status_tab)
        tabs.addTab(status_tab, "状态监控")
        
        # 配置标签页
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        tabs.addTab(config_tab, "配置")
        
        # 构建状态监控界面
        self.build_status_tab(status_layout)
        
        # 构建配置界面
        self.build_config_tab(config_layout)
        
        # 添加底部按钮
        self.build_bottom_buttons(main_layout)
    
    def build_status_tab(self, layout):
        """构建状态监控标签页"""
        # 连接状态组
        connection_group = QGroupBox("连接状态")
        connection_layout = QVBoxLayout(connection_group)
        
        self.connection_status_label = QLabel("未连接")
        self.connection_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
        connection_layout.addWidget(self.connection_status_label)
        
        self.device_info_label = QLabel("设备: 未找到")
        connection_layout.addWidget(self.device_info_label)
        
        layout.addWidget(connection_group)
        
        # 心率数据显示组
        data_group = QGroupBox("心率数据")
        data_layout = QVBoxLayout(data_group)
        
        # 心率数值显示
        heart_rate_layout = QHBoxLayout()
        self.heart_rate_label = QLabel("--")
        self.heart_rate_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #e74c3c;")
        self.heart_rate_label.setAlignment(Qt.AlignCenter)
        heart_rate_layout.addWidget(self.heart_rate_label)
        
        self.heart_rate_float_label = QLabel("--")
        self.heart_rate_float_label.setStyleSheet("font-size: 24px; color: #3498db;")
        self.heart_rate_float_label.setAlignment(Qt.AlignCenter)
        heart_rate_layout.addWidget(self.heart_rate_float_label)
        
        data_layout.addLayout(heart_rate_layout)
        
        # 心率进度条
        self.heart_rate_progress = QProgressBar()
        self.heart_rate_progress.setRange(0, 200)
        self.heart_rate_progress.setValue(0)
        self.heart_rate_progress.setFormat("心率: %v BPM")
        data_layout.addWidget(self.heart_rate_progress)
        
        layout.addWidget(data_group)
        
        # 状态日志组
        log_group = QGroupBox("状态日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
    
    def build_config_tab(self, layout):
        """构建配置标签页"""
        # OSC配置组
        osc_group = QGroupBox("OSC配置")
        osc_layout = QFormLayout(osc_group)
        
        self.osc_ip_edit = QLineEdit(self.config.get('DATABASE', 'osc_ip'))
        osc_layout.addRow("OSC IP地址:", self.osc_ip_edit)
        
        self.osc_port_spin = QSpinBox()
        self.osc_port_spin.setRange(1, 65535)
        self.osc_port_spin.setValue(self.config.getint('DATABASE', 'osc_port'))
        osc_layout.addRow("OSC端口:", self.osc_port_spin)
        
        self.osc_int_edit = QLineEdit(self.config.get('DATABASE', 'osc_int'))
        osc_layout.addRow("int参数地址:", self.osc_int_edit)
        
        self.osc_float_edit = QLineEdit(self.config.get('DATABASE', 'osc_float'))
        osc_layout.addRow("float参数地址:", self.osc_float_edit)
        
        self.osc_bool_edit = QLineEdit(self.config.get('DATABASE', 'osc_bool'))
        osc_layout.addRow("bool参数地址:", self.osc_bool_edit)
        
        layout.addWidget(osc_group)
        
        # 设备配置组
        device_group = QGroupBox("设备配置")
        device_layout = QFormLayout(device_group)
        
        self.device_name_edit = QLineEdit(self.config.get('DATABASE', 'device_name'))
        device_layout.addRow("设备名称:", self.device_name_edit)
        
        self.hr_min_spin = QSpinBox()
        self.hr_min_spin.setRange(0, 200)
        self.hr_min_spin.setValue(self.config.getint('DATABASE', 'hr_min'))
        device_layout.addRow("最低心率:", self.hr_min_spin)
        
        self.hr_max_spin = QSpinBox()
        self.hr_max_spin.setRange(0, 200)
        self.hr_max_spin.setValue(self.config.getint('DATABASE', 'hr_max'))
        device_layout.addRow("最高心率:", self.hr_max_spin)
        
        self.obs_mode_combo = QComboBox()
        self.obs_mode_combo.addItem("普通模式", 0)
        self.obs_mode_combo.addItem("OBS模式", 1)
        self.obs_mode_combo.setCurrentIndex(self.config.getint('DATABASE', 'obs_mode'))
        device_layout.addRow("工作模式:", self.obs_mode_combo)
        
        layout.addWidget(device_group)
        
        # 保存配置按钮
        self.save_config_button = QPushButton("保存配置")
        self.save_config_button.clicked.connect(self.save_config)
        layout.addWidget(self.save_config_button)
        
        layout.addStretch()
    
    def build_bottom_buttons(self, layout):
        """构建底部按钮"""
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("连接并发送参数")
        self.start_button.clicked.connect(self.start_monitoring)
        self.start_button.setStyleSheet("QPushButton { background-color: #27ae60; color: white; font-size: 14px; }")
        
        self.stop_button = QPushButton("终止并断开连接")
        self.stop_button.clicked.connect(self.stop_monitoring)
        self.stop_button.setStyleSheet("QPushButton { background-color: #e74c3c; color: white; font-size: 14px; }")
        self.stop_button.setEnabled(False)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)
    
    def start_monitoring(self):
        """开始心率监测"""
        # 保存当前配置
        self.save_config()
        
        # 重新读取配置
        self.config.read('config.ini')
        
        # 创建工作线程
        self.worker = HeartRateWorker(self.config)
        
        # 连接信号
        self.worker.status_update.connect(self.update_status)
        self.worker.heart_rate_update.connect(self.update_heart_rate_display)
        self.worker.connection_status.connect(self.update_connection_status)
        self.worker.device_found.connect(self.update_device_info)
        
        # 启动线程
        self.worker.start()
        
        # 更新按钮状态
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        self.log_text.append("开始心率监测...")
    
    def stop_monitoring(self):
        """停止心率监测"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(5000)  # 等待5秒线程结束
        
        # 更新按钮状态
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        self.connection_status_label.setText("未连接")
        self.connection_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
        
        self.log_text.append("已终止并断开设备连接")
    
    def update_status(self, message):
        """更新状态消息"""
        self.log_text.append(message)
        # 自动滚动到底部
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def update_heart_rate_display(self, heart_rate, heart_rate_float):
        """更新心率显示"""
        self.heart_rate_label.setText(f"{heart_rate}")
        self.heart_rate_float_label.setText(f"{heart_rate_float:.2f}")
        self.heart_rate_progress.setValue(heart_rate)
    
    def update_connection_status(self, connected):
        """更新连接状态"""
        if connected:
            self.connection_status_label.setText("已连接")
            self.connection_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
        else:
            self.connection_status_label.setText("连接断开")
            self.connection_status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: orange;")
    
    def update_device_info(self, device_info):
        """更新设备信息"""
        self.device_info_label.setText(f"设备: {device_info}")
    
    def update_ui(self):
        """定期更新UI"""
        # 这里可以添加需要定期更新的UI元素
        pass
    
    def save_config(self):
        """保存配置到文件"""
        self.config.set('DATABASE', 'osc_ip', self.osc_ip_edit.text())
        self.config.set('DATABASE', 'osc_port', str(self.osc_port_spin.value()))
        self.config.set('DATABASE', 'osc_int', self.osc_int_edit.text())
        self.config.set('DATABASE', 'osc_float', self.osc_float_edit.text())
        self.config.set('DATABASE', 'osc_bool', self.osc_bool_edit.text())
        self.config.set('DATABASE', 'device_name', self.device_name_edit.text())
        self.config.set('DATABASE', 'hr_min', str(self.hr_min_spin.value()))
        self.config.set('DATABASE', 'hr_max', str(self.hr_max_spin.value()))
        self.config.set('DATABASE', 'obs_mode', str(self.obs_mode_combo.currentData()))
        
        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)
        
        self.log_text.append("配置已保存")
    
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)  # 等待3秒线程结束
        
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle('Fusion')
    
    window = HeartRateMonitorGUI()
    window.show()
    
    sys.exit(app.exec_())