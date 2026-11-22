# -*- coding: utf-8 -*-
# @version 3.2.5
"""第二音色影子分数的校准纯函数库（WP2，G0 阶段：只建档，不参与判定）。

为什么单独一个模块、为什么全是纯函数：
  第二路（wespeaker 256 维）与主路（CAM++ 192 维）的余弦分布**不可比**——
  不同模型对同人/异人的分数量程完全不同，直接把两路分数加权融合毫无意义。
  先把影子期的 (target, competitor, margin) 分布按
  **model_id × template_fp × language** 建档积累起来（`record`），等 G0 数据集
  就绪后再用这里的标准化函数把它们拉到同一把尺子上（分位排名 / z-score /
  Platt），最后才允许 `fused_score` 线性融合。**影子期内权重只记录、不参与
  判定**；升辅助（keep→review 降级）的权重要在验证集上网格搜索后**冻结**。

尺子选择：**分位排名（percentile_rank）以「竞争者底噪池」为公共刻度**——
  竞争者池（非启用模板在第二路上的最高分）就是「这个世界里随便一个人能有多
  像」，两路各自拿自己的底噪池做分位，得到的排名天然可比（0.9 = 比九成的
  路人更像，与模型量程无关）。z-score 对分布形状假设更强（近似正态才稳），
  只作备选；Platt 需要带标签样本 ≥200/键才启用（`PLATT_MIN_SAMPLES`），
  否则一律退回分位排名。

判据纪律（与 WP1/Jev 影子同源，**本模块默认影子、永不参与 decide**）：
  · 多原型沿用 mix 并集 max（与 `_as_template_list` 的并集语义一致）；
  · 升辅助只允许 keep→review 单向降级、**永不 drop**
    （`apply_assist`，触发条件 assist_margin，reason="second_voice_conflict"）；
  · 本任务默认 `enabled=False`（影子），`apply_assist` 直接原样返回 verdict。

无网络硬依赖：本模块不 import 任何联网库，文件读写全部 best-effort，
写失败返回 False 绝不抛出（影子数据的持久化失败不该惊动主流程）。
"""
import json
import math
import os
import time

#: 建档文件 schema（升级时按 schema 判断要不要迁移/重建）
CALIB_SCHEMA = "vt.voiceprint.score_calibration.v1"
#: 融合权重起点（可审计的线性加权）：主路 0.7 + 第二路 0.3 + margin 0.0。
#: 影子期只记录各路标准化分，**不进判定**；升辅助前在验证集上网格搜索后冻结。
DEFAULT_WEIGHTS = (0.7, 0.3, 0.0)
#: Platt 每键最少样本数。低于它样本太少，sigmoid 拟合会过拟合成阶跃函数，
#: 一律禁用退回分位排名。
PLATT_MIN_SAMPLES = 200
#: 每键分布样本上限（滚动保留最近 N 条，防建档文件无限膨胀）
MAX_SAMPLES_PER_KEY = 5000
#: 升辅助降级的触发裕量（草案值，G0 后按分布重标定）：第二路 target 比
#: drop 线还低出这么多，才算与主路 keep「真冲突」。保守起见给足余量，
#: 宁可少降级（误降级的代价是人工复核，误 keep 的代价是错字幕）。
ASSIST_MARGIN_DEFAULT = 0.10
#: 辅助降级 reason（验收口径固定字符串）
ASSIST_REASON = "second_voice_conflict"

#: 数据目录覆盖（自检注入用；缺省 <data>/voiceprint/calibration）
DIR_ENV = "VT_VP_CALIB_DIR"


def data_root():
    """校准建档目录（best-effort 对齐引擎 DATA_DIR，引擎不可用再回落）。"""
    r = (os.environ.get(DIR_ENV) or "").strip().strip('"')
    if r:
        return os.path.abspath(r)
    try:
        import features.voiceprint.voiceprint_sync as _vps
        return os.path.join(_vps.data_dir(), "voiceprint", "calibration")
    except Exception:  # noqa: BLE001  引擎/同步不可用（纯 CLI / 早期 import）
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(here)))), "data", "voiceprint", "calibration")


