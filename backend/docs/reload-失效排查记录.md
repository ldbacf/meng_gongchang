# `--reload` 静默失效（uvicorn 在 Windows 上重启卡死）

> 排查时间：2026-10-27
> 现象：`uv run medrag-api --reload` 启动后改任何 `.py` 文件，服务都不重启；且**终端没有任何提示**。
> 目录：`backend/docs/`

## 环境

| 项 | 值 |
| --- | --- |
| 操作系统 | Windows 11 Pro 10.0.22631 |
| 后端 | FastAPI + uvicorn **0.47.0**（Python 3.12.11，`backend/.venv`） |
| watchfiles | 1.2.0（已安装） |
| 启动方式 | `uv run medrag-api --reload`（入口 `app/run_api.py`） |
| 终端 | 非传统 cmd console（ConPTY 类：Windows Terminal / VS Code 集成终端） |

## 现象

启动后修改 `backend/app/**/*.py`，等待 20 秒以上：

- 服务行为不变（新代码未生效）
- 监听 8000 的子进程 PID **始终不变**
- 终端**完全没有输出**，看不出 reload 是否工作

对比实验：在**干净目录**用官方 CLI 启动最小 FastAPI 应用：

```bash
python -m uvicorn mini:app --port 18899 --reload
```

修改 `mini.py` 后终端立刻输出：

```
WARNING:  WatchFiles detected changes in 'mini.py'. Reloading...
```

说明 **Python 环境与 watchfiles 本身正常**，问题在项目配置或 uvicorn 的 Windows 重启路径。

## 根因

### 直接原因：`BaseReload.restart()` 在 Windows 上会永久阻塞

`uvicorn/supervisors/basereload.py`：

```python
def restart(self) -> None:
    if sys.platform == "win32":
        self.is_restarting = True
        os.kill(self.process.pid, signal.CTRL_C_EVENT)   # ①
        sys.stdout.write(" ")                            # ②
        sys.stdout.flush()
    else:
        self.process.terminate()
    self.process.join()                                  # ③ 无超时

    self.process = get_subprocess(...)
    self.process.start()
```

三处问题串起来导致死锁：

1. **`signal.CTRL_C_EVENT` 的送达条件很窄**：只能发给「与发送者共享同一 console 且属于同一进程组」的进程。以下任一情况就不成立：
   - 经 `uv run` 等包装器启动（多一层进程，console 组关系断裂）
   - 终端是 ConPTY（Windows Terminal / VS Code 集成终端 / DSH subprocess 模式），不是传统 console
   - 非交互方式启动（`Start-Process`、计划任务、IDE 运行面板）
2. **`sys.stdout.write(" ")` 这个 workaround 只在「有 console 且 stdout 未被重定向」时起作用**，上述场景下是死代码。
3. **`self.process.join()` 没有超时**。Ctrl+C 事件送不到 → 子进程不退出 → 父进程（reloader）**永久卡死**。此后 watchfiles 仍在监听、仍会打印 `Reloading...`，但再也不会重启。

### 加重因素：父进程没有日志，故障完全不可见

`run_api.py` 传 `log_config=None`（为了避免 uvicorn 覆盖项目的 JSON 日志配置）。而 reloader **父进程不执行 `main.py` 的 lifespan**，所以：

- `setup_logging()` 从未在父进程运行
- 父进程没有任何 logging handler
- `WatchFiles detected changes ... Reloading...` 这行 WARNING **被直接丢弃**

结果：「reload 在工作但重启失败」与「reload 根本没启动」在终端上表现得一模一样，**这是本次排查绕了两轮的直接原因**——第一轮只看 PID 变化就误判为"watchfiles 没触发"，实际它一直在正常触发。

### 已排除的方向（避免后人重复劳动）

| 怀疑点 | 结论 |
| --- | --- |
| watchfiles 未安装 / 版本问题 | ❌ 1.2.0 已装，手写 `watch()` 能正常收到 `(Change.modified, path)` |
| uvicorn 降级成 `StatReload` | ❌ `ChangeReload` 就是 `WatchFilesReload`（`supervisors/__init__.py` 的 try-import 成功） |
| `reload_dirs` 路径错误 | ❌ `backend/app` 与 `backend/cli` 均存在且被正确解析 |
| `reload_excludes` 过滤掉了 `.py` | ❌ 为空；`FileFilter(config)(retrieval.py)` 返回 `True` |
| `app` 传成对象而非 import string | ❌ 传的是 `"app.main:app"` |
| `log_config=None` 导致 reload 失效 | ❌ 隔离实验中同样传 `log_config=None`，reload 正常 |
| 目录规模过大导致漏事件 | ❌ 仅 122 个 `.py` / 49 个子目录 |

