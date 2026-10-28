"""Per-1000-game action-logic report for the 1846 self-play arena.

Reads the newest self-play JSONL samples and their game.json action logs,
filters out degenerate pass-only games, and writes a Chinese Markdown report
that explains what the current AI actually did, which weights drove it, what
correlated with winning, and what the next block of games should fix.

Usage:
  python train/analyze.py --data train/data --out train/reports --label 1000
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

TYPES = ["lay_tile", "place_token", "run_routes", "dividend", "buy_train", "par",
         "buy_shares", "sell_shares", "bid", "buy_company", "assign", "pass",
         "discard_train", "bankrupt"]
PHASES = ["I", "II", "III", "IV"]
OFFBOARD_HEXES = {"B8", "B18", "C5", "C17", "C21", "D22", "E23", "F22", "G21",
                  "H20", "I1", "I17", "J10"}
CHICAGO = "D6"
CHICAGO_CONNECTIONS = "C5"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CHANGELOG = Path(__file__).resolve().parent / "logic_changelog.json"


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return rows


def neighbors(hex_id):
    """Pointy-layout neighbours from a coordinate like D6 / B16."""
    if not hex_id or not hex_id[0].isalpha():
        return set()
    letter = hex_id[0]
    number = int(hex_id[1:])
    x = LETTERS.index(letter)
    y = number - 1
    result = set()
    for dx, dy in ((-1, 1), (-2, 0), (-1, -1), (1, -1), (2, 0), (1, 1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < len(LETTERS) and ny >= 0:
            result.add(f"{LETTERS[nx]}{ny + 1}")
    return result


def is_offboard_adjacent(hex_id):
    return bool(neighbors(hex_id) & OFFBOARD_HEXES)


def load_game(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    actions = data.get("actions") or []
    non_pass = sum(1 for action in actions if action.get("type") != "pass")
    lay = sum(1 for action in actions if action.get("type") == "lay_tile")
    par = sum(1 for action in actions if action.get("type") == "par")
    degenerate = non_pass < 30 or lay == 0 or par == 0
    return {"actions": actions, "result": data.get("result") or {},
            "non_pass": non_pass, "lay": lay, "par": par, "degenerate": degenerate}


def load_sample(path):
    rows = read_jsonl(path)
    meta = next((row for row in rows if row.get("type") == "meta"), {})
    result = next((row for row in rows if row.get("type") == "result"), {})
    decisions = [row for row in rows if row.get("type") == "decision"]
    return meta, result, decisions


def action_type(vector):
    if not vector:
        return "?"
    for i, value in enumerate(vector[:14]):
        if value > 0.5:
            return TYPES[i]
    return "?"


def rank_of(values, chosen):
    order = sorted(range(len(values)), key=lambda i: (-values[i], i))
    try:
        return order.index(chosen)
    except ValueError:
        return len(order)


def softmax_entropy(values, temperature=1.5):
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    sigma = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) or 1.0
    top = max(values)
    weights = [math.exp(((v - top) / (temperature * sigma))) for v in values]
    total = sum(weights)
    if total <= 0:
        return 0.0
    probs = [w / total for w in weights]
    return -sum(p * math.log(p + 1e-12) for p in probs if p > 0)


def safe_mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def parse_games(data_dir, limit=1200):
    """Return usable games plus counts of degenerate samples."""
    jsonl_files = sorted(Path(data_dir).glob("*.jsonl"), key=safe_mtime)[-limit:]
    games = []
    degenerate = 0
    missing_game = 0
    for path in jsonl_files:
        meta, result, decisions = load_sample(path)
        game_path = path.with_suffix(".game.json")
        game = load_game(game_path) if game_path.is_file() else None
        if game is None:
            missing_game += 1
            continue
        if meta.get("degenerate") or game["degenerate"]:
            degenerate += 1
            continue
        if meta.get("feature_version", 0) < 2:
            degenerate += 1
            continue
        games.append({"path": path, "meta": meta, "result": result,
                      "decisions": decisions, "game": game})
    return games, degenerate, missing_game, len(jsonl_files)


def analyze_game(entry):
    actions = entry["game"]["actions"]
    result = entry["game"]["result"] or entry["result"].get("scores") or {}
    scores = {str(k): float(v) for k, v in result.items()}
    order = sorted(scores, key=lambda k: -scores[k])
    ranks = {player: order.index(player) + 1 for player in scores}
    founder = {}
    for action in actions:
        if action.get("type") == "par" and action.get("corporation") and action.get("entity"):
            founder.setdefault(action["corporation"], action["entity"])

    counts = Counter(action.get("type") for action in actions)
    laid = Counter(action.get("hex") for action in actions if action.get("type") == "lay_tile")
    upgrade_tiles = {"14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
                     "25", "26", "27", "28", "29", "30", "31", "39", "40", "41", "42",
                     "43", "44", "45", "46", "47", "51", "57", "70", "290", "294", "295",
                     "296", "297", "298", "299", "300", "611", "619"}
    upgrades = sum(1 for action in actions if action.get("type") == "lay_tile" and
                   action.get("tile", "").split("-")[0] in upgrade_tiles)
    chicago = []
    c5_routes = 0
    d6_c5_routes = 0
    ew_routes = 0
    offboards = set()
    route_revenue = []
    for action in actions:
        if action.get("type") == "lay_tile" and action.get("hex") == CHICAGO:
            tile = action.get("tile", "").split("-")[0]
            if tile in {"298", "299", "300"}:
                chicago.append((action.get("entity"), tile))
        if action.get("type") == "run_routes":
            for route in action.get("routes") or []:
                hexes = route.get("hexes") or []
                if CHICAGO_CONNECTIONS in hexes:
                    c5_routes += 1
                    offboards.add(CHICAGO_CONNECTIONS)
                    if CHICAGO in hexes:
                        d6_c5_routes += 1
                if "E/W" in (route.get("revenue_str") or ""):
                    ew_routes += 1
                for hex_id in hexes:
                    if hex_id in OFFBOARD_HEXES:
                        offboards.add(hex_id)
                if route.get("revenue") is not None:
                    route_revenue.append(float(route["revenue"]))

    lay_by_player = Counter()
    for action in actions:
        if action.get("type") != "lay_tile":
            continue
        actor = action.get("entity")
        owner = founder.get(actor, actor if actor in ranks else None)
        if owner in ranks:
            lay_by_player[owner] += 1
    chicago_green = any(tile == "298" for _, tile in chicago)
    chicago_brown = any(tile == "299" for _, tile in chicago)
    chicago_gray = any(tile == "300" for _, tile in chicago)
    chicago_owner = founder.get(chicago[0][0]) if chicago else None
    c5_owner_ranks = []
    c5_seen = set()
    for action in actions:
        if action.get("type") != "run_routes":
            continue
        entity = action.get("entity")
        if any(CHICAGO_CONNECTIONS in (route.get("hexes") or []) for route in action.get("routes") or []):
            owner = founder.get(entity)
            if owner in ranks and owner not in c5_seen:
                c5_seen.add(owner)
                c5_owner_ranks.append(ranks[owner])
    return {
        "counts": counts,
        "laid": laid,
        "upgrades": upgrades,
        "chicago": chicago,
        "chicago_green": chicago_green,
        "chicago_brown": chicago_brown,
        "chicago_gray": chicago_gray,
        "chicago_owner": chicago_owner,
        "c5_routes": c5_routes,
        "d6_c5_routes": d6_c5_routes,
        "ew_routes": ew_routes,
        "offboards": offboards,
        "route_revenue": route_revenue,
        "ranks": ranks,
        "scores": scores,
        "founder": founder,
        "c5_owner_ranks": c5_owner_ranks,
        "lay_by_player": lay_by_player,
        "non_pass": entry["game"]["non_pass"],
    }


def analyze_decisions(games):
    total = 0
    top1 = 0
    ranks = []
    gaps = []
    entropies = []
    phase_types = defaultdict(Counter)
    chosen_types = Counter()
    offboard_lay = 0
    offboard_miss = 0
    for entry in games:
        for decision in entry["decisions"]:
            prior = decision.get("prior") or []
            chosen = decision.get("chosen", 0)
            actions = decision.get("actions") or []
            if not prior or chosen >= len(actions):
                continue
            total += 1
            rank = rank_of(prior, chosen)
            ranks.append(rank)
            top1 += 1 if rank == 0 else 0
            ordered = sorted(prior, reverse=True)
            gaps.append(ordered[0] - ordered[1] if len(ordered) > 1 else 0.0)
            entropies.append(softmax_entropy(prior))
            state = decision.get("state") or []
            phase = PHASES[max(range(4), key=lambda i: state[i])] if len(state) >= 4 else "?"
            kind = action_type(actions[chosen])
            chosen_types[kind] += 1
            phase_types[phase][kind] += 1
            if kind == "lay_tile":
                link = actions[chosen][32] if len(actions[chosen]) > 32 else 0.0
                edges = actions[chosen][33] if len(actions[chosen]) > 33 else 0.0
                if link > 0.5:
                    offboard_lay += 1
                elif edges > 0:
                    offboard_miss += 1
    return {
        "total": total,
        "top1_rate": top1 / total if total else 0.0,
        "mean_rank": statistics.mean(ranks) if ranks else 0.0,
        "median_rank": statistics.median(ranks) if ranks else 0.0,
        "mean_gap": statistics.mean(gaps) if gaps else 0.0,
        "mean_entropy": statistics.mean(entropies) if entropies else 0.0,
        "chosen_types": chosen_types,
        "phase_types": phase_types,
        "offboard_lay": offboard_lay,
        "offboard_miss": offboard_miss,
    }


def latest_changes():
    try:
        data = json.loads(CHANGELOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list) and data:
        return data[-1].get("changes") or []
    return []


def previous_metrics(out_dir):
    index = Path(out_dir) / "index.json"
    if not index.is_file():
        return None
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data[-1] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)


def pct(value):
    return f"{value * 100:.1f}%"


def build_report(games, degenerate, missing_game, total_files, label, out_dir, model_status, model_log):
    games = sorted(games, key=lambda g: safe_mtime(g["path"]))
    analyzed = [analyze_game(g) for g in games]
    decisions = analyze_decisions(games)
    n = len(analyzed)
    action_totals = Counter()
    for game in analyzed:
        action_totals.update(game["counts"])
    total_actions = sum(action_totals.values()) or 1
    end_reasons = Counter(str(g["meta"].get("end_reason", "?")) for g in games)
    bankrupt = end_reasons.get("bankrupt", 0)
    lay_total = action_totals.get("lay_tile", 0)
    chicago_green = sum(1 for g in analyzed if g["chicago_green"])
    chicago_any = sum(1 for g in analyzed if g["chicago"])
    c5_games = sum(1 for g in analyzed if g["c5_routes"] > 0)
    ew_games = sum(1 for g in analyzed if g["ew_routes"] > 0)
    offboard_games = sum(1 for g in analyzed if g["offboards"])
    avg_lays = lay_total / n if n else 0
    avg_routes = sum(g["c5_routes"] for g in analyzed) / n if n else 0
    avg_ew = sum(g["ew_routes"] for g in analyzed) / n if n else 0
    avg_non_pass = sum(g["non_pass"] for g in analyzed) / n if n else 0
    top_hexes = Counter()
    for game in analyzed:
        top_hexes.update(game["laid"])

    green_owner_top2 = 0
    green_n = 0
    for game in analyzed:
        if not game["chicago_green"]:
            continue
        owner = game["chicago_owner"]
        if owner in game["ranks"]:
            green_n += 1
            green_owner_top2 += 1 if game["ranks"][owner] <= 2 else 0
    c5_players = [r for game in analyzed for r in game["c5_owner_ranks"]]
    c5_top2 = sum(1 for r in c5_players if r <= 2)
    top_layer_ranks = []
    winner_lays = []
    loser_lays = []
    for game in analyzed:
        lays = game["lay_by_player"]
        if lays:
            best = max(lays.values())
            leaders = [player for player, count in lays.items() if count == best and player in game["ranks"]]
            if leaders:
                top_layer_ranks.append(min(game["ranks"][player] for player in leaders))
        if game["ranks"]:
            winner = min(game["ranks"], key=game["ranks"].get)
            winner_lays.append(lays.get(winner, 0))
            for player in game["ranks"]:
                if player != winner:
                    loser_lays.append(lays.get(player, 0))

    prev = previous_metrics(out_dir)
    metrics = {
        "label": label, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "usable_games": n, "degenerate": degenerate, "total_files": total_files,
        "decisions": decisions["total"], "top1_rate": round(decisions["top1_rate"], 3),
        "mean_rank": round(decisions["mean_rank"], 2),
        "chicago_green": chicago_green, "c5_games": c5_games,
        "offboard_lay": decisions["offboard_lay"], "offboard_miss": decisions["offboard_miss"],
        "avg_lays": round(avg_lays, 2), "winrate": model_status.get("winrate"),
        "train_steps": model_status.get("train_steps"), "loss": model_status.get("loss"),
    }

    lines = []
    lines.append(f"# 1846 自战 AI 行动逻辑分析（第 {label} 局）")
    lines.append("")
    lines.append(f"> 样本：最近 {total_files} 个自战文件，可用 {n} 局，退化 {degenerate} 局"
                f"（缺失 game.json {missing_game} 局）｜决策 {decisions['total']} 条"
                f"｜生成时间 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 一句话结论")
    lines.append("")
    if n == 0:
        lines.append("**这批样本里没有可用于策略分析的完整对局。** 全部是退化局（只出 pass、没有开办公司/铺轨）。"
                     "这不是 AI 不想动，而是神经网络塌缩成永远 pass 的典型症状；修复见文末清单。")
    else:
        lines.append(
            f"这一批 AI **每局平均铺 {avg_lays:.1f} 块瓦**，"
            f"**{pct(chicago_green / n)} 的对局升级了芝加哥**，"
            f"**{pct(c5_games / n)} 的对局跑出了芝加哥连接（C5）**，"
            f"**{pct(ew_games / n)} 的对局跑出东西向奖励**；"
            f"前 1 候选被采纳率 {pct(decisions['top1_rate'])}，平均排序 {decisions['mean_rank']:.2f}。"
        )
    lines.append("")
    lines.append("## 一、这一批局在做什么")
    lines.append("")
    lines.append("| 行动 | 次数 | 占比 | 每局 |")
    lines.append("|:--|--:|--:|--:|")
    for kind, count in action_totals.most_common():
        if n:
            lines.append(f"| {kind} | {count} | {pct(count / total_actions)} | {count / n:.1f} |")
        else:
            lines.append(f"| {kind} | {count} | {pct(count / total_actions)} | — |")
    lines.append("")
    lines.append(f"每局非 pass 行动 {avg_non_pass:.1f} 次；铺轨/升级 {lay_total} 次，其中升级 "
                f"{sum(g['upgrades'] for g in analyzed)} 次。铺得最多的格子："
                + "、".join(f"{hex_id}×{count}" for hex_id, count in top_hexes.most_common(10)) + "。")
    lines.append("")
    lines.append("结束方式：" + "、".join(f"{reason} {count} 局" for reason, count in end_reasons.most_common())
                 + f"（破产率 {pct(bankrupt / n) if n else '—'}）。")
    lines.append("")
    lines.append("### 按时代的行动结构")
    lines.append("")
    lines.append("| 时代 | " + " | ".join(["铺轨", "开办", "营运", "分红", "买车", "pass"]) + " |")
    lines.append("|:--|--:|--:|--:|--:|--:|--:|")
    for phase in PHASES:
        bucket = decisions["phase_types"].get(phase, Counter())
        lines.append(f"| {phase} | " + " | ".join(str(bucket.get(k, 0)) for k in
                                                   ["lay_tile", "par", "run_routes", "dividend", "buy_train", "pass"]) + " |")
    lines.append("")
    lines.append("## 二、AI 是怎么想的")
    lines.append("")
    lines.append("当前每个决策点的流程是：**引擎合法候选 → 启发式先验 → 神经网络残差 → 带温度的 softmax 采样**。"
                 "没有 MCTS；引擎局面无法廉价克隆，所以用候选排序 + 先验蒸馏 + 结果加权来代替树搜索。")
    lines.append("")
    lines.append("启发式先验里权重最高的是：")
    lines.append("")
    lines.append("| 项 | 权重/规则 |")
    lines.append("|:--|:--|")
    lines.append("| 外域连接 | 旋转真正接通外域：+42，再按外域收入加 0.6×收入；只朝向外域却没接通：−30 |")
    lines.append("| 芝加哥 | 升级 D6：+30 基础，绿 +55 / 棕 +90 / 灰 +125；接通 C5 再 +40 |")
    lines.append("| 城市收益 | 新瓦城市收入 ×0.7；升级带来的收入增量再 ×0.45 |")
    lines.append("| 通过性 | 同一路径连通边数 ×8 |")
    lines.append("| 成本 | 铺轨成本 ×0.28 扣分；没钱买车时再扣 40 |")
    lines.append("| 车站 | 芝加哥站 +58；保留/远程站 +22 |")
    lines.append("| 私营 | MS 44 / BIG4 34 / C&WI 38（芝加哥免费站） |")
    lines.append("")
    lines.append(f"实际决策统计：前 1 候选被采纳 **{pct(decisions['top1_rate'])}**，平均排序 "
                 f"**{decisions['mean_rank']:.2f}**，先验熵 **{decisions['mean_entropy']:.2f}**，"
                 f"首选与次选平均分差 **{decisions['mean_gap']:.1f}**。"
                 + ("采样接近贪心：探索主要发生在分数接近的候选之间。" if decisions["top1_rate"] > 0.75 else
                    "采样保留了明显的探索：不少局面没有直接选先验第一。"))
    lines.append("")
    neural = model_status
    if isinstance(neural.get("winrate"), (int, float)):
        lines.append(f"神经网络检查点：第 **{neural.get('train_steps', 0)}** 步，策略/价值损失 "
                     f"**{neural.get('loss', '—')}**，对三个启发式席位的胜率 **"
                     f"{(neural.get('winrate') * 100):.0f}%**（4 人局随机基线 25%）。")
    else:
        lines.append(f"神经网络检查点：第 **{neural.get('train_steps', 0)}** 步，策略/价值损失 "
                     f"**{neural.get('loss', '—')}**；尚无有效评估胜率。")
    lines.append("")
    lines.append("网络只输出一个残差分数，经过**每个决策内标准化**（减均值、除标准差、截断 ±3）后按 15 分权重叠加。"
                 "早期版本直接把原始 logit 乘 60，导致一个永远 pass 的局部最优压过全部启发式，整局退化；"
                 "这一版已改为有界残差，并在采样时加入 5% 均匀探索。")
    lines.append("")
    lines.append("## 三、轨道、外域与芝加哥")
    lines.append("")
    lines.append(f"- 芝加哥升级：{chicago_green}/{n} 局到绿（{pct(chicago_green / n) if n else '—'}），"
                 f"{sum(1 for g in analyzed if g['chicago_brown'])} 局到棕，"
                 f"{sum(1 for g in analyzed if g['chicago_gray'])} 局到灰；有芝加哥行动的局 {chicago_any}。")
    lines.append(f"- 芝加哥连接：{c5_games} 局至少跑过一次 C5（{pct(c5_games / n) if n else '—'}），"
                 f"平均每局 {avg_routes:.2f} 条 C5 线路；其中 D6–C5 同线 {sum(g['d6_c5_routes'] for g in analyzed)} 条。")
    lines.append(f"- 东西向：{ew_games} 局跑出 E/W 奖励（{pct(ew_games / n) if n else '—'}），平均每局 {avg_ew:.2f} 条。")
    lines.append(f"- 外域覆盖：{offboard_games} 局至少用过一处外域（{pct(offboard_games / n) if n else '—'}）。")
    lines.append(f"- 旋转质量：在铺轨决策中，**接通外域** {decisions['offboard_lay']} 次，"
                 f"**朝向外域但没接通** {decisions['offboard_miss']} 次"
                 f"（失误率 {pct(decisions['offboard_miss'] / max(1, decisions['offboard_lay'] + decisions['offboard_miss']))}）。")
    lines.append("")
    lines.append("## 四、什么更可能赢（描述性，不是因果）")
    lines.append("")
    if n:
        lines.append(f"- 绿芝加哥的发起公司总裁进入前二：{green_owner_top2}/{green_n}"
                     f"（{pct(green_owner_top2 / green_n) if green_n else '—'}；4 人局基线 50%）。")
        lines.append(f"- 跑过 C5 的公司总裁（每局去重）进入前二：{c5_top2}/{len(c5_players)}"
                     f"（{pct(c5_top2 / len(c5_players)) if c5_players else '—'}；4 人局基线 50%）。")
        if top_layer_ranks:
            lines.append(f"- 每局铺轨最多的玩家，平均名次 {statistics.mean(top_layer_ranks):.2f}"
                         f"（{len(top_layer_ranks)} 局；4 人局随机 2.50）。")
        if winner_lays and loser_lays:
            lines.append(f"- 冠军平均铺 {statistics.mean(winner_lays):.1f} 块，其他玩家 "
                         f"{statistics.mean(loser_lays):.1f} 块。")
    else:
        lines.append("样本不足，不做胜负相关统计。")
    lines.append("")
    lines.append("> 注意：这些是同一批自战局内的相关性。芝加哥/外域与胜利可能互为因果，"
                 "也可能只是领先的公司更有钱去抢芝加哥。要看因果，需要下一批做对照（固定种子、只改芝加哥权重）。")
    lines.append("")
    lines.append("## 五、自我修正")
    lines.append("")
    if prev:
        lines.append(f"与上一份（第 {prev.get('label')} 局，可用 {prev.get('usable_games')} 局）相比：")
        lines.append("")
        lines.append("| 指标 | 上一份 | 本份 |")
        lines.append("|:--|--:|--:|")
        for key, label_text in (("usable_games", "可用局数"), ("chicago_green", "绿芝加哥局数"),
                                ("c5_games", "C5 局数"), ("top1_rate", "前1采纳率"),
                                ("mean_rank", "平均排序"), ("train_steps", "训练步数"),
                                ("winrate", "对启发式胜率")):
            lines.append(f"| {label_text} | {prev.get(key, '—')} | {metrics.get(key, '—')} |")
        lines.append("")
    else:
        lines.append("这是第一份自动分析，没有上一份可比。")
        lines.append("")
    changes = latest_changes()
    lines.append("最近一次修正记录（train/logic_changelog.json）：")
    lines.append("")
    if changes:
        for index, change in enumerate(changes, 1):
            lines.append(f"{index}. {change}")
    else:
        lines.append("1. 暂无记录。")
    lines.append("")
    lines.append("## 六、下一千局要改什么")
    lines.append("")
    fixes = []
    if decisions["offboard_miss"] > max(3, decisions["offboard_lay"] * 0.15):
        fixes.append("旋转仍有超过 15% 的朝外域但不接通，继续检查 Connectivity.analyze_tile 的边/节点判定。")
    if n and chicago_green / n < 0.3:
        fixes.append("芝加哥升级率仍低于 30%，考虑把 C&WI 的竞价权重和 D6 绿瓦权重再提高一档。")
    if n and chicago_green / n > 0.9:
        fixes.append("芝加哥升级率高于 90%，可能过度集中；观察是否挤压其他外域线路，必要时下调 D6 绿瓦加分。")
    if top_layer_ranks and statistics.mean(top_layer_ranks) > 2.6:
        fixes.append(f"铺轨最多的玩家平均名次 {statistics.mean(top_layer_ranks):.2f}，差于 4 人局随机 2.50；"
                     "AI 有“能铺就铺”的倾向，下一批检查铺轨边际收益/成本，不要把铺轨数当目标。")
    if decisions["top1_rate"] > 0.85:
        fixes.append("前 1 采纳率过高，探索不足；提高采样温度或均匀探索比例。")
    if isinstance(neural.get("winrate"), (int, float)) and neural["winrate"] < 0.3:
        fixes.append("神经网络对启发式仍低于 30%，先别加大网络权重；优先扩大样本和修特征。")
    if n and bankrupt / n > 0.15:
        fixes.append(f"破产率 {pct(bankrupt / n)} 偏高；检查 buy_train 的现金保留、紧急增发与分红策略。")
    if not fixes:
        fixes.append("当前没有触发硬性阈值；保持权重，观察下一千局的芝加哥/外域曲线。")
    for item in fixes:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 七、数据质量")
    lines.append("")
    lines.append(f"- 退化局 {degenerate} 个（只 pass、无铺轨/无开办），已从训练与统计中剔除。")
    lines.append(f"- 缺失 game.json {missing_game} 个；旧版 40 维动作特征样本不再参与训练。")
    lines.append("- 训练器只读取 feature_version >= 2 且 degenerate != true 的样本。")
    lines.append("")
    lines.append("*分析人：Pig9013 ｜ 使用模型：Deepseek-flash ｜ 数据：1846 自战平台本地样本*")
    lines.append("")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"logic-{label:04d}.md"
    path.write_text("\n".join(lines), encoding="utf-8")

    index_path = out_dir / "index.json"
    history = []
    if index_path.is_file():
        try:
            history = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            history = []
    history = [item for item in history if item.get("label") != label]
    history.append(metrics)
    history.sort(key=lambda item: item.get("label", 0))
    index_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="train/data")
    parser.add_argument("--out", default="train/reports")
    parser.add_argument("--label", type=int, default=0)
    parser.add_argument("--limit", type=int, default=1200)
    args = parser.parse_args()

    data_dir = Path(args.data)
    games, degenerate, missing_game, total_files = parse_games(data_dir, args.limit)
    status = {}
    status_path = Path("train/status.json")
    if status_path.is_file():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            status = {}
    log = []
    log_path = Path("train/log.jsonl")
    if log_path.is_file():
        try:
            rows = log_path.read_text(encoding="utf-8").strip().splitlines()[-20:]
            log = [json.loads(row) for row in rows if row.strip()]
        except (OSError, json.JSONDecodeError):
            log = []
    label = args.label or status.get("games", 0) or len(games)
    path, metrics = build_report(games, degenerate, missing_game, total_files, label,
                                 args.out, status, log)
    print(json.dumps({"report": str(path), **metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
