# WindBridge 风桥

[English](README.en.md) · [安全策略](SECURITY.md)

面向 Windows 的局域网文件与文本传输工具，采用 Python/Tkinter 桌面端和 Flask 网页服务。其他设备通过浏览器访问，无需账号或云端中转。当前版本：**0.2.0**。

<p align="center">
  <img src="assets/venti_sticker.png" width="160" alt="温迪主题插图">
</p>

## 功能与边界

- 文件：电脑选择或拖放文件供浏览器下载；浏览器支持多文件上传及上传进度显示。
- 文本：双向发送文本和链接；可选将收到的网页文本复制到系统剪贴板，默认关闭。不持续监控系统剪贴板。
- 访问：二维码包含本次运行的共享配对码，可手动轮换；不区分设备身份或权限。
- 系统集成：系统托盘及可选的 Windows“发送到”菜单入口，可在“连接设置”中安装或移除。
- 设备发现：实现 UDP 查询响应及查询函数，尚未接入设备列表界面。
- 上传限制：单个 HTTP 请求体上限为 **2 GiB（2,147,483,648 字节）**，包含全部文件和表单开销；文本最多保留前 200,000 个字符。

上传会清理文件名，并在检测到同名文件时追加编号；并发同名上传尚无原子冲突保护。当前未实现文件夹传输、断点续传或传输内容扫描。

## 安装与使用

已验证环境：Windows 11、Python 3.14.7。接收设备需与电脑网络互通，并具备可运行 JavaScript 的浏览器；桌面端需保持运行。

```powershell
git clone https://github.com/yifanchen12/windbridge.git
cd windbridge
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

1. 扫描首页二维码，或在另一台设备上打开显示的地址。
2. 通过“文件桥”共享文件，或在浏览器中上传文件；通过“文本桥”发送文本。
3. 浏览器读取电脑端的新文本时，点击“读取电脑文本”。
4. 托盘可用时，默认关闭窗口会驻留托盘；从托盘菜单选择“退出”可结束服务。

首次出现 Windows 防火墙提示时，仅允许可信的“专用网络”。连接失败时，检查地址、端口、防火墙及路由器的设备隔离设置。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-test
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建前退出正在运行的 WindBridge。产物为 `dist\WindBridge.exe`；环境检查不替代跨设备传输验证。

## 网络与数据

| 项目 | 默认值或位置 |
| --- | --- |
| HTTP 服务 | TCP 8765，可配置；监听全部 IPv4 网卡 |
| 设备发现 | UDP 38765；响应包含设备名、IP 和服务端口，不含配对码 |
| 设置 | `%LOCALAPPDATA%\WindBridge\settings.json` |
| 接收目录 | `%USERPROFILE%\Downloads\WindBridge\`，可配置 |
| 可选“发送到”入口 | `%APPDATA%\Microsoft\Windows\SendTo\发送到 WindBridge.cmd` |

桌面端共享列表、文本和活动记录仅保存在进程内存中；设置与接收文件保存在磁盘。浏览器会保存会话配对码，地址也可能留在浏览历史或请求日志中。应用未集成遥测或云端中转服务。

## 安全

- 仅用于可信局域网，不应通过端口映射或反向代理暴露到公网。
- 当前使用明文 HTTP，无 TLS 或端到端加密。配对码属于访问凭据，不提供传输加密；敏感文件应先单独加密。
- 持有配对码的设备可下载全部已共享文件、上传文件及读写桥接文本。轮换配对码仅阻止后续使用旧码的请求，不中断已接受的传输。
- 本机文件转交接口与网页共用监听端口，通过回环来源检查及独立控制凭据限制访问，并非单独绑定回环地址。
- 不公开配置文件、完整配对地址、二维码或敏感日志；接收文件应作为不可信输入检查后再打开。

安全问题请通过 [GitHub 私密漏洞报告](https://github.com/yifanchen12/windbridge/security/advisories/new) 提交，详见 [安全策略](SECURITY.md)。

## 授权与主题资源

仓库目前未附带开源许可证；公开可见不表示授予开源许可，使用或分发前请向维护者确认授权范围。温迪主题贴图为生成式同人插图，非官方素材；项目与米哈游／HoYoverse 无隶属或背书关系，相关角色权利归各自权利人所有。
