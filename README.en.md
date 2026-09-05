# WindBridge

[简体中文](README.md) · [Security policy](SECURITY.md)

A Windows application for transferring files and text over a local network, built with Python/Tkinter and Flask. Other devices connect through a browser; no account or cloud relay is required. Current version: **0.3.0**.

<p align="center">
  <img src="assets/venti_sticker.png" width="160" alt="Venti-themed illustration">
</p>

## Features and limitations

- **Files:** select or drop desktop files for browser download; upload through a browser queue with pause/resume, bounded retries, and acknowledged progress.
- **Text:** send text and links in either direction. Optionally copy received browser text to the system clipboard; disabled by default. No continuous clipboard monitoring.
- **Access:** a QR code contains a shared, per-run pairing token that can be rotated manually. There are no per-device identities or permissions.
- **Integration:** system tray and optional Windows Send To entry, installable and removable from Connection Settings.
- **Discovery:** UDP query responses and a query function are implemented; no device-list interface is available yet.
- **Limits:** **4 MiB** chunks, **2 GiB (2,147,483,648 bytes)** per file, and 128 retained upload records. The legacy multipart endpoint retains its 2 GiB request-body limit. Text is truncated to 200,000 characters.

Uploads sanitize filenames and append a number for collisions. Completed chunked uploads are published without overwriting existing files. Folder transfer and content scanning are not implemented.

## Install and use

Verified environment: Windows 11 and Python 3.14.7. The receiving device needs network connectivity to the desktop and a JavaScript-enabled browser. Keep the desktop application running.

```powershell
git clone https://github.com/yifanchen12/windbridge.git
cd windbridge
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

1. Scan the home-page QR code or open the displayed address on another device.
2. Share files through **文件桥** (File Bridge), upload from the browser, or send text through **文本桥** (Text Bridge).
3. Click **读取电脑文本** (Read desktop text) in the browser to retrieve updated desktop text.
4. When the tray is available, closing the window keeps the application in the tray by default. Select **退出** (Exit) from the tray menu to stop the service.

If Windows Firewall prompts for access, allow trusted private networks only. For connection failures, check the address, port, firewall, and router client-isolation settings.

## Resumable transfers

- Pause, resume, or cancel browser uploads. Temporary failures trigger up to three automatic retries; acknowledged chunks are retained if retries fail.
- After refreshing or reopening the page, select the original file again. After restarting the desktop application, scan its new QR code first. Keep the filename, size, modification time, and content unchanged.
- Previously uploaded chunks are verified before resuming; completion verifies SHA-256. Progress counts only bytes acknowledged by the desktop.
- `.windbridge-partials/` in the receiving directory stores partial data and upload records. Creating or listing tasks removes records unchanged for over seven days. Cancellation removes temporary data, not completed files.
- Changing the receiving directory leaves previous tasks in their original location; switch back to resume them. Use only one WindBridge process per receiving directory.
- Desktop downloads support HTTP Range / If-Range. Pause/resume depends on the browser or download manager; the original file and share link must remain valid. Share files again after restarting.

## Test and build

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-test
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Exit any running WindBridge instance before building. Output: `dist\WindBridge.exe`. The environment check does not replace cross-device transfer testing. Use `-OutputDirectory dist\v0.3.0` to build into a separate directory.

Optional frontend tests: with Node.js, run `node tests/test_hash.cjs`; with Playwright and Chrome configured, run `node tests/test_browser.cjs`. The browser test uses only temporary files and a loopback service.

Source execution and builds require a complete Tcl/Tk installation. If `init.tcl` is missing, repair the Python environment or set valid `TCL_LIBRARY` / `TK_LIBRARY` paths. Packaged executables include the required runtime libraries.

## Network and data

| Item | Default or location |
| --- | --- |
| HTTP service | TCP 8765, configurable; binds to all IPv4 interfaces |
| Discovery | UDP 38765; replies include device name, IP, and service port, but no pairing token |
| Settings | `%LOCALAPPDATA%\WindBridge\settings.json` |
| Upload destination | `%USERPROFILE%\Downloads\WindBridge\`, configurable |
| Optional Send To entry | `%APPDATA%\Microsoft\Windows\SendTo\发送到 WindBridge.cmd` |

Desktop sharing lists, text, and activity records remain in process memory; settings, received files, partial chunks, and upload records are stored on disk. The browser stores the session pairing token, and URLs may remain in browser history or request logs. The application has no integrated telemetry or cloud relay.

## Security

- Use only on trusted local networks. Do not expose the service through port forwarding or a reverse proxy.
- Traffic uses plaintext HTTP, without TLS or end-to-end encryption. Pairing tokens control access, not encryption; encrypt sensitive files separately before transfer.
- Any device holding the token can download all shared files, upload files, inspect or cancel any upload task, and read or replace bridged text. Rotation rejects subsequent requests using the old token; it does not terminate transfers already accepted.
- Local file handoff shares the HTTP listener. Access is restricted by a loopback-source check and a separate control credential, not by a loopback-only socket.
- Do not publish settings, complete pairing URLs, QR codes, or sensitive logs. Inspect received files as untrusted input before opening them.

Report vulnerabilities through [GitHub private reporting](https://github.com/yifanchen12/windbridge/security/advisories/new). See the [security policy](SECURITY.md) for details.

## License and theme assets

The repository currently has no open-source license. Public visibility is not an open-source license grant; confirm permitted use and redistribution with the maintainer. The Venti-themed sticker is AI-generated fan art, not an official asset. This project is not affiliated with or endorsed by miHoYo or HoYoverse; character rights belong to their respective holders.
