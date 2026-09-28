#!/usr/bin/env python3
"""校验 personal-ai-companion 这个 skill 包（零第三方依赖）。

用法：
    python scripts/validate_skill.py            # 校验开发仓库（要求 README/LICENSE 等在）
    python scripts/validate_skill.py --runtime  # 校验安装副本形态（不要求项目文档）

退出码：0 = 全通过；1 = 有 ERROR；2 = 参数错误。
原则：**没有输出"通过"就是没通过**——不要靠"没看到报错"判断。

设计说明见 references/10-skill工程化.md。
"""

from __future__ import annotations

import hashlib
import re
import sys
from math import ceil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

# ── 可配置常量 ───────────────────────────────────────────────────────────────
SKILL_NAME = "personal-ai-companion"

# 上下文预算（SKILL.md 是唯一永久加载的文件，必须封顶）。
#   · 行数上限 150 —— 直接采用上游值。
#   · **近似 token 上限 4500 —— 这才是真正的指标**（见下面的近似算法）。
#   · 字符数上限 6000 —— ★ **本地偏离，不是漏改**：
#     上游给的 5000 是**英文口径**（英文 1 token ≈ 4 字符）。中文正相反，**1 字 ≈ 1 token**，
#     所以同一段内容用中文写，"字符数"会天然是英文的 3–4 倍，而 token 数是一样的。
#     拿 5000 字符卡 54% 中文的文本 = 拿英文尺子量中文，会误伤。
#     本包实测：5239 字符里 CJK 占 2851 → 若按"CJK 计 1、非 CJK 每 4 字符计 1"折算
#     ≈ 3448 tokens，**远低于 4500 的 token 上限**。
#     **token 上限才是约束，字符上限只用来抓"某一段突然暴涨"这类异常。**
SKILL_MAX_LINES = 150
SKILL_MAX_CHARACTERS = 6_000
SKILL_MAX_APPROX_TOKENS = 4_500

# frontmatter 允许的键。上游默认只有 name + description；
# 本包是刻意加 license 的（v1.5 决定：目标是分享，不给许可 = 别人不能合法用）。
# 这是**本地约定**，不是漏改——见 references/10-skill工程化.md 第八节。
ALLOWED_FRONTMATTER_KEYS = ("name", "description", "license")

# 运行时白名单：只有这些会被装进使用者的包
RUNTIME_ROOTS = ("SKILL.md", "agents", "references", "scripts", "templates")
# 运行时目录里绝不许可出现的东西
FORBIDDEN_PARTS = {"research", "documentation", ".git", "__pycache__", "_audit_scratch"}

# 开发仓库必需的文件（--runtime 时跳过项目文档类）
REQUIRED_PROJECT = ("README.md", "LICENSE", "CHANGELOG.md", "VERIFICATION.md")
REQUIRED_RUNTIME = ("SKILL.md",)
REQUIRED_REFERENCES = (
    # ★ v2.1.2 补：`0-快速开始.md` 原来**漏在这张清单里**。
    #   后果实测过：SKILL.md 的必读路由指向它（REQUIRED_ROUTES 也查它），
    #   但"清单完整性"不查它 —— **把它删掉，exit code 仍是 0**。
    #   这正是本文件自己警告过的病：**"文件之间的一致性，机器不查就一定漂"**。
    "0-快速开始.md",
    "1-采集与访谈.md", "2-人格档案.md", "3-常驻载体与个性化.md",
    "4-感知与陪伴闭环.md", "5-工程化与护屏.md", "6-验证纪律.md",
    "7-发布与脱敏.md", "8-状态面板与游戏化.md", "9-对外表达.md",
    "10-skill工程化.md",
)
REQUIRED_TEMPLATES = (
    "素材清单.md", "访谈提纲.md", "自我剖析模板.md",
    "人格档案模板.md", "人设内容包模板.md",
)

