"""
ERC1363 Transfer with Callback Validator

验证 ERC1363 代币的 transferAndCall 操作是否正确执行。
"""

from typing import Dict, Any
from decimal import Decimal


class ERC20TransferWithCallback1363Validator:
    """验证 ERC1363 transferAndCall 操作"""
    
    def __init__(
        self,
        token_address: str,
        to_address: str,
        amount: float,
        token_decimals: int = 18
    ):
        self.token_address = token_address.lower()
        self.to_address = to_address.lower()
        
        # 使用 Decimal 精确计算
        self.expected_amount = int(Decimal(str(amount)) * Decimal(10 ** token_decimals))
        self.token_decimals = token_decimals
        
        # transferAndCall(address,uint256,bytes) 函数选择器（使用 3 参数版本以避免重载问题）
        self.expected_selector = '0x1296ee62'
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证 ERC1363 transferAndCall 交易
        
        检查项：
        1. 交易成功执行 (30%)
        2. 发送者代币余额正确减少 (40%)
        3. 接收者代币余额正确增加 (20%)
        4. 使用了 transferAndCall 函数（正确的 selector）(10%)
        """
        results = []
        total_score = 0
        max_score = 100
        
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
                'max_score': max_score,
                'checks': results,
                'details': {
                    'token_address': self.token_address,
                    'to_address': self.to_address,
                    'expected_amount': self.expected_amount,
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证发送者代币余额减少 (40 分)
        sender_balance_before = state_before.get('token_balance', 0)
        sender_balance_after = state_after.get('token_balance', 0)
        actual_decrease = sender_balance_before - sender_balance_after
        
        if actual_decrease == self.expected_amount:
            results.append({
                'check': 'Sender Token Balance Decrease',
                'passed': True,
                'message': f'Sender balance correctly decreased by {self.expected_amount} units',
                'weight': 0.4,
                'details': {
                    'balance_before': sender_balance_before,
                    'balance_after': sender_balance_after,
                    'actual_decrease': actual_decrease,
                    'expected_decrease': self.expected_amount
                }
            })
            total_score += 40
        else:
            results.append({
                'check': 'Sender Token Balance Decrease',
                'passed': False,
                'message': f'Balance decrease mismatch. Expected: {self.expected_amount}, Got: {actual_decrease}',
                'weight': 0.4,
                'details': {
                    'balance_before': sender_balance_before,
                    'balance_after': sender_balance_after,
                    'actual_decrease': actual_decrease,
                    'expected_decrease': self.expected_amount
                }
            })
        
        # 3. 验证接收者代币余额增加 (20 分)
        receiver_balance_before = state_before.get('target_token_balance', 0)
        receiver_balance_after = state_after.get('target_token_balance', 0)
        actual_increase = receiver_balance_after - receiver_balance_before
        
        if actual_increase == self.expected_amount:
            results.append({
                'check': 'Receiver Token Balance Increase',
                'passed': True,
                'message': f'Receiver balance correctly increased by {self.expected_amount} units',
                'weight': 0.2,
                'details': {
                    'balance_before': receiver_balance_before,
                    'balance_after': receiver_balance_after,
                    'actual_increase': actual_increase,
                    'expected_increase': self.expected_amount
                }
            })
            total_score += 20
        else:
            results.append({
                'check': 'Receiver Token Balance Increase',
                'passed': False,
                'message': f'Balance increase mismatch. Expected: {self.expected_amount}, Got: {actual_increase}',
                'weight': 0.2,
                'details': {
                    'balance_before': receiver_balance_before,
                    'balance_after': receiver_balance_after,
                    'actual_increase': actual_increase,
                    'expected_increase': self.expected_amount
                }
            })
        
        # 4. 验证使用了正确的函数 selector (10 分)
        tx_data = tx.get('data', '') or tx.get('input', '')
        
        if isinstance(tx_data, bytes):
            tx_data = tx_data.hex()
        if isinstance(tx_data, str) and tx_data.startswith('0x'):
            tx_data = tx_data[2:]
        
        # 提取函数 selector (前 4 字节 = 8 个十六进制字符)
        if len(tx_data) >= 8:
            actual_selector = '0x' + tx_data[:8]
            
            if actual_selector.lower() == self.expected_selector.lower():
                results.append({
                    'check': 'Function Selector',
                    'passed': True,
                    'message': f'Correct transferAndCall selector: {actual_selector}',
                    'weight': 0.1,
                    'details': {
                        'expected': self.expected_selector,
                        'actual': actual_selector
                    }
                })
                total_score += 10
            else:
                results.append({
                    'check': 'Function Selector',
                    'passed': False,
                    'message': f'Incorrect function selector. Expected transferAndCall ({self.expected_selector}), got {actual_selector}',
                    'weight': 0.1,
                    'details': {
                        'expected': self.expected_selector,
                        'actual': actual_selector
                    }
                })
        else:
            results.append({
                'check': 'Function Selector',
                'passed': False,
                'message': 'Transaction data too short or missing',
                'weight': 0.1
            })
        
        # 汇总结果
        all_passed = all(check['passed'] for check in results)
        
        return {
            'passed': all_passed,
            'score': total_score,
            'max_score': max_score,
            'checks': results,
            'details': {
                'token_address': self.token_address,
                'to_address': self.to_address,
                'expected_amount': self.expected_amount,
                'sender_balance_before': sender_balance_before,
                'sender_balance_after': sender_balance_after,
                'receiver_balance_before': receiver_balance_before,
                'receiver_balance_after': receiver_balance_after,
                'expected_selector': self.expected_selector,
                'actual_selector': actual_selector if len(tx_data) >= 8 else 'N/A'
            }
        }

