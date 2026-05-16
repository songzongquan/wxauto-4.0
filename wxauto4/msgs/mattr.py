from .base import (
    BaseMessage, 
    HumanMessage
)
from wxauto4 import uia
from wxauto4.param import (
    WxParam, 
    WxResponse, 
    PROJECT_NAME
)
from wxauto4.utils import uilock

from typing import (
    Dict, 
    List, 
    Any,
    TYPE_CHECKING
)
if TYPE_CHECKING:
    from wxauto4.ui.chatbox import ChatBox

class SystemMessage(BaseMessage):
    attr = 'system'
    
    def __init__(
            self, 
            control: uia.Control, 
            parent: "ChatBox",
            additonal_attr: Dict[str, Any]={}
        ):
        super().__init__(control, parent, additonal_attr)
        self.sender = 'system'
        self.sender_remark = 'system'

class FriendMessage(HumanMessage):
    attr = 'friend'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any]={}
        ):
        super().__init__(control, parent, additonal_attr)
        self._sender = None  # 延迟获取：首次访问sender属性时通过点击头像获取
        self._sender_remark = None

    @property
    def sender(self):
        """延迟获取发送者昵称，首次访问时通过点击头像获取并缓存

        群聊中每条消息可能来自不同发送者，因此每条消息独立获取。
        """
        if self._sender is None:
            self._sender = self._extract_sender()
        return self._sender

    @sender.setter
    def sender(self, value):
        self._sender = value

    @property
    def sender_remark(self):
        """延迟获取发送者备注名"""
        if self._sender_remark is None:
            self._sender_remark = self.sender
        return self._sender_remark

    @sender_remark.setter
    def sender_remark(self, value):
        self._sender_remark = value

    def _extract_sender(self) -> str:
        """从消息控件中提取发送者昵称

        查找策略：
        1. 在消息控件的子元素中查找发送者名称标签（旧版本兼容）
        2. 在消息控件的前一个兄弟控件中查找（旧版本兼容）
        3. 通过点击头像打开资料卡获取昵称（WeChat 4.1.9+）
        """
        try:
            # 策略1：在消息控件的子元素中查找发送者名称
            children = self.control.GetChildren()
            for child in children:
                cn = child.ClassName or ''
                if 'Sender' in cn or 'NameLabel' in cn:
                    if child.Name:
                        return child.Name
                if child.ControlTypeName == 'TextControl' and child.Name:
                    name = child.Name.strip()
                    if name and len(name) <= 20 and '\n' not in name:
                        return name

            # 策略2：在消息控件的前一个兄弟控件中查找
            parent_ctrl = self.control.GetParentControl()
            if parent_ctrl:
                siblings = parent_ctrl.GetChildren()
                for i, sib in enumerate(siblings):
                    if sib.runtimeid == self.control.runtimeid and i > 0:
                        prev = siblings[i - 1]
                        if prev.ClassName and 'Sender' in prev.ClassName:
                            return prev.Name
                        if prev.Name and prev.ClassName != 'mmui::ChatTextItemView' and prev.ClassName != 'mmui::ChatItemView':
                            return prev.Name

            # 策略3：通过点击头像获取昵称（WeChat 4.1.9+）
            # 每条消息首次访问sender时独立点击头像获取，结果缓存在_sender
            nickname = self._get_sender_from_avatar()
            if nickname:
                return nickname
        except Exception:
            pass
        return ''

    @staticmethod
    def _dismiss_profile_popups(pid) -> bool:
        """关闭指定进程的所有资料卡弹窗，等待弹窗完全消失后返回"""
        import time
        import win32gui
        from wxauto4.utils.win32 import get_windows_by_pid
        found = False
        for _ in range(5):  # 最多重试5次确保弹窗关闭
            has_popup = False
            for hwnd in get_windows_by_pid(pid):
                try:
                    c = uia.ControlFromHandle(hwnd)
                    if c.ClassName == 'mmui::ProfileUniquePop':
                        has_popup = True
                        found = True
                        native_hwnd = c.GetTopLevelControl().NativeWindowHandle
                        win32gui.PostMessage(native_hwnd, 0x0010, 0, 0)  # WM_CLOSE
                except:
                    pass
            if not has_popup:
                break
            time.sleep(0.3)
        return found

    @staticmethod
    def _read_profile_popup(pid, timeout=3) -> str:
        """等待并读取资料卡弹窗中的昵称，读完后关闭弹窗"""
        import time
        import win32gui
        from wxauto4.utils.win32 import get_windows_by_pid
        nickname = ''
        t0 = time.time()
        while time.time() - t0 < timeout:
            for hwnd in get_windows_by_pid(pid):
                try:
                    c = uia.ControlFromHandle(hwnd)
                    if c.ClassName == 'mmui::ProfileUniquePop':
                        name_ctrl = c.TextControl(
                            AutomationId='right_v_view.nickname_button_view.display_name_text'
                        )
                        if name_ctrl.Exists(1) and name_ctrl.Name:
                            nickname = name_ctrl.Name
                        # 关闭弹窗
                        import win32gui
                        native_hwnd = c.GetTopLevelControl().NativeWindowHandle
                        win32gui.PostMessage(native_hwnd, 0x0010, 0, 0)  # WM_CLOSE
                        time.sleep(0.3)
                        return nickname
                except:
                    pass
            time.sleep(0.2)
        return nickname

    @uilock
    def _get_sender_from_avatar(self) -> str:
        """通过点击消息头像获取发送者昵称

        流程：先关闭残留弹窗 → 滚动到消息可见 → 点击头像 → 读取弹窗昵称 → 关闭弹窗

        注意：监听模式下消息来自子窗口(WeChatSubWnd)，必须操作子窗口
        而非主窗口，否则 _show() 会把主窗口拉到前台遮挡子窗口。
        """
        import time
        import win32api
        import win32con
        from wxauto4.utils.win32 import get_windows_by_pid
        try:
            root = self.root
            main_wnd = getattr(root, 'parent', None) or root

            # 0. 关闭可能残留的资料卡弹窗
            self._dismiss_profile_popups(main_wnd.pid)

            # 1. 激活消息所在窗口
            root._show()

            # 2. 将消息滚动到可见区域
            if not self.roll_into_view():
                return ''

            # 3. 获取视口和消息的位置信息
            msgbox_rect = self.parent.msgbox.BoundingRectangle
            ctrl_rect = self.control.BoundingRectangle

            # 头像在消息左上角 (offset 25, 10)
            avatar_x = ctrl_rect.left + 25
            avatar_y = ctrl_rect.top + 10

            if avatar_y < msgbox_rect.top:
                # 头像在视口上方，需要向上滚动
                visible_y = max(ctrl_rect.top, msgbox_rect.top)
                center_x = (ctrl_rect.left + ctrl_rect.right) // 2
                center_y = (visible_y + min(ctrl_rect.bottom, msgbox_rect.bottom)) // 2
                win32api.SetCursorPos((center_x, center_y))
                time.sleep(0.1)

                for _ in range(100):
                    win32api.mouse_event(
                        win32con.MOUSEEVENTF_WHEEL, 0, 0, 120, 0
                    )
                    time.sleep(0.1)
                    ctrl_rect = self.control.BoundingRectangle
                    avatar_y = ctrl_rect.top + 10
                    if avatar_y >= msgbox_rect.top:
                        break

            # 安全检查：头像必须在 msgbox 可见范围内
            if not (msgbox_rect.top <= avatar_y <= msgbox_rect.bottom
                    and msgbox_rect.left <= avatar_x <= msgbox_rect.right):
                return ''

            # 4. 再次确认没有残留弹窗（滚动期间可能触发弹窗）
            self._dismiss_profile_popups(main_wnd.pid)

            # 5. 点击头像
            win32api.SetCursorPos((avatar_x, avatar_y))
            time.sleep(0.05)
            win32api.mouse_event(
                win32con.MOUSEEVENTF_LEFTDOWN, avatar_x, avatar_y, 0, 0
            )
            time.sleep(0.05)
            win32api.mouse_event(
                win32con.MOUSEEVENTF_LEFTUP, avatar_x, avatar_y, 0, 0
            )

            # 6. 等待并读取弹窗中的昵称（内部会关闭弹窗）
            nickname = self._read_profile_popup(main_wnd.pid, timeout=3)

            # 7. 确保弹窗已完全关闭（等待弹窗窗口消失）
            self._dismiss_profile_popups(main_wnd.pid)

            # 8. 恢复消息所在窗口
            root._show()
            return nickname
        except Exception:
            return ''

    def _click(self, x, y, right=False):
        self.roll_into_view()
        if right:
            self.control.RightClick(x=x, y=y, ratioX=0, ratioY=0)
        else:
            self.control.Click(ratioX=0, ratioY=0)

    @property
    def _bias(self):
        return WxParam.DEFAULT_MESSAGE_XBIAS


