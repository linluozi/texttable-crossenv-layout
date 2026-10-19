# texttable 跨环境宽度修复

上游：`texttable` 1.7.2（MIT，https://github.com/foutaise/texttable）
改动文件：`texttable.py`（唯一被修改的源文件）+ 新增 `test_crossenv.py`
许可证：`LICENSE` 与上游逐字节一致，未做任何修改。

配图见 `docs/assets/`，图中每个数字都来自 `figs-data.json`（两棵源码树实跑的结果）。

---

## 1. 问题：同一份输入，换个环境就画出不同的表

`texttable` 有两个**可选依赖**，装与不装会走完全不同的代码路径：

| 可选依赖 | 作用 | 未安装时 |
|---|---|---|
| `wcwidth` | 判断字符占几列 | 用 `unicodedata.east_asian_width` 自己估 |
| `cjkwrap` | 中文换行 | 退回标准库 `textwrap` |

两者都**没有写进 `setup.py` 的 `install_requires`**，所以「装了没装」纯看用户环境。问题就出在这里：两条回退路径的计量口径与官方实现不一致，于是**同样的输入、同样的代码，在不同机器上渲染出宽度不同的表格**。

最直接的例子（同一份字节完全相同的文件，只是读取方式不同）：

```
# 上游 1.7.2，Python 3.12，未装 wcwidth
windows(CRLF)    边框 13 列
posix(normalized) 边框 12 列
binary+decode     边框 13 列
```

Windows 上 `open(path, newline='')` 会保留行尾 `\r`，POSIX 习惯的默认读取不会。`\r` 进了单元格，被算成「一列宽」，但 `textwrap` 随后又把它当空白吃掉，于是**边框比内容宽一列**。

### 三个独立缺陷

| # | 缺陷 | 触发条件 | 后果 |
|---|---|---|---|
| D1 | `Cc` / `Cf` / `Zl` / `Zp` 被判为 1 列 | 未装 `wcwidth` | 零宽字符（`\r`、BOM、ZWJ、ZWSP）撑宽列 |
| D2 | 组合标记晚于 `east_asian_width` 判定 | 未装 `wcwidth` | U+3099、U+302A 这类「既宽又组合」的字符被判 2 列 |
| D3 | 换行按**字符数**、测量按**显示列** | 未装 `cjkwrap` | 宽字符行溢出自己的边框 |

D3 最直观：

```
+--------+          ← 边框按 6 列画
|   h    |
+========+
| 中文字 |          ← 内容实际 12 列
+--------+
```

---

## 2. 修复

全部改动都在 `texttable.py`，共 4 处：

### 2.1 零宽判定（D1 + D2）

顺序改为「组合标记 → 宽字符 → 类别」：

```python
category = unicodedata.category(c)
if unicodedata.combining(c) or category in ('Mn', 'Me', 'Mc'):
    return 0                        # 组合标记永远不占列
if unicodedata.east_asian_width(c) in 'WF':
    return 2
if category == 'Cf':
    return 1 if ord(c) in _CF_NOT_ZERO_WIDTH else 0
if category in ('Cc', 'Zl', 'Zp'):
    return 0
if category == 'Lo' and _in_zero_width_range(c):   # Hangul 中声/终声
    return 0
return 1
```

`_CF_NOT_ZERO_WIDTH` 是 14 个**各版 wcwidth 互相矛盾**的码位（`U+00AD` SOFT HYPHEN 等）：0.2.x 说 0 列，0.8/0.9 说 1 列。这种码位无论选哪边都会和另一版不符，所以显式排除、保持原状，不去制造新的不一致。

`_ZERO_WIDTH_RANGES` 覆盖 Hangul 中声/终声（`U+1160–U+11FF`、`U+D7B0–U+D7FF`）：它们类别是 `Lo`（按定义该占 1 列），但实际与前置初声合成一个字，不占独立列。

### 2.2 按列换行（D3）

新增 `_ColumnWrapper(textwrap.TextWrapper)`，只覆写两个比较长度的位置（`_handle_long_word` / `_wrap_chunks`），分块与空白处理完全沿用 `textwrap` 原实现。

