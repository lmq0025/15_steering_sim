# 电液转向质量性能预测软件离线部署计划

## 1. 当前验证基线

- Python 3.11.16，64 位；
- PySide6 6.10.0、PyQtGraph 0.13.7；
- NumPy 2.4.6、SciPy 1.17.1、pandas 3.0.5；
- Matplotlib 3.11.2、openpyxl 3.1.5；
- 当前验证系统：Windows 10/11 兼容内核，AMD64；
- 正式模型：`ENGINEERING_STEERING_MODEL`、`ENGINEERING_HYDRAULIC_V1`。

软件运行不需要网络、云服务或 Amesim。计算内核使用 Python、NumPy 和项目内
配置文件；Windows 专用内容限制在 BAT、PowerShell 打包脚本和启动环境初始化层。

## 2. 必须先获取的目标设备信息

交付前使用 `TARGET_DEVICE_INFORMATION.xlsx` 收集操作系统、CPU 架构、内存、
磁盘、管理员权限、图形桌面、U盘策略和软件安装限制。信息未确认前，不承诺
某一平台的可执行包能够直接运行。

跨平台源码兼容不等于打包产物跨平台。Windows x64 产物不能复制到 Linux 或
ARM64 运行；每个操作系统和 CPU 架构必须在同类构建机上单独构建和验证。

## 3. Windows x64

### 3.1 当前推荐方式

1. 在联网准备机建立与目标机同架构的 Python 3.11 环境；
2. 下载固定版本 Conda 包或 wheelhouse，并保存 SHA-256 清单；
3. 在离线目标机解压/安装环境，不修改系统 Python；
4. 将项目复制到本地可写目录；
5. 运行 `scripts\d4\check_desktop_environment.py`；
6. 双击 `start_steering_desktop.bat`；
7. 检查 `outputs\desktop\logs` 的启动日志并执行验收任务谱。

BAT 为 ASCII + CRLF，显式初始化 Conda DLL 搜索目录。Python 启动器在导入 Qt
之前建立日志，并捕获未处理异常和退出码。

### 3.2 PyInstaller 目录版

使用 `scripts/d4/build_pyinstaller.ps1` 在干净 Windows x64 构建机生成目录版。
应优先目录版而不是单文件版，便于检查 Qt 插件和科学计算 DLL。需要验证：

- `platforms/qwindows.dll`；
- `imageformats` 中实际需要的 PNG/JPEG 插件；
- NumPy/SciPy 的 BLAS、OpenMP 和运行库 DLL；
- 字体回退及中文文件名；
- 无 Python、无管理员权限账户下的启动与计算。

构建脚本存在不代表独立版已经在甲方设备验证。

## 4. Linux x86-64

建议使用目标发行版或兼容的最低 glibc 构建机创建独立 wheelhouse/Conda 环境，
并提供 `.sh` 启动器。Qt 需要 X11 或 Wayland 图形会话，至少检查 xcb、XKB、
OpenGL/EGL、fontconfig 和常用字体。无图形桌面的服务器不能直接运行本软件；
可保留计算脚本，但不属于桌面 GUI 验收。

PyInstaller 必须在 Linux x86-64 上重新构建。不可使用 Windows 产物交叉复制。

## 5. 国产 Linux 与 ARM64

- 先确认发行版、glibc、内核、桌面环境和 aarch64/loongarch64 等准确架构；
- PySide6 官方 wheel、NumPy/SciPy BLAS 和 PyInstaller 对不同架构的覆盖不同；
- ARM64 应在真实 ARM64 或受控原生构建环境中构建，不以 x86 模拟运行作为验收；
- 龙芯等非 aarch64 架构可能需要发行版包或源码构建 Qt/Python 科学栈；
- 必须重新执行数值回归，检查浮点库、线程库和图形驱动差异；
- 若目标机禁止安装运行库，采用同平台目录版并由甲方安全策略审批。

## 6. 离线介质准备原则

每个平台分别准备：源码/目录版、配置、示例任务谱、固定依赖清单、离线包、
哈希清单、启动诊断、用户手册和验收结果。wheelhouse 只能包含目标 Python ABI、
操作系统和 CPU 架构匹配的包。不得在目标机临时联网下载依赖。

U盘导入前确认介质白名单、病毒扫描、文件大小限制、执行权限和哈希核验流程。
日志和结果目录必须对普通用户可写；项目目录不可写时启动器自动回退到用户
本地数据目录或临时目录记录启动日志。

## 7. 离线验收清单

1. 核对操作系统、架构、内存、磁盘和图形桌面；
2. 校验交付包 SHA-256；
3. 断网状态启动两次，正常关闭不报错；
4. 切换五个页面并检查中文字体、缩放和 Qt 插件；
5. 导入中文路径 CSV/XLSX；
6. 执行健康联合仿真和 6 s/° 斜坡；
7. 核对十二轮和四通道到位/稳态表；
8. 执行 D1、D2、D3 代表计算；
9. 导出 CSV、XLSX、PNG 和中文报告；
10. 检查日志、配置哈希、输入哈希和计算耗时；
11. 以普通用户重复启动；
12. 记录未通过项，不以跨平台源码兼容替代目标机验收。

## 8. 当前限制

当前仅完成 Windows AMD64 源码环境的实际验证。Linux、国产 Linux、ARM64 和
无管理员权限的甲方实机尚未获得，因此这些平台仍处于部署准备状态。