# ★ 回归哨兵：这些行为边界**删掉就会出事**，而且不容易被发现。
# ⚠️ 哨兵要挂在**它真正生效的那个文件**上——`SKILL.md` 只放常驻级铁律；
# 阶段内才生效的规则挂到对应 references（这才是"门禁"该守的位置）。
REGRESSION_MARKERS = (
    # ── SKILL.md 常驻铁律 ──────────────────────────────────────────────
    "绝不编造",                      # 铁律一
    "人格只能由本人提供",             # 铁律一
    "降级段落",                      # 没采集到也不许编、不许留空
    "零留空",
    "验证优先于声称",                 # 铁律四
    "一次只推进一个阶段",             # 铁律三
    "不要推荐默认形象",               # v1.7：阶段 0 去默认形象
    # ⚠️ 2026-09-27：**两条旧哨兵被显式替换**（不是偷偷放宽）——
    #    `清单勾选` / `清单外` 守的是 v1.7 的设计（"先发清单让他勾"）。
    #    一位真人推翻了这个设计：「为什么要问别人有没有这些东西呢」
    #    → 采集改成"先访谈、需要什么再问什么"，清单降级为采集者的检查表。
    #    **旧哨兵在新设计下是错的**，所以换成守新边界的这两条。
    #    ⚠️ 换哨兵是敏感动作：必须写明"为什么旧的作废"，否则等于一点点掏空门禁。
    "不做预先盘问",                   # v2.1：采集入口的新边界
    "别拿去问人",                     # v2.1：清单降级为检查表
)

# 分文件哨兵：这些规则**不该常驻在 SKILL.md**（白占上下文），
# 但同样不许在各自的参考文件里被误删。
PER_FILE_MARKERS: dict[str, tuple[str, ...]] = {
    "references/1-采集与访谈.md": (
        "冲突本身就是最有价值的发现",   # 冲突不许抹平
    ),
    "references/0-快速开始.md": (
        "本人确认",                    # 落盘必须带确认标记
    ),
    "references/10-skill工程化.md": (
        "回归哨兵",                    # 教别人也这么做
        "运行白名单",
        "--runtime",
    ),
}

# 必检的渐进式披露路由：SKILL.md 必须能找到这些关键文件。
# ⚠️ 按 **basename** 匹配，不按全路径——列表里写简称（`10-skill工程化`）
# 和写全路径（`references/10-skill工程化.md`）是同一件事，不该因写法判 fail。
REQUIRED_ROUTES = (
    "0-快速开始",
    "1-采集与访谈",
    "6-验证纪律",
    "10-skill工程化",
    "素材清单",
)


def err(msg: str) -> None:
    ERRORS.append(msg)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def approximate_token_count(content: str) -> int:
    """保守估计中英混排的 token 数（中文不能按字符折算，会低估）。

    注意：官方建议用 count_tokens 接口精确计算；这里零依赖，只求保守。
    """
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", content))
    latin = len(re.findall(r"[A-Za-z0-9_]+", content))
    other = len(re.findall(r"[^\sA-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", content))
    return cjk + ceil(latin * 1.3) + ceil(other / 4)


# ── 1. frontmatter ───────────────────────────────────────────────────────────
def validate_frontmatter() -> None:
    skill = ROOT / "SKILL.md"
    if not skill.is_file():
        err("missing SKILL.md")
        return
    raw = skill.read_bytes()
    # ★ BOM 检查：PS 的 Set-Content/Out-File 默认会给 UTF-8 文件加 BOM。
    #   BOM 会把 frontmatter 开头的 `---` 变成 `\ufeff---`，导致**所有**严格解析
    #   frontmatter 的工具报"边界无效"——而报错信息不会告诉你是 BOM 干的。
    #   本项目的坑清单里早有同类记录（数据文件带 BOM → JSON.parse 抛错），这里补上机器检查。
    if raw.startswith(b"\xef\xbb\xbf"):
        err("SKILL.md starts with a UTF-8 BOM — frontmatter parsers will fail; "
            "rewrite the file without BOM (e.g. [IO.File]::WriteAllText with UTF8Encoding($false))")
    content = raw.decode("utf-8-sig")  # 容错解码，好让下面的检查继续报更有用的信息
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", content, re.DOTALL)
    if not match:
        err("SKILL.md has invalid YAML frontmatter boundaries "
            "(expected the file to start with '---' on its own line, "
            "then keys, then a closing '---')")
        return
    frontmatter = match.group(1)
    keys = re.findall(r"^([A-Za-z0-9_-]+):", frontmatter, re.MULTILINE)
    unexpected = [k for k in keys if k not in ALLOWED_FRONTMATTER_KEYS]
    if unexpected:
        err(f"SKILL.md frontmatter has unexpected keys {unexpected}; "
            f"allowed = {list(ALLOWED_FRONTMATTER_KEYS)}")
    name_match = re.search(r"^name:\s*([^\n]+)$", frontmatter, re.MULTILINE)
    desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    name = name_match.group(1).strip() if name_match else ""
    desc = desc_match.group(1).strip() if desc_match else ""
    if name != SKILL_NAME or not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        err(f"invalid skill name: {name!r} (must equal '{SKILL_NAME}')")
    if not desc:
        err("description is empty")
    if len(desc) > 1024:
        err(f"description too long: {len(desc)} > 1024")
    if "<" in desc or ">" in desc:
        err("description must not contain angle brackets")
    if "\n" in desc:
        err("description must be a single physical line")


