# skill 工程化：把一个 skill 做成「能分发的包」

> **什么时候读这份**：你要把做好的东西**交给别人用**的时候。
> 不是"写完文档就完事"——**能分发 ≠ 文档写得好**，中间隔着一整套工程约束。
>
> 这份文件的立场：**可执行的检查 > 文档里的承诺**。
> 你说"包是完整的"没有意义，`validate_skill.py` 退出码是 0 才有意义。
>
> ★★ **权威源（v2.1.4 补，此前本文件没有指向它）**：
> **Agent Skills 开放规范** → `https://agentskills.io/specification`
> （含 frontmatter 六字段的定义与约束）；配套的
> **评测** `…/skill-creation/evaluating-skills`、
> **触发率优化** `…/skill-creation/optimizing-descriptions`、
> **最佳实践** `…/skill-creation/best-practices`；
> 官方参考验证器 `https://github.com/agentskills/agentskills/tree/main/skills-ref`。
> 宿主侧行为（字段被静默忽略、1536 字符截断、六个可分发字段）见
> `https://code.claude.com/docs/en/skills.md`。
>
> ⚠️ **本文件此前只引用"上游值"而不给出处，导致两处口径写错**（行数 150 被当成上游值、
> 而上游是 500）。**凡是引用规范的地方，都要带链接**——否则下一个人无法核对。

---

## ★★ 第零条：加东西的门槛——**没被真实使用验证过的想法，不进这个包**

> 2026-09-27 由一位**真人**提出。他原话：
> 「**先不改这个，毕竟我自己都还没使用过，就不放在开源项目里面了。**」
>
> **为什么这条要放在最前面**：本 skill 的铁律四是「验证优先于声称」，
> 而这条是它的**另外一半**——**没验过的东西，也不要放到别人手上。**
>
> 一个想法听起来再对（"屏幕使用时间应该放进陪伴精灵"），
> 只要**提出者自己都还没用过**，它就还只是一个假设。
> **假设可以写进 `CHANGELOG`、可以记成 issue、可以标"候选"，
> 但不要写进别人会照着做的那段正文里。**

**加任何东西之前，先过这张表：**

| 我自己跑过吗 | 可以怎么处理 |
|---|---|
| **一次都没有** | 只能记成「**候选**」，**明确标出"未验证"**，不许混进正文 |
| **跑过 1 次** | 可以进，但**必须标「样本量 1」**，并写清"换个环境可能不同" |
| **跑过 ≥2 次且结果一致** | 才算「已验证」，可以正常写 |

> ★ 这条对**本 skill 自己**同样适用：`VERIFICATION.md` 里那张"未验证清单"就是它的执行结果——
> **它连自己没验过的地方都不肯藏。**

---

## 一、先分清三件常被混淆的事

| | 是什么 | 例子 |
|---|---|---|
| **行为内核** | 模型读的指令，决定它怎么做事 | `SKILL.md` |
| **运行时内容** | 使用者装包时**必须一起装**的 | `SKILL.md`、`references/`、`scripts/`、`agents/` |
| **项目文档** | 只给**维护者和贡献者**看的 | `documentation/`、`CONTRIBUTING`、原始研究素材 |

> **最容易犯的错：把项目文档塞进运行时目录。**
> 使用者装完发现包里躺着一堆"架构说明""原始调研"，**既占上下文又可能泄密**。
> **运行白名单必须是白名单，不是"除了这些别的都别放"的口头约定**（见第四节）。

---

## 二、包的标准结构

```
<skill-name>/
├── SKILL.md              ← 行为内核（唯一必需；frontmatter 只有 name + description）
├── README.md             ← 人类入口（这是什么 / 适不适合你 / 三步上手 / 已知限制）
├── CHANGELOG.md          ← 每个版本改了什么、为什么
├── VERIFICATION.md       ← 验过什么、怎么验的、**什么没验**
├── LICENSE               ← 不给许可 = 保留所有权利 = 别人法律上不能合法用
├── agents/
│   └── openai.yaml       ← 界面元数据（显示名 / 简介 / 默认提示词），跨平台用
├── references/           ← 按需加载的长文档
├── templates/            ← 填空模板（本工作区统一用 templates/，见第七节）
├── scripts/              ← 可直接跑的骨架 + **验证器**
└── documentation/        ← 只给维护者看（**不进运行时**）
```

