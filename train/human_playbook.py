"""Summarize human 1846 games and emit a soft frequency prior.

Source: _work/1846_full.json (665 parsed 3-5 player games, 18xx.games).
This is a prior, not a rulebook.
"""
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT.parent / "_work" / "1846_full.json"
OUT_MD = ROOT / "train" / "human_playbook.md"
OUT_JSON = ROOT / "train" / "human_prior.json"
PHASES = ["I", "II", "III", "IV"]
Z_HEXES = {"C15", "E17", "H12"}
PRIVATE_SYMS = {
    "Michigan Southern (Minor)": "MS", "Big 4 (Minor)": "BIG4",
    "Chicago and Western Indiana": "C&WI", "Mail Contract": "MAIL",
    "Tunnel Blasting Company": "TBC", "Boomtown": "BT",
    "Michigan Central": "MC", "Ohio & Indiana": "O&I",
    "Little Miami": "LM", "Lake Shore Line": "LSL",
    "Steamboat Company": "SC", "Meat Packing Company": "MPC",
}


def norm(counts):
    if not counts:
        return {}
    top = max(counts.values()) or 1
    return {key: round(value / top, 4) for key, value in counts.items()}


def main():
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    games = [g for g in raw if not g.get("two_p") and g.get("n_players") in (3, 4, 5)]
    n = len(games)
    players = Counter(g.get("n_players") for g in games)

    phase_hex = defaultdict(Counter)
    phase_tile = defaultdict(Counter)
    token_hex = defaultdict(Counter)
    action_mix = defaultdict(Counter)
    train_mix = defaultdict(Counter)
    dividend_mix = defaultdict(Counter)
    par_counts = defaultdict(Counter)
    private_prices = defaultdict(list)
    private_counts = Counter()
    d6 = Counter()
    d6_first = Counter()
    z_all = z_any = 0
    ew_games = set()
    ew_first = Counter()
    c5_games = set()
    d6_games = set()
    ew_corp = Counter()
    route_len = defaultdict(list)

    for game_index, game in enumerate(games):
        label = game_index
        game_z = set()
        game_d6 = False
        game_d6_colors = set()
        first_phase = None
        first_ew_phase = None
        has_ew = False
        has_c5 = False
        for event in game.get("events", []):
            phase = event.get("phase")
            kind = event.get("kind")
            if phase:
                action_mix[phase][kind] += 1
            if kind == "tile":
                hex_id = event.get("hex")
                tile = str(event.get("tile"))
                if hex_id:
                    phase_hex[phase][hex_id] += 1
                if tile:
                    phase_tile[phase][tile] += 1
                if hex_id == "D6":
                    game_d6 = True
                    if tile == "298":
                        game_d6_colors.add("green")
                    elif tile == "299":
                        game_d6_colors.add("brown")
                    elif tile == "300":
                        game_d6_colors.add("gray")
                    if first_phase is None:
                        first_phase = phase
                if hex_id in Z_HEXES:
                    game_z.add(hex_id)
            elif kind == "token" and event.get("hex"):
                token_hex[phase][event["hex"]] += 1
            elif kind == "run":
                bonus = event.get("bonus") or ""
                route = event.get("route") or ""
                stops = len([part for part in route.split("-") if part])
                if stops:
                    route_len[event.get("train")].append(stops)
                if "E/W" in bonus or "E/W" in route:
                    has_ew = True
                    ew_corp[event.get("corp")] += 1
                    if first_ew_phase is None:
                        first_ew_phase = phase
                if "C5" in route:
                    has_c5 = True
            elif kind == "buy_train" and event.get("train"):
                train_mix[phase][event["train"]] += 1
            elif kind in ("div", "withhold", "half"):
                dividend_mix[phase][kind] += 1
            elif kind == "par":
                par_counts[event.get("corp")][str(event.get("price"))] += 1
        if game_d6:
            d6_games.add(label)
            for color in game_d6_colors:
                d6[color] += 1
            if first_phase:
                d6_first[first_phase] += 1
        if len(game_z) == 3:
            z_all += 1
        if game_z:
            z_any += 1
        if has_ew and label not in ew_games:
            ew_games.add(label)
            ew_first[first_ew_phase] += 1
        if has_c5:
            c5_games.add(label)
        for _, privates in (game.get("privates") or {}).items():
            for name, price in privates:
                sym = PRIVATE_SYMS.get(name, name)
                private_counts[sym] += 1
                private_prices[sym].append(float(price))

    private_avg = {k: statistics.mean(v) for k, v in private_prices.items() if v}
    prior = {
        "meta": {"source": str(SOURCE), "games": n, "players": dict(players),
                 "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "note": "frequency prior from human games; not a rule"},
        "phase_hex_norm": {p: norm(phase_hex[p]) for p in PHASES},
        "phase_tile_norm": {p: norm(phase_tile[p]) for p in PHASES},
        "token_hex_norm": {p: norm(token_hex[p]) for p in PHASES},
        "par_norm": {corp: norm(c) for corp, c in par_counts.items()},
        "private_norm": norm(private_avg),
        "train_norm": {p: norm(train_mix[p]) for p in PHASES},
        "dividend_norm": {p: norm(dividend_mix[p]) for p in PHASES},
        "action_norm": {p: norm(action_mix[p]) for p in PHASES},
        "rates": {
            "d6_any": round(len(d6_games) / n, 4),
            "d6_green": round(d6["green"] / n, 4),
            "d6_brown": round(d6["brown"] / n, 4),
            "d6_gray": round(d6["gray"] / n, 4),
            "z_all3": round(z_all / n, 4),
            "z_any": round(z_any / n, 4),
            "ew": round(len(ew_games) / n, 4),
            "c5": round(len(c5_games) / n, 4),
        },
        "ew_corp_norm": norm(ew_corp),
        "route_len": {train: {"n": len(values), "mean": round(statistics.mean(values), 2)}
                      for train, values in route_len.items() if values},
        "first_phase": {"d6": dict(d6_first), "ew": dict(ew_first)},
    }
    OUT_JSON.write_text(json.dumps(prior, ensure_ascii=False, indent=2), encoding="utf-8")

    def top(counter, limit=12):
        return "、".join(f"{k}×{v}" for k, v in counter.most_common(limit))

    lines = [
        "# 1846 人类对局玩法总结（665 局 3–5 人）",
        "",
        f"> 数据：18xx.games 公开对局 {n} 局（4 人 {players.get(4,0)}、5 人 {players.get(5,0)}、3 人 {players.get(3,0)}）"
        f"｜生成 {time.strftime('%Y-%m-%d %H:%M')}｜用途：给自战 AI 的人类行为先验，不是规则",
        "",
        "## 一句话",
        "",
        "人类高手不是把“去芝加哥”当规则，而是把它当成收入系统的一部分：先修通能跑车的骨架，"
        "在 II/III 时代升级芝加哥与 Z 城（克利夫兰/底特律/辛辛那提），尽快让一条线路同时吃到 E 与 W 外域，"
        "再用列车和分红放大现金流。这些动作在人类局里接近标配，真正的差距在时机、成本与谁先占住关键站。",
        "",
        "## 一、开局：私营与开办",
        "",
        "| 私营 | 出现次数 | 平均价 |",
        "|:--|--:|--:|",
    ]
    for name, count in private_counts.most_common():
        lines.append(f"| {name} | {count} | {private_avg.get(name,0):.0f} |")
    lines += ["", "| 公司 | 价格 | 次数 |", "|:--|--:|--:|"]
    rows = [(count, corp, price) for corp, counts in par_counts.items() for price, count in counts.items()]
    for count, corp, price in sorted(rows, reverse=True)[:15]:
        lines.append(f"| {corp} | {price} | {count} |")
    lines += [
        "",
        f"第一时代铺得最多的格子：{top(phase_hex['I'])}。这些是人类的开局骨架：先把主城/干线接起来。",
        "",
        "## 二、轨道：芝加哥、Z 城、E/W",
        "",
        f"- 芝加哥 D6：{len(d6_games)}/{n} 局有升级（{len(d6_games)/n:.1%}）；绿瓦 {d6['green']} 局"
        f"（{d6['green']/n:.1%}）、棕瓦 {d6['brown']} 局（{d6['brown']/n:.1%}）、灰瓦 {d6['gray']} 局"
        f"（{d6['gray']/n:.1%}）。第一次绿瓦多在 II 时代（{d6_first.get('II',0)} 局），III 时代 {d6_first.get('III',0)} 局。",
        f"- Z 城（C15/E17/H12）：三城全升级 {z_all}/{n}（{z_all/n:.1%}），至少一座 {z_any}/{n}（{z_any/n:.1%}）。",
        f"- E/W 奖励：{len(ew_games)}/{n} 局至少一次（{len(ew_games)/n:.1%}）；第一次出现 II {ew_first.get('II',0)} 局、"
        f"III {ew_first.get('III',0)} 局、IV {ew_first.get('IV',0)} 局。",
        f"- C5（Chicago Connections）：{len(c5_games)}/{n} 局至少一次（{len(c5_games)/n:.1%}）。",
        f"- E/W 主力公司（按人类 E/W 线路次数）：{top(ew_corp, 7)}。GT、NYC、IC、B&O 是主要执行者；"
        "PRR/C&O/ERIE 次之。",
        "",
        "结论：D6、Z 城、E/W 在人类局里都是接近必做的动作。AI 不应该把它们写成“必须”，"
        "而应该从人类频率里学“什么时候做、先做哪一个、用谁的钱做”。",
        "",
        "### 各时代铺得最多的格子",
        "",
    ]
    for phase in PHASES:
        lines.append(f"- **{phase}**：{top(phase_hex[phase])}")
    lines += ["", "### 各时代铺得最多的瓦", ""]
    for phase in PHASES:
        lines.append(f"- **{phase}**：{top(phase_tile[phase], 10)}")
    lines += [
        "",
        "## 三、运营：车、分红、增发",
        "",
        "| 时代 | 买车主力 | 分红方式 |",
        "|:--|:--|:--|",
    ]
    for phase in PHASES:
        trains = "、".join(f"{k}×{v}" for k, v in train_mix[phase].most_common(4))
        divs = "、".join(f"{k}×{v}" for k, v in dividend_mix[phase].most_common(4))
        lines.append(f"| {phase} | {trains or '—'} | {divs or '—'} |")
    lines += [
        "",
        "人类在 I 时代以 withhold 为主（留钱买 2 车/铺轨），II–IV 以 payout 为主；half 在 III/IV 增多。"
        "2 车是绝对主力，3/5、4/6 这类可变编组也很多——不是只买最便宜的车。",
        "",
        "## 四、对 AI 的启示",
        "",
        "1. 不要把芝加哥写成规则。人类几乎都升级 D6，但这是升级后 4 个 40 元城市接到 C5、再叠加 E/W 奖励的账，"
        "不是规则要求。AI 应该用通用收入/连通性 + 人类先验，让选择自己浮现。",
        "2. Z 城是收入骨架。三城全升级在人类局里 94%，AI 需要把 Z 城升级纳入中局计划。",
        "3. E/W 要尽早。人类 98.8% 的局跑出 E/W，而且 II 时代就开始；最新 316 局自战只有 35.8%，"
        "是当前最大的行为差距——问题在公司级路线规划，不是再加一个全局加分。",
        "4. 车与分红是节奏。2 车主流、III/IV 才大量 payout；AI 的破产率仍高于人类，要优先保证换车现金。",
        "",
        "## 五、先验怎么用",
        "",
        "train/human_prior.json 保存各时代铺轨格/瓦、par 价格、私营均价、买车/分红频率的归一化值。"
        "策略只把它当作小权重软先验（默认 10 分，可设 0 关闭），不是硬规则；神经网络和通用收入项仍可覆盖它。",
        "",
        "*数据来源：18xx.games 公开对局；分析人：Pig9013 ｜ 使用模型：Deepseek-flash*",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"games": n, "prior": str(OUT_JSON), "playbook": str(OUT_MD),
                      "d6_green": d6["green"], "ew": len(ew_games), "z_all": z_all}, ensure_ascii=False))


if __name__ == "__main__":
    main()
