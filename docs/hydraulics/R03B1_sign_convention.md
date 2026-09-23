# R03-B1 符号约定

## 阀

- 所有液压组件端口流量以“流入该组件”为正。
- 路径 `X-Y` 的路径流量以从 X 流向 Y 为正；反向压差产生负路径流量。
- SC_1 端口守恒采用 `q_P + q_T + q_A + q_B = 0`。这只是无内部容积阀的拓扑守恒，不预设实际流向。
- `ext0=P, ext1=T, ext2=B, ext3=A, ext4=signal`；`orifice_13=P-B`、`orifice_14=P-A`、`orifice_24=T-A`、`orifice_23=T-B`。

## HJ020

- `q1`、`q2` 以流入液压缸相应腔为正。
- 本 Python 边界的 `x` 是 HJ020 输出变量 `xact`：`x=0` 为 port1 端最小容积位置，`x=stroke` 为 port2 端最小容积位置。
- 本 Python 边界的 `v=dxact/dt`。HJ020.c 的机械端口速度 `v_port=-v`，转换只发生在边界层。
- `V1=A_p*x+dead1`，`V2=A_annular*(stroke-x)+dead2`。
- 液压杆力正方向沿 HJ020 的 `frod` 正方向；合法行程内且当前粘性系数为零时，`F=p1*A_p-p2*A_annular`。
- 本轮不实现端止点外运动；越界显式报错，不静默截断。

## 功率

- 端口液压功率按 `p*q_into_component` 计。
- 本轮只能计算几何和压力力的静态诊断。`pcdyn2_`/`q0top_` 未闭合前，不能给出与 AMESim 等价的储能功率，故不报告伪造的功率残差。

