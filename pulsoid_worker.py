# -*- coding: utf-8 -*-
"""
Pulsoid Worker - 通过 WebSocket 从 Pulsoid/Stromno 获取心率数据

该模块提供与 HeartRateWorker 相同的信号接口，便于在 GUI 中无缝切换数据源。
"""

import json
import time
import requests
import websocket
from pythonosc.udp_client import SimpleUDPClient
from PyQt5.QtCore import QThread, pyqtSignal


def get_websocket_url(widget_id: str) -> str:
    """
    调用 Stromno API 获取 WebSocket URL
    
    Args:
        widget_id: Pulsoid Widget ID
        
    Returns:
        WebSocket URL，失败返回空字符串
    """
    try:
        response = requests.post(
            'https://api.stromno.com/v1/api/public/rpc',
            headers={'Content-Type': 'application/json'},
            json={
                'id': str(int(time.time() * 1000)),
                'jsonrpc': '2.0',
                'method': 'getWidget',
                'params': {'widgetId': widget_id}
            },
            timeout=10
        )
        
        if response.status_code != 200:
            return ''
        
        data = response.json()
        if 'error' in data:
            return ''
        
        return data.get('result', {}).get('ramielUrl', '')
    except Exception as e:
        print(f"获取 WebSocket URL 失败: {e}")
        return ''


class PulsoidWorker(QThread):
    """Pulsoid 心率数据获取工作线程"""
    
    # 与 HeartRateWorker 相同的信号接口
    status_update = pyqtSignal(str)
    heart_rate_update = pyqtSignal(int, float)
    connection_status = pyqtSignal(bool)
    device_found = pyqtSignal(str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.ws = None
        
        # 从配置中读取参数
        self.osc_ip = config.get('DATABASE', 'osc_ip')
        self.osc_port = config.getint('DATABASE', 'osc_port')
        self.osc_int = config.get('DATABASE', 'osc_int')
        self.osc_float = config.get('DATABASE', 'osc_float')
        self.osc_bool = config.get('DATABASE', 'osc_bool')
        self.hr_min = config.getint('DATABASE', 'hr_min')
        self.hr_max = config.getint('DATABASE', 'hr_max')
        self.widget_id = config.get('DATABASE', 'pulsoid_widget_id', fallback='')
        self.obs_mode = config.getint('DATABASE', 'obs_mode')
        
        # 初始化 OSC 客户端
        self.osc_client = SimpleUDPClient(self.osc_ip, self.osc_port)
        
        # 心率超时检测
        self.last_heartrate_time = 0
        self.timeout_seconds = 10
    
    def stop(self):
        """停止工作线程"""
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
    
    def send_osc(self, heart_rate: int) -> str:
        """发送 OSC 数据"""
        percent_f = min(heart_rate / self.hr_max, 1.0)
        self.osc_client.send_message(self.osc_bool, True)
        self.osc_client.send_message(self.osc_int, heart_rate)
        self.osc_client.send_message(self.osc_float, percent_f)
        return f"心率整数值: {heart_rate}; 心率浮点值: {percent_f:.2f}"
    
    def on_message(self, ws, message: str):
        """处理 WebSocket 消息"""
        try:
            data = json.loads(message)
            heart_rate = data.get('data', {}).get('heartRate', 0)
            
            if heart_rate > 0:
                self.last_heartrate_time = time.time()
                vrc_status = self.send_osc(heart_rate)
                
                # 发送信号更新 UI
                percent_f = min(heart_rate / self.hr_max, 1.0)
                self.heart_rate_update.emit(heart_rate, percent_f)
                
                status_text = f"Pulsoid 实时心率 -> {vrc_status}"
                if self.obs_mode == 1:
                    status_text += ", 正在输出 txt."
                    with open("rate.txt", "w", encoding="utf-8") as f:
                        f.write(f"{heart_rate}")
                
                self.status_update.emit(status_text)
        except Exception as e:
            self.status_update.emit(f"解析心率数据失败: {e}")
    
    def on_error(self, ws, error):
        """处理 WebSocket 错误"""
        self.status_update.emit(f"WebSocket 错误: {error}")
        self.connection_status.emit(False)
    
    def on_close(self, ws, close_status_code, close_msg):
        """处理 WebSocket 关闭"""
        self.status_update.emit("WebSocket 连接已关闭")
        self.connection_status.emit(False)
    
    def on_open(self, ws):
        """处理 WebSocket 打开"""
        self.status_update.emit("Pulsoid WebSocket 连接成功！正在监听心率...")
        self.device_found.emit(f"Pulsoid (Widget: {self.widget_id[:8]}...)")
        self.connection_status.emit(True)
    
    def run(self):
        """线程运行函数"""
        self.running = True
        
        if not self.widget_id:
            self.status_update.emit("错误：未配置 Pulsoid Widget ID")
            self.connection_status.emit(False)
            return
        
        self.status_update.emit(f"正在获取 Pulsoid WebSocket 地址...")
        
        ws_url = get_websocket_url(self.widget_id)
        if not ws_url:
            self.status_update.emit("错误：无法获取 WebSocket URL，请检查 Widget ID 是否正确")
            self.connection_status.emit(False)
            return
        
        self.status_update.emit(f"正在连接 Pulsoid WebSocket...")
        
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                
                # 运行 WebSocket（阻塞）
                self.ws.run_forever()
                
                if self.running:
                    self.status_update.emit("连接断开，5秒后重试...")
                    time.sleep(5)
                    
            except Exception as e:
                self.status_update.emit(f"连接异常: {e}")
                if self.running:
                    time.sleep(5)
        
        # 线程结束时发送断开信号
        self.osc_client.send_message(self.osc_bool, False)
        self.status_update.emit("Pulsoid 心率监测已停止")
