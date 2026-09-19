# CONTRIBUTIONS

## PE6201 A2 — Team A-1

**Problem B: Outpatient Referral Coordination**

This contribution log records the primary responsibilities of each team member.  
Shared deliverables were developed collaboratively; the entries below indicate primary ownership rather than exclusive authorship.

| Team Member | Primary Contributions | Main Deliverables |
|---|---|---|
| **CHENG HAO** | Built and maintained the evaluation harness, deterministic grading logic, and reproducible scripted baseline. Ran the assigned Qwen3 30B A3B Instruct v2 live-model evaluation. | D4, D5(a), D5(b) |
| **HU YIXIANG** | Developed the single-agent execution loop, integrated tools, and implemented and tested sequential/parallel calling. Ran the assigned DeepSeek V4 Flash v2 live-model evaluation. | D1, D2(a), D2(c), D5(b) |
| **LI JIAYI** | Performed cost accounting, monthly cost projection, sensitivity analysis, and break-even calculations. Ran the assigned Mistral Small 3.2 24B Instruct v2 live-model evaluation. | D6, D5(b) |
| **SHI JING** | Designed tool descriptors, contributed to the v1-to-v2 prompt revision, and implemented and verified deterministic guardrails. Ran the assigned Claude Haiku 4.5 v2 live-model evaluation. | D2(b), D3, D5(b) |
| **ZHANG LIWEI** | Consolidated experimental evidence, contributed to Report Sections 4 and 5, and assembled the demonstration materials. Ran the assigned Gemini 3.1 Flash Lite v2 live-model evaluation. | Report, D6/D7 presentation, D5(b) |
| **ZHANG SHIYUE** | Developed the single-agent execution loop, integrated tools, and implemented and tested sequential/parallel calling. Ran the assigned GPT-5 Mini v2 live-model evaluation. | D1, D2(a), D2(c), D5(b) |
| **ZHU YIN** | Designed tool descriptors, contributed to the v1-to-v2 prompt revision, and implemented and verified deterministic guardrails. Ran the same-model v1 comparison using GPT-5 Mini. | D2(b), D3, D5(b) v1 comparison |

## Shared Team Contributions

- Each member contributed evaluation cases under the team allocation.
- Each member ran the assigned live-model configuration using their own API key and provided the resulting evidence.
- Implementation owners supplied explanations, experiment outputs, and supporting evidence for the corresponding report sections.
- The team jointly reviewed the final report, repository contents, results, and submission package.

## Live Model Evaluation Allocation

| Team Member | Model | Descriptor Version |
|---|---|---|
| CHENG HAO | Qwen3 30B A3B Instruct | v2 |
| HU YIXIANG | DeepSeek V4 Flash | v2 |
| LI JIAYI | Mistral Small 3.2 24B Instruct | v2 |
| SHI JING | Claude Haiku 4.5 | v2 |
| ZHANG LIWEI | Gemini 3.1 Flash Lite | v2 |
| ZHANG SHIYUE | GPT-5 Mini | v2 |
| ZHU YIN | GPT-5 Mini | v1 |

The six v2 runs form the cross-model battery. The GPT-5 Mini v1 run is paired with the GPT-5 Mini v2 run for the controlled descriptor comparison in D2(b).
