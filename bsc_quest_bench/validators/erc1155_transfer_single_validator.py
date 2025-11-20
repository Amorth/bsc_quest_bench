"""
ERC1155 Transfer Single Validator

验证 ERC1155 单个代币 ID 的转账操作。
"""

from typing import Dict, Any


class ERC1155TransferSingleValidator:
    """验证 ERC1155 safeTransferFrom 操作"""
    
    def __init__(
        self,
        nft_address: str,
        to_address: str,
        token_id: int,
        amount: int
    ):
        self.nft_address = nft_address.lower()
        self.to_address = to_address.lower()
        self.token_id = token_id
        self.expected_amount = amount
        self.max_score = 100
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证 ERC1155 转账交易
        
        Args:
            tx: 交易对象
            receipt: 交易收据
            state_before: 交易前状态
            state_after: 交易后状态
            
        Returns:
            验证结果字典
        
        检查项：
        1. 交易成功执行 (30%)
        2. 调用了正确的 ERC1155 合约 (20%)
        3. 使用了 safeTransferFrom 函数 (20%)
        4. 发送者余额减少，接收者余额增加 (30%)
        """
        checks = []
        total_score = 0
        
        # 1. 验证交易成功 (30 分)
        tx_status = receipt.get('status', 0)
        if tx_status == 1:
            checks.append({
                'name': 'Transaction Success',
                'passed': True,
                'message': 'Transaction executed successfully',
                'score': 30
            })
            total_score += 30
        else:
            checks.append({
                'name': 'Transaction Success',
                'passed': False,
                'message': f'Transaction failed with status: {tx_status}',
                'score': 30
            })
            # 如果交易失败，直接返回
            return {
                'passed': False,
                'score': 0,
                'max_score': self.max_score,
                'checks': checks,
                'details': {
                    'nft_address': self.nft_address,
                    'to_address': self.to_address,
                    'token_id': self.token_id,
                    'expected_amount': self.expected_amount,
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证调用了正确的 ERC1155 合约 (20 分)
        tx_to = tx.get('to', '').lower()
        if tx_to == self.nft_address:
            checks.append({
                'name': 'Contract Address',
                'passed': True,
                'message': f'Correct ERC1155 contract: {tx_to}',
                'score': 20
            })
            total_score += 20
        else:
            checks.append({
                'name': 'Contract Address',
                'passed': False,
                'message': f'Wrong contract. Expected: {self.nft_address}, Got: {tx_to}',
                'score': 20
            })
        
        # 3. 验证使用了 safeTransferFrom 函数 (20 分)
        tx_data = tx.get('data', '') or tx.get('input', '')
        
        if isinstance(tx_data, bytes):
            tx_data = tx_data.hex()
        if isinstance(tx_data, str) and tx_data.startswith('0x'):
            tx_data = tx_data[2:]
        
        # safeTransferFrom(address,address,uint256,uint256,bytes) 函数选择器
        expected_selector = '0xf242432a'
        actual_selector = 'N/A'
        
        if len(tx_data) >= 8:
            actual_selector = '0x' + tx_data[:8]
            
            if actual_selector.lower() == expected_selector.lower():
                checks.append({
                    'name': 'Function Signature',
                    'passed': True,
                    'message': f'Correct safeTransferFrom selector: {actual_selector}',
                    'score': 20,
                    'details': {
                        'expected': expected_selector,
                        'actual': actual_selector
                    }
                })
                total_score += 20
            else:
                checks.append({
                    'name': 'Function Signature',
                    'passed': False,
                    'message': f'Incorrect function selector. Expected safeTransferFrom ({expected_selector}), got {actual_selector}',
                    'score': 20,
                    'details': {
                        'expected': expected_selector,
                        'actual': actual_selector
                    }
                })
        else:
            checks.append({
                'name': 'Function Signature',
                'passed': False,
                'message': 'Transaction data too short or missing',
                'score': 20
            })
        
        # 4. 验证余额变化 (30 分)
        sender_balance_before = state_before.get('erc1155_balance', 0)
        sender_balance_after = state_after.get('erc1155_balance', 0)
        recipient_balance_before = state_before.get('target_erc1155_balance', 0)
        recipient_balance_after = state_after.get('target_erc1155_balance', 0)
        
        sender_decrease = sender_balance_before - sender_balance_after
        recipient_increase = recipient_balance_after - recipient_balance_before
        
        balance_check_passed = (
            sender_decrease == self.expected_amount and
            recipient_increase == self.expected_amount
        )
        
        if balance_check_passed:
            checks.append({
                'name': 'Balance Transfer',
                'passed': True,
                'message': f'Balances changed correctly: -{self.expected_amount} from sender, +{self.expected_amount} to recipient',
                'score': 30,
                'details': {
                    'sender_balance_before': sender_balance_before,
                    'sender_balance_after': sender_balance_after,
                    'sender_decrease': sender_decrease,
                    'recipient_balance_before': recipient_balance_before,
                    'recipient_balance_after': recipient_balance_after,
                    'recipient_increase': recipient_increase,
                    'expected_amount': self.expected_amount
                }
            })
            total_score += 30
        else:
            checks.append({
                'name': 'Balance Transfer',
                'passed': False,
                'message': f'Balance mismatch. Expected: {self.expected_amount}, Sender decrease: {sender_decrease}, Recipient increase: {recipient_increase}',
                'score': 30,
                'details': {
                    'sender_balance_before': sender_balance_before,
                    'sender_balance_after': sender_balance_after,
                    'sender_decrease': sender_decrease,
                    'recipient_balance_before': recipient_balance_before,
                    'recipient_balance_after': recipient_balance_after,
                    'recipient_increase': recipient_increase,
                    'expected_amount': self.expected_amount
                }
            })
        
        # 汇总结果
        all_passed = all(check['passed'] for check in checks)
        
        return {
            'passed': all_passed,
            'score': total_score,
            'max_score': self.max_score,
            'checks': checks,
            'details': {
                'nft_address': self.nft_address,
                'to_address': self.to_address,
                'token_id': self.token_id,
                'expected_amount': self.expected_amount,
                'sender_balance_before': sender_balance_before,
                'sender_balance_after': sender_balance_after,
                'recipient_balance_before': recipient_balance_before,
                'recipient_balance_after': recipient_balance_after,
                'actual_selector': actual_selector
            }
        }