### `agents/openai.yaml` —— 别漏了这个

```yaml
interface:
  display_name: "狗头军师"
  short_description: "安抚恋爱情绪，分析聊天与多人关系，并维护可撤销记忆"
  default_prompt: "使用 $goutoujunshi 帮我梳理情绪、分析当前关系，并给出下一步建议。"
```

**三行而已，但它决定了这个 skill 在别的宿主里长什么样。** 只写 `SKILL.md` 的包，
在支持 `agents/` 的平台上会显示成没有名字、没有简介的一坨。

> ⚠️ **`default_prompt` 里必须出现 `$<skill-name>`**，否则用户不知道怎么触发。
> 这条要写进验证器（见第五节）。

---

## 三、`SKILL.md` 的预算：常驻开销是有上限的

**唯一被永久加载的文件就是 `SKILL.md`**（description 甚至更早被加载）。
所以它有三个硬上限：

| 指标 | 上限 | 为什么 |
|---|---|---|
| **行数** | 150 | 正文越长，每次触发的成本越高 |
| **字符数** | 5000（**英文口径**） | 中文按此卡会误伤，见下 |
| **近似 tokens** | 4500 | 中文不能按字符数折算，要**单独算** |

> ⚠️ **本工作区的一处刻意偏离（别当成 bug 修掉）**：
> 上游给的 5000 字符是**英文口径**（英文 1 token ≈ 4 字符），而中文 1 字 ≈ 1 token，
> 同一段内容用中文写，字符数天然是英文的 3–4 倍、token 数却一样。
> 所以**本包的验证器把字符上限放到 6000，但 token 上限仍是 4500**——
> **token 才是真约束，字符数只用来抓"某一段突然暴涨"**。
> （对照：`goutoujunshi` 那份参考实现照上游写 5000 字符，所以两包的验证器在这条上不一致。）

**中文的近似 token 算法**（不能直接用字符数，会低估）：

```python
def approximate_token_count(content: str) -> int:
    """保守估计中英混排的 token 数，不依赖第三方库。"""
    cjk   = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", content))
    latin = len(re.findall(r"[A-Za-z0-9_]+", content))
    other = len(re.findall(r"[^\sA-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", content))
    return cjk + ceil(latin * 1.3) + ceil(other / 4)
```

> **超预算了怎么办**：**不是删内容，是搬家**——把细节移进 `references/`，
> `SKILL.md` 只留**路由**（"这个问题读哪份参考"）。
> 这正是**渐进式披露**：`SKILL.md` 负责指路，不负责讲完。

---

## 四、运行白名单：**白名单，不是黑名单**

**必须明确列出"装包时同步哪些目录"，并且让验证器检查运行时目录里没有混进别的东西。**

```python
RUNTIME_ROOTS = ("SKILL.md", "agents", "references", "scripts", "assets")
FORBIDDEN_PARTS = {"research", "documentation", ".git", "__pycache__"}
```

规则两条：

1. **只有白名单里的目录会被安装**（`documentation/` 默认不在内）；
2. **白名单目录内部也不许嵌非运行时内容** —— 否则有人把 `research/` 拖进 `references/`，
   它就悄悄进了发行包。

> **为什么这条值得单列**：它是**唯一一条"你不检查就一定会出错"的规则**——
> 目录结构会随手长，而发行包不会自己变干净。

---

## 五、验证器：**可执行的规范**（这一节是整份文件的核心）

**文档会过期、会漏读、会被跳过；验证器不会。** 把它当成交付的门。

### 它必须检查的七件事

