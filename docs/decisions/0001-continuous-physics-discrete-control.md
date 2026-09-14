# ADR-0001: 连续物理、离散控制、独立求解器

- 状态：Accepted
- 日期：2026-09-14

机械与液压模型提供无副作用连续 RHS；耦合层组装全系统；solver 负责推进；控制器只按采样周期消费 measurement/reference 并输出 command。这样可替换 RK、BDF、Radau，并为 DAE 扩展保留空间。