def key_of(template_fp, language=""):
    """建档键：model_id 是文件名，键 = template_fp × language。"""
    return "%s|%s" % (str(template_fp or "-"), str(language or "-"))


def _calib_path(model_id, root=None):
    safe = "".join(c for c in str(model_id or "model")
                   if c not in '\\/:*?"<>|') or "model"
    return os.path.join(root or data_root(), safe + ".json")


def _read_root(path):
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def load_stats(model_id, root=None):
    """读回整份建档 dict：{键: {"target": [...], "competitor": [...],
    "margin": [...], "labels": [...]}}。文件缺失/损坏返回空 dict。"""
    obj = _read_root(_calib_path(model_id, root))
    if not obj:
        return {}
    stats = obj.get("stats")
    return dict(stats) if isinstance(stats, dict) else {}


def record(model_id, template_fp, language, target, competitor,
           label=None, root=None, extra=None):
    """累积一对影子分数（best-effort；返回是否落盘成功）。

    `target`     本簇/本 cue 与启用第二路模板的最高余弦（并集 max）；
    `competitor` 同一段音频与非启用第二路模板的最高余弦（底噪池样本）；
    `label`      可选人工/主路 verdict 代理标签（1=本人 / 0=非本人）——
                 Platt 需要它，分位排名不需要；None 则不记标签。
    margin = target - competitor 在读取侧现算，也顺带累积一份便于查分布。

    同键滚动保留最近 MAX_SAMPLES_PER_KEY 条。写失败返回 False、绝不抛出。
    """
    if target is None or target != target:
        return False                       # NaN/缺失分数不建档
    try:
        target = round(float(target), 6)
        competitor = (None if competitor is None or competitor != competitor
                      else round(float(competitor), 6))
        margin = (None if competitor is None
                  else round(target - competitor, 6))
        path = _calib_path(model_id, root)
        obj = _read_root(path) or {"schema": CALIB_SCHEMA, "model_id":
                                   str(model_id), "stats": {}}
        stats = obj.get("stats") if isinstance(obj.get("stats"), dict) else {}
        k = key_of(template_fp, language)
        bucket = stats.get(k) if isinstance(stats.get(k), dict) else {}
        for name, val in (("target", target), ("competitor", competitor),
                          ("margin", margin)):
            lst = bucket.get(name)
            if not isinstance(lst, list):
                lst = []
            lst.append(val)
            bucket[name] = lst[-MAX_SAMPLES_PER_KEY:]
        if label is not None:
            lst = bucket.get("labels")
            if not isinstance(lst, list):
                lst = []
            lst.append(1 if label else 0)
            bucket["labels"] = lst[-MAX_SAMPLES_PER_KEY:]
        if extra:
            bucket["extra"] = dict(extra)   # 整体覆盖（展示用键，非分布数据）
        stats[k] = bucket
        obj["stats"] = stats
        obj["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        return False


# ------------------------------------------------------- 标准化（纯函数）

def percentile_rank(x, pool):
    """分位排名：x 在竞争者底噪池中的位置 -> [0, 1]（两模型可比的公共刻度）。

    口径：pool 中**严格小于** x 的占比（并列值不给自己加分，避免「池子里全是
    同一个分数」时排名虚高）。边界口径：
      · x 低于全部样本 -> 0.0；高于全部样本 -> 1.0；恰在中位 -> ~0.5；
      · 池为空 / x 为 NaN -> **0.5（中性）**——没有底噪信息时既不抬也不压，
        由调用方（融合端）自行决定是否采信；
      · 池全为 NaN -> 同空池处理。
    """
    if x is None or x != x:
        return 0.5
    clean = [float(v) for v in (pool or []) if v is not None and v == v]
    if not clean:
        return 0.5
    x = float(x)
    below = sum(1 for v in clean if v < x)
    return below / float(len(clean))


def zscore(x, pool):
    """z 分数备选口径：(x - 池均值) / 池标准差（ddof=0）。

    池为空 / 方差为 0（全员同分）-> 0.0（中性，不夸大）；x 为 NaN -> None。
    对分布形状假设比分位强（近似正态才稳），故只作备选、不作默认。
    """
    if x is None or x != x:
        return None
    clean = [float(v) for v in (pool or []) if v is not None and v == v]
    if not clean:
        return 0.0
    mu = sum(clean) / float(len(clean))
    var = sum((v - mu) ** 2 for v in clean) / float(len(clean))
    if var <= 1e-12:
        return 0.0
    return (float(x) - mu) / math.sqrt(var)


# ------------------------------------------------------- Platt（纯函数）

def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def fit_platt(scores, labels, iters=2000, lr=0.1, l2=1e-4):
    """对 (score, 0/1 label) 拟合 sigmoid 的 (A, B)：p = 1/(1+exp(-(A*score+B)))。

    纯 Python 小梯度下降（全批、log-loss + 微 L2 防发散）；样本 < 200
    （`PLATT_MIN_SAMPLES`）或缺任一类 -> 返回 None（禁用退回分位，调用方
    必须检查 None）。分数为 NaN/None 的样本跳过。
    """
    xs, ys = [], []
    for s, y in zip(scores or [], labels or []):
        if s is None or s != s:
            continue
        xs.append(float(s))
        ys.append(1.0 if y else 0.0)
    if len(xs) < PLATT_MIN_SAMPLES or not (0.0 < sum(ys) < len(ys)):
        return None
    n = float(len(xs))
    a, b = 1.0, 0.0
    step = lr
    for _it in range(int(iters)):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(a * x + b)
            d = p - y
            ga += d * x
            gb += d
        ga, gb = ga / n + l2 * a, gb / n
        a -= step * ga
        b -= step * gb
        step *= 0.999                # 轻微衰减，后期细化
    return (a, b)


def platt_apply(x, ab):
    """用拟合结果给单点打分；ab 为 None 或 x 无效 -> None。"""
    if ab is None or x is None or x != x:
        return None
    return _sigmoid(ab[0] * float(x) + ab[1])


# ------------------------------------------------------- 校准入口 / 融合

def calibrate(model_id, template_fp, language, x, root=None, method="auto",
              pool=None):
    """单点第二路分数 -> 与主路可比的标准化分。

    method="auto"：键上样本 >= 200 且带标签且两类齐全时用 Platt，
    否则用分位排名（竞争者底噪池为刻度；pool 缺省取该键的 competitor 列表）。
    返回 {"method", "score", "n", "disabled_reason"}；完全无数据时
    method="none"、score=None（调用方按「校准不可用」处理，不得臆造分数）。
    """
    stats = load_stats(model_id, root)
    bucket = stats.get(key_of(template_fp, language)) or {}
    targets = bucket.get("target") or []
    comp = bucket.get("competitor") or []
    labels = bucket.get("labels") or []
    use_pool = list(pool) if pool is not None else comp
    if method == "platt" or (method == "auto" and labels
                             and len(targets) >= PLATT_MIN_SAMPLES):
        ab = fit_platt(targets, labels)
        if ab is not None:
            s = platt_apply(x, ab)
            if s is not None:
                return {"method": "platt", "score": round(s, 6),
                        "n": len(targets), "disabled_reason": ""}
        if method == "platt":
            return {"method": "none", "score": None, "n": len(targets),
                    "disabled_reason": "platt_unavailable"}
    if use_pool or targets:
        return {"method": "percentile", "n": len(targets),
                "score": round(percentile_rank(x, use_pool), 6),
                "disabled_reason": ""}
    return {"method": "none", "score": None, "n": 0,
            "disabled_reason": "no_data"}


def fused_score(cam_cal, second_cal, margin_cal, w=DEFAULT_WEIGHTS):
    """线性加权融合（起点口径，可审计）：w = (主路, 第二路, margin)。

    输入是**各自标准化后**的分数（分位 / Platt / z，[0,1] 或 z 值），不是原始
    余弦。缺项处理：None/NaN 的项按权重剔除后**重新归一**剩余权重——主路缺席
    直接返回 None（没有主路就没有判定资格，第二路只是辅助证据）；margin 权重
    出厂 0.0，等价于二元融合。影子期本函数只被记录/评测调用，不进 decide。
    """
    if not (isinstance(w, (list, tuple)) and len(w) == 3):
        return None
    if cam_cal is None or cam_cal != cam_cal:
        return None
    terms = [(float(wi), xi) for wi, xi in zip(w, (cam_cal, second_cal,
                                                   margin_cal))
             if wi and xi is not None and xi == xi]
    if not terms:
        return None
    wsum = sum(wi for wi, _x in terms)
    if wsum <= 0:
        return None
    return sum(wi * float(x) for wi, x in terms) / wsum


def grid_search_fused(rows, weights_grid=None):
    """验证集网格搜索（G0 后冻结权重用，影子期只做离线评测）。

    rows = [(cam_cal, second_cal, margin_cal, is_host)]；对每组权重算
    「同人均值 - 异人均值」分离度，返回 [(weight, separation, n)] 按分离度
    降序——最终权重由人工确认后写死（不自动落盘、不自动生效）。
    """
    grid = list(weights_grid) if weights_grid else [
        (1.0, 0.0, 0.0), (0.9, 0.1, 0.0), (0.8, 0.2, 0.0), (0.7, 0.3, 0.0),
        (0.6, 0.4, 0.0), (0.5, 0.5, 0.0), (0.7, 0.2, 0.1), (0.6, 0.3, 0.1)]
    out = []
    for w in grid:
        same, diff = [], []
        for cam, sec, mg, is_host in rows or []:
            v = fused_score(cam, sec, mg, w)
            if v is None:
                continue
            (same if is_host else diff).append(v)
        if same and diff:
            sep = sum(same) / len(same) - sum(diff) / len(diff)
            out.append((tuple(w), round(sep, 6), len(same) + len(diff)))
    out.sort(key=lambda t: -t[1])
    return out


# ------------------------------------------------------- 升辅助降级（默认关）

def apply_assist(decisions, second_scores, enabled=False, threshold=0.55,
                 low=0.45, assist_margin=ASSIST_MARGIN_DEFAULT, fused=None):
    """升辅助：第二路证据与主路 keep 真冲突时，把该 cue 降级 keep→review。

    **纪律（验收口径）**：
      · 只允许 keep→review 单向降级，**永不 drop**；
      · 默认 `enabled=False`（影子）——直接原样返回 verdict 与空摘要，
        什么都不改；
      · 触发：主路 keep 且第二路 target 有效、且
        `second_target + assist_margin < low`（第二路深信「不是本人」），
        或显式传入融合分 `fused[i]` 且其 + assist_margin < low；
      · 降级 reason 固定 "second_voice_conflict"，score/其余字段不动。

    返回 (decisions, summary)；summary 记 applied / skipped / disabled 原因，
    供影子期统计与后续升辅助审计。
    """
    summary = {"enabled": bool(enabled), "applied": 0, "candidates": 0,
               "reason": ASSIST_REASON, "disabled_reason": ""}
    if not enabled:
        summary["disabled_reason"] = "shadow_only"
        return list(decisions or []), summary
    margin = float(assist_margin)
    out = []
    for i, row in enumerate(decisions or []):
        c, st, sc = row
        sec = second_scores[i] if second_scores and i < len(second_scores) \
            else None
        sec = sec if (sec is not None and sec == sec) else None
        fus = fused[i] if fused and i < len(fused) else None
        fus = fus if (fus is not None and fus == fus) else None
        if st == "keep":
            summary["candidates"] += 1
        conflict = False
        if st == "keep" and sec is not None and sec + margin < float(low):
            conflict = True
        elif st == "keep" and sec is None and fus is not None \
                and fus + margin < float(low):
            conflict = True
        if conflict:
            out.append((c, "review", sc))
            summary["applied"] += 1
        else:
            out.append(row)
    return out, summary


__all__ = ["CALIB_SCHEMA", "DEFAULT_WEIGHTS", "PLATT_MIN_SAMPLES",
           "ASSIST_MARGIN_DEFAULT", "ASSIST_REASON", "DIR_ENV",
           "data_root", "key_of", "load_stats", "record",
           "percentile_rank", "zscore", "fit_platt", "platt_apply",
           "calibrate", "fused_score", "grid_search_fused", "apply_assist"]
