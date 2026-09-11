# Toivo Life · Commit Message 规范

用中文写 commit, 一行标题 + 一段正文, 一眼能看出**改了什么** + **为什么**。
坏例子: `更新代码` / `修 bug` / `wip`。

## 格式

```
<类型>(<范围>): <一句话概括, ≤ 50 字, 结尾不加句号>

<正文: 说清"为什么改" + "关键取舍", 每行 ≤ 72 字>
<可以分段, 段之间空一行>

<可选: 破坏性变更 / 关联 issue>
```

### 标题

- **类型** (必填, 全小写英文): 让 git log 一眼可扫。
- **范围** (可选, 小括号): 业务包名或子系统, 缩到最小。多个范围用 `,` 或写在正文里。
- **概括** (必填, 中文): 动宾结构, 说"做了什么", 不是"计划做什么"。

### 类型清单

| 类型 | 用途 | 例子 |
|---|---|---|
| `feat` | 新功能 / 新业务包 / 新命令 | `feat(jd_targeted_resume): 新增 JD 定制版业务包` |
| `fix` | 修 bug (行为不对) | `fix(render): 修正长表格换页时表头丢失` |
| `refactor` | 重构, 不改行为 | `refactor(products): 把 build_prompts 提到基类` |
| `perf` | 性能优化 | `perf(pipeline): 减少 prompt 模板 IO 到 1 次` |
| `docs` | 文档 / 注释 / README | `docs: 把 input/README.md 纳入版本管理` |
| `test` | 测试用例 / 回归数据 | `test(career_resume): 加 20 份简历回归集` |
| `chore` | 构建 / 依赖 / 工具链 / 配置 | `chore: 升级 pydantic 到 2.9` |
| `style` | 代码格式 (空格 / 换行 / 排版), 不含语义 | `style: 统一 schema.py 缩进` |
| `revert` | 回滚 | `revert: 撤销 b0bc5f7` |
| `init` | 项目 / 业务包首次落地 (少用) | `init: Toivo Life v0.3.1 baseline` |

不要发明新的类型。写不下去的 90% 都是 `feat` / `fix` / `refactor` 里挑一个。

### 范围

- 业务包用目录名: `career_resume`, `jd_targeted_resume`
- 子系统用短名: `render`, `cli`, `providers`, `products`, `schema`
- 配置文件级别就写文件名: `.gitignore`, `pyproject`

多处改动如果实在无法归到一个范围, 省略括号就行, 不要堆一串。

### 正文

必须写正文, 除非改的是 typo / 空格。正文回答:

1. **为什么要改** —— 触发这次改动的问题 / 需求
2. **怎么改的** (只在方案不唯一时写) —— 选了 A 没选 B 的原因
3. **有什么风险 / 副作用** (如有)

不要复述 diff. 代码里能看到的东西不用在 commit 里再抄一遍。

### 破坏性变更

正文最后加一段, 顶格写:

```
BREAKING CHANGE: 说清哪个接口 / 命令 / schema 字段变了, 使用方要改什么
```

## 例子

**好**:

```
fix(pipeline): 修复 prompt 占位符从未被替换的隐藏 bug

老代码 build_prompts 里 6 个 {var} 从未做 str.replace, LLM 读到的是
字面 "{resume_text}"; 而尾部又追加了简历原文, 相当于双喂。改用逐个
str.replace + 一个自检 raise 兜底, 未来加占位符不会再漏。
```

```
feat(jd_targeted_resume): 新增 JD 定制版业务包

作为独立业务包引入, 有自己的 inputs.py / schema.py / prompt / template,
不做成 career_resume 的 mode 开关 —— 通用竞争力诊断和 JD 匹配是两个
不同的报告产品, 强行合并只会互相污染。
```

**不好**:

```
更新           ← 没类型没范围没内容
fix: 修bug    ← 修的哪个 bug?
feat: 加了个东西  ← ...
更新 pipeline 添加验证, 修改 schema 增加字段, 修改 README 增加说明   ← 一个 commit 塞太多主题, 拆分
```

## 一次 commit 只做一件事

如果 commit message 里出现两个不相关的动词 (加了 A **并且** 修了 B), 就应该拆成两次 commit. 拆分标准: 未来想 revert 其中一个, 是否会连累另一个?

## 工具

仓库根目录有 `.gitmessage` 模板, 首次 clone 后跑一次:

```bash
git config commit.template .gitmessage
```

之后 `git commit` (不带 `-m`) 会自动打开编辑器带出骨架。