关键取舍：**纯窄字符仍走原生 `textwrap`**。

```python
def textwrapper(txt, width):
    if _is_narrow_only(txt):
        return textwrap.wrap(txt, width)
    return _ColumnWrapper(width=width).wrap(txt)
```

这样「从不使用宽字符」的调用方输出**逐字节不变**（已用 19 个 ASCII 用例 × 3 个 Python 版本验证）。

### 2.3 放不下就报错

列宽 1 装不下单个双宽汉字时，上游会静默输出错位表格。改为抛 `ValueError`，与 `cjkwrap` 的行为一致（它的消息是 `invalid width 1 (must be > 1 when CJK chars)`）。

---

## 3. 验证

### 3.1 复现脚本

```bash
python reproduce.py                        # 对交付目录：10/10 通过
python reproduce.py --root <未打补丁副本>   # 对上游：2/10 通过
```

### 3.2 验收矩阵（24 个组合，全部通过）

3 个 Python × 4 种 wcwidth 状态（内置 / 0.2.13 / 0.9.2 / 缺失）× 2 种 cjkwrap 状态：

| Python | wcwidth | 无 cjkwrap | 有 cjkwrap |
|---|---|---|---|
| 3.12.10 | builtin | 70 passed | 66 passed, 3 xfailed |
| 3.12.10 | 0.2.13 | 70 passed | 66 passed, 3 xfailed |
| 3.12.10 | 0.9.2 | 70 passed | 66 passed, 3 xfailed |
| 3.12.10 | absent | 70 passed | 66 passed, 3 xfailed |
| 3.13.14 | 同上 × 4 | 70 passed | 66 passed, 3 xfailed |
| 3.14.5 | 同上 × 4 | 70 passed | 66 passed, 3 xfailed |

`70 = 27 个上游测试 + 43 个新增测试`。完整输出见 `evidence/accept_matrix.txt`。

### 3.3 跨环境一致性

同一批 38 个用例，在 6 个环境下逐一比对输出：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 跨环境输出分歧的用例 | 17 | 6 |
| 渲染出不自洽表格（环境×用例） | 40 | 16 |

残余的 6 个全部**不是 texttable 能修的**，逐条实测确认：

| 用例 | 变体差异 | 根因 |
|---|---|---|
| `drift_2630` | 边框 11 vs 12 | Unicode 15.1 起把 U+2630 判为 `W`，15.0 判 `N` |
| `drift_2FFC` | 11 vs 12 | U+2FFC 在 15.1 从 `N` 变 `W` |
| `drift_31E4` | 11 vs 12 | U+31E4 在 16.0 从 `N` 变 `W` |
| `drift_31EF` | 11 vs 12 | U+31EF 在 15.1 从 `N` 变 `W` |
| `drift_4DC0` | 11 vs 12 | U+4DC0 在 16.0 从 `N` 变 `W` |
| `zero_soft_hyphen` | 10 vs 11 | wcwidth 0.2.13 判 SHY 为 0 列，0.8/0.9 判 1 列 |

前五个是 **Unicode 数据库本身改了数据**：15.0→15.1 共 5 个码位、15.1→16.0 共 198 个码位从 `N` 变 `W`。任何按 `unicodedata` 测量宽度的库都会跟着变，与实现无关——除非把表硬编码进去，那又会和未来版本脱节。

第六个是 **wcwidth 依赖自身各版本矛盾**，已在 `_CF_NOT_ZERO_WIDTH` 里显式排除，不去制造新的不一致。

### 3.4 变异测试（证明测试有区分力）

在修复版上逐个植入退化，看新增测试能否抓住：