# ── 2. 上下文预算 ────────────────────────────────────────────────────────────
def validate_budget() -> None:
    skill = ROOT / "SKILL.md"
    if not skill.is_file():
        return
    content = read(skill)
    lines = len(content.splitlines())
    chars = len(content)
    tokens = approximate_token_count(content)
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", content))
    cjk_pct = round(100 * cjk / chars, 1) if chars else 0.0
    if lines > SKILL_MAX_LINES:
        err(f"SKILL.md exceeds {SKILL_MAX_LINES} lines: {lines}")
    if chars > SKILL_MAX_CHARACTERS:
        err(f"SKILL.md exceeds {SKILL_MAX_CHARACTERS} characters: {chars}")
    if tokens > SKILL_MAX_APPROX_TOKENS:
        err(f"SKILL.md exceeds approx token budget {SKILL_MAX_APPROX_TOKENS}: {tokens}")
    # 把 CJK 占比一起打出来：字符数这个指标只有结合它才读得懂（见常量处的说明）
    print(f"  SKILL.md: {lines} 行 / {chars} 字符（CJK {cjk_pct}%）/ ~{tokens} tokens")


# ── 3. 清单完整性 ────────────────────────────────────────────────────────────
def validate_inventory(runtime_only: bool) -> None:
    for name in REQUIRED_RUNTIME:
        if not (ROOT / name).is_file():
            err(f"missing required runtime file: {name}")
    if not runtime_only:
        for name in REQUIRED_PROJECT:
            if not (ROOT / name).is_file():
                err(f"missing required project file: {name}")
    for name in REQUIRED_REFERENCES:
        if not (ROOT / "references" / name).is_file():
            err(f"missing required reference: references/{name}")
    for name in REQUIRED_TEMPLATES:
        if not (ROOT / "templates" / name).is_file():
            err(f"missing required template: templates/{name}")
    # agents/openai.yaml 是可选增强；有则必须含 $SKILL_NAME
    agent = ROOT / "agents" / "openai.yaml"
    if agent.is_file() and f"${SKILL_NAME}" not in read(agent):
        err(f"agents/openai.yaml default_prompt must mention ${SKILL_NAME}")


# ── 4. ★ 回归哨兵 + 渐进式披露路由 ───────────────────────────────────────────
def validate_routes_and_regressions() -> None:
    skill = ROOT / "SKILL.md"
    if not skill.is_file():
        return
    content = read(skill)
    for marker in REGRESSION_MARKERS:
        if marker not in content:
            err(f"SKILL.md missing required behavior boundary (regression marker): {marker!r}")
    for route in REQUIRED_ROUTES:
        if route not in content:
            err(f"SKILL.md missing required progressive-disclosure route: {route}")
    # 分文件哨兵：挂在各自生效的参考文件上
    for rel, markers in PER_FILE_MARKERS.items():
        target = ROOT / rel
        if not target.is_file():
            err(f"missing file for per-file markers: {rel}")
            continue
        text = read(target)
        for marker in markers:
            if marker not in text:
                err(f"{rel} missing required behavior boundary (regression marker): {marker!r}")