| # | 检查 | 抓什么病 |
|---|---|---|
| 1 | **frontmatter**：键**恰好**是 `name` + `description`；name 匹配 `[a-z0-9-]{1,64}`；description 非空、≤1024 字符、不含尖括号 | 元数据漂移 |
| 2 | **上下文预算**：行数 / 字符数 / 近似 tokens 三项都不超 | 常驻开销膨胀 |
| 3 | **清单完整性**：必需文件逐个存在（含 `agents/openai.yaml`）；`default_prompt` 里有 `$<skill-name>` | 包不完整、没法触发 |
| 4 | ★ **回归哨兵**：一串**关键行为边界句**必须还在 | **"改了 A 处顺带删掉 B 处"** |
| 5 | ★ **markdown 本地链接必须能解析** | **悬空链接 / 改了文件名没改引用** |
| 6 | **运行边界**：运行时目录里没有 `research` / `documentation` / `.git` / `__pycache__` / `.pyc` | 非运行内容混进发行包 |
| 7 | **没有残留占位符**（`[TODO`） | 模板没填就发出去 |

### ★ 第 4 条「回归哨兵」是最值钱的一条

**它的原理**：把你**绝对不希望被改掉的行为边界**，作为字符串写进验证器。
只要有人（包括未来的你）在改 skill 时顺手删了其中一条，**验证器立刻报错**。

```python
REGRESSION_MARKERS = (
    "不从姓名、MBTI、旧案例或模型推测补事实",     # 反造假
    "首次明确同意后才启用",                        # 授权边界
    "不声称能直接读取、解密或导出",                 # 能力边界
    "明确表示不想发展、要求不要联系或反复表示不欢迎时停止推进",  # 停止条件
    # … 每条都是一条"删了就会出事"的规则
)
```

> **为什么它比"写文档提醒自己"强**：本 skill 的完整实例里，
> 有一类错误反复出现 **9 次**——**"改了 A 处的数字/名称，没同步引用它的 B/C/D 处"**。
> 靠人记是记不住的（第四次、第五次都还是照犯），**靠脚本才拦得住**。
>
> **哨兵怎么选**：不是选重要的句子，是选**"删掉之后行为会变坏、而且不容易被发现"**的句子。
> 一眼能看出重要的话不用当哨兵——**那些是给人看的，这些是给机器看的**。

### ★ 第 5 条是同一个病的另一张脸

`references/` 里改个文件名、或者换个目录，**引用它的那些文档不会自动跟着改**。
本 skill 的完整实例里真栽过：一份档案的两处副本分了叉，而多处引用还指着旧的那份，
**一次诊断直接跑偏、浪费一整轮**。

```python
def validate_markdown_links():
    link_pattern = re.compile(r"\]\(([^)]+)\)")
    for markdown in ROOT.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or re.match(r"^(?:https?://|mailto:)", target):
                continue
            if not (markdown.parent / target).resolve().exists():
                ERRORS.append(f"broken local link in {markdown.relative_to(ROOT)}: {raw_target}")
```

> **注意**：这是**标准 markdown 链接** `[文字](路径)`。
> 如果你的包用的是 `[[wiki 链接]]`，要**另写一条规则**——
> 而且要先弄清宿主怎么解析（**Obsidian 按 basename 解析、允许省略目录**，
> 所以"看着像断链"的其实能通；**别拿一个会误报的规则去当门**）。

### 骨架：一个通用验证器

```python
#!/usr/bin/env python3
"""校验一个可分发的 skill 包。用法：python validate_skill.py [--runtime]"""
from __future__ import annotations
import re, sys
from math import ceil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
SKILL_NAME = "<skill-name>"          # ← 改这里
SKILL_MAX_LINES, SKILL_MAX_CHARS, SKILL_MAX_TOKENS = 150, 5_000, 4_500
REQUIRED = ("SKILL.md", "README.md", "LICENSE", "CHANGELOG.md")
RUNTIME_ROOTS = ("SKILL.md", "agents", "references", "scripts", "templates")
FORBIDDEN_PARTS = {"research", "documentation", ".git", "__pycache__"}

def err(msg: str) -> None:
    ERRORS.append(msg)

def validate_frontmatter() -> None: ...
def validate_budget() -> None: ...
def validate_inventory(runtime_only: bool) -> None: ...
def validate_regressions() -> None: ...      # ← 回归哨兵
def validate_runtime_boundaries() -> None: ...
def validate_links() -> None: ...
def validate_placeholders() -> None: ...

def main() -> int:
    runtime_only = "--runtime" in sys.argv[1:]
    for check in (validate_frontmatter, validate_budget,
                  lambda: validate_inventory(runtime_only),
                  validate_regressions, validate_runtime_boundaries,
                  validate_links, validate_placeholders):
        check()
    for e in ERRORS:
        print(f"ERROR: {e}")
    if ERRORS:
        return 1
    print(f"{SKILL_NAME} validation passed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

> **`--runtime` 这个开关值得抄**：安装副本里没有 `documentation/`，
> 所以校验时要能跳过"项目文档必须存在"那几条。
> **同一份验证器要能在两种形态下都跑得通**——否则使用者一装包就报错。

**完整可跑的参考实现**：`D:\harness\goutoujunshi\scripts\validate_skill.py`（245 行，零依赖）。

---

## 六、接进 CI：让门自己关

`.github/workflows/validate.yml` —— 每次改动自动跑验证器。

```yaml
name: validate
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.x" }
      - run: python3 scripts/validate_skill.py
      - run: python3 scripts/validate_skill.py --runtime
