# BSC Quest Bench - 单轮交易生成评估系统

BSC Quest Bench 是一个用于评估 LLM 基于自然语言直接生成准确交易代码能力的评估系统。

## 系统架构

### 核心组件

1. **控制层 (Control Layer)** - `quest_controller.py`
   - 管理 LLM 输入输出
   - 协调各层交互
   - 提取 TypeScript 代码块
   - 保存评分指标

2. **环境层 (Environment Layer)** - `quest_env.py`
   - 初始化本地 Anvil 节点 (fork from BSC testnet)
   - 创建测试账户并设置初始余额
   - 提供 Web3 连接和链上状态查询

3. **执行层 (Execution Layer)** - `quest_executor.py`
   - 执行 TypeScript 生成的交易
   - 获取交易执行结果和 receipt
   - 调用验证器进行验证
   - 返回评分结果

4. **验证器 (Validators)** - `validators/`
   - 针对不同原子问题的验证逻辑
   - 验证交易执行结果是否符合预期
   - 计算得分

5. **题库 (Question Bank)** - `question_bank/`
   - 存储原子问题定义
   - 包含问题描述、参数、验证规则等

6. **Skill Manager** - `skill_manager/`
   - 执行 LLM 生成的 TypeScript 代码
   - 复用 bsc_gym_env 的 skill_runner

## 项目结构

```
bsc_quest_bench/
├── __init__.py
├── quest_controller.py       # 控制层 ⭐
├── quest_env.py              # 环境层
├── quest_executor.py         # 执行层
├── skill_manager/            # Skill Manager
│   ├── __init__.py
│   └── ts_skill_manager.py
├── validators/               # 验证器 (持久化组件)
│   ├── __init__.py
│   └── bnb_transfer_validator.py
└── question_bank/            # 题库
    └── basic_transactions/
        └── native_transfer/
            └── bnb_transfer_basic.json

test_transactions/bsc_quest_bench_test/
├── test_bnb_transfer.py              # 验证器测试
├── test_llm_generation.py            # LLM 完整流程测试 ⭐
├── test_config.py                    # LLM 配置 (API keys)
├── bnb_transfer_solution.ts          # 完美答案
└── results/                          # 评估结果保存目录
```

## 快速开始

### 前置要求

1. Python 3.8+
2. Node.js / Bun
3. Foundry (Anvil)

安装 Foundry:
```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

### 运行测试

#### 方式 1: 直接模式 (推荐)

直接在 Python 中构造交易对象，无需依赖外部 TypeScript 运行时:

```bash
cd test_transactions/bsc_quest_bench_test
python test_bnb_transfer.py
```

这种方式:
- ✅ 无需安装 bun/node
- ✅ 运行速度快
- ✅ 适合开发和调试
- ✅ 直接验证验证器逻辑

#### 方式 2: TypeScript 集成模式 (可选)

执行实际的 TypeScript 代码，模拟完整的 LLM 生成流程:

```bash
cd test_transactions/bsc_quest_bench_test
python test_bnb_transfer.py --typescript
```

这种方式:
- ⚠️ 需要安装 bun: `curl -fsSL https://bun.sh/install | bash`
- ⚠️ 需要 bsc_gym_env/skill_runner 环境
- ✅ 测试完整的代码生成和执行流程
- ✅ 适合集成测试

## 原子问题示例

### BNB 转账 (bnb_transfer_basic)

**问题描述**: 从一个地址转账固定金额的 BNB 到另一个地址

**验证规则**:
- 交易执行成功 (30分)
- 目标地址正确 (25分)
- 转账金额正确 (25分)
- Gas 设置合理 (10分)
- 余额变化正确 (10分)

**总分**: 100分

## 验证器说明

### BNBTransferValidator

验证 BNB 原生代币转账的正确性。

**验证项**:
1. 交易是否成功执行
2. 目标地址是否正确
3. 转账金额是否正确 (允许 0.1% 容差)
4. Gas 设置是否合理
5. 余额变化是否正确 (允许 1% 容差)

## 扩展开发

### 添加新的原子问题

1. 在 `question_bank/` 创建问题定义 JSON
2. 在 `validators/` 创建对应的验证器
3. 在 `test_transactions/bsc_quest_bench_test/` 创建测试脚本和完美答案

### 验证器接口

验证器需要实现 `validate()` 方法:

```python
def validate(
    self,
    tx: Dict[str, Any],           # 交易对象
    receipt: Dict[str, Any],      # 交易回执
    state_before: Dict[str, Any], # 交易前状态
    state_after: Dict[str, Any]   # 交易后状态
) -> Dict[str, Any]:
    """
    返回:
    {
        'passed': bool,        # 是否通过
        'score': int,          # 得分
        'max_score': int,      # 最高分
        'checks': List[Dict],  # 检查项列表
        'feedback': str        # 反馈信息
    }
    """
```

## 设计理念

### 为什么有两种测试模式？

1. **直接模式**: 用于快速验证验证器逻辑
   - 这是单轮评估系统的核心部分
   - 验证器是持久化组件,需要独立测试
   - 无需依赖外部运行时,降低测试复杂度

2. **TypeScript 集成模式**: 用于测试完整流程
   - 模拟 LLM 生成 TypeScript 代码
   - 执行代码并验证结果
   - 用于端到端集成测试

### 关键区别: Quest Bench vs Gym Env

| 特性 | Quest Bench (单轮) | Gym Env (多轮) |
|------|-------------------|----------------|
| 交互模式 | 单次生成 | 多轮对话 |
| 验证器 | 持久化组件 | 集成在环境中 |
| 测试方式 | 直接构造交易 | 执行 TypeScript |
| 目标 | 验证器开发和测试 | LLM 交互评估 |

## 技术栈

- **EVM**: Anvil (Foundry)
- **Web3**: Web3.py
- **TypeScript Runtime**: Bun (仅集成模式需要)
- **RPC**: https://bsc-testnet.drpc.org

## LLM 支持

控制层支持多种 LLM provider:

### OpenRouter (推荐)

```python
from bsc_quest_bench.quest_controller import QuestController

controller = QuestController(
    model_name="anthropic/claude-sonnet-4",  # provider/model 格式
    question_path="path/to/question.json",
    validator_class=validator_factory,
    api_key="sk-or-v1-your-key"
)
```

### 直接使用 OpenAI / Anthropic / Google

```python
# OpenAI
controller = QuestController(
    model_name="gpt-4-turbo",
    api_key="sk-your-openai-key",
    ...
)

# Anthropic
controller = QuestController(
    model_name="claude-3-sonnet-20240229",
    api_key="sk-ant-your-key",
    ...
)
```

### 自定义 API endpoint

```python
controller = QuestController(
    model_name="custom-model",
    base_url="https://your-api.com/v1",
    api_key="your-key",
    ...
)
```

## 开发状态

当前版本: v0.1.0

已实现:
- ✅ 控制层 (LLM 交互管理) ⭐
- ✅ 环境层 (本地 Anvil fork)
- ✅ 执行层 (交易执行和验证调度)
- ✅ Skill Manager (TypeScript 代码执行)
- ✅ BNB 转账验证器
- ✅ BNB 转账原子问题
- ✅ 验证器测试脚本
- ✅ LLM 完整流程测试脚本 ⭐

计划中:
- ⏳ ERC20 转账验证器
- ⏳ DEX Swap 验证器
- ⏳ 更多原子问题
- ⏳ 组合问题生成器
- ⏳ 批量评估脚本