# ── 5. 运行边界 ──────────────────────────────────────────────────────────────
def validate_runtime_boundaries() -> None:
    for root_name in RUNTIME_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            rel = path.relative_to(ROOT)
            if FORBIDDEN_PARTS.intersection(rel.parts):
                err(f"non-runtime content nested inside runtime allowlist: {rel}")
            if path.is_file() and path.suffix in {".pyc", ".pyo"}:
                err(f"compiled artifact found in runtime content: {rel}")


# ── 6. ★ 本地 markdown 链接必须能解析 ────────────────────────────────────────
# ⚠️ 只检查**看起来是路径**的目标。
# 文档里常出现 `[文字](路径)` 这种**举例用的占位写法**（不是在写链接），
# 以及 `[vault] D:\...` 这类**标记前缀**——它们都不含路径分隔符，不该当链接查。
# 误报会让整个门禁失去可信度，所以宁可少查一点。
LINK_LOOKS_LIKE_PATH = re.compile(r"[\\/]|\.(?:md|py|js|json|ya?ml|html|txt|png|jpg)$")


def validate_markdown_links() -> None:
    link_pattern = re.compile(r"\]\(([^)]+)\)")
    for markdown in ROOT.rglob("*.md"):
        if ".git" in markdown.parts:
            continue
        text = read(markdown)
        for raw in link_pattern.findall(text):
            target = raw.strip().split("#", 1)[0]
            if not target or re.match(r"^(?:https?://|mailto:)", target):
                continue
            if not LINK_LOOKS_LIKE_PATH.search(target):
                continue  # 举例占位，不是真链接
            if not (markdown.parent / target).resolve().exists():
                err(f"broken local link in {markdown.relative_to(ROOT)}: {raw}")


# ── 7. 占位符残留 ────────────────────────────────────────────────────────────
# 只查**运行时内容**：项目文档（CHANGELOG/VERIFICATION/10-工程化）里
# 本来就会**引用**占位符来讲解它，那是内容不是残留。
PLACEHOLDER_SCAN_ROOTS = ("SKILL.md", "agents", "references", "templates", "scripts")
# 允许出现占位符字样的文件（它们的工作就是讲解占位符）
PLACEHOLDER_EXEMPT = {"10-skill工程化.md", "validate_skill.py"}


def validate_placeholders() -> None:
    for root_name in PLACEHOLDER_SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            if path.name in PLACEHOLDER_EXEMPT:
                continue
            if path.suffix.lower() not in {".md", ".yaml", ".yml", ".py", ".js"}:
                continue
            text = read(path)
            if "[" + "TODO" in text:
                err(f"template placeholder not filled in {path.relative_to(ROOT)}")


# ── 8. 内容自洽（2026-09-27 加）────────────────────────────────────────────────
# ★ 为什么需要这一节：上面前七节里，**只有"链接"和"BOM"能挡住改包时的连带错误**。
#   2026-09-27 一天之内，清单从 18 类长到 21 类，下列错误**每次都是人肉发现的**：
#     · 类数写在 5 处（本文件头 + E组 + references/1 两处 + SKILL.md），漏改一处不报错
#     · 我插新类时编成 21 号却排在 16 号前面 —— 顺序成了 15, 21, 16…
#       （**这是本项目第三次犯"编号与顺序不符"**，所以这次把它变成机器检查）
#     · 工作区里同时躺着 18 类 / 20 类的旧副本，各自演化
#   前四轮验收的规律是「**补文档型能修好、机制型全漏**」——这一节就是那类机制。
CHECKLIST_REL = Path("templates") / "素材清单.md"
CLASS_RE = re.compile(r"^###\s+(\d+)\.\s*(.+)$")
GROUP_RE = re.compile(r"^##\s*([A-Z0-9]+)\s*组\b")
# 头部声明，例：「把下面 **21 类、分 6 组**」
DECLARED_RE = re.compile(r"\*\*(\d+)\s*类[、,]\s*分\s*(\d+)\s*组\*\*")
# 冻结副本：文件名里带版本号的**故意**保留旧类数，不算过期
FROZEN_COPY_RE = re.compile(r"-v\d+(?:\.\d+)*\.md$")
# `类` 后面跟这些词，说明这句话在**声明清单规模**（而不是在举例/分组/指代）
TOTAL_TAIL_WORDS = ("清单", "勾选", "候选", "大类", "类型")
COPY_SEARCH_PARENTS = (
    Path(r"D:\harness\projects"),
    Path(r"D:\harness\goutoujunshi"),
)


