# R03-B1 方程可追溯性

| Python 组件 | AMESim 对象 | active mode | 已实现 | 证据 | 未实现/限制 |
|---|---|---|---|---|---|
| `StaticValveDynamics` | VALVEDYNAMICS0 | spool dynamics=1, static/order 0 | 静态上下限、裁剪诊断、零连续状态 | `VALVEDYNAMICS0.spe/.c`、A2.5 定义表 | mode 2/3、全模型离散状态 owner |
| `SafeExpression` | FX00 | 当前保存表达式 | 四路开口及 spool 映射；AST 白名单解释器 | A2.5 冻结参数、SC_1 内部映射 | 非当前表达式所需的 AMESim 通用语言 |
| `HYDVORF0` | HYDVORF0 | method=1 | 参数、输入限幅/归一化接口、明确阻断 | `HYDVORF0.spe/.c`、`hydr_public.h` | 私有 `eqarea/orif3f_` 方程体缺失，流量未实现 |
| `HJ020Cylinder` | HJ020 | 双腔单杆缸、fluid index 0 | 面积、容积、压力力、泄漏、合法行程守卫 | `HJ020.spe/.c`、A2.5 冻结参数 | 私有 `pcdyn2_/q0top_` 方程体缺失，压力 RHS 未实现；高保真 endstop 未实现 |
| `ConstantFluidProperties` | FP04 | proptype=2 | 保存并 SI 化密度、体积模量、黏度、气含量、饱和压力 | `FP04.spe/.c`、模型参数 | `fpconbmu_/pcdyn2_/q0top_` 的混合物性算法未重构 |

## 参数来源

配置由 `scripts/hydraulics/generate_r03b1_config.py` 从 `r03a25_resolved_key_parameters.csv` 与 `hydraulic_parameters.csv` 生成。核心类中没有客户模型尺寸、流量或压力特征点魔法数字。

## HJ020 active branch 摘要

官方源码确认 `A_p=pi*d_p²/4`、`A_a=A_p-pi*d_r²/4`，`V1=A_p*xact+dead1`、`V2=A_a*(stroke-xact)+dead2`，`q_leak=(p1-p2)*leak`，合法行程内 `frod=p1*A_p-p2*A_a+v_port*c_visc`。本项目规定 `v=dxact/dt=-v_port`。压力导数必须调用 `pcdyn2_`，活塞扫掠流量含 `q0top_`，因此没有用常体积模量近似替代。

## 明确不在本轮实现

VALVEDYNAMICS0 mode 2/3、其他 SC_1 实例差异、57 个离散状态完整 owner、高保真 endstop、泵站、蓄能器、溢流阀网络、完整管路动态、六轴机械耦合。

