"""
验证器模块

包含各种原子问题的验证器
"""

from .bnb_transfer_validator import BNBTransferValidator
from .bnb_transfer_percentage_validator import BNBTransferPercentageValidator
from .bnb_transfer_with_message_validator import BNBTransferWithMessageValidator
from .bnb_transfer_to_contract_validator import BNBTransferToContractValidator
from .bnb_transfer_max_amount_validator import BNBTransferMaxAmountValidator
from .erc20_transfer_validator import ERC20TransferValidator
from .erc20_transfer_percentage_validator import ERC20TransferPercentageValidator
from .erc20_approve_validator import ERC20ApproveValidator
from .erc20_burn_validator import ERC20BurnValidator
from .erc20_revoke_approval_validator import ERC20RevokeApprovalValidator
from .erc20_transfer_max_amount_validator import ERC20TransferMaxAmountValidator
from .erc20_transfer_with_callback_1363_validator import ERC20TransferWithCallback1363Validator
from .erc20_approve_and_call_1363_validator import ERC20ApproveAndCall1363Validator
from .erc20_permit_and_transferfrom_validator import ERC20PermitAndTransferFromValidator
from .erc20_flashloan_validator import ERC20FlashLoanValidator
from .erc1155_transfer_single_validator import ERC1155TransferSingleValidator
from .erc1155_safe_transfer_with_data_validator import ERC1155SafeTransferWithDataValidator
from .erc721_transfer_validator import ERC721TransferValidator
from .erc721_safe_transfer_validator import ERC721SafeTransferValidator
from .erc721_approve_validator import ERC721ApproveValidator
from .erc721_set_approval_for_all_validator import ERC721SetApprovalForAllValidator
from .wbnb_deposit_validator import WBNBDepositValidator
from .wbnb_withdraw_validator import WBNBWithdrawValidator
from .contract_call_simple_validator import ContractCallSimpleValidator
from .contract_call_with_value_validator import ContractCallWithValueValidator
from .contract_call_with_params_validator import ContractCallWithParamsValidator
from .contract_delegate_call_validator import ContractDelegateCallValidator
from .contract_payable_fallback_validator import ContractPayableFallbackValidator

__all__ = [
    'BNBTransferValidator',
    'BNBTransferPercentageValidator',
    'BNBTransferWithMessageValidator',
    'BNBTransferToContractValidator',
    'BNBTransferMaxAmountValidator',
    'ERC20TransferValidator',
    'ERC20TransferPercentageValidator',
    'ERC20ApproveValidator',
    'ERC20BurnValidator',
    'ERC20RevokeApprovalValidator',
    'ERC20TransferMaxAmountValidator',
    'ERC20TransferWithCallback1363Validator',
    'ERC20ApproveAndCall1363Validator',
    'ERC20PermitAndTransferFromValidator',
    'ERC20FlashLoanValidator',
    'ERC1155TransferSingleValidator',
    'ERC1155SafeTransferWithDataValidator',
    'ERC721TransferValidator',
    'ERC721SafeTransferValidator',
    'ERC721ApproveValidator',
    'ERC721SetApprovalForAllValidator',
    'WBNBDepositValidator',
    'WBNBWithdrawValidator',
    'ContractCallSimpleValidator',
    'ContractCallWithValueValidator',
    'ContractCallWithParamsValidator',
    'ContractDelegateCallValidator',
    'ContractPayableFallbackValidator'
]

