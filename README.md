<div align="center">
  <img src="docs/icon.png" width="96" height="96" alt="PathNote Icon" />
  <h1>PathNote · 路径备注</h1>
  <p><b>不改真实纯英文路径，在 Windows 资源管理器与“打开 / 另存为”窗口的文件名末尾直接显示中文备注</b></p>
  <p>
    <a href="https://github.com/huilygyc/PathNote/releases/latest"><img src="https://img.shields.io/badge/下载安装包-PathNote__Setup__v1.1.0.exe-2563EB?style=for-the-badge" alt="Download Setup" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-10B981?style=for-the-badge" alt="MIT License" /></a>
  </p>
</div>

---

## 解决什么痛点？

很多专业开发与工程工具（如深度学习训练脚本、EDA/CAD 图纸、Keil/Vivado 固件、Unity/Blender 资产等）**强制要求纯英文路径**，但时间一长很容易忘记 `exp_04`、`coad`、`best_ep120.pt` 这些英文文件夹和文件到底是干什么的。

**PathNote（路径备注）** 保持磁盘上的真实路径与文件名 **100% 原生纯英文不变**（不向你的工程目录写入任何隐藏垃圾文件），同时直接在 **Windows 10/11 资源管理器** 和任意软件弹出的 **“打开 / 另存为”文件对话框** 中，于每个文件或文件夹名字后面原位显示括号备注：

```text
📁 AsusMCenterAppstore  (华硕控制中心商店)         2025/7/10 9:55     文件夹
📁 coad                 (代码工程 · 日常练习)      2024/11/18 22:10   文件夹
📄 best_ep120.pt        (YOLOv8 螺丝检测权重)      2026/11/24 21:00   PT 文件
```

---

## 界面预览

### 备注库与分类管理中心
![PathNote 主界面](docs/preview_main.png)

### 快速添加备注与资源管理器实时预览
![添加备注弹窗](docs/preview_edit.png)

---

## 普通用户下载即用（无需安装 Python）

前往 [**Releases 页面**](https://github.com/huilygyc/PathNote/releases/latest) 选择任一版本：

1. **一键安装版（推荐）**：下载 **`PathNote_Setup_v1.1.0.exe`**，双击即可完成安装并自动创建桌面快捷方式与开机自启（无需管理员权限）。
2. **绿色免安装版**：下载 **`PathNote_Portable_v1.1.0_x64.zip`**，解压到任意目录双击 `PathNote.exe` 即可使用。

---

## 核心特性

- **原位行尾括号直接显示 `(备注 · 用途)`**：毫秒级坐标追踪，支持 Windows 10/11 多标签页资源管理器及各软件 `#32770`“打开/另存为”对话框，**100% 鼠标点击穿透**，不影响双击、框选与拖拽。
- **文件改名 / 移动后备注自动跟随**：底层记录 NTFS 64 位 `FileId` 与卷序列号，通过 `OpenFileById` 自动追踪重命名或跨目录移动后的新路径（自动排除回收站），父目录移动时内部子文件备注自动级联更新。
- **窗口拖动零残影 + 待机 `0%` CPU 占用**：接入系统 `SetWinEventHook` 事件钩子，拖动窗口时 120Hz+ 刚体同步平移画布；窗口静止不操作时后台自动深度休眠。
- **Z 轴右键菜单智能裁剪**：弹出系统右键菜单或置顶小窗口时，实时从绘制区域挖除被遮挡矩形，绝不穿透覆盖菜单文字。
- **指哪设哪 & 自定义分类管理**：鼠标指向任意英文文件按 `Alt + S` 即可添加备注，起备注时可选择或新建分类（不选默认归入「默认分类」），支持右键菜单集成与 JSON 备份导入导出。

---

## 默认全局快捷键（可在偏好设置中自定义）

| 快捷键 | 功能说明 |
| :--- | :--- |
| **`Alt + A`** | **开启 / 关闭**文件名末尾的 `(备注 · 用途)` 显示 |
| **`Alt + S`** | 为**鼠标当前指向**或选中的英文文件/文件夹直接添加或修改备注 |
| **`Alt + Q`** | 唤起**全局中文备注快速搜索**（`Enter` 直接驱动保存窗口/资源管理器跳转目录，`Ctrl+C` 复制英文路径） |

---

## 开发者源码运行与打包

```powershell
git clone https://github.com/huilygyc/PathNote.git
cd PathNote
pip install -r requirements.txt
python main.py

# 一键重新生成瘦身版 PathNote_Setup_v1.1.0.exe 安装包与便携 ZIP
pip install pyinstaller pillow
.\build_release.bat
```

---

## 开源协议

基于 [MIT License](LICENSE) 开源。
