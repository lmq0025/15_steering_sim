# R03-A2.5 VALVEDYNAMICS0 专项说明

## 结论

Simcenter AMESim 2021.1 的官方 `VALVEDYNAMICS0.spe` 将 `spool dynamics` 定义为三个枚举：`1 = no (static)`、`2 = 1st order`、`3 = 2nd order`。当前 10 个 SC_1 实例均保存为 `1`，因此当前激活的是静态（零阶）模式，不是一阶或二阶模式。

在值 1 下，`valve time constant`、`valve natural frequency` 和 `valve damping ratio` 均不参与激活模式。`.spe` 只在 `spooldyn == 2` 时显示 time constant，只在 `spooldyn == 3` 时显示 natural frequency 与 damping ratio；`.c` 的参数检查分支与此一致。

## 状态解释

官方 `.c` 使用 `cxv_size = spooldyn > 1`、`cxvder_size = spooldyn > 2`。因此值 1 不分配 fractional spool position 或 fractional spool velocity 连续状态，和模型 `.state` 中没有 VALVEDYNAMICS0 连续状态完全一致。它还声明两个整数存储 `DISC_LIMIT`、`DISC_ENDSTOPS`，用于限制/端止点相关记忆或事件处理；这解释了为什么静态模式仍可能涉及内部离散存储，但不能据此给 57 个全模型离散状态逐项命名。

## R03-B 边界

当前证据足以支持 R03-B 将本模型的 SC_1 阀芯响应按静态模式实现，并保留限幅/端止点事件的验证接口。若未来把 `spool dynamics` 改为 2 或 3，必须分别启用一阶 time-constant 或二阶 natural-frequency/damping 参数，并重新冻结状态与验证通道。

## 证据

- `E:\Simcenter\2021.1\Amesim\submodels\VALVEDYNAMICS0.spe`：第 17–46、74–109、116–139 行。
- `E:\Simcenter\2021.1\Amesim\submodels\VALVEDYNAMICS0.c`：第 40–43、75–83、98–131、167–170、192–217 行。
- A2 参数表：10 个 `VALVEDYNAMICS0` 实例的 `spool dynamics = 1`。

本说明只记录模式定义和参数激活关系，不实现任何液压方程。