class SelfMessage(HumanMessage):
    attr = 'self'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any]={}
        ):
        super().__init__(control, parent, additonal_attr)
        self.sender = self._get_self_name()
        self.sender_remark = self.sender

    def _get_self_name(self) -> str:
        """获取自己的昵称，优先自动检测"""
        # 从root向上查找_self_nickname
        root = self.root
        if hasattr(root, '_self_nickname') and root._self_nickname:
            return root._self_nickname
        # 子窗口(WeChatSubWnd)的parent是WeChatMainWnd
        parent_wnd = getattr(root, 'parent', None)
        if parent_wnd and hasattr(parent_wnd, '_self_nickname') and parent_wnd._self_nickname:
            return parent_wnd._self_nickname
        # 尝试自动检测（仅WeChatMainWnd支持此方法）
        main_wnd = parent_wnd if parent_wnd and hasattr(parent_wnd, '_detect_self_nickname') else root
        if hasattr(main_wnd, '_detect_self_nickname'):
            nickname = main_wnd._detect_self_nickname()
            if nickname:
                return nickname
        return '我'

    def _click(self, x, y, right=False):
        self.roll_into_view()
        if right:
            self.control.RightClick(x=x, y=y, ratioX=1, ratioY=0)
        else:
            self.control.Click(x=x, y=y, ratioX=1, ratioY=0)

    @property
    def _bias(self):
        return -WxParam.DEFAULT_MESSAGE_XBIAS