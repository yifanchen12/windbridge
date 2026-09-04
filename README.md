# WindBridge 风桥

面向同一局域网设备的本地文件与文本传输工具。电脑端启动后，手机、平板或另一台电脑扫描二维码即可访问，无需账号或云端中转。

<p align="center">
  <img src="assets/venti_sticker.png" width="180" alt="WindBridge 温迪主题贴图">
</p>

## 功能范围

- 电脑选择文件，移动端网页直接下载
- 移动端选择或拖放文件，发送到电脑接收目录
- 电脑与网页双向传递文本、链接和地址
- 自动生成局域网访问地址和配对二维码
- 一键更换配对码，使旧链接立即失效
- 桌面文件拖放共享
- UDP 局域网节点发现（不广播配对码）
- 系统托盘驻留与快速打开移动端
- Windows 资源管理器“发送到 WindBridge”入口
- 文件名清理、重复文件自动改名、2 GB 单请求上限
- 蒙德风格视觉与新生成的温迪 Q 版透明贴图

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

电脑与移动设备需要连接到同一个局域网。首次启动时，如 Windows 防火墙询问是否允许访问，请仅勾选专用网络。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-test
```

## 打包

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

输出文件：`dist\WindBridge.exe`

## 说明

- 文件只通过当前局域网传输，不会上传到第三方服务器。
- 配对码用于阻止同一网络中的未配对设备直接调用接口，但它不替代可信局域网和操作系统防火墙。
- “发送到 WindBridge”入口可以在应用的“连接设置”页面安装或移除，不写入系统级目录，不需要管理员权限。

## 本地数据位置

```text
%LOCALAPPDATA%\WindBridge\settings.json
%USERPROFILE%\Downloads\WindBridge\
%APPDATA%\Microsoft\Windows\SendTo\发送到 WindBridge.cmd  （仅在用户主动安装后存在）
```

`settings.json` 包含监听端口、接收目录、托盘偏好和仅供本机进程通信的随机控制凭据。不要将该文件、带 `token=` 的配对 URL、二维码截图或包含个人路径的日志提交到公开仓库或 Issue。

## 安全与隐私声明

1. **信任边界**：WindBridge 面向家庭、宿舍或办公室的可信局域网，不适合公共 Wi-Fi、校园访客网或直接暴露到互联网。不要进行端口映射或把监听端口开放到公网。
2. **传输方式**：当前局域网网页使用 HTTP。文件不会经过云端，但同一网络中的流量不具备 TLS 加密保护；敏感文件应先自行加密，或只在可信网络中传输。
3. **配对凭据**：二维码及连接地址包含临时配对码。配对完成后可在桌面端点击“更换配对码”，旧地址会立即失效。UDP 设备发现不会广播配对码。
4. **文件安全**：从其他设备接收的文件均视为不可信输入。应用会清理文件名并避免覆盖同名文件，但不会扫描文件内容；打开前请使用本机安全软件检查。
5. **本地控制**：资源管理器发送功能通过仅监听回环地址的本机接口工作，并使用随机控制凭据验证请求。该凭据不会显示在 UI、日志或网络发现报文中。
6. **数据收集**：项目不包含遥测、广告 SDK、远程统计或云端中转服务。共享列表和文本桥内容仅保存在本次运行的内存中。
7. **防火墙**：首次运行时仅允许 Windows“专用网络”。如系统把当前网络标记为公用网络，请先确认网络可信再调整。
8. **公开报告**：提交 Issue 时请删除配对码、完整连接 URL、个人文件名、个人目录、IP 地址及其他身份信息。安全问题请使用私密漏洞报告。

完整的漏洞报告方式和运行安全要求见 [`SECURITY.md`](SECURITY.md)。

## 项目结构

```text
main.py                  应用入口、文件转交与环境检查
windbridge/gui.py        桌面界面、拖放、托盘和资源管理器集成
windbridge/server.py     局域网 HTTP 文件与文本接口
windbridge/discovery.py  不含配对码的 UDP 节点发现
windbridge/state.py      运行期共享文件、文本和活动状态
windbridge/settings.py   本地设置及控制凭据
web/index.html           响应式移动端页面
assets/                  应用图标和温迪主题透明贴图
tests/                   核心接口、安全边界和状态测试
```

## 版本与授权

- 当前版本：`0.2.0`
- 默认分支：`main`
- 项目为非官方同人主题工具，与米哈游／HoYoverse 无隶属或背书关系。
- 仓库未附带统一的开源许可证文件；除另行书面授权外，源代码与原创资源的使用应遵循仓库所有者的授权范围。相关角色名称及设定权利归各自权利人所有。
