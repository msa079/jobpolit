# JobPolit 学生实习求职助手

基于 LangChain / LangGraph 的本地 AI 求职助手，提供实习岗位搜索、JD 要求解析，以及结合已提交简历的岗位匹配分析。

> 个人学习与求职展示项目。匹配结果是辅助建议，不代表录用概率；当前版本仅用于本机运行。

## 功能

- **岗位搜索**：按公司或岗位方向搜索实习信息，返回岗位标题和来源链接。
- **JD 分析**：将用户粘贴的完整 JD 提取为岗位职责、硬性要求与加分项。
- **岗位匹配**：读取当前账号已保存的简历画像，生成命中项、缺失项、学历差距和投递建议。
- **历史会话**：支持新建、查看、重命名和删除会话，通过 SQLite 与 checkpoint 保存会话数据。
- **网页交互**：提供注册、登录、简历提交面板和聊天界面。

## 使用示例

1. 注册或登录，在“简历投递”面板提交自己的简历文本。
2. 输入“帮我找后端开发方向的实习”，获取相关岗位链接。
3. 打开招聘链接，将完整“岗位职责”和“任职要求”粘贴到聊天中。
4. 询问“根据我的简历，我是否适合投递这个岗位？”，查看分析依据及建议。

“简历投递”仅向本地应用提交，不会自动向企业或招聘网站投递。

## 核心设计

```text
网页请求 → HTTP 接口 → Agent
                         ├─ search_jobs：搜索岗位并返回链接
                         ├─ analyze_jd：解析岗位要求
                         └─ match_job：读取画像 → 解析 JD → 生成匹配报告

简历提交 → 结构化提取 → 按账号保存画像
会话状态 → LangGraph checkpoint → SQLite
```

- `create_agent()` 注册三个工具，由模型结合提示词、历史与工具描述选择调用。
- Pydantic 约束用户画像、岗位要求和报告的字段与类型；不等同于事实真实性校验。
- 匹配工具内部解析 JD，提示词与工具说明约束避免重复调用解析工具。
- 岗位网页可能存在访问限制或动态加载，当前采用“搜索返回链接、用户粘贴 JD”的流程。
- 技能评分当前由模型生成；模型判断学历门槛明确不满足时，程序强制调整分数与结论。

## 本地启动

### 环境

- Python 3.12 或以上
- [uv](https://docs.astral.sh/uv/)
- 支持工具调用和结构化输出的 OpenAI 兼容模型接口
- [Tavily](https://tavily.com/) API Key（岗位搜索使用）

### 配置和运行

在项目根目录执行：

```powershell
uv sync --locked
Copy-Item .env.example .env
```

编辑本机 `.env`，填写：

```dotenv
MODEL_NAME=your-model-name
MODEL_BASE_URL=https://your-provider.example.com/v1
MODEL_API_KEY=your-api-key
TAVILY_API_KEY=your-tavily-api-key
```

然后运行：

```powershell
uv run python -m src.main
```

默认访问 http://127.0.0.1:8787 ，终端按 Ctrl+C 停止。更换端口或关闭自动打开浏览器：

```powershell
uv run python -m src.web --port 8789 --no-browser
```

模型及搜索服务可能收费。数据默认保存在本机 `data/checkpoint.db`，可通过 `JOBPOLIT_DB` 环境变量指定数据库路径。

## 代码结构

| 文件 | 职责 |
| --- | --- |
| `src/agent.py` | Agent 构建、自定义状态与会话配置 |
| `src/tools.py` | 搜索、JD 分析、岗位匹配工具 |
| `src/core.py` | 结构化提取与匹配报告生成 |
| `src/schemas.py` | Pydantic 数据模型 |
| `src/prompts.py` | 提取、匹配和工具选择提示词 |
| `src/db.py`、`src/memory.py` | checkpoint、SQLite 及会话目录 |
| `src/config.py` | 模型配置 |
| `src/web.py`、`src/auth.py`、`src/profiles.py` | HTTP、认证、账号画像存储 |
| `src/static/` | 网页界面与交互 |

## 适用范围与限制

- 岗位搜索结果只用于发现线索，不保证岗位仍在招、要求完整或用户满足全部条件。
- 匹配分数尚未通过人工标注数据集评估；温度设为 0 也不保证结果完全一致。
- 技能程度、缺失信息等判断仍可能出错，投递前应人工核对原文。
- 简历提取与 JD 解析走不同输入流程，普通聊天不更新用户画像。
- 简历与消息保存在本机，但相关文本会发送到配置的模型服务；搜索请求会发送给 Tavily。
- 仅监听 `127.0.0.1`，不能直接作为公网部署版本使用。

## 开发分工

本人实现核心 Agent、业务工具、提示词、数据模型、画像存储和底层会话持久化，并针对网页读取不稳定的问题调整岗位信息获取流程。

前端、HTTP 接口、账号认证及相关效果验证由 AI 编程工具辅助完成。不声称具备已验证的匹配准确率或生产级部署能力。

## 本地数据

`.env`、密钥、数据库、会话记录、虚拟环境和本地开发配置不提交到仓库。请勿在 Issue、截图或提交中放入真实简历、账号凭据或 API Key。