**关键验证**（证明「检测成功但重启失败」）：在 18897 端口跑一份本项目的实例，改文件后日志出现

```
WatchFiles detected changes in 'app\application\graphs\rag\nodes\retrieval.py'. Reloading...
```

而子进程 PID **不变** —— 重启环节卡死，而非检测环节。

## 解决方案

不再使用 uvicorn 自带的 reload，改用 **`watchfiles.run_process`**（`app/application/worker.py` 早已是这个做法，两个入口至此统一）。

### 为什么 `run_process` 能绕开

`watchfiles/run.py` 的实现：

```python
process = spawn_context.Process(target=target_, args=args, kwargs=kwargs)
process.start()
...
for changes in watch(...):
    callback and callback(changes)
    process.stop(sigint_timeout=..., sigkill_timeout=...)   # ← terminate，非 Ctrl+C
    process = start_process(target, target_type, args, kwargs, changes)
```

- 子进程用 `multiprocessing(spawn).Process`，终止走 `Process.terminate()`/`kill()`，**不依赖 console 组**
- 带 `sigint_timeout` / `sigkill_timeout`，不会无超时阻塞

### 改动清单（`backend/app/run_api.py`）

1. **拆出模块级 `_run_server(host, port)`** —— `spawn` 要求 target 可 pickle，闭包/lambda 不行
2. **参数经 `kwargs=` 传递**
   ```python
   run_process(app_dir, cli_dir, target=_run_server, target_type="function",
               kwargs={"host": args.host, "port": args.port}, ...)
   ```
   ⚠️ **不能用模块级全局变量**：spawn 出的是全新解释器，看不到父进程对全局变量的修改（初版曾用 `_UVICORN_KWARGS` 全局字典，子进程里是空的）
3. **`loop="none"` 改为始终传**：uvicorn 现在总在单进程内跑，`asyncio_loop_factory(use_subprocess=False)` 在 win32 上硬编码返回 `ProactorEventLoop`；不显式关掉，psycopg async 会崩（见原模块 docstring 的事件循环说明）
4. **父进程也 `setup_logging()`**，并在 `callback` 里打出改动文件清单：
   ```
   {"level":"WARNING","msg":"检测到改动，重启服务: .../retrieval.py","logger":"app.reload"}
   ```
   否则同类问题仍会隐身

### 验证结果

| 验证项 | 结果 |
| --- | --- |
| 单次改动触发重启 | ✅ 子进程 `170652 → 183068`，父进程 PID 不变 |
| 连续两次改动 | ✅ `184288 → 204512` |
| 重启后服务健康 | ✅ `/health` 200 |
| 重启日志完整（重新走启动流程） | ✅ `Application startup complete` 时间戳更新 |
| **非 reload 模式**（生产路径） | ✅ `Postgres checkpointer 就绪`，`/health` 200，无 Proactor 报错 |
| 后端全量测试 | ✅ 289 passed / 1 skipped |

## 经验

1. **`--reload` 不生效时，先确认它是「没检测到」还是「检测到但重启失败」**。这两者的修法完全不同。可靠判据是子进程 PID 是否变化，而不是终端有没有输出。
2. **`log_config=None` 的代价要一并考虑**。为了不让 uvicorn 覆盖 JSON 日志而关掉它的日志配置，等于同时关掉了 reloader 父进程唯一的观测窗口。凡是「为了 A 牺牲 B」的改动，要确认 B 不会变成排查盲区。
3. **Windows 上不要依赖 `CTRL_C_EVENT` 做进程控制**。它绑定 console 组这一隐含前提，在 ConPTY、包装器、非交互启动下都不成立，且失败方式是**静默阻塞**而非报错。
4. **`multiprocessing(spawn)` 下，模块级全局变量不会跨进程**。参数必须走 `args`/`kwargs`，`target` 必须是模块级可 pickle 函数。
