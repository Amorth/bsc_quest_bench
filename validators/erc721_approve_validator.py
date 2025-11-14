"""
ERC721 Approve Validator

验证 ERC721 NFT 的 approve 操作是否正确执行。
"""

from typing import Dict, Any


class ERC721ApproveValidator:
    """验证 ERC721 授权操作"""
    
    def __init__(
        self,
        nft_address: str,
        spender_address: str,
        token_id: int
    ):
        self.nft_address = nft_address.lower()
        self.spender_address = spender_address.lower()
        self.token_id = token_id
        
        # approve(address,uint256) 函数选择器
        self.expected_selector = '0x095ea7b3'
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证 ERC721 授权交易
        
        检查项：
        1. 交易成功执行 (40%)
        2. 批准的地址正确设置 (40%)
        3. 使用了 approve 函数（正确的 selector）(20%)
        """
        results = []
        total_score = 0
        max_score = 100
        
        # 1. 验证交易成功 (40 分)
        tx_status = receipt.get('status', 0)
        if tx_status == 1:
            results.append({
                'check': 'Transaction Success',
                'passed': True,
                'message': 'Transaction executed successfully',
                'weight': 0.4
            })
            total_score += 40
        else:
            results.append({
                'check': 'Transaction Success',
                'passed': False,
                'message': f'Transaction failed with status: {tx_status}',
                'weight': 0.4
            })
            # 如果交易失败，直接返回
            return {
                'passed': False,
                'score': 0,
                'max_score': max_score,
                'checks': results,
                'details': {
                    'nft_address': self.nft_address,
                    'token_id': self.token_id,
                    'spender_address': self.spender_address,
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证批准的地址 (40 分)
        approved_before = state_before.get('nft_approved', '').lower() if state_before.get('nft_approved') else None
        approved_after = state_after.get('nft_approved', '').lower() if state_after.get('nft_approved') else None
        
        if approved_after and approved_after == self.spender_address:
            results.append({
                'check': 'Approval Check',
                'passed': True,
                'message': f'NFT #{self.token_id} correctly approved for {self.spender_address}',
                'weight': 0.4,
                'details': {
                    'approved_before': approved_before,
                    'approved_after': approved_after,
                    'expected': self.spender_address
                }
            })
            total_score += 40
        else:
            results.append({
                'check': 'Approval Check',
                'passed': False,
                'message': f'Approval not set correctly. Expected: {self.spender_address}, Got: {approved_after}',
                'weight': 0.4,
                'details': {
                    'approved_before': approved_before,
                    'approved_after': approved_after,
                    'expected': self.spender_address
                }
            })
        
        # 3. 验证使用了正确的函数 selector (20 分)
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
                    'message': f'Correct approve selector: {actual_selector}',
                    'weight': 0.2,
                    'details': {
                        'expected': self.expected_selector,
                        'actual': actual_selector
                    }
                })
                total_score += 20
            else:
                results.append({
                    'check': 'Function Selector',
                    'passed': False,
                    'message': f'Incorrect function selector. Expected approve ({self.expected_selector}), got {actual_selector}',
                    'weight': 0.2,
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
                'weight': 0.2
            })
        
        # 汇总结果
        all_passed = all(check['passed'] for check in results)
        
        return {
            'passed': all_passed,
            'score': total_score,
            'max_score': max_score,
            'checks': results,
            'details': {
                'nft_address': self.nft_address,
                'token_id': self.token_id,
                'spender_address': self.spender_address,
                'approved_before': approved_before,
                'approved_after': approved_after,
                'expected_selector': self.expected_selector,
                'actual_selector': actual_selector if len(tx_data) >= 8 else 'N/A'
            }
        }

