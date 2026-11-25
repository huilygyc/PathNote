# 影名 FileAlias — Windows 英文路径文件原位括号别名助手

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D4)](https://github.com/huilygyc/FileAlias)
[![Release](https://img.shields.io/badge/Release-v1.0.0-2563EB)](https://github.com/huilygyc/FileAlias/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-10B981.svg)](LICENSE)

专为**必须保存在纯英文路径下**（如深度学习训练工程、EDA/CAD 图纸、Keil/Vivado 嵌入式固件、游戏/建模资产、代码仓库等），但时间一长容易忘记英文文件夹或文件具体用途的场景打造。

**核心效果**：保持磁盘真实路径与文件名 **100% 原生纯英文不变**（不在你的工程目录里写入任何垃圾文件），同时直接在 **Windows 资源管理器** 和任意软件的 **“打开 / 另存为”文件对话框** 中，于每个文件或文件夹名字末尾原位显示括号备注：

```text
📁 AsusMCenterAppstore  (华硕控制中心商店)         2025/7/10 9:55     文件夹
📁 coad                 (代码工程 · 日常练习)      2024/11/18 22:10   文件夹
📄 best_ep120.pt        (YOLOv8 螺丝检测权重)      2026/11/24 21:00   PT 文件
```

---

## 界面预览

### 别名库与分类管理主界面
![管理主界面](docs/preview_main.png)

### 快速设置别名与实时预览弹窗
![设置别名弹窗](docs/preview_edit.png)

---

## 普通用户免安装直接使用（推荐，无需安装 Python）

1. 前往 [**GitHub Releases 下载页面**](https://github.com/huilygyc/FileAlias/releases/latest) 下载最新的 **`FileAlias_v1.0.0_Windows_x64.zip`**。
2. 解压到电脑任意固定目录（绿色免安装，数据默认保存在程序同级 `data` 文件夹中）。
3. 双击运行 **`FileAlias.exe`**：
   - **加备注**：在资源管理器或“另存为”窗口中，**鼠标指向**（或选中）任意英文文件夹/文件，直接按 **`Alt + S`**，输入用途回车即可立即在它后面显示括号备注！
   - **一键开关**：随时按 **`Alt + A`** 开启或关闭所有行尾括号显示。
   - **开机自启 & 右键菜单**：可在软件「偏好设置」中一键开启**开机自动后台启动**与**系统资源管理器右键菜单**（均无需管理员权限）。

---

## 核心特性亮点

- **文件改名 / 移动后别名自动跟随（v1.1 新增）**：底层记录 NTFS 64 位 `FileId` 与卷序列号，通过 `OpenFileById` 毫秒级反查最新路径（自动排除回收站）——同盘内无论如何重命名文件夹或拖动文件位置，括号里的别名都会自动跟着走，子目录与内部文件自动级联同步。
- **窗口拖动零残影 + 静止 `0%` CPU 占用（v1.1 新增）**：接入系统级 `SetWinEventHook` 事件钩子，拖动资源管理器窗口时按位移增量在主线程 120Hz+ 刚体平移画布；无滚动或交互时后台自动进入深度休眠，待机占用 `0.00%`。
- **原位行尾括号直接显示 `(别名或用途)`**：基于 `IUIAutomation` 2ms 级批量坐标缓存追踪，支持 Windows 10 / 11 多标签资源管理器及任意软件的 `#32770`“打开/另存为”窗口。
- **100% 鼠标点击穿透 & Z 轴右键菜单智能避让**：双击打开、框选、拖拽、滚轮上下滚动丝滑跟随；弹出右键菜单或置顶窗口遮挡时，利用 `QRegion` 实时几何挖除遮挡区，绝不穿透菜单文字。
- **高分屏与深浅色自适应**：完美适配 100% / 125% / 150% / 200% DPI 缩放、浅色/深色资源管理器及整行选中蓝色高亮背景；支持 5 种柔和括号文字色调切换。
- **多维分类与标签管理**：起别名时可自由选择或新建分类（不选自动归入「默认分类」），支持侧边栏分类筛选、重命名、文件夹移动后一键级联修复子路径及 JSON 备份导入导出。
- **全局中文搜索直跳保存窗口（`Alt + Q`）**：搜索中文别名按 `Enter`，若当前正打开着软件的“另存为/打开”窗口，可直接驱动保存窗口跳转到对应英文目录！

---

## 默认全局快捷键（均可在偏好设置中自定义）

| 快捷键 | 功能说明 |
| :--- | :--- |
| **`Alt + A`** | **开启 / 关闭**文件名末尾的 `(别名或用途)` 显示 |
| **`Alt + S`** | 为**鼠标当前指向**或选中的英文文件/文件夹直接添加或修改括号别名 |
| **`Alt + Q`** | 唤起**全局中文别名快速搜索**（`Enter` 跳转目录/定位，`Ctrl+C` 复制纯英文路径） |

---

## 开发者从源码运行与自行打包

### 1. 环境准备（Windows 10/11 + Python 3.10+）
```powershell
git clone https://github.com/huilygyc/FileAlias.git
cd FileAlias
pip install -r requirements.txt
```

### 2. 源码直接运行
```powershell
python main.py
# 或双击 run.bat 后台无黑框运行
```

### 3. 一键打包生成免安装 `.exe` 与 `.zip` 发行包
```powershell
pip install pyinstaller pillow
.\build_release.bat
```
打包完成后将在 `release\FileAlias_v1.0.0_Windows_x64.zip` 生成可直接分发给任何 Windows 用户使用的绿色免安装包。

---

## 开源协议

本项目基于 [MIT License](LICENSE) 开源，欢迎自由使用、分享与提交 PR。
