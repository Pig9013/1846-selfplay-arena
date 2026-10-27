**中文** · [English](README.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

# 1846 Self-Play Arena · 1846 自战实验室

一个在本地运行的 **1846: The Race for the Midwest** 自战 / 自学习平台：用 18xx.games 的开源规则引擎执行规则，提供规则感知的机器人、神经网络自战训练回路、可回放的网页观战界面，以及一套用真实对局日志校验规则数值的审计工具。

[![verify](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml/badge.svg)](https://github.com/Pig9013/1846-selfplay-arena/actions/workflows/verify.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**版本 1.0.0** · Windows · 离线运行 · 不依赖网站账号和云端模型

---

## 这个项目解决什么问题

18xx 的规则细节（地形费用、外域收入随时代变化、东西向奖励、Z/芝加哥专用瓦、车站阻挡、瓦片库存）在自制 AI 里极容易做错。这个项目把「规则」交给经过网站实战检验的引擎，把「决策」留给自己，并且用**真实对局日志**反查规则实现是否正确：

- **规则执行**：`18xx-master`（tobymao/18xx，MIT）作为唯一裁判；机器人只生成候选，最终由引擎校验。
- **真实对局审计**：`audit/` 从引擎导出瓦片目录，重放 95 份 18xx.games 日志的铺轨/时代/奖励分配，独立重算 **69,494 条线路收入**，与网站记录一致率 **99.99%**。
- **自学习回路**：KataGo 式的最小实现——多进程自战采样 → 策略/价值网络训练 → 热加载新模型 → 对启发式基线评估胜率。
- **可观察**：网页实时显示版图、成本、外域数值、奖励归属、瓦片库存、每回合铺轨/升级槽位。

> 1846 是 Thomas Lehmann 设计、GMT Games 出版的作品。本仓库**不包含**规则书、美术素材或任何官方文件；规则引擎是第三方 MIT 代码，自战数据由本项目的机器人产生。

## 主要特性

| 模块 | 说明 |
| --- | --- |
| 规则数值 | 铺轨费用 = max($20, 印值)，跨河/山/隧道在**首次接通**时付边费；Z 瓦 / 芝加哥瓦 / 普通瓦分离；瓦片数量受限；车站满员后阻挡通行 |
| 外域与东西向 | 外域收入按时代（黄/棕）取值；E→E 禁止、W→W 允许、Holland 与 Louisville 中立；E/W 奖励取两端外域图标数值之和 |
| 私营公司 | Boomtown / Meat Packing / Steamboat 按**格子**与**拥有者**生效（码头 Wheeling/Holland +$40，其余 +$20），分配与归属可见 |
| 机器人 | 规则感知候选生成（连接检查、瓦片库存、颜色/保留轨道、股份与列车限制），启发式打分，可叠加神经网络策略 |
| 自学习 | `p1846/selfplay.rb` 采样 → `train/nnserver.py` 推理 → `train/trainer.py` 训练 → `train/orchestrate.py` 编排 |
| 观战 | 本地网页：版图、回放、玩家资产、公司表、决策理由、训练面板 |
| 审计 | `audit/log_audit.py` 用真实日志重算线路收入；`verify_game.rb` 逐行动重放并核对现金守恒 |
| 资源占用 | 子进程低于正常优先级；并发默认「核心数 − 2」；训练只用 2 个 torch 线程 |

## 快速开始

### 依赖

- Windows 10/11，Python 3.12（仅标准库即可运行平台；训练需要 PyTorch）
- 本项目自带 Ruby 3.4.9 便携运行时于 `runtime/`（不修改系统 Ruby）
- **18xx 规则引擎**放在本目录的**同级**：`../18xx-master`（克隆 `https://github.com/tobymao/18xx`，或使用你已经有的快照）

```
父目录/
├── 1846自战平台/      ← 本仓库
│   ├── server.py
│   ├── arena.rb
│   ├── p1846/
│   ├── train/
│   ├── audit/
│   ├── web/
│   └── runtime/        ← Ruby 运行时（发布包自带，仓库中忽略）
└── 18xx-master/        ← 规则引擎（MIT）
```

### 运行平台

```bat
启动平台.cmd
```

浏览器打开 `http://127.0.0.1:1846`，选择人数与席位策略，开始自战。也可以：

```bat
python server.py --no-browser --port 1846
```

### 跑自学习

```bat
python train\orchestrate.py --workers 6 --minutes 120 --train-every 4 --steps 200 --eval-every 30 --seed 3000
```

或双击 `启动训练.cmd`。模型写入 `train/checkpoints/latest.pt`，样本写入 `train/data/`，网页「自学习训练」面板可启停。

### 校验规则

```bat
ruby audit\export_catalog.rb     :: 从引擎导出瓦片目录
python audit\log_audit.py        :: 重算真实日志的线路收入并比对
python verify_all.py runs        :: 逐局重放并核对收入与现金守恒
python tests\\test_audit.py       :: 审计器单元测试（CI 也跑这个）
```

## 仓库结构

```
server.py              本机 HTTP 服务、对局/训练管理、静态页面
arena.rb               单局自战循环：候选生成 → 打分/网络 → 引擎执行
engine_boot.rb         原生 Ruby 加载适配（跳过仅供浏览器的 JS 段）
verify_game.rb         独立复核一局（逐行动重放、收入重算、现金守恒）
verify_all.py          批量复核
p1846/board.rb         版图与规则数值导出（成本、边费、外域、标签、库存、奖励归属）
p1846/actions.rb       合法候选生成 + 线路组合搜索（上游 AutoRouter）
p1846/policy.rb        启发式打分
p1846/model.rb         神经网络特征编码（128 维状态 / 40 维动作）
p1846/selfplay.rb      自战采样进程（写出训练样本）
train/net.py           策略/价值网络
train/nnserver.py      本机推理服务（热加载检查点）
train/trainer.py       训练循环（优势加权模仿 + 价值回归）
train/orchestrate.py   多进程自战 + 训练 + 评估编排
audit/                 真实对局日志审计工具与瓦片目录
web/                   中文观战与训练面板
examples/              自战样例（对局 JSON、引擎日志、训练样本）
```

## 数据格式

### 对局（`examples/selfplay/*/game.json`）

18xx 引擎格式：玩家、种子、完整 `raw_actions`。可直接用 `verify_game.rb` 重放：

```bat
ruby verify_game.rb "examples\selfplay\4p-seed606\game.json"
```

### 训练样本（`examples/training/*.jsonl.gz`）

每局一个 JSONL，逐行：

```json
{"type":"decision","actor":"1","state":[128 个浮点],"actions":[[40 个浮点],...],"chosen":0,"prior":[...]}
{"type":"result","scores":{"1":5506,"2":0,...},"z":{"1":0.98,...}}
```

- `state`：局面特征（时代、银行、公司现金/列车/股价、玩家资产、版图统计）
- `actions`：该决策点最多 12 个合法候选的动作特征
- `chosen`：实际执行的候选下标
- `prior`：启发式打分（用于蒸馏）
- `z`：按最终资产标准化的名次收益（均值 0、标准差 1）

## 规则校验结果

95 份日志、69,494 条线路收入重算，与网站一致率 **99.99%**（5 条差异来自审计器自身的板面跟踪缺口）。审计过程中确认并修正了两条容易错的实现：

- **Mail Contract** 按**经过**的站点计费（含 N/M 列车跳过、不计收入的站）；
- **港口图标是粘性的**：城市升级后港口图标保留到 IV 时代移除奖励事件。

铺轨费用的真实分布也与规则 6.48 一致：H16 首铺 $40 / 升级 $20；B16 不跨山边 $20、跨过 $60；I11 跨河 $60；F18 出现 20/40/60/80 组合。

## 自学习现状（1.0）

- 回路已打通：9 分钟 6 进程可产生约 100+ 局、数万决策样本，损失稳定下降。
- 对三个启发式席位的小样本胜率约 0.67（样本少，仅供参考，**不代表棋力已经超过人类或启发式**）。
- 没有 MCTS：引擎局面无法廉价克隆，当前用「候选排序 + 先验蒸馏 + 优势加权」代替树搜索。

## 已知限制

- 只支持标准 1846、3–5 人、无可选规则。
- 机器人候选未覆盖全部特殊能力（部分私营公司铺轨、列车交易）。
- 网页版图是数据驱动的简化绘图：数值、方位、邻接与规则一致，但不是官方美术。
- 真实对局的完整行动序列无法从网站 API 取回（归档对局返回空 actions），本地日志又隐藏私营公司分配环节，因此审计采用「板面 + 收入重算」，不是整局重放。

## 版本

当前 **1.0.0**。变更见 [CHANGELOG.md](CHANGELOG.md)。路线图：补齐特殊能力候选、把铺轨槽位/库存/奖励归属纳入网络特征、加入更严格的对手池评估。

## English summary

A local, offline arena for **1846: The Race for the Midwest**. A sibling
checkout of the MIT-licensed [tobymao/18xx](https://github.com/tobymao/18xx)
engine judges every action; this project adds rules-aware candidate generation,
a data-driven board/replay UI, a KataGo-style self-play training loop and a
real-log rule auditor (95 logs, 69,494 route revenues recomputed, 99.99% match).
Version 1.0.0. Sample games and compressed training samples live under
`examples/` and in the v1.0.0 release. The repository does not vendor the rules
engine, the Ruby runtime, or any official 1846 assets.

## 许可与声明

- 本仓库原创代码：MIT（见 [LICENSE](LICENSE)）。
- 规则引擎：`tobymao/18xx`，MIT。
- **1846: The Race for the Midwest** 设计 Thomas Lehmann，GMT Games 出版；本项目与其出版商无关，不包含规则书、地图美术或任何官方组件。
- 自战数据由本项目的机器人产生，可自由用于研究。
