"""
ERC1363 ApproveAndCall Validator

验证 ERC1363 代币的 approveAndCall 操作是否正确执行。
"""

from typing import Dict, Any
from decimal import Decimal


class ERC20ApproveAndCall1363Validator:
    """验证 ERC1363 approveAndCall 操作"""
    
    def __init__(
        self,
        token_address: str,
        spender_address: str,
        amount: float,
        token_decimals: int = 18
    ):
        self.token_address = token_address.lower()
        self.spender_address = spender_address.lower()
        
        # 使用 Decimal 精确计算
        self.expected_amount = int(Decimal(str(amount)) * Decimal(10 ** token_decimals))
        self.token_decimals = token_decimals
        
        # approveAndCall 函数选择器（接受两种重载版本）
        # 2 参数版本: approveAndCall(address,uint256) = 0x3177029f
        # 3 参数版本: approveAndCall(address,uint256,bytes) = 0xcae9ca51
        self.expected_selectors = ['0x3177029f', '0xcae9ca51']
        self.max_score = 100
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证 ERC1363 approveAndCall 交易
        
        Args:
            tx: 交易对象
            receipt: 交易收据
            state_before: 交易前状态
            state_after: 交易后状态
            
        Returns:
            验证结果字典
        
        检查项：
        1. 交易成功执行 (30%)
        2. Allowance 正确设置 (50%)
        3. 使用了 approveAndCall 函数（正确的 selector）(20%)
        """
        
        results = []
        total_score = 0
        
        # 1. 验证交易成功 (30 分)
        tx_status = receipt.get('status', 0)
        if tx_status == 1:
            results.append({
                'check': 'Transaction Success',
                'passed': True,
                'message': 'Transaction executed successfully',
                'weight': 0.3
            })
            total_score += 30
        else:
            results.append({
                'check': 'Transaction Success',
                'passed': False,
                'message': f'Transaction failed with status: {tx_status}',
                'weight': 0.3
            })
            # 如果交易失败，直接返回
            return {
                'passed': False,
                'score': 0,
                'max_score': self.max_score,
                'checks': results,
                'details': {
                    'token_address': self.token_address,
                    'spender_address': self.spender_address,
                    'expected_amount': self.expected_amount,
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证 allowance 正确设置 (50 分)
        allowance_before = state_before.get('allowance', 0)
        allowance_after = state_after.get('allowance', 0)
        
        if allowance_after == self.expected_amount:
            results.append({
                'check': 'Allowance Set Correctly',
                'passed': True,
                'message': f'Allowance correctly set to {self.expected_amount} units',
                'weight': 0.5,
                'details': {
                    'allowance_before': allowance_before,
                    'allowance_after': allowance_after,
                    'expected_allowance': self.expected_amount
                }
            })
            total_score += 50
        else:
            results.append({
                'check': 'Allowance Set Correctly',
                'passed': False,
                'message': f'Allowance mismatch. Expected: {self.expected_amount}, Got: {allowance_after}',
                'weight': 0.5,
                'details': {
                    'allowance_before': allowance_before,
                    'allowance_after': allowance_after,
                    'expected_allowance': self.expected_amount
                }
            })
        
        # 3. 验证使用了正确的函数 selector (20 分)
        tx_data = tx.get('data', '') or tx.get('input', '')
        
        if isinstance(tx_data, bytes):
            tx_data = tx_data.hex()
        if isinstance(tx_data, str) and tx_data.startswith('0x'):
            tx_data = tx_data[2:]
        
        # 提取函数 selector (前 4 字节 = 8 个十六进制字符)
        actual_selector = 'N/A'
        if len(tx_data) >= 8:
            actual_selector = '0x' + tx_data[:8]
            
            # 检查是否匹配任何一个预期的选择器
            if actual_selector.lower() in [s.lower() for s in self.expected_selectors]:
                # 确定使用的是哪个版本
                version = "2-parameter" if actual_selector.lower() == '0x3177029f' else "3-parameter"
                results.append({
                    'check': 'Function Selector',
                    'passed': True,
                    'message': f'Correct approveAndCall selector ({version}): {actual_selector}',
                    'weight': 0.2,
                    'details': {
                        'expected': self.expected_selectors,
                        'actual': actual_selector,
                        'version': version
                    }
                })
                total_score += 20
            else:
                results.append({
                    'check': 'Function Selector',
                    'passed': False,
                    'message': f'Incorrect function selector. Expected approveAndCall ({" or ".join(self.expected_selectors)}), got {actual_selector}',
                    'weight': 0.2,
                    'details': {
                        'expected': self.expected_selectors,
                        'actual': actual_selector
                    }
                })
        else:
            results.append({
                'check': 'Function Selector',
                'passed': False,
                'message': 'Transaction data too short or missing',
                'weight': 0.2
            })
        
        # 汇总结果
        all_passed = all(check['passed'] for check in results)
        
        return {
            'passed': all_passed,
            'score': total_score,
            'max_score': self.max_score,
            'checks': results,
            'details': {
                'token_address': self.token_address,
                'spender_address': self.spender_address,
                'expected_amount': self.expected_amount,
                'allowance_before': allowance_before,
                'allowance_after': allowance_after,
                'expected_selectors': self.expected_selectors,
                'actual_selector': actual_selector
            }
        }

