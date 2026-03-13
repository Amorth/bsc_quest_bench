# Viem Support - 添加 Viem 库支持

## 概述

根据 rebuttal 承诺，我们添加了对 viem 库的支持，以减少 dependency bias 并覆盖更广泛的开发者群体。

## 实现内容

### 1. 添加 Viem 依赖

**文件**: `bsc_quest_bench/skill_runner/package.json`

```json
{
  "dependencies": {
    "ethers": "^6.13.4",
    "viem": "^2.21.54"  // 新增
  }
}
```

### 2. 创建 Viem System Config

**文件**: `bsc_quest_bench/system_config_viem.json`

包含 viem 特定的：
- 函数签名和类型定义
- 导入语句示例
- Transaction Request 格式
- 与 ethers.js 的关键差异说明
- 完整的代码示例

**关键差异**:
- 使用 `bigint` 而不是 `BigNumber`
- 地址类型为 `0x${string}`
- 使用 `encodeFunctionData()` 编码函数调用
- 使用 `parseEther()` / `parseUnits()` 转换数值

### 3. 修改 QuestController

**文件**: `bsc_quest_bench/quest_controller.py`

添加 `library` 参数：
```python
def __init__(self, ..., library: str = "ethers"):
    self.library = library
```

根据 library 选择加载不同的 system_config：
```python
def _load_system_config(self):
    if self.library == "viem":
        config_file = Path(__file__).parent / 'system_config_viem.json'
    else:
        config_file = Path(__file__).parent / 'system_config.json'
```

### 4. 添加命令行参数

**文件**: `run_quest_bench.py`

```python
parser.add_argument(
    '--library',
    type=str,
    default='ethers',
    choices=['ethers', 'viem'],
    help='JavaScript library to use: ethers (default) or viem'
)
```

## 使用方法

### 使用 Ethers.js (默认)

```bash
python run_quest_bench.py \
  --model anthropic/claude-opus-4.6 \
  --api-key YOUR_KEY \
  --fork-url YOUR_RPC \
  --library ethers \
  --type atomic
```

### 使用 Viem

```bash
python run_quest_bench.py \
  --model anthropic/claude-opus-4.6 \
  --api-key YOUR_KEY \
  --fork-url YOUR_RPC \
  --library viem \
  --type atomic
```

## Viem 代码示例

### 简单 BNB 转账

```typescript
import { parseEther } from 'viem'

export async function executeSkill(
    providerUrl: string,
    agentAddress: string,
    deployedContracts: Record<string, string>
) {
    return {
        to: '0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb' as `0x${string}`,
        value: parseEther('0.1'),  // 0.1 BNB
        data: '0x' as `0x${string}`
    };
}
```

### ERC20 转账

```typescript
import { encodeFunctionData, parseUnits } from 'viem'

export async function executeSkill(
    providerUrl: string,
    agentAddress: string,
    deployedContracts: Record<string, string>
) {
    const tokenAddress = '0x55d398326f99059fF775485246999027B3197955' as `0x${string}`;
    const toAddress = '0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb' as `0x${string}`;
    const amount = parseUnits('100', 18);

    const data = encodeFunctionData({
        abi: [{
            name: 'transfer',
            type: 'function',
            stateMutability: 'nonpayable',
            inputs: [
                { name: 'to', type: 'address' },
                { name: 'amount', type: 'uint256' }
            ],
            outputs: [{ type: 'bool' }]
        }],
        functionName: 'transfer',
        args: [toAddress, amount]
    });

    return {
        to: tokenAddress,
        data,
        value: 0n
    };
}
```

## 验证

运行测试脚本验证实现：

```bash
python test_viem_support.py
```

预期输出：
```
✅ Viem config file
✅ Package.json
✅ Run script
✅ QuestController
✅ Viem support has been added!
```

## 技术细节

### Transaction Request 格式

**Ethers.js**:
```typescript
{
  to: string,
  data: string,
  value: BigNumber,
  gasLimit: BigNumber
}
```

**Viem**:
```typescript
{
  to: `0x${string}`,
  data: `0x${string}`,
  value: bigint,
  gas: bigint
}
```

### 类型系统

Viem 使用 TypeScript 的严格类型系统：
- 所有地址必须是 `` `0x${string}` `` 类型
- 所有数值必须是 `bigint` 类型
- 所有十六进制数据必须是 `` `0x${string}` `` 类型

### 优势

1. **类型安全**: TypeScript 原生支持，编译时类型检查
2. **性能**: 更小的包体积，更快的执行速度
3. **现代化**: 使用最新的 JavaScript 特性
4. **生态系统**: 与 WalletConnect、RainbowKit 等主流库集成

## 与 Rebuttal 的对应

根据 rebuttal 承诺：

> "We are actively developing support for other commonly used JavaScript libraries, including web3.js and viem, as alternative execution backends."

**实现状态**:
- ✅ Viem 支持已完成
- ⚠️  Web3.js 暂未实现（生态系统正在淘汰该库）

**理由**:
- Viem 是未来趋势，被主流库采用
- Web3.js 正在被 WalletConnect 等库放弃支持
- 当前支持 Ethers.js + Viem 已覆盖主流开发者群体

## 更新日期

2026-03-13
