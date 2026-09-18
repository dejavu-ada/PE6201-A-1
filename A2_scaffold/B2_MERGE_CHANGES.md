# B1 + B2 合并说明（ZHU YIN）

## 合并基线

本版本以团队上传的 `PE6201-A-1-main-v2.zip` 为主线，保留其中的：

- 50条 Problem B Evaluation Cases；
- v1/v2 Descriptors与Prompt切换；
- 并行/串行实验；
- Poka-Yoke参数防错；
- 已生成的Live Model与成本实验结果；
- B1已有的 `tool_trace`、`errors` 和自由文本检测器。

随后选择性合入并扩展此前B2安全逻辑，没有用旧工程整包覆盖团队v2。

## 本次实际修改

### `guardrails.py`

- 保留Step Cap、Budget Ceiling、重复调用检测和Autonomy Gate；
- 增加工具白名单；
- 增加严格参数失败入口；
- 增加工具输出Prompt Injection停止；
- 将 `book_slot` 幂等键改为 `book_slot + referral_id`；
- 为安全停止记录 `blocked_action`；
- 增加统一 `halt()`，保证停止原因与日志一致。

### `tools.py`

- 增加Problem B六个工具的调用契约；
- 检查缺失参数、多余参数、类型、ID格式、科室、紧急等级、ISO日期、时间、合法窗口和真实可用Slot；
- 扩展恶意指令标记；
- 增加 `detect_untrusted_output()`，将工具返回和转诊自由文本视为不可信数据。

### `agent.py`

- 修复Live Backend无人工回调时自动批准预约的问题；
- 工具执行顺序变为：白名单 → 参数校验 → 去重/幂等 → Gate → 工具执行 → 不可信输出检查；
- Prompt Injection在进入Transcript前停止；
- 安全停止增加结构化人工升级字段；
- `tool_trace`对患者身份、联系方式和临床摘要进行脱敏；
- 备用Step Cap通过Guardrail日志停止，不再仅抛出裸异常。

### `backends.py`

- 为全部50个Problem B Scripted流程加入真实 `as_of()` 调用；
- 解决Prompt/Descriptor要求调用 `as_of`，但Scripted流程只在Thought里写死日期的矛盾；
- 并行模式仍为最多4轮，串行模式最长7轮，未超过8/16轮上限。

### `guardrail_cases.json` 与 `run_guardrails.py`

- 从10条扩展到15条；
- 真实验证未授权工具、非法参数、换Slot重复预约、三类恶意自由文本/工具输出、结构化人工升级和Live无确认拒绝；
- 结果写入 `outputs/guardrail_results.json` 和CSV。

## 修改后验证

| 检查 | 结果 |
|---|---:|
| 数据完整性 | 通过 |
| Poka-Yoke | 8/8 |
| 50案例并行评估 | 70/70 |
| 50案例串行评估 | 70/70 |
| Guardrail Cases | 15/15 |
| Hostile Cases | 3/3 |

70次而不是50次，是因为Harness对40条正向案例各运行1次，对10条负向案例各运行3次。

## 没有重新运行的内容

没有调用Live Model，也没有消耗新的Live Token。ZIP中原有Live输出是在本次B2合并之前生成的；如果报告要把它们作为最终结果，应由负责Live Battery的成员在最终代码上重新运行。

## 团队仍需完成

1. 完成人工或第二模型Judgement Queue；70/70只代表Code Check。
2. 确认B1的v1确实是未经v2改写的真实基线，并据此更新Descriptor实验。
3. 在最终代码上重跑需要写入报告的Live Model Battery。
4. 把D3报告段落、负面Demo和贡献说明并入团队提交。
5. 使用ZHU YIN自己的GitHub账号提交本次B2文件。

## 推荐运行顺序

```bash
cd A2_reference_data
python3 check_my_data.py

cd ../A2_scaffold
python3 test_poka_yoke.py
python3 run_eval.py
PARALLEL_TOOLS=false python3 run_eval.py
python3 run_guardrails.py --verbose
```
