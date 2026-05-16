from .base import BaseUISubWnd, BaseUIWnd
from .navigationbox import NavigationBox
from .sessionbox import SessionBox
from .chatbox import ChatBox
from wxauto4.utils.win32 import (
    FindWindow,
    GetAllWindows,
    GetPathByHwnd,
    get_windows_by_pid
)
from wxauto4.param import WxParam, WxResponse, PROJECT_NAME
from wxauto4.logger import wxlog
from wxauto4 import uia
from typing import (
    Union, 
    List,
    Literal
)
import random
import os
import re
import sys
import time

class WeChatSubWnd(BaseUISubWnd):
    _ui_cls_name: str = 'mmui::FramelessMainWindow'
    _win_cls_name: str = 'Qt51514QWindowIcon'
    _chat_api: ChatBox = None
    nickname: str = ''

    def __init__(
            self, 
            key: Union[str, int], 
            parent: 'WeChatMainWnd', 
            timeout: int = 3
        ):
        self.root = self
        self.parent = parent
        if isinstance(key, str):
            hwnd = FindWindow(classname=self._win_cls_name, name=key, timeout=timeout)
        else:
            hwnd = key
        self.control = uia.ControlFromHandle(hwnd)
        if self.control is not None:
            chatbox_control = self.control.\
                GroupControl(ClassName="mmui::ChatMessagePage").\
                CustomControl(ClassName="mmui::XSplitterView")
            self._chat_api = ChatBox(chatbox_control, self)
            self.nickname = self.control.Name

    def __repr__(self):
        return f'<{PROJECT_NAME} - {self.__class__.__name__} object("{self.nickname}")>'

    @property
    def pid(self):
        if not hasattr(self, '_pid'):
            self._pid = self.control.ProcessId
        return self._pid
    
    def _get_chatbox(
            self, 
            nickname: str=None, 
            exact: bool=False
        ) -> ChatBox:
        return self._chat_api
    
    def _get_windows(self):
        wins = []
        for hwnd in get_windows_by_pid(self.pid):
            try:
                wins.append(uia.ControlFromHandle(hwnd))
            except:
                pass
        ignore_cls = ['basepopupshadow', 'popupshadow']
        return [win for win in wins if win.ClassName not in ignore_cls]
    
    def chat_info(self):
        return self._chat_api.get_info()
    
    def send_msg(
            self,
            msg: str,
            who: str=None,
            clear: bool=True,
            at: Union[str, List[str]]=None,
            exact: bool=False,
        ) -> WxResponse:
        self._show()
        chatbox = self._get_chatbox(who, exact)
        if chatbox is None:
            return WxResponse.failure(f"未找到聊天窗口：{who}")
        return chatbox.send_msg(msg, clear, at)

    def send_files(
            self,
            filepath,
            who=None,
            exact=False
        ) -> WxResponse:
        self._show()
        chatbox = self._get_chatbox(who, exact)
        if chatbox is None:
            return WxResponse.failure(f"未找到聊天窗口：{who}")
        return chatbox.send_file(filepath)
    
    def get_msgs(self):
        chatbox = self._get_chatbox()
        if chatbox:
            return chatbox.get_msgs()
        return []

    def get_new_msgs(self):
        return self._get_chatbox().get_new_msgs()

    def get_msg_by_id(self, msg_id):
        chatbox = self._get_chatbox()
        if chatbox:
            return chatbox.get_msg_by_id(msg_id)

    def get_msg_by_hash(self, msg_hash: str):
        chatbox = self._get_chatbox()
        if chatbox:
            return chatbox.get_msg_by_hash(msg_hash)

    def get_last_msg(self):
        chatbox = self._get_chatbox()
        if chatbox:
            return chatbox.get_last_msg()

    

