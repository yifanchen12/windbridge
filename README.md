# WindBridge 风桥

面向同一局域网设备的本地文件与文本传输工具。电脑端启动后，手机、平板或另一台电脑扫描二维码即可访问，无需账号或云端中转。

<p align="center">
  <img src="assets/venti_sticker.png" width="180" alt="WindBridge 温迪主题贴图">
</p>

## 首版功能

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