def _collect_classes(text: str) -> tuple[list[int], dict[str, list[int]], str]:
    """按出现顺序取类号，并记录每类归属的组。"""
    order: list[int] = []
    per_group: dict[str, list[int]] = {}
    current = ""
    for line in text.splitlines():
        group = GROUP_RE.match(line)
        if group:
            current = group.group(1)
            per_group.setdefault(current, [])
            continue
        cls = CLASS_RE.match(line)
        if cls:
            num = int(cls.group(1))
            order.append(num)
            if current:
                per_group[current].append(num)
    declared = DECLARED_RE.search(text)
    declared_text = declared.group(0) if declared else ""
    return order, per_group, declared_text


def validate_content_consistency(runtime_only: bool) -> None:
    path = ROOT / CHECKLIST_REL
    if not path.is_file():
        err(f"missing checklist: {CHECKLIST_REL.as_posix()}")
        return
    text = read(path)
    order, per_group, declared_text = _collect_classes(text)

    if not order:
        err(f"{CHECKLIST_REL.as_posix()}: found no '### N.' class headings")
        return

    # ① 类号严格 1..N、无重无缺（顺序也要对，不只是集合对）
    expected = list(range(1, len(order) + 1))
    if order != expected:
        err(f"{CHECKLIST_REL.as_posix()}: class numbering is not strictly 1..{len(order)} "
            f"in document order (got {order})")

    # ② 头部声明的类数要与实际相符
    if declared_text:
        declared_n = int(DECLARED_RE.search(text).group(1))
        if declared_n != len(order):
            err(f"{CHECKLIST_REL.as_posix()}: header declares {declared_n} 类 "
                f"but there are {len(order)} '### N.' headings")
    else:
        err(f"{CHECKLIST_REL.as_posix()}: header must declare '**N 类、分 M 组**' "
            f"(so the count is machine-checkable)")

    # ③ 各组声明的类数要与实际相符（例：C2 组 4 类）
    declared_groups = re.findall(r"\*\*([A-Z0-9]+)\s*组\s*(\d+)\s*类\*\*", text)
    if declared_groups:
        for gname, gcount in declared_groups:
            actual = len(per_group.get(gname, []))
            if actual != int(gcount):
                err(f"{CHECKLIST_REL.as_posix()}: group {gname} declares {gcount} 类 "
                    f"but has {actual}")

    # ④ 其它文件里声明的类数必须与权威源一致（防"改了 A 处没同步 B 处"）
    #
    # ★ 历史叙述里的旧类数是**合法的**（CHANGELOG 记的就是"从几类长到几类"），
    #   但**必须显式标记**，否则百年之后没人分得清"这个 15 是当时的现状还是漏改"。
    #   规则：讲到旧类数的行，行内要出现 `count-history:` 标记，
    #   或者整行带 `<!-- count-frozen -->`（用于历史表格整块冻结）。
    n = len(order)
    others = ("SKILL.md", "references/1-采集与访谈.md", "CHANGELOG.md", "VERIFICATION.md")
    # ⚠️ **匹配口径的边界要靠事实验定，不能靠感觉**。这一节试了三版：
    #    ① `\*\*(\d+)\s*类` —— 太窄：SKILL.md 改成"19 类勾选"时**没报错**。
    #    ② `(\d+)\s*类`    —— 太松：**72 个误报**，"3 类失败""6 类材料"里的
    #       "类"是**量词**（3 种失败），不是"清单类别"。
    #    ③ 现在这版 —— 自己按 `类` 切词，逐个回看数字，而不是用正则去猜。
    #       ⚠️ **正则解决不了这个问题**，试过三种都错：
    #         · `(\d+)\s*类(?=。|，|$)` 会从 "第 16 类" 里**匹配到 "6 类"**
    #           （引擎从 6 起步，回看只看到 "1"，前面并没有"第"）
    #         · Python 不支持**变长**后顾，`(?<!第\s)` 直接抛错
    #         · 把 `、` 当断言又会误报 "A 组 2 类、B 组 7 类"
    #       → **手工回看**才能同时判对："第 N 类" 是指代（跳过）、
    #         "N 类。" 才是断言（检查）、"A 组 N 类、" 是分组计数（跳过）。
    #    教训：门禁宁可少查也不能误报（skill 自己的话），
    #    但也**不能宽到放过真错**——两个方向都要拿实例试。
    def _asserted_counts(line: str) -> list[str]:
        """取出这一行里"声称清单规模"的数字。

        ⚠️ **这一节试了四版，两个方向都翻过车，最后落在这个口径上**：
        | 版本 | 结果 |
        |---|---|
        | `\\*\\*(\\d+)\\s*类` | **漏报**：SKILL.md 改成"19 类勾选"它没反应（要求星号前缀） |
        | `(\\d+)\\s*类` | **误报 72 条**："3 类失败""6 类材料"里的"类"是**量词**，不是清单类别 |
        | 加"尾巴必须是。，或规模词" | **又漏报**："不要把 21 类逐条发给他"的尾巴是"逐条发给他"——而那**确实**在声称 21 类 |
        | **现在这版** | **只认"规模词紧跟在『类』后面"**：`N 类清单 / 勾选 / 候选 / 大类 / 类型`，或 `共 N 类` |

        **为什么这是对的**：只有"**类**"字后面**紧跟表示整体的词**时，它才在说"总共几类"。
        其余写法（"3 类失败""第 12 类""18 类、没有它"）都**不是规模声明**——
        它们要么是量词、要么是指代、要么是并列，**管了就是误报**。

        > ★ 代价要写清楚：**"不要把 21 类逐条发给他"这种写法现在不查了。**
        > 这是**明知**的取舍——门禁宁可少查也不能误报。
        > **本包的写法约定（2026-09-27 定，换写法请连带更新本节）**：
        > **声明清单规模时一律写 `N 类清单` 或 `N 类勾选`**——
        > `SKILL.md`、`references/1-采集与访谈.md`、`templates/素材清单.md` 已统一成这个写法，
        > 所以"清单从 21 类变成别的数"这件事**仍然会被抓住**。
        > 换成人话：**这个哨兵守的是"约定写法"，不是"自然语言"。**
        """
        out: list[str] = []
        for m in re.finditer("类", line):
            j = m.start() - 1
            while j >= 0 and line[j].isspace():
                j -= 1
            k = j
            while k >= 0 and line[k].isdigit():
                k -= 1
            if k == j:                      # "类"前面不是数字
                continue
            before = line[:k + 1].rstrip()
            if before.endswith("第"):        # "第 N 类" = 指代某一类，不是规模
                continue
            # 规模词必须**紧跟在"类"后面**（跳过空格与粗体星号）
            tail = line[m.end():]
            t = 0
            while t < len(tail) and tail[t] in " \t\u3000*":
                t += 1
            if not tail[t:].startswith(TOTAL_TAIL_WORDS):
                continue
            out.append(line[k + 1:j + 1])
        return out

    ASSERT_RE = re.compile(r"共\s*(\d+)\s*类")
    TIME_RE = re.compile(r"共\s*(\d+)\s*类")

    # 冻结标记：`<!-- count-frozen -->`，可带说明写成 `<!-- count-frozen: 原因 -->`。
    # ⚠️ 判据必须是"**整行就是**这个注释"，不能是"**包含**这个子串"——实测两个坑：
    #   ① 文档里**讲解**这个标记的那一行（用反引号包着它）会把开关**反向翻转**，
    #      于是后半篇被当成冻结区、哨兵静默失效；
    #   ② 开标记后面跟说明文字时，字面量匹配不到，整块冻结根本没生效。
    FROZEN_MARK_RE = re.compile(r"^<!--\s*count-frozen\s*(?::.*?)?-->$")

    def strip_frozen(text: str) -> str:
        """把 <!-- count-frozen --> … <!-- count-frozen --> 之间的历史块清空。

        历史块按行标记，但内容可能跨行，所以必须先整块清掉再逐行查——
        否则旧版本那段"当时的类数"会一直误报。
        ⚠️ **用空行占位、不删行**：删行会让报错里的行号整体偏移，
        而"行号指向别处"会让下一个读报错的人白跑一趟（本项目犯过）。
        """
        out, frozen = [], False
        for line in text.splitlines():
            if FROZEN_MARK_RE.match(line.strip()):
                frozen = not frozen
                out.append("")
                continue
            out.append("" if frozen else line)
        return "\n".join(out)

    def strip_quoted(text: str) -> str:
        """删掉**引文**：反引号包裹的代码/报错原文，以及中英文引号里的内容。

        为什么必须删：文档里要**讲解**踩过的坑，就必然要写出那些错的字样
        （`header declares 20 类`、"第 25 类"…）。那是**引文**，不是声明，
        机器不该拿它当现状——不删就会**拦下门禁自己的文档**（实测误报 6 条）。

        ⚠️ 两个坑都是实测踩出来的：
          ① 引号有三种写法（ASCII `"`、中文 `“”`、中文 `「」`），**只处理一种就会漏**。
             本项目文档里那几处用的正是 **ASCII `"`** —— 我一开始只按中文引号写，
             结果误报依旧，白绕了好几轮。
          ② **不许用 `str.lstrip()` / `str.strip()`**：Python 把中文引号 `"` 也当空白
             （U+201D 属于 Unicode 空白），会把 `"19 类勾选"` 剥成 `勾选"…`，
             哨兵随即把引文误判成声明。**只剥真正的空格与制表符。**
        三类引号数量为奇数说明切分不可靠，此时**退回原文本**、宁可多查。
        """
        if text.count("`") % 2 or text.count('"') % 2:
            return text
        text = re.sub(r"`[^`]*`", "", text)
        text = re.sub(r"\u201c[^\u201c\u201d]*\u201d", "", text)
        return re.sub(r'"[^"]*"', "", text)

    for rel in others:
        p = ROOT / rel
        if not p.is_file():
            continue
        for lineno, line in enumerate(strip_quoted(strip_frozen(read(p))).splitlines(), 1):
            if "count-history:" in line:
                continue
            for found in _asserted_counts(line) + TIME_RE.findall(line):
                if int(found) != n:
                    err(f"{rel}:{lineno}: asserts a {found}-class checklist "
                        f"but the checklist has {n}")

    # ★ 悬空引用要**扫全包**，而且要处理**列表指代**。
    #   实测两个坑（都真的漏过）：
    #     ① 只扫 others 名单里的四个文件 → 正文里的引用根本不在管辖范围
    #     ② `第 12、13、25 类` 这种**列表指代**：正则 `第\s*(\d+)\s*类`
    #        只认紧邻"第"的那个数字；逐个"类"回看数字又只拿到 `25`
    #        （`、` 不是数字，往回走一步就停在 `25`，而"第"在 `12` 前面）
    #   → 正确做法：**先切出"N、N、N…类"这一段**，再逐个数字判范围。
    MULTI_REF_RE = re.compile(r"第\s*((?:\d+\s*[、,，]\s*)*\d+)\s*类")
    DIGITS_RE = re.compile(r"\d+")
    for md in sorted(ROOT.rglob("*.md")):
        if ".git" in md.parts:
            continue
        rel = md.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(strip_quoted(strip_frozen(read(md))).splitlines(), 1):
            for run in MULTI_REF_RE.findall(line):
                for ref in DIGITS_RE.findall(run):
                    if int(ref) > n:
                        err(f"{rel}:{lineno}: references 第 {ref} 类 but the checklist "
                            f"only has {n} classes")

    # ⑤ 工作区里的**非冻结**同名副本必须与权威源逐字节一致
    if not runtime_only:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for parent in COPY_SEARCH_PARENTS:
            if not parent.is_dir():
                continue
            for copy in parent.rglob("素材清单*.md"):
                if FROZEN_COPY_RE.search(copy.name):
                    continue  # 文件名带版本号 = 故意冻结的旧版本
                try:
                    raw = copy.read_bytes()
                except OSError:
                    continue
                # 文件里显式声明"这是冻结副本"的也跳过——
                # 试验快照本来就该与权威源不同，但它必须**自己说清楚**。
                if b"FROZEN-CHECKLIST-COPY" in raw:
                    continue
                if hashlib.sha256(raw).hexdigest() != digest:
                    err(f"stale checklist copy (differs from templates/素材清单.md, "
                        f"and not marked FROZEN-CHECKLIST-COPY): {copy}")