| 变异 | 无 wcwidth | 有 wcwidth |
|---|---|---|
| M1 去掉 `Cc/Zl/Zp` 零宽判定 | 抓到 (5 红) | 存活（该分支不执行） |
| M2 去掉 `Cf` 零宽判定 | 抓到 (6 红) | 存活（同上） |
| M3 组合标记判定移到 `eaw` 之后 | 抓到 (4 红) | 存活（同上） |
| M4 去掉 Hangul 零宽区间 | 抓到 (4 红) | 存活（同上） |
| M5 换行器退回纯 `textwrap` | 抓到 (11 红) | 抓到 (11 红) |
| M6 切分按字符数而非列数 | 抓到 (11 红) | 抓到 (11 红) |
| M7 列宽不足时静默塞入 | 抓到 (1 红) | 抓到 (1 红) |
| W1 `wcwidth` 分支改成计 1 列 | — | 抓到 (33 红) |
| W2 `wcwidth` 分支去掉 `max(0, ...)` | — | 抓到 (3 红) |

**两个维度都要跑**：M1–M4 只在无 wcwidth 时执行，只在有 wcwidth 的环境跑会得出「全部存活」的错误结论。

### 3.5 与 wcwidth 的逐码位对齐

已分配字符（289,159 个）上，修复后的 fallback 与 wcwidth **100.000000% 一致**。
未分配码位（`Cn`，8 个）仍有差异——它们在两版 wcwidth 之间就已互不一致，无法对齐。

### 3.6 无回归

- 上游 27 个测试：3 个版本全过。
- 19 个 ASCII 用例：3 个版本输出**逐字节相同**。
- `flake8` 在 `texttable.py` 上的告警数：上游 28 → 修复后 27（没有新增）。
- `ruff check test_crossenv.py`：All checks passed。

---

## 4. 已知边界（不修，如实记录）

1. **`cjkwrap` 自己的零宽缺陷**：`cjkwrap.cjklen("a\u3099")` 返回 3，实际应为 1（它只看 `east_asian_width`，不看组合标记）。装了 cjkwrap 时，含 U+3099 的表格仍会错位。这是第三方库的问题，`texttable` 无法修复；对应 3 个测试已标 `xfail` 并写明原因。
2. **Unicode 版本漂移**：见 3.3，属数据源变化。
3. **soft hyphen 等 14 个 `Cf` 码位**：各版 wcwidth 互相矛盾，显式排除。
4. **列宽 1 装双宽字符**：物理上不可能，改为抛 `ValueError`（与 cjkwrap 一致）。
5. **CJK 换行风格**：装了 cjkwrap 时仍由它决定换行点；本修复只保证**不溢出**，不改变既有换行风格。

---

## 5. 文件清单

```
texttable.py            修复后的源码（唯一修改的源文件）
test_crossenv.py        43 个新增测试
tests.py                上游原测试（未改）
texttable-xplat.patch   对 1.7.2 的标准补丁（patch --binary -p1 可用）
reproduce.py            独立复现/验证脚本
figs-data.json          配图数据源（两棵树实测结果）
LICENSE                 上游 MIT，逐字节一致
README.md CHANGELOG.md setup.py setup.cfg MANIFEST.in tox.ini .coveragerc texttable.pyi PKG-INFO
docs/assets/
  fig1_same_bytes.png        同一份字节 → 两张不同宽度的表
  fig2_reproduce_checks.png  10 项复现检查：上游 2/10 → 修复 10/10
  fig3_consistency.png       跨 6 环境分歧 17→6，不自洽渲染 40→16
  fig4_agreement.png         按类别：1993 个码位宽度算错 → 0
  fig5_wrapping.png          宽字符列内换行 4/15 → 14/15
  fig6_acceptance.png        24 组合全绿 + 变异 7/7 被抓
evidence/
  repro_before.txt      上游原版 2/10
  repro_after.txt       修复版 10/10
  accept_matrix.txt     24 个组合全绿
  mutation_nowcwidth.txt 7/7 变异被抓
```

打补丁：

```bash
cd texttable-1.7.2-source
patch --binary -p1 < texttable-xplat.patch
```

> 用 `patch --binary` 而非 `git apply`：Windows 上 `git apply` 会受 `core.autocrlf` 影响，把整份文件转成 CRLF。

---

## 6. 改动范围

`texttable.py` 从 756 行增到 916 行（净增 160 行；补丁 202 行增删）。

未改动：`Texttable` 的公开 API、`__init__` 签名、`draw()` 的返回契约、任何已发布功能的默认行为（纯窄字符路径逐字节不变）。