class WeChatMainWnd(WeChatSubWnd):
    _ui_cls_name: str = 'mmui::MainWindow'
    _win_cls_name: str = 'Qt51514QWindowIcon'
    _ui_name: str = '微信'

    def __init__(self, nickname: str = None, hwnd: int = None):
        self.root = self
        self.parent = self
        self._self_nickname = ''
        if hwnd:
            self._setup_ui(hwnd)
        else:
            wxs = [i for i in GetAllWindows() if i[1] == self._win_cls_name]
            if len(wxs) == 0:
                raise Exception('未找到已登录的微信主窗口')
            for index, (hwnd, clsname, winname) in enumerate(wxs):
                self._setup_ui(hwnd)
                if self.control.ClassName == self._ui_cls_name:
                    break
                elif index+1 == len(wxs):
                    raise Exception(f'未找到微信窗口：{nickname}')
        # if NetErrInfoTipsBarWnd(self):
        #     raise NetWorkError('微信无法连接到网络')

        print(f'初始化成功，获取到已登录窗口：{self.nickname}')

    def _setup_ui(self, hwnd: int):
        self.HWND = hwnd
        self.control = uia.ControlFromHandle(hwnd)
        if self.control is not None:
            navigation_control = self.control.\
                ToolBarControl(ClassName="mmui::MainTabBar")
            sessionbox_control = self.control.\
                GroupControl(ClassName="mmui::ChatMasterView")
            chatbox_control = self.control.\
                GroupControl(ClassName="mmui::ChatMessagePage").\
                CustomControl(ClassName="mmui::XSplitterView")
            self._navigation_api = NavigationBox(navigation_control, self)
            self._session_api = SessionBox(sessionbox_control, self)
            self._chat_api = ChatBox(chatbox_control, self)
            self.nickname = self.control.Name

    def __repr__(self):
        return f'<{PROJECT_NAME} - {self.__class__.__name__} object("{self.nickname}")>'

    def _get_wx_path(self):
        return GetPathByHwnd(self.HWND)

    def _detect_self_nickname(self, timeout=3):
        """自动检测当前登录用户的昵称

        通过点击主窗口导航栏上方的头像区域，读取弹出资料卡中的昵称
        """
        if self._self_nickname:
            return self._self_nickname
        try:
            self._show()
            # 头像在MainTabBar上方（TabBar从y=43开始，第一个tab从y=139开始）
            # 点击TabBar顶部区域（约x=30, y=50偏移）触发头像点击
            tabbar = self.control.ToolBarControl(ClassName="mmui::MainTabBar")
            if not tabbar.Exists(1):
                wxlog.debug('未找到MainTabBar')
                return ''
            tabbar.Click(x=30, y=50, ratioX=0, ratioY=0)

            # 等待弹窗出现（弹窗是独立窗口 mmui::ProfileUniquePop）
            nickname = ''
            from wxauto4.utils.win32 import get_windows_by_pid
            t0 = time.time()
            while time.time() - t0 < timeout:
                for hwnd in get_windows_by_pid(self.pid):
                    try:
                        c = uia.ControlFromHandle(hwnd)
                        if c.ClassName == 'mmui::ProfileUniquePop':
                            # 昵称在 AutomationId=right_v_view.nickname_button_view.display_name_text
                            name_ctrl = c.TextControl(
                                AutomationId='right_v_view.nickname_button_view.display_name_text'
                            )
                            if name_ctrl.Exists(1) and name_ctrl.Name:
                                nickname = name_ctrl.Name
                            # 关闭弹窗
                            c.SendKeys('{Esc}')
                            time.sleep(0.3)
                            break
                    except:
                        pass
                if nickname:
                    break
                time.sleep(0.3)

            # 恢复主窗口（弹窗可能导致主窗口失焦或最小化）
            self._show()

            if not nickname:
                wxlog.debug('自动检测昵称失败，未找到资料弹窗或昵称文本')
                # 确保关闭可能残留的弹窗
                self.control.SendKeys('{Esc}')
                time.sleep(0.2)
                self._show()
            else:
                self._self_nickname = nickname
                wxlog.debug(f'自动检测到当前用户昵称: {nickname}')

            return self._self_nickname
        except Exception as e:
            wxlog.debug(f'自动检测昵称异常: {e}')
            self._show()
            return ''
    
    def _get_wx_dir(self):
        wxdir = os.path.dirname(self._get_wx_path())
        for d in os.listdir(wxdir):
            if re.match(r'\d+\.\d+\.\d+\.\d+', d):
                return os.path.join(wxdir, d)

    def _get_chatbox(
            self,
            nickname: str=None,
            exact: bool=False
        ) -> ChatBox:
        self._show()
        if nickname and (chatbox := WeChatSubWnd(nickname, self, timeout=0)).control:
            return chatbox._chat_api
        else:
            if nickname:
                switch_result = self._session_api.switch_chat(keywords=nickname, exact=exact)
                if not switch_result:
                    return None
            if self._chat_api.msgbox.Exists(0.5):
                return self._chat_api

    def switch_chat(
            self,
            keywords: str,
            exact: bool = True,
            force: bool = False,
            force_wait: Union[float, int] = 0.5
        ):
        self._show()
        return self._session_api.switch_chat(keywords, exact, force, force_wait)
        
    def get_all_sub_wnds(self):
        sub_wxs = GetAllWindows(classname=WeChatSubWnd._win_cls_name)
        return [
            sub_win 
            for i in sub_wxs 
            if (
                uia.ControlFromHandle(i[0]).ClassName == WeChatSubWnd._ui_cls_name
                and (sub_win:= WeChatSubWnd(i[0], self)).pid == self.pid
            )
        ]
    
    def get_sub_wnd(self, who: str):
        subwins = self.get_all_sub_wnds()
        for subwin in subwins:
            if subwin.nickname == who:
                return subwin
            
    def open_separate_window(self, keywords: str) -> WeChatSubWnd:
        self._show()
        if subwin := self.get_sub_wnd(keywords):
            wxlog.debug(f"{keywords} 获取到已存在的子窗口: {subwin}")
            return subwin
        if nickname := self._session_api.switch_chat(keywords):
            wxlog.debug(f"{keywords} 切换到聊天窗口: {nickname}")
            if subwin := self.get_sub_wnd(nickname):
                wxlog.debug(f"{nickname} 获取到已存在的子窗口: {subwin}")
                return subwin
            else:
                keywords = nickname
        if result := self._session_api.open_separate_window(keywords):
            find_nickname = result['data'].get('nickname', keywords)
            return WeChatSubWnd(find_nickname, self)