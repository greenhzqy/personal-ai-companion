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
    "清单勾选",                      # v1.7：采集不许开放式问
    "清单外",                        # v1.7：防清单变成新天花板
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

    if ERRORS:
        for e in ERRORS:
            print(f"ERROR: {e}")
        print(f"\n{len(ERRORS)} error(s).")
        return 1
    print(f"{SKILL_NAME} validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
