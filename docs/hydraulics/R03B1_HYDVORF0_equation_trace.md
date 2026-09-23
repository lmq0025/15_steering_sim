# R03-B1 HYDVORF0 方程追溯

## 当前实例与 active mode

代表实例为 `dirvalve_6/orifice_13,14,23,24`。四个实例均为 HYDVORF0，`pressure drop definition method=1`，即特征流量/特征压降法；每条流路保存 `1 L/min @ 1 bar`、临界流数 1000、测量密度 850 kg/m³、测量运动黏度 60 cSt、输入区间 `[0,100]`。

## 官方源码能够确认的算法外壳

`HYDVORF0.c` 先调用 `eqarea(...)`，由特征点计算等效面积、液压直径及实际临界流数。计算阶段对输入做 `dlimit_`，归一化开度；method=1 下面积与液压直径分别按归一化开度及其平方根缩放，再调用 `orif3f_(p3,p2,area,hdiam,Cqmax,lambda_c,...)`。`q2` 的正方向与 `p3 -> p2` 一致；零面积应为零流量，反向压差允许反向流量。

## 不能闭合的部分

安装目录仅在 `lib/hydr_public.h` 提供 `eqarea`、`orif3f_` 函数声明；算法体属于安装的私有求解库，未在 `.c/.spe` 或帮助元数据中提供。因而以下细节没有足够证据：

- 等效面积/直径求解在特征点落于过渡区时的精确迭代；
- `orif3f_` 的层流—湍流连续过渡函数；
- 压力相关密度与体积流换算的精确调用顺序。

## R03-B1 结论

代码保留完整 method=1 配置、开度归一化和接口，但 `HYDVORF0.flow()` 显式抛出 `UnresolvedAmesimUtilityError`。未使用 `Cd*A*sqrt(2*dp/rho)` 等教科书公式替代。当前子项为 **BLOCKED**；需要 Siemens 对 `orifices.c/orifices_common.c` 的可引用算法说明，或由 AMESim 导出足够密集且覆盖正反向/过渡区的单元特性数据后，才能实现可追溯替代。

