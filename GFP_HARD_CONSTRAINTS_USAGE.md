# GFP 硬约束用法

当前版本已经支持两类真正的硬约束：

1. 固定残基
2. 强制保留 GFP 色团 `SYG`

注意：

- `SYG` 会在 GFP 任务里自动加入硬约束
- 固定残基需要你在 `POST /design_protein` 请求体里显式传 `fixed_residues`
- 不要再只把这些约束写在自然语言 prompt 里


## 请求示例

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Design an improved GFP and iteratively optimize it",
    "sequence": "KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK",
    "max_iterations": 1,
    "candidates_per_round": 4,
    "patience": 1,
    "fixed_residues": [
      {"position": 96, "residue": "R"},
      {"position": 148, "residue": "H"},
      {"position": 203, "residue": "T"},
      {"position": 205, "residue": "S"},
      {"position": 222, "residue": "E"}
    ]
  }'
```


## 当前行为

- 工作流会在每轮初始候选、突变候选、再生成候选进入评分前，先把这些位点强制投影回指定残基
- GFP 任务里，`SYG` 也会被自动强制保留
- 如果某个候选仍然绕过投影而违反固定残基，评分阶段会加硬惩罚并标记为 `valid_candidate=false`


## 你现在应该怎么传位点

如果你当前使用的是 mature avGFP 坐标，请统一按这套编号传。

在你当前配置下：

- `reference length = 236`
- `chromophore start = 63`
- `motif = SYG`

因此不要再把旧编号体系和当前编号体系混用。
