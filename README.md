# PCBLEtoVRC
利用PC蓝牙模块连接通用心率广播协议获取心率并向VRC发送心率参数的工具\n
启动软件，首先进入配置选项卡调整我们的 配置\n
OSC的IP地址和端口地址一般不用修改，除非你需要将参数推送到另外的电脑\n
参数信息按需修改，根据你模型使用的心率参数自行修改，如果你是用的是我提供的心率预制件，可以直接使用\n
设备配置根据你的实际情况修改：设备名可以模糊搜索，一般在你打开手环的心率广播以后，手环上会显示你手环设备的名字\n
最低心率和最高心率的设置只会影响float参数的取值\n
工作模式如果选择【OBS模式】，将会在文件夹下生成一个【rate.txt】，实时更新心率数值，以便OBS等推流软件调用\n
点击【保存配置】将会修改【config.ini】配置文件，下次启动将会直接调用\n
<img width="578" height="452" alt="image" src="https://github.com/user-attachments/assets/6251d020-1854-4e45-a7a3-893f925e4a69" />\n
启动你的手环心率广播并确保你的电脑已经启动蓝牙功能\n
<img width="578" height="452" alt="image" src="https://github.com/user-attachments/assets/af4b8721-5313-4186-8194-9e654174bde0" />\n
点击【连接并发送参数】，将会尝试连接你的手环设备并获取心率数值，发送给目标端口\n
<img width="502" height="632" alt="image" src="https://github.com/user-attachments/assets/31ed0798-bad3-434a-880e-65a3e6540f0e" />