```

> **为什么两行都要跑**：第一次验**开发仓库**（要求 `documentation/` 在），
> 第二次验**安装副本形态**（不要求）。**两种形态都过，包才是真的能发。**

---

## 七、许可与社区文件：**不给许可就是不许用**

| 文件 | 作用 | 不写的后果 |
|---|---|---|
| `LICENSE` | 授权 | **未选许可 = 保留所有权利 = 别人法律上不能合法用** |
| `LICENSE.zh-CN.md` | 中文对照 | 给中文使用者降低理解成本 |
| `CONTRIBUTING.md` | 别人怎么贡献 | 收到 PR 但没规矩 |
| `CODE_OF_CONDUCT.md` | 行为准则 | 社区冲突没有依据 |
| `SECURITY.md` | 安全问题怎么报 | 有人发现漏洞不知道找谁 |
| `.github/ISSUE_TEMPLATE/` | issue 模板 | 收到一堆信息不全的 issue |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 模板 | 同上 |
| `README_EN.md` | 英文入口 | 非中文使用者直接劝退 |

> **最常被跳过、后果最严重的是 `LICENSE`。**
> 本 skill 的完整实例真踩过：写 `license: 待本人选定` 挂了很久——
> **它看起来只是"还没定"，实际效果是"谁都不能用"。**

---

## 八、本工作区的两处刻意约定（照做，别对齐上游）

| 约定 | 上游规范怎么说 | 本工作区为什么这么定 |
|---|---|---|
| 用 `templates/` 而非 `assets/` | 规范的 `assets/` 包含 "templates" | **本工作区其他 skill（`bzd-*`、`resume-skill`）统一用 `templates/`**，跨 skill 一致性优先于对齐上游命名 |
| `references/` 之间允许互相引用 | "Link references one level deep only" | 那些交叉引用是**指路**（"见发布那一节"），不是必读链；`SKILL.md` 对每份 reference 都是**直接一层** |

> **写下来是为了让偏离变成本人拍板的决定，而不是漏改。**
> 偏离规范是可以的——**但必须附理由**，否则下一个人会当成 bug 修掉。

---

## 九、验收清单（发出去之前逐条过）

- [ ] `python3 scripts/validate_skill.py` 退出码 **0**（不是"没看到报错"）
- [ ] `python3 scripts/validate_skill.py --runtime` 也退出码 **0**
- [ ] `LICENSE` 已选定（不是 `待选定`）
- [ ] `agents/openai.yaml` 里 `default_prompt` 含 `$<skill-name>`
- [ ] `VERIFICATION.md` 写清了**什么没验**（只写验过的等于误导）
- [ ] `references/` 里没有原始调研素材、没有 `.git`、没有 `.pyc`
- [ ] 所有本地 markdown 链接能解析
- [ ] 全局搜 `[TODO` 无残留
- [ ] 回归哨兵覆盖了**所有"删了会出事"**的行为边界

> **最后一条最重要**：这份清单里**只有第一条是不可协商的**。
> 其余每一条，验证器都会替你检查——**这就是为什么要把规范做成可执行的**。
