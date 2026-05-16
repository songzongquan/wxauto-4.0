from wxauto4 import WeChat
import time

wx = WeChat()
wx.ChatWith('文件传输助手')
wx.SendMsg("hello,world")

def on_message(msg, chat):
    sender = msg.sender if hasattr(msg, 'sender') else ''
    print(f"[{msg.attr}] {sender}: {msg.content}")

wx.AddListenChat('任老师', on_message)

print("已开始监听【任老师】，按 Ctrl+C 停止...")
try:
    wx.KeepRunning()
except KeyboardInterrupt:
    print("停止监听")
    wx.StopListening()