# ★ 跨文件一致性哨兵：**"采集顺序"这条规则写在四处，必须一起改**。
#
# 为什么要这一条（v2.1.2，原因与证据都实测过）：
#   v2.1 把采集顺序整个翻了过来（"先发清单" → "先访谈，清单最后当检查表"），
#   并同步了 `SKILL.md` / `references/1-采集与访谈.md` / `templates/素材清单.md` 三处，
#   **唯独漏了 `README.md`**——它继续写着「素材清单（**先发这份**）」，
#   跟权威版**直接相反**，而**所有现有哨兵都没拦住**（它们只盯"类数"这类数字，不盯句子）。
#   故障注入实测：把 README 那句改回旧顺序，验证器**仍 exit 0**。
#   → 所以这里按 basename 查两件事：① 新顺序句还在；② 那句话周围不许再出现"先发"。
#   ⚠️ 这两条只管**这一句话**，不假装能覆盖所有口径漂移。
_COUNT_SENTINEL_MARKER = "order-sentinel"


def validate_cross_file_consistency(runtime_only: bool) -> None:
    """README 与权威版在"采集顺序"上必须说同一件事。"""
    if runtime_only:
        # 安装副本里没有 README（它不在 RUNTIME_ROOTS 里），这条只在开发仓库形态下有效。
        return
    readme = ROOT / "README.md"
    if not readme.is_file():
        err("missing README.md (cannot check the collection-order sentinel)")
        return
    lines = read(readme).splitlines()
    marked = [i for i, line in enumerate(lines) if _COUNT_SENTINEL_MARKER in line]
    if not marked:
        err(f"README.md lost its '{_COUNT_SENTINEL_MARKER}' marker — the collection-order "
            f"sentinel can no longer locate the sentence it guards")
        return
    line = lines[marked[0]]
    # ① 新顺序必须写在那一句里
    if "先访谈" not in line or "素材清单" not in line:
        err("README.md's collection order no longer says '先访谈 … 素材清单 最后当检查表' "
            "(v2.1 翻了顺序，README 必须跟着改)")
    # ② 那句里不许再出现把清单排在前的说法
    for stale in ("先发这份", "先发清单", "先发素材清单"):
        if stale in line:
            err(f"README.md puts the checklist first again ({stale!r}) — "
                f"the authoritative order is 先访谈 → 再建模 → 清单最后当检查表")


def main() -> int:
    unexpected = [a for a in sys.argv[1:] if a != "--runtime"]
    if unexpected:
        print(f"ERROR: unsupported arguments: {' '.join(unexpected)}")
        return 2
    runtime_only = "--runtime" in sys.argv[1:]

    print(f"validating {SKILL_NAME}"
          f"{' (runtime form)' if runtime_only else ''} ...")
    validate_frontmatter()
    validate_budget()
    validate_inventory(runtime_only)
    validate_routes_and_regressions()
    validate_runtime_boundaries()
    validate_markdown_links()
    validate_placeholders()
    validate_content_consistency(runtime_only)
    validate_cross_file_consistency(runtime_only)

    if ERRORS:
        for e in ERRORS:
            print(f"ERROR: {e}")
        print(f"\n{len(ERRORS)} error(s).")
        return 1
    print(f"{SKILL_NAME} validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
