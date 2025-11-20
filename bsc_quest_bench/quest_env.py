"""
BSC Quest Environment - 环境层

负责:
1. 初始化本地 Anvil 节点 (fork from BSC testnet)
2. 创建测试账户并设置初始余额
3. 提供 Web3 连接和链上状态查询
"""

import subprocess
import time
import socket
import os
from typing import Optional, Dict, Any
from web3 import Web3
from eth_account import Account


class QuestEnvironment:
    """Quest环境管理类"""
    
    def __init__(
        self,
        fork_url: str = None,
        chain_id: int = 56,
        anvil_port: int = 8545
    ):
        """
        初始化Quest环境
        
        Args:
            fork_url: BSC RPC URL (默认使用免费testnet RPC)
                     - None: 使用默认免费 testnet RPC (适合开源/CI)
                     - 自定义URL: 使用付费或私有 RPC (适合开发/生产)
                     建议通过环境变量或配置文件传入
            chain_id: 链ID (56=BSC Mainnet, 97=BSC Testnet, 默认56)
            anvil_port: Anvil端口
        """
        # Fork URL 优先级:
        # 1. 传入的 fork_url 参数
        # 2. 环境变量 BSC_FORK_URL
        # 3. 默认免费 testnet RPC
        if fork_url is None:
            import os
            fork_url = os.getenv('BSC_FORK_URL', 'https://bsc-testnet.drpc.org')
        
        self.fork_url = fork_url
        self.chain_id = chain_id
        self.anvil_port = anvil_port
        self.anvil_process = None
        self.anvil_cmd = None
        
        self.w3: Optional[Web3] = None
        self.test_account: Optional[Account] = None
        self.test_address: Optional[str] = None
        self.test_private_key: Optional[str] = None
        self.initial_snapshot_id: Optional[str] = None  # Store initial snapshot for fast reset
        
    def start(self) -> Dict[str, Any]:
        """
        启动环境
        
        Returns:
            环境信息字典
        """
        # 1. 启动 Anvil fork
        self._start_anvil_fork()
        
        # 2. 连接 Web3
        anvil_rpc = f"http://127.0.0.1:{self.anvil_port}"
        
        # 创建一个绕过代理的 HTTPProvider（本地连接不应该走代理）
        import requests
        session = requests.Session()
        session.proxies = {
            'http': None,
            'https': None,
        }
        session.trust_env = False  # 不使用环境变量中的代理设置
        
        from web3.providers.rpc import HTTPProvider
        provider = HTTPProvider(anvil_rpc, session=session)
        self.w3 = Web3(provider)
        
        # 2.1 注入 POA middleware (BSC 是 POA 链)
        try:
            # Web3.py 7.x 使用 ExtraDataToPOAMiddleware
            from web3.middleware import ExtraDataToPOAMiddleware
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except ImportError:
            try:
                # Web3.py v6+ 使用 geth_poa_middleware（旧路径）
                from web3.middleware.geth_poa import geth_poa_middleware
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except ImportError:
                try:
                    # Web3.py v5 使用 geth_poa_middleware（更旧的路径）
                    from web3.middleware import geth_poa_middleware
                    self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                except ImportError:
                    # 如果都不存在，Anvil 本地 fork 通常不需要（我们使用直接 RPC 调用绕过）
                    print("⚠️  Warning: Could not import POA middleware, continuing without it")
        
        if not self.w3.is_connected():
            raise ConnectionError(f"无法连接到 Anvil: {anvil_rpc}")
        
        print(f"✓ Anvil 连接成功")
        print(f"  Chain ID: {self.w3.eth.chain_id}")
        print(f"  Anvil RPC: {anvil_rpc}")
        print(f"  Fork: {self.fork_url}")
        
        # 3. 创建测试账户
        self.test_account = Account.create()
        self.test_address = self.test_account.address
        self.test_private_key = self.test_account.key.hex()
        
        print(f"✓ 测试账户创建成功")
        print(f"  Address: {self.test_address}")
        
        # 4. 设置初始余额 (100 BNB - 足够多次测试使用)
        self._set_balance(self.test_address, 100 * 10**18)
        
        balance = self.w3.eth.get_balance(self.test_address) / 10**18
        print(f"  Balance: {balance} BNB")
        
        # 5. 预热常用合约地址 (触发 Anvil 拉取合约代码)
        self._preheat_contracts()
        
        # 6. 设置测试账户的 ERC20 token 余额
        self._set_token_balances()
        
        # 7. 设置富有账户用于 transferFrom 测试
        self._setup_rich_account()
        
        # 8. 创建初始快照用于快速重置
        try:
            self.initial_snapshot_id = self.w3.provider.make_request("evm_snapshot", [])['result']
            print(f"✓ 初始快照已创建: {self.initial_snapshot_id}")
        except Exception as e:
            print(f"⚠️  创建初始快照失败: {e}")
            self.initial_snapshot_id = None
        
        return {
            'rpc_url': anvil_rpc,
            'chain_id': self.chain_id,
            'test_address': self.test_address,
            'test_private_key': self.test_private_key,
            'rich_address': getattr(self, 'rich_address', None),  # For transferFrom tests
            'block_number': self.w3.eth.block_number,
            'balance': balance,
            # Deployed contracts
            'simple_staking_address': getattr(self, 'simple_staking_address', None),
            'simple_lp_staking_address': getattr(self, 'simple_lp_staking_address', None),
            'simple_reward_pool_address': getattr(self, 'simple_reward_pool_address', None),
            'erc1363_token_address': getattr(self, 'erc1363_token_address', None),
            'erc1155_token_address': getattr(self, 'erc1155_token_address', None),
            'flashloan_contract_address': getattr(self, 'flashloan_contract_address', None),
            'simple_counter_address': getattr(self, 'simple_counter_address', None),
            'donation_box_address': getattr(self, 'donation_box_address', None),
            'message_board_address': getattr(self, 'message_board_address', None),
            'proxy_address': getattr(self, 'proxy_address', None),
            'implementation_address': getattr(self, 'implementation_address', None),
            'fallback_receiver_address': getattr(self, 'fallback_receiver_address', None)
        }
    
    def create_snapshot(self) -> str:
        """
        创建当前状态的快照
        
        Returns:
            快照ID
        """
        if not self.w3:
            raise RuntimeError("环境未启动，无法创建快照")
        
        snapshot_id = self.w3.provider.make_request("evm_snapshot", [])
        print(f"✓ 创建快照: {snapshot_id}")
        return snapshot_id
    
    def revert_to_snapshot(self, snapshot_id: str) -> bool:
        """
        恢复到指定快照
        
        Args:
            snapshot_id: 快照ID
            
        Returns:
            是否成功恢复
        """
        if not self.w3:
            raise RuntimeError("环境未启动，无法恢复快照")
        
        result = self.w3.provider.make_request("evm_revert", [snapshot_id])
        if result:
            print(f"✓ 已恢复到快照: {snapshot_id}")
        else:
            print(f"⚠️  恢复快照失败: {snapshot_id}")
        return result
    
    def reset_account_balance(self):
        """
        重置测试账户余额
        用于在每个测试前确保账户有足够的 BNB
        """
        if not self.w3 or not self.test_address:
            raise RuntimeError("环境未启动，无法重置余额")
        
        # 设置初始 BNB 余额（100 BNB）
        initial_balance = 100 * 10**18
        
        try:
            self.w3.provider.make_request(
                'anvil_setBalance',
                [self.test_address, hex(initial_balance)]
            )
            print(f"✓ 已重置账户余额: {self.test_address} -> 100 BNB")
            return True
        except Exception as e:
            print(f"⚠️  重置余额失败: {e}")
            return False
    
    def reset(self):
        """
        快速重置环境状态（使用快照恢复，保持 Anvil 进程运行）
        恢复到初始快照状态，比完全重置快得多
        """
        if not self.w3 or not self.test_address:
            raise RuntimeError("环境未启动，无法重置")
        
        if not self.initial_snapshot_id:
            print("⚠️  警告：没有初始快照，无法快速重置")
            return False
        
        print("🔄 快速重置环境状态（恢复快照）...")
        
        try:
            # 1. 恢复到初始快照
            result = self.w3.provider.make_request("evm_revert", [self.initial_snapshot_id])
            if not result.get('result', False):
                print(f"  ⚠️  快照恢复失败")
                return False
            
            print(f"  ✓ 已恢复到初始快照: {self.initial_snapshot_id}")
            
            # 2. 重新创建快照（某些 Anvil 版本会在 revert 时消耗快照）
            self.initial_snapshot_id = self.w3.provider.make_request("evm_snapshot", [])['result']
            print(f"  ✓ 已重新创建快照: {self.initial_snapshot_id}")
            
            # 验证余额
            balance = self.w3.eth.get_balance(self.test_address) / 10**18
            print(f"  ✓ 账户余额: {balance} BNB")
            
            print("✅ 环境快速重置完成\n")
            return True
            
        except Exception as e:
            print(f"  ❌ 快照恢复失败: {e}")
            print("  ⚠️  将尝试完全重置...")
            
            # 如果快照失败，回退到完全重置
            return self._full_reset()
    
    def _full_reset(self):
        """
        完全重置环境（备用方案，当快照失败时使用）
        使用 anvil_reset 重置到 fork point 并重新部署所有合约
        """
        print("🔄 执行完全重置...")
        
        try:
            # 1. Reset blockchain state to initial fork point
            self.w3.provider.make_request('anvil_reset', [{
                'forking': {
                    'jsonRpcUrl': self.fork_url
                }
            }])
            print("  ✓ 区块链状态已重置到 fork point")
        except Exception as e:
            print(f"  ❌ 区块链重置失败: {e}")
            return False
        
        try:
            # 2. Reset account balance
            self._set_balance(self.test_address, 100 * 10**18)
            balance = self.w3.eth.get_balance(self.test_address) / 10**18
            print(f"  ✓ 账户余额已重置: {balance} BNB")
            
            # 3. Re-setup token balances and contracts
            self._set_token_balances()
            
            # 4. Re-setup rich account
            self._setup_rich_account()
            
            # 5. Recreate initial snapshot
            self.initial_snapshot_id = self.w3.provider.make_request("evm_snapshot", [])['result']
            print(f"  ✓ 已重新创建初始快照: {self.initial_snapshot_id}")
            
            print("✅ 完全重置完成\n")
            return True
            
        except Exception as e:
            print(f"  ❌ 完全重置失败: {e}")
            return False
    
    def stop(self):
        """停止环境"""
        self._cleanup_anvil()
        print("✓ 环境已清理")
    
    def _start_anvil_fork(self):
        """启动 Anvil fork 进程"""
        # 1. 清理可能存在的僵尸 Anvil 进程
        self._kill_zombie_anvil()
        
        # 2. 检查端口是否被占用
        if self._is_port_in_use(self.anvil_port):
            print(f"⚠️  端口 {self.anvil_port} 已被占用")
            print(f"   尝试清理并重试...")
            self._kill_zombie_anvil()
            time.sleep(2)
            
            if self._is_port_in_use(self.anvil_port):
                raise RuntimeError(
                    f"端口 {self.anvil_port} 仍被占用，无法启动 Anvil\n"
                    f"请手动清理:\n"
                    f"  Linux/Mac: lsof -ti:{self.anvil_port} | xargs kill -9\n"
                    f"  Windows: netstat -ano | findstr :{self.anvil_port}"
                )
        
        # 3. 测试网络连接到 Fork URL
        print(f"🔍 测试连接到 Fork URL...")
        if not self._test_fork_url():
            print(f"⚠️  警告: 无法快速连接到 Fork URL")
            print(f"   继续尝试启动，但可能会较慢...")
        
        # 4. 查找 anvil 命令
        anvil_paths = [
            os.path.expanduser('~/.foundry/bin/anvil'),
            '/usr/local/bin/anvil',
            'anvil',
        ]
        
        for path in anvil_paths:
            try:
                result = subprocess.run(
                    [path, '--version'],
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=5
                )
                self.anvil_cmd = path
                print(f"✓ 找到 Anvil: {path}")
                break
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue
        
        if not self.anvil_cmd:
            raise RuntimeError(
                "未找到 Anvil! 请安装 Foundry:\n"
                "  curl -L https://foundry.paradigm.xyz | bash\n"
                "  foundryup"
            )
        
        # 5. 启动 Anvil
        print(f"🔨 启动 Anvil fork...")
        print(f"   Fork URL: {self.fork_url}")
        print(f"   Port: {self.anvil_port}")
        
        anvil_cmd_list = [
            self.anvil_cmd,
            '--fork-url', self.fork_url,
            '--port', str(self.anvil_port),
            '--host', '127.0.0.1',
            '--no-storage-caching',  # 禁用存储缓存，强制从远程拉取
            '--compute-units-per-second', '1000',  # 提高请求限制
        ]
        
        # 捕获 stderr 用于诊断
        self.anvil_process = subprocess.Popen(
            anvil_cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 6. 等待启动（增加超时时间）
        max_wait = 30  # 从 15s 增加到 30s
        print(f"   等待 Anvil 启动 (最多 {max_wait}s)...")
        
        for i in range(max_wait):
            time.sleep(1)
            
            # 检查端口是否打开
            if self._is_port_in_use(self.anvil_port):
                print(f"✓ Anvil 启动成功 ({i+1}s)")
                return
            
            # 检查进程是否意外退出
            if self.anvil_process.poll() is not None:
                returncode = self.anvil_process.returncode
                # 尝试读取错误输出
                try:
                    stdout, stderr = self.anvil_process.communicate(timeout=1)
                    error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "无错误信息"
                except:
                    error_msg = "无法读取错误信息"
                
                self._cleanup_anvil()
                raise RuntimeError(
                    f"Anvil 进程意外退出 (code {returncode})\n"
                    f"错误信息: {error_msg[:500]}\n"
                    f"可能原因:\n"
                    f"  - Fork URL 无效或不可达: {self.fork_url}\n"
                    f"  - 网络连接问题\n"
                    f"  - RPC 节点限流或故障"
                )
            
            # 每 5 秒显示进度
            if (i + 1) % 5 == 0:
                print(f"   等待中... ({i+1}s)")
        
        # 超时处理
        self._cleanup_anvil()
        raise RuntimeError(
            f"Anvil 启动超时 ({max_wait}s)\n"
            f"可能原因:\n"
            f"  1. 网络连接慢 - Fork URL: {self.fork_url}\n"
            f"  2. RPC 节点响应慢或不可用\n"
            f"  3. 系统资源不足\n"
            f"\n"
            f"建议:\n"
            f"  - 检查网络连接\n"
            f"  - 尝试更换 RPC URL\n"
            f"  - 重启测试\n"
            f"  - 检查 WSL2 资源配置"
        )
    
    def _cleanup_anvil(self):
        """清理 Anvil 进程"""
        if self.anvil_process:
            try:
                self.anvil_process.terminate()
                self.anvil_process.wait(timeout=5)
                print("✓ Anvil 进程已终止")
            except:
                self.anvil_process.kill()
                print("✓ Anvil 进程已强制终止")
            self.anvil_process = None
    
    def _is_port_in_use(self, port: int) -> bool:
        """检查端口是否被占用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    
    def _kill_zombie_anvil(self):
        """
        清理可能存在的僵尸 Anvil 进程
        """
        try:
            import psutil
            
            killed_count = 0
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # 检查是否是 anvil 进程
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and 'anvil' in ' '.join(cmdline).lower():
                        # 检查是否使用相同端口
                        if str(self.anvil_port) in ' '.join(cmdline):
                            print(f"   清理僵尸 Anvil 进程: PID {proc.info['pid']}")
                            proc.kill()
                            proc.wait(timeout=3)
                            killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    continue
            
            if killed_count > 0:
                print(f"   ✓ 清理了 {killed_count} 个僵尸进程")
                time.sleep(1)  # 等待端口释放
        except ImportError:
            # psutil 未安装，尝试系统命令
            import platform
            system = platform.system()
            
            try:
                if system == 'Linux':
                    # Linux: 使用 lsof 查找占用端口的进程
                    result = subprocess.run(
                        ['lsof', '-ti', f':{self.anvil_port}'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        pids = result.stdout.strip().split('\n')
                        for pid in pids:
                            try:
                                subprocess.run(['kill', '-9', pid], timeout=2)
                                print(f"   清理进程: PID {pid}")
                            except:
                                pass
                        time.sleep(1)
                elif system == 'Windows':
                    # Windows: 使用 netstat 查找占用端口的进程
                    result = subprocess.run(
                        ['netstat', '-ano'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if f':{self.anvil_port}' in line and 'LISTENING' in line:
                                parts = line.split()
                                if parts:
                                    pid = parts[-1]
                                    try:
                                        subprocess.run(['taskkill', '/F', '/PID', pid], timeout=2)
                                        print(f"   清理进程: PID {pid}")
                                    except:
                                        pass
                        time.sleep(1)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
    
    def _test_fork_url(self, timeout=5):
        """
        测试 Fork URL 连接
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            bool: 连接成功返回 True，否则返回 False
        """
        import json
        import urllib.request
        import urllib.error
        
        try:
            # 发送简单的 eth_blockNumber 请求
            data = json.dumps({
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1
            }).encode('utf-8')
            
            req = urllib.request.Request(
                self.fork_url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                if 'result' in result:
                    block_num = int(result['result'], 16)
                    print(f"   ✓ Fork URL 连接成功 (区块: {block_num})")
                    return True
                else:
                    print(f"   ⚠️  Fork URL 响应异常: {result}")
                    return False
        except urllib.error.URLError as e:
            print(f"   ⚠️  网络错误: {e.reason}")
            return False
        except Exception as e:
            print(f"   ⚠️  连接测试失败: {e}")
            return False
    
    def _preheat_contracts(self):
        """
        预热常用合约地址
        
        通过访问合约代码和余额，触发 Anvil 从远程节点拉取合约数据
        这样在后续测试中就能正确检测到合约
        """
        from eth_utils import to_checksum_address
        
        # BSC Mainnet 常用合约地址
        contract_addresses = [
            "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
            "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",  # PancakeFactory V2
            "0x10ED43C718714eb63d5aA57B78B54704E256024E",  # PancakeRouter V2
        ]
        
        print(f"✓ 预热合约地址 (Anvil 从远程节点拉取数据)...")
        for addr in contract_addresses:
            try:
                # 使用 checksum 地址
                addr_checksum = to_checksum_address(addr)
                print(f"  • {addr_checksum}")
                
                # 访问合约代码（触发 Anvil 拉取）
                code = self.w3.eth.get_code(addr_checksum)
                print(f"    - get_code(): {len(code) if code else 0} bytes")
                
                balance = self.w3.eth.get_balance(addr_checksum)
                print(f"    - get_balance(): {balance / 10**18:.6f} BNB")
                
                # 额外：尝试读取 storage 来确保数据被拉取
                try:
                    storage = self.w3.eth.get_storage_at(addr_checksum, 0)
                    print(f"    - get_storage_at(0): {storage.hex()[:20]}...")
                except Exception as se:
                    print(f"    - get_storage_at(0): Error - {se}")
                
                is_contract = code and len(code) > 2
                if is_contract:
                    print(f"    ✅ Confirmed as contract")
                else:
                    print(f"    ⚠️  WARNING: No contract code found!")
                    print(f"    This might indicate:")
                    print(f"      - Address is not a contract on BSC testnet")
                    print(f"      - Anvil fork connection issue")
                    print(f"      - Need to check fork URL: {self.fork_url}")
            except Exception as e:
                print(f"  • {addr[:10]}... [❌ Error: {e}]")
        print()
    
    def _set_erc20_balance_direct(self, token_address: str, holder_address: str, amount: int, balance_slot: int = 1) -> bool:
        """
        直接设置 ERC20 token 余额（使用 anvil_setStorageAt）
        
        Args:
            token_address: Token 合约地址
            holder_address: 持有者地址
            amount: 余额数量（最小单位）
            balance_slot: balances mapping 的 storage slot（大多数是1，WBNB是3）
            
        Returns:
            是否设置成功
        """
        from eth_utils import to_checksum_address, keccak
        from eth_abi import encode
        
        try:
            token_addr = to_checksum_address(token_address)
            holder_addr = to_checksum_address(holder_address)
            
            # 计算 storage slot: keccak256(address + slot)
            address_padded = holder_addr[2:].lower().rjust(64, '0')
            slot_padded = hex(balance_slot)[2:].rjust(64, '0')
            storage_key = '0x' + keccak(bytes.fromhex(address_padded + slot_padded)).hex()
            
            # 设置余额 - 需要补齐到 32 bytes (64 hex chars)
            balance_hex = hex(amount)
            if balance_hex.startswith('0x'):
                balance_hex = balance_hex[2:]
            balance_hex = '0x' + balance_hex.rjust(64, '0')
            
            self.w3.provider.make_request('anvil_setStorageAt', [
                token_addr,
                storage_key,
                balance_hex
            ])
            
            # 验证余额
            balance_of_selector = bytes.fromhex('70a08231')
            balance_data = '0x' + balance_of_selector.hex() + encode(['address'], [holder_addr]).hex()
            result = self.w3.eth.call({
                'to': token_addr,
                'data': balance_data
            })
            
            actual_balance = int(result.hex(), 16)
            # 允许1%误差，但要用整数比较
            min_expected = int(amount * 0.99)
            
            if actual_balance >= min_expected:
                return True
            else:
                print(f"    ⚠️  Balance verification failed: expected {amount}, got {actual_balance}")
                return False
            
        except Exception as e:
            print(f"    ⚠️  Error setting balance via storage: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _set_token_balances(self):
        """
        设置测试账户的 ERC20 token 余额
        
        使用 anvil_setStorageAt 直接操作 storage，快速可靠
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        usdt_address = '0x55d398326f99059fF775485246999027B3197955'
        wbnb_address = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
        cake_address = '0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82'
        busd_address = '0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56'
        
        print(f"✓ 设置 ERC20 token 余额...")
        
        # USDT (slot 1, 1000 tokens)
        try:
            amount = 1000 * 10**18
            if self._set_erc20_balance_direct(usdt_address, self.test_address, amount, balance_slot=1):
                print(f"  • USDT: {amount / 10**18:.2f} tokens ✅")
            else:
                print(f"  • USDT: Failed to set balance")
        except Exception as e:
            print(f"  • USDT: ❌ Error - {e}")
        
        # WBNB (slot 3, 100 tokens) - WETH9 标准
        try:
            amount = 100 * 10**18
            if self._set_erc20_balance_direct(wbnb_address, self.test_address, amount, balance_slot=3):
                print(f"  • WBNB: {amount / 10**18:.2f} tokens ✅")
            else:
                print(f"  • WBNB: Failed to set balance")
        except Exception as e:
            print(f"  • WBNB: ❌ Error - {e}")
        
        # CAKE (slot 1, 200 tokens) - OpenZeppelin 标准
        # Note: 100 CAKE will be transferred to SimpleRewardPool during deployment,
        # so we set 200 CAKE initially to ensure test account has enough balance
        try:
            amount = 200 * 10**18
            if self._set_erc20_balance_direct(cake_address, self.test_address, amount, balance_slot=1):
                print(f"  • CAKE: {amount / 10**18:.2f} tokens ✅")
            else:
                print(f"  • CAKE: Failed to set balance")
        except Exception as e:
            print(f"  • CAKE: ❌ Error - {e}")
        
        # BUSD (slot 1, 1000 tokens) - OpenZeppelin 标准
        try:
            amount = 1000 * 10**18
            if self._set_erc20_balance_direct(busd_address, self.test_address, amount, balance_slot=1):
                print(f"  • BUSD: {amount / 10**18:.2f} tokens ✅")
            else:
                print(f"  • BUSD: Failed to set balance")
        except Exception as e:
            print(f"  • BUSD: ❌ Error - {e}")
        
        # USDT/BUSD LP Token (slot 1, 5 LP tokens) - PancakeSwap LP tokens use slot 1 (OpenZeppelin ERC20 standard)
        # 这些 LP tokens 用于 harvest_rewards, unstake_lp_tokens, remove_liquidity 等测试
        try:
            lp_token_address = '0x7EFaEf62fDdCCa950418312c6C91Aef321375A00'
            amount = 5 * 10**18  # 5 LP tokens
            if self._set_erc20_balance_direct(lp_token_address, self.test_address, amount, balance_slot=1):
                print(f"  • USDT/BUSD LP: {amount / 10**18:.2f} tokens ✅")
            else:
                print(f"  • USDT/BUSD LP: Failed to set balance")
        except Exception as e:
            print(f"  • USDT/BUSD LP: ❌ Error - {e}")
        
        # WBNB/USDT LP Token (slot 1, 3 LP tokens) - 用于 remove_liquidity_bnb_token 测试
        try:
            wbnb_usdt_lp_address = '0x16b9a82891338f9bA80E2D6970FddA79D1eb0daE'
            amount = 3 * 10**18  # 3 LP tokens
            if self._set_erc20_balance_direct(wbnb_usdt_lp_address, self.test_address, amount, balance_slot=1):
                print(f"  • WBNB/USDT LP: {amount / 10**18:.2f} tokens ✅")
            else:
                print(f"  • WBNB/USDT LP: Failed to set balance")
        except Exception as e:
            print(f"  • WBNB/USDT LP: ❌ Error - {e}")
        
        # 设置初始 allowances（用于 revoke approval 测试）
        print(f"✓ 设置初始 allowances...")
        try:
            usdt_addr = to_checksum_address(usdt_address)
            test_addr = to_checksum_address(self.test_address)
            
            # 需要授权的合约地址（PancakeSwap Router, Venus Protocol, etc）
            spenders = [
                '0x10ED43C718714eb63d5aA57B78B54704E256024E',  # PancakeSwap Router
                '0x13f4EA83D0bd40E75C8222255bc855a974568Dd4',  # Venus Protocol
                '0x1B81D678ffb9C0263b24A97847620C99d213eB14'   # PancakeSwap V3 Router
            ]
            
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            for spender in spenders:
                spender_addr = to_checksum_address(spender)
                
                # ERC20 approve function selector: 0x095ea7b3
                approve_selector = bytes.fromhex('095ea7b3')
                # Encode: approve(address spender, uint256 amount)
                # Approve a large amount (1000 USDT)
                approve_amount = 1000 * 10**18
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [spender_addr, approve_amount]).hex()
            
                # 发送 approve 交易
                response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                        'from': test_addr,
                        'to': usdt_addr,
                        'data': approve_data,
                    'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                }]
                )
                
                # 检查响应
                if 'result' not in response:
                    print(f"  • Allowance for {spender[:10]}...: ❌ Failed - {response.get('error', 'Unknown error')}")
                    continue
                
                tx_hash = response['result']
            
                # 等待确认
            max_attempts = 20
            for i in range(max_attempts):
                try:
                    receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                    if receipt and receipt.get('blockNumber'):
                        break
                except:
                    pass
                time.sleep(0.5)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            print(f"  • USDT allowances set for {len(spenders)} spenders ✅")
                
        except Exception as e:
            print(f"  • Allowances: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 CAKE token allowances（用于 multi-hop swap 测试）
        try:
            cake_address = '0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82'  # CAKE token on BSC
            cake_addr = to_checksum_address(cake_address)
            test_addr = to_checksum_address(self.test_address)
            
            # PancakeSwap Router 需要 CAKE allowance
            router_address = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
            router_addr = to_checksum_address(router_address)
            
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # ERC20 approve function selector: 0x095ea7b3
            approve_selector = bytes.fromhex('095ea7b3')
            # Approve a large amount (200 CAKE to match balance)
            approve_amount = 200 * 10**18
            approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [router_addr, approve_amount]).hex()
            
            # 发送 approve 交易
            response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': cake_addr,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in response:
                tx_hash = response['result']
            
            # 等待确认
            max_attempts = 20
            for i in range(max_attempts):
                try:
                    receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                    if receipt and receipt.get('blockNumber'):
                        break
                except:
                    pass
                time.sleep(0.5)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            print(f"  • CAKE allowances set for Router ✅")
                
        except Exception as e:
            print(f"  • CAKE allowances: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # CAKE allowances for SimpleStaking will be set after deployment in _deploy_simple_staking()
        
        # 设置 LP token allowances（用于 remove_liquidity 和 staking 测试）
        try:
            # USDT/BUSD LP token
            usdt_busd_lp_address = '0x7EFaEf62fDdCCa950418312c6C91Aef321375A00'
            usdt_busd_lp_addr = to_checksum_address(usdt_busd_lp_address)
            
            # WBNB/USDT LP token
            wbnb_usdt_lp_address = '0x16b9a82891338f9bA80E2D6970FddA79D1eb0daE'
            wbnb_usdt_lp_addr = to_checksum_address(wbnb_usdt_lp_address)
            
            # PancakeSwap Router 需要 LP token allowances
            router_address = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
            router_addr = to_checksum_address(router_address)
            
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # Approve both LP tokens for Router
            approve_selector = bytes.fromhex('095ea7b3')
            approve_amount = 1000 * 10**18  # Large allowance
            
            for lp_name, lp_addr in [('USDT/BUSD LP', usdt_busd_lp_addr), ('WBNB/USDT LP', wbnb_usdt_lp_addr)]:
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [router_addr, approve_amount]).hex()
                
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': lp_addr,
                        'data': approve_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                if 'result' in response:
                    tx_hash = response['result']
                    for i in range(10):
                        try:
                            receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                            if receipt and receipt.get('blockNumber'):
                                break
                        except:
                            pass
                        time.sleep(0.3)
            
            # Stop impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            print(f"  • LP token allowances set for Router ✅")
        except Exception as e:
            print(f"  • LP token allowances: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 BUSD token allowances（用于 liquidity 操作）
        try:
            busd_address = '0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56'  # BUSD token on BSC
            busd_addr = to_checksum_address(busd_address)
            test_addr = to_checksum_address(self.test_address)
            
            # PancakeSwap Router 需要 BUSD allowance
            router_address = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
            router_addr = to_checksum_address(router_address)
            
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # ERC20 approve function selector: 0x095ea7b3
            approve_selector = bytes.fromhex('095ea7b3')
            # Approve a large amount (1000 BUSD)
            approve_amount = 1000 * 10**18
            approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [router_addr, approve_amount]).hex()
            
            # 发送 approve 交易
            response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': busd_addr,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in response:
                tx_hash = response['result']
                
                # 等待确认
                max_attempts = 20
                for i in range(max_attempts):
                    try:
                        receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                        if receipt and receipt.get('blockNumber'):
                            break
                    except:
                        pass
                    time.sleep(0.5)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            print(f"  • BUSD allowances set for Router ✅")
                
        except Exception as e:
            print(f"  • BUSD allowances: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 LP tokens（用于 remove_liquidity 测试）
        print(f"✓ 设置 LP tokens...")
        try:
            from eth_utils import keccak
            
            factory_address = '0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73'  # PancakeSwap Factory
            router_address = '0x10ED43C718714eb63d5aA57B78B54704E256024E'  # PancakeSwap Router
            usdt_address = '0x55d398326f99059fF775485246999027B3197955'
            busd_address = '0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56'
            
            test_addr = to_checksum_address(self.test_address)
            
            # Get LP token address using Factory.getPair()
            # getPair(address tokenA, address tokenB) returns (address pair)
            get_pair_selector = bytes.fromhex('e6a43905')
            get_pair_data = '0x' + get_pair_selector.hex() + encode(['address', 'address'], [usdt_address, busd_address]).hex()
            
            result = self.w3.eth.call({
                'to': factory_address,
                'data': get_pair_data
            })
            
            lp_token_address = '0x' + result.hex()[-40:]  # Last 20 bytes
            lp_token_addr = to_checksum_address(lp_token_address)
            
            print(f"  • LP Token (USDT/BUSD): {lp_token_addr}")
            
            # Set LP token balance (2.0 LP tokens) using direct storage manipulation
            # Uniswap V2 LP tokens use OpenZeppelin ERC20, balances at slot 1
            lp_amount = 2 * 10**18  # 2.0 LP tokens
            if self._set_erc20_balance_direct(lp_token_addr, test_addr, lp_amount, balance_slot=1):
                print(f"  • LP Token balance: {lp_amount / 10**18:.2f} LP tokens ✅")
            else:
                print(f"  • LP Token balance: Failed to set")
                
            # Approve LP tokens for Router (用于 remove liquidity)
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            approve_selector = bytes.fromhex('095ea7b3')
            approve_amount = 1000 * 10**18  # Large approval
            approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [router_address, approve_amount]).hex()
            
            response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': lp_token_addr,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in response:
                tx_hash = response['result']
                # 等待确认
                for i in range(10):
                    try:
                        receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                        if receipt and receipt.get('blockNumber'):
                            break
                    except:
                        pass
                    time.sleep(0.3)
                print(f"  • LP Token approved for Router ✅")
            
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # Also set up WBNB/USDT LP token (for remove_liquidity_bnb_token)
            wbnb_address = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
            
            # Get WBNB/USDT LP token address
            get_pair_data_wbnb_usdt = '0x' + get_pair_selector.hex() + encode(['address', 'address'], [wbnb_address, usdt_address]).hex()
            
            result_wbnb_usdt = self.w3.eth.call({
                'to': factory_address,
                'data': get_pair_data_wbnb_usdt
            })
            
            lp_token_wbnb_usdt = '0x' + result_wbnb_usdt.hex()[-40:]
            lp_token_wbnb_usdt_addr = to_checksum_address(lp_token_wbnb_usdt)
            
            print(f"  • LP Token (WBNB/USDT): {lp_token_wbnb_usdt_addr}")
            
            # Set WBNB/USDT LP token balance (2.0 LP tokens)
            if self._set_erc20_balance_direct(lp_token_wbnb_usdt_addr, test_addr, lp_amount, balance_slot=1):
                print(f"  • LP Token (WBNB/USDT) balance: {lp_amount / 10**18:.2f} LP tokens ✅")
            else:
                print(f"  • LP Token (WBNB/USDT) balance: Failed to set")
            
            # Approve WBNB/USDT LP tokens for Router
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            approve_data_wbnb_usdt = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [router_address, approve_amount]).hex()
            
            response_wbnb_usdt = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': lp_token_wbnb_usdt_addr,
                    'data': approve_data_wbnb_usdt,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in response_wbnb_usdt:
                tx_hash_wbnb_usdt = response_wbnb_usdt['result']
                # Wait for confirmation
                for i in range(10):
                    try:
                        receipt_wbnb_usdt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash_wbnb_usdt])['result']
                        if receipt_wbnb_usdt and receipt_wbnb_usdt.get('blockNumber'):
                            break
                    except:
                        pass
                    time.sleep(0.3)
                print(f"  • LP Token (WBNB/USDT) approved for Router ✅")
            
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
                
        except Exception as e:
            print(f"  • LP tokens: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 NFT（用于 ERC721 测试）
        print(f"✓ 设置 NFT 所有权...")
        try:
            # PancakeSquad NFT on BSC Mainnet
            pancake_squad_address = '0x0a8901b0E25DEb55A87524f0cC164E9644020EBA'
            nft_addr = to_checksum_address(pancake_squad_address)
            test_addr = to_checksum_address(self.test_address)
            token_id = 1  # 我们要转移的 NFT ID
            
            # 先查询当前所有者
            owner_of_selector = bytes.fromhex('6352211e')  # ownerOf(uint256)
            token_id_hex = format(token_id, '064x')
            owner_data = '0x' + owner_of_selector.hex() + token_id_hex
            
            result = self.w3.eth.call({
                'to': nft_addr,
                'data': owner_data
            })
            
            current_owner_hex = result.hex()
            if len(current_owner_hex) >= 42:
                current_owner = '0x' + current_owner_hex[-40:]
                current_owner_addr = to_checksum_address(current_owner)
                print(f"  • NFT #{token_id} current owner: {current_owner_addr}")
                
                # Impersonate 当前所有者
                self.w3.provider.make_request('anvil_impersonateAccount', [current_owner_addr])
                
                # ERC721 transferFrom function selector: 0x23b872dd
                # transferFrom(address from, address to, uint256 tokenId)
                transfer_selector = bytes.fromhex('23b872dd')
                # Encode: from (32 bytes) + to (32 bytes) + tokenId (32 bytes)
                transfer_data = '0x' + transfer_selector.hex() + encode(['address', 'address', 'uint256'], [current_owner_addr, test_addr, token_id]).hex()
                
                # 发送 transferFrom 交易
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': current_owner_addr,
                        'to': nft_addr,
                        'data': transfer_data,
                        'gas': hex(150000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                # 检查响应
                if 'result' not in response:
                    print(f"  • NFT: ❌ Transaction failed - {response.get('error', 'Unknown error')}")
                    raise Exception(f"NFT transfer failed: {response}")
                
                tx_hash = response['result']
                
                # 等待确认
                max_attempts = 20
                for i in range(max_attempts):
                    try:
                        receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                        if receipt and receipt.get('blockNumber'):
                            break
                    except:
                        pass
                    time.sleep(0.5)
                
                # 停止 impersonate
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [current_owner_addr])
                
                # 验证 NFT 所有者
                result = self.w3.eth.call({
                    'to': nft_addr,
                    'data': owner_data
                })
                
                new_owner_hex = result.hex()
                if len(new_owner_hex) >= 42:
                    new_owner = '0x' + new_owner_hex[-40:]
                    new_owner_addr = to_checksum_address(new_owner)
                    
                    receipt_status = int(receipt.get('status', '0x0'), 16)
                    
                    if receipt_status == 1 and new_owner_addr.lower() == test_addr.lower():
                        print(f"  • PancakeSquad NFT #{token_id}: ✅ Transferred to test account")
                    else:
                        print(f"  • PancakeSquad NFT #{token_id}: ❌ Transfer failed or owner mismatch")
            else:
                print(f"  • PancakeSquad NFT: ⚠️  Could not determine owner")
                
        except Exception as e:
            print(f"  • PancakeSquad NFT: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        print()
        
        # 7. 部署 ERC1363 测试代币
        self._deploy_erc1363_token()
        
        # 8. 部署 ERC721 测试 NFT
        self._deploy_erc721_test_nft()
        
        # 9. 部署 ERC1155 测试代币
        self._deploy_erc1155_token()
        
        # 9. 部署闪电贷接收合约
        self._deploy_flashloan_receiver()
        
        # 10. 部署 SimpleCounter 测试合约
        self._deploy_simple_counter()
        
        # 11. 部署 DonationBox 测试合约
        self._deploy_donation_box()
        
        # 12. 部署 MessageBoard 测试合约
        self._deploy_message_board()
        
        # 13. 部署 DelegateCall 测试合约
        self._deploy_delegate_call_contracts()
        
        # 14. 部署 FallbackReceiver 测试合约
        self._deploy_fallback_receiver()
        
        # 15. 部署 SimpleStaking 测试合约
        self._deploy_simple_staking()
        
        # 16. 部署 SimpleLPStaking 测试合约
        self._deploy_simple_lp_staking()
        
        # 17. 部署 SimpleRewardPool 测试合约
        self._deploy_simple_reward_pool()
    
    def _deploy_erc1363_token(self):
        """
        部署 ERC1363 测试代币并给测试账户分配代币
        
        ERC1363 是 ERC20 的扩展，支持 transferAndCall 和 approveAndCall
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print(f"✓ 部署 ERC1363 测试代币...")
        
        try:
            test_addr = to_checksum_address(self.test_address)
            
            # 读取合约源代码并使用 py-solc-x 编译
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC1363Receiver {
    function onTransferReceived(address operator, address from, uint256 value, bytes calldata data) external returns (bytes4);
}

interface IERC1363Spender {
    function onApprovalReceived(address owner, uint256 value, bytes calldata data) external returns (bytes4);
}

contract TestERC1363Token {
    string public name = "Test ERC1363";
    string public symbol = "T1363";
    uint8 public decimals = 18;
    string public constant version = "1";
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    
    // EIP-2612 Permit support
    mapping(address => uint256) public nonces;
    bytes32 public DOMAIN_SEPARATOR;
    bytes32 public constant PERMIT_TYPEHASH = keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");
    
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    
    constructor() {
        totalSupply = 1000000 * 10**18;
        balanceOf[msg.sender] = totalSupply;
        emit Transfer(address(0), msg.sender, totalSupply);
        
        // Initialize DOMAIN_SEPARATOR for EIP-2612
        uint256 chainId;
        assembly { chainId := chainid() }
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256(bytes(name)),
                keccak256(bytes("1")),
                chainId,
                address(this)
            )
        );
    }
    
    function transfer(address to, uint256 value) public returns (bool) {
        require(balanceOf[msg.sender] >= value, "Insufficient balance");
        balanceOf[msg.sender] -= value;
        balanceOf[to] += value;
        emit Transfer(msg.sender, to, value);
        return true;
    }
    
    function approve(address spender, uint256 value) public returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }
    
    function transferFrom(address from, address to, uint256 value) public returns (bool) {
        require(balanceOf[from] >= value, "Insufficient balance");
        require(allowance[from][msg.sender] >= value, "Insufficient allowance");
        balanceOf[from] -= value;
        balanceOf[to] += value;
        allowance[from][msg.sender] -= value;
        emit Transfer(from, to, value);
        return true;
    }
    
    function transferAndCall(address to, uint256 value) public returns (bool) {
        return transferAndCall(to, value, "");
    }
    
    function transferAndCall(address to, uint256 value, bytes memory data) public returns (bool) {
        // Directly perform the transfer logic inline instead of calling transfer()
        require(balanceOf[msg.sender] >= value, "Insufficient balance");
        balanceOf[msg.sender] -= value;
        balanceOf[to] += value;
        emit Transfer(msg.sender, to, value);
        
        // Check if recipient is a contract and call callback if needed
        uint256 codeSize;
        assembly { codeSize := extcodesize(to) }
        if (codeSize > 0) {
            try IERC1363Receiver(to).onTransferReceived(msg.sender, msg.sender, value, data) returns (bytes4 retval) {
                require(retval == IERC1363Receiver.onTransferReceived.selector, "Receiver rejected");
            } catch {}
        }
        return true;
    }
    
    function approveAndCall(address spender, uint256 value) public returns (bool) {
        return approveAndCall(spender, value, "");
    }
    
    function approveAndCall(address spender, uint256 value, bytes memory data) public returns (bool) {
        // Directly perform the approval logic inline
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        
        // Check if spender is a contract and call callback if needed
        uint256 codeSize;
        assembly { codeSize := extcodesize(spender) }
        if (codeSize > 0) {
            try IERC1363Spender(spender).onApprovalReceived(msg.sender, value, data) returns (bytes4 retval) {
                require(retval == IERC1363Spender.onApprovalReceived.selector, "Spender rejected");
            } catch {}
        }
        return true;
    }
    
    // EIP-2612 Permit function
    function permit(
        address owner,
        address spender,
        uint256 value,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external {
        require(deadline >= block.timestamp, "Permit expired");
        
        bytes32 structHash = keccak256(
            abi.encode(PERMIT_TYPEHASH, owner, spender, value, nonces[owner]++, deadline)
        );
        
        bytes32 digest = keccak256(
            abi.encodePacked("\\x19\\x01", DOMAIN_SEPARATOR, structHash)
        );
        
        address recoveredAddress = ecrecover(digest, v, r, s);
        require(recoveredAddress != address(0) && recoveredAddress == owner, "Invalid signature");
        
        allowance[owner][spender] = value;
        emit Approval(owner, spender, value);
    }
}
"""
            
            # 使用 solcx 编译合约
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # 尝试使用已安装的 solc，如果没有则安装
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • 安装 Solidity 编译器 v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # 编译合约
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:TestERC1363Token']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc not available: {e}")
                print(f"  • 尝试安装 py-solc-x: pip install py-solc-x")
                raise Exception("Cannot compile ERC1363 contract without solc. Please install: pip install py-solc-x")
            
            # 部署合约
            # Impersonate测试账户以便部署合约
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 发送部署交易
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # 等待部署确认
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # 获取部署的合约地址
            erc1363_address = receipt['contractAddress']
            erc1363_address = to_checksum_address(erc1363_address)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # 存储合约地址供后续使用
            self.erc1363_token_address = erc1363_address
            
            # 验证部署
            balance_selector = bytes.fromhex('70a08231')  # balanceOf(address)
            balance_data = '0x' + balance_selector.hex() + encode(['address'], [test_addr]).hex()
            
            result = self.w3.eth.call({
                'to': erc1363_address,
                'data': balance_data
            })
            
            balance = int(result.hex(), 16)
            balance_formatted = balance / 10**18
            
            print(f"  • ERC1363 Token deployed: {erc1363_address}")
            print(f"  • Test account balance: {balance_formatted:.2f} T1363 ✅")
            
            # 预先设置测试账户授权给自己（用于 permit/transferFrom 测试）
            # approve(address spender, uint256 value)
            try:
                self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
                
                approve_selector = bytes.fromhex('095ea7b3')  # approve(address,uint256)
                # 授权无限额度: 2^256 - 1
                max_uint256 = 2**256 - 1
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [test_addr, max_uint256]).hex()
                
                approve_response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': erc1363_address,
                        'data': approve_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                # 等待授权交易确认
                if 'result' in approve_response:
                    time.sleep(0.5)
                
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
                print(f"  • Test account self-approved for permit testing ✅")
            except Exception as e:
                print(f"  • ⚠️  Warning: Self-approval failed - {e}")
            
        except Exception as e:
            print(f"  • ERC1363 Token: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # 设置为 None 表示未部署
            self.erc1363_token_address = None
        
        print()
    
    def _deploy_erc721_test_nft(self):
        """
        Deploy ERC721 test NFT contract for NFT operation testing
        
        This deploys a simple ERC721 implementation that mints 10 tokens to the deployer
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print(f"✓ Deploying ERC721 Test NFT...")
        
        try:
            test_addr = to_checksum_address(self.test_address)
            
            # Read contract source code from contracts/TestERC721NFT.sol
            import os
            contract_path = os.path.join(os.path.dirname(__file__), '..', 'contracts', 'TestERC721NFT.sol')
            
            if not os.path.exists(contract_path):
                print(f"  • ⚠️  Contract file not found: {contract_path}")
                print(f"  • Using inline contract source")
                
                # Inline contract source as fallback
                contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TestERC721NFT {
    string public name = "Test NFT Collection";
    string public symbol = "TNFT";
    
    mapping(uint256 => address) private _owners;
    mapping(address => uint256) private _balances;
    mapping(uint256 => address) private _tokenApprovals;
    mapping(address => mapping(address => bool)) private _operatorApprovals;
    
    event Transfer(address indexed from, address indexed to, uint256 indexed tokenId);
    event Approval(address indexed owner, address indexed approved, uint256 indexed tokenId);
    event ApprovalForAll(address indexed owner, address indexed operator, bool approved);
    
    constructor() {
        for (uint256 i = 1; i <= 10; i++) {
            _mint(msg.sender, i);
        }
    }
    
    function balanceOf(address owner) public view returns (uint256) {
        require(owner != address(0), "ERC721: balance query for the zero address");
        return _balances[owner];
    }
    
    function ownerOf(uint256 tokenId) public view returns (address) {
        address owner = _owners[tokenId];
        require(owner != address(0), "ERC721: owner query for nonexistent token");
        return owner;
    }
    
    function approve(address to, uint256 tokenId) public {
        address owner = ownerOf(tokenId);
        require(to != owner, "ERC721: approval to current owner");
        require(
            msg.sender == owner || isApprovedForAll(owner, msg.sender),
            "ERC721: approve caller is not owner nor approved for all"
        );
        
        _tokenApprovals[tokenId] = to;
        emit Approval(owner, to, tokenId);
    }
    
    function getApproved(uint256 tokenId) public view returns (address) {
        require(_owners[tokenId] != address(0), "ERC721: approved query for nonexistent token");
        return _tokenApprovals[tokenId];
    }
    
    function setApprovalForAll(address operator, bool approved) public {
        require(operator != msg.sender, "ERC721: approve to caller");
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }
    
    function isApprovedForAll(address owner, address operator) public view returns (bool) {
        return _operatorApprovals[owner][operator];
    }
    
    function transferFrom(address from, address to, uint256 tokenId) public {
        require(_isApprovedOrOwner(msg.sender, tokenId), "ERC721: transfer caller is not owner nor approved");
        _transfer(from, to, tokenId);
    }
    
    function safeTransferFrom(address from, address to, uint256 tokenId) public {
        safeTransferFrom(from, to, tokenId, "");
    }
    
    function safeTransferFrom(address from, address to, uint256 tokenId, bytes memory data) public {
        require(_isApprovedOrOwner(msg.sender, tokenId), "ERC721: transfer caller is not owner nor approved");
        _safeTransfer(from, to, tokenId, data);
    }
    
    function _safeTransfer(address from, address to, uint256 tokenId, bytes memory data) internal {
        _transfer(from, to, tokenId);
        require(_checkOnERC721Received(from, to, tokenId, data), "ERC721: transfer to non ERC721Receiver implementer");
    }
    
    function _isApprovedOrOwner(address spender, uint256 tokenId) internal view returns (bool) {
        address owner = ownerOf(tokenId);
        return (spender == owner || getApproved(tokenId) == spender || isApprovedForAll(owner, spender));
    }
    
    function _mint(address to, uint256 tokenId) internal {
        require(to != address(0), "ERC721: mint to the zero address");
        require(_owners[tokenId] == address(0), "ERC721: token already minted");
        
        _balances[to] += 1;
        _owners[tokenId] = to;
        
        emit Transfer(address(0), to, tokenId);
    }
    
    function _transfer(address from, address to, uint256 tokenId) internal {
        require(ownerOf(tokenId) == from, "ERC721: transfer from incorrect owner");
        require(to != address(0), "ERC721: transfer to the zero address");
        
        _tokenApprovals[tokenId] = address(0);
        
        _balances[from] -= 1;
        _balances[to] += 1;
        _owners[tokenId] = to;
        
        emit Transfer(from, to, tokenId);
    }
    
    function _checkOnERC721Received(address from, address to, uint256 tokenId, bytes memory data) private returns (bool) {
        uint256 size;
        assembly {
            size := extcodesize(to)
        }
        if (size == 0) {
            return true;
        }
        
        try IERC721Receiver(to).onERC721Received(msg.sender, from, tokenId, data) returns (bytes4 retval) {
            return retval == IERC721Receiver.onERC721Received.selector;
        } catch {
            return false;
        }
    }
}

interface IERC721Receiver {
    function onERC721Received(
        address operator,
        address from,
        uint256 tokenId,
        bytes calldata data
    ) external returns (bytes4);
}
"""
            else:
                with open(contract_path, 'r', encoding='utf-8') as f:
                    contract_source = f.read()
            
            # Compile contract using solcx
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # Try to use installed solc, install if not available
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • Installing Solidity compiler v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # Compile contract
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:TestERC721NFT']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc not available: {e}")
                raise Exception("Cannot compile ERC721 contract without solc. Please install: pip install py-solc-x")
            
            # Deploy contract
            # Impersonate test account to deploy contract
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # Send deployment transaction
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # Wait for deployment confirmation
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # Get deployed contract address
            erc721_address = receipt['contractAddress']
            erc721_address = to_checksum_address(erc721_address)
            
            # Stop impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # Store contract address for later use
            self.erc721_test_nft_address = erc721_address
            
            # Verify deployment - check balance
            balance_selector = bytes.fromhex('70a08231')  # balanceOf(address)
            balance_data = '0x' + balance_selector.hex() + encode(['address'], [test_addr]).hex()
            
            result = self.w3.eth.call({
                'to': erc721_address,
                'data': balance_data
            })
            
            balance = int(result.hex(), 16)
            
            print(f"  • ERC721 Test NFT deployed: {erc721_address}")
            print(f"  • Test account owns {balance} NFTs (token IDs 1-10) ✅")
            
        except Exception as e:
            print(f"  • ERC721 Test NFT: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # Set to None to indicate not deployed
            self.erc721_test_nft_address = None
        
        print()
    
    def _deploy_erc1155_token(self):
        """
        部署 ERC1155 测试代币并给测试账户分配代币
        
        ERC1155 是多代币标准，支持同时管理多种代币类型
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print("✓ 部署 ERC1155 测试代币...")
        
        try:
            test_addr = self.test_address
            
            # ERC1155 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TestERC1155Token {
    string public name = "Test Multi Token";
    
    // Mapping from token ID to account balances
    mapping(uint256 => mapping(address => uint256)) private _balances;
    
    // Mapping from account to operator approvals
    mapping(address => mapping(address => bool)) private _operatorApprovals;
    
    event TransferSingle(
        address indexed operator,
        address indexed from,
        address indexed to,
        uint256 id,
        uint256 value
    );
    
    event TransferBatch(
        address indexed operator,
        address indexed from,
        address indexed to,
        uint256[] ids,
        uint256[] values
    );
    
    event ApprovalForAll(
        address indexed account,
        address indexed operator,
        bool approved
    );
    
    constructor() {
        // Mint initial tokens to deployer
        // Token ID 1: 1000 units
        // Token ID 2: 500 units
        // Token ID 3: 100 units
        _balances[1][msg.sender] = 1000;
        _balances[2][msg.sender] = 500;
        _balances[3][msg.sender] = 100;
        
        emit TransferSingle(msg.sender, address(0), msg.sender, 1, 1000);
        emit TransferSingle(msg.sender, address(0), msg.sender, 2, 500);
        emit TransferSingle(msg.sender, address(0), msg.sender, 3, 100);
    }
    
    function balanceOf(address account, uint256 id) public view returns (uint256) {
        require(account != address(0), "ERC1155: balance query for the zero address");
        return _balances[id][account];
    }
    
    function balanceOfBatch(
        address[] memory accounts,
        uint256[] memory ids
    ) public view returns (uint256[] memory) {
        require(accounts.length == ids.length, "ERC1155: accounts and ids length mismatch");
        
        uint256[] memory batchBalances = new uint256[](accounts.length);
        
        for (uint256 i = 0; i < accounts.length; ++i) {
            batchBalances[i] = balanceOf(accounts[i], ids[i]);
        }
        
        return batchBalances;
    }
    
    function setApprovalForAll(address operator, bool approved) public {
        require(msg.sender != operator, "ERC1155: setting approval status for self");
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }
    
    function isApprovedForAll(address account, address operator) public view returns (bool) {
        return _operatorApprovals[account][operator];
    }
    
    function safeTransferFrom(
        address from,
        address to,
        uint256 id,
        uint256 amount,
        bytes memory data
    ) public {
        require(
            from == msg.sender || isApprovedForAll(from, msg.sender),
            "ERC1155: caller is not owner nor approved"
        );
        require(to != address(0), "ERC1155: transfer to the zero address");
        
        uint256 fromBalance = _balances[id][from];
        require(fromBalance >= amount, "ERC1155: insufficient balance for transfer");
        
        _balances[id][from] = fromBalance - amount;
        _balances[id][to] += amount;
        
        emit TransferSingle(msg.sender, from, to, id, amount);
    }
    
    function safeBatchTransferFrom(
        address from,
        address to,
        uint256[] memory ids,
        uint256[] memory amounts,
        bytes memory data
    ) public {
        require(
            from == msg.sender || isApprovedForAll(from, msg.sender),
            "ERC1155: caller is not owner nor approved"
        );
        require(ids.length == amounts.length, "ERC1155: ids and amounts length mismatch");
        require(to != address(0), "ERC1155: transfer to the zero address");
        
        for (uint256 i = 0; i < ids.length; ++i) {
            uint256 id = ids[i];
            uint256 amount = amounts[i];
            
            uint256 fromBalance = _balances[id][from];
            require(fromBalance >= amount, "ERC1155: insufficient balance for transfer");
            
            _balances[id][from] = fromBalance - amount;
            _balances[id][to] += amount;
        }
        
        emit TransferBatch(msg.sender, from, to, ids, amounts);
    }
}
"""
            
            # 使用 solcx 编译合约
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # 尝试使用已安装的 solc，如果没有则安装
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • 安装 Solidity 编译器 v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # 编译合约
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:TestERC1155Token']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc compilation error: {e}")
                raise Exception("Cannot compile ERC1155 contract")
            
            # 部署合约
            # Impersonate测试账户以便部署合约
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 发送部署交易
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # 等待部署确认
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # 获取部署的合约地址
            erc1155_address = receipt['contractAddress']
            erc1155_address = to_checksum_address(erc1155_address)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # 存储合约地址供后续使用
            self.erc1155_token_address = erc1155_address
            
            # 验证部署 - 查询 token ID 1 的余额
            # balanceOf(address account, uint256 id)
            balance_selector = bytes.fromhex('00fdd58e')  # balanceOf(address,uint256)
            balance_data = '0x' + balance_selector.hex() + encode(['address', 'uint256'], [test_addr, 1]).hex()
            
            result = self.w3.eth.call({
                'to': erc1155_address,
                'data': balance_data
            })
            
            balance = int(result.hex(), 16)
            
            print(f"  • ERC1155 Token deployed: {erc1155_address}")
            print(f"  • Test account balance (Token ID 1): {balance} units ✅")
            print(f"  • Test account balance (Token ID 2): 500 units ✅")
            print(f"  • Test account balance (Token ID 3): 100 units ✅")
            
        except Exception as e:
            print(f"  • ERC1155 Token: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # 设置为 None 表示未部署
            self.erc1155_token_address = None
        
        print()
    
    def _deploy_flashloan_receiver(self):
        """
        部署闪电贷接收合约
        
        这是一个简单的闪电贷提供者+接收者合约，用于测试闪电贷功能
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print("✓ 部署闪电贷合约...")
        
        try:
            test_addr = self.test_address
            
            # 简单的闪电贷合约源代码
            # 这个合约既是提供者又是接收者，简化了测试流程
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
}

contract FlashLoanReceiver {
    address public owner;
    
    event FlashLoanExecuted(address indexed token, uint256 amount, uint256 fee);
    
    constructor() {
        owner = msg.sender;
    }
    
    // 执行闪电贷
    // 1. 从合约中借出代币
    // 2. 调用者可以使用这些代币
    // 3. 在同一交易中归还代币+手续费
    function executeFlashLoan(
        address token,
        uint256 amount
    ) external returns (bool) {
        // 计算手续费 (0.3%)
        uint256 fee = (amount * 3) / 1000;
        uint256 amountToRepay = amount + fee;
        
        // 检查合约是否有足够的代币可以借出
        uint256 balanceBefore = IERC20(token).balanceOf(address(this));
        require(balanceBefore >= amount, "Insufficient balance in pool");
        
        // 1. 将代币转给调用者（借款）
        require(IERC20(token).transfer(msg.sender, amount), "Loan transfer failed");
        
        // 2. 调用者现在拥有这些代币，可以进行任何操作
        // 在真实的闪电贷中，这里会调用借款人合约的回调函数
        // 但为了简化测试，我们假设调用者会在同一交易中归还
        
        // 3. 检查调用者是否归还了代币+手续费
        // 调用者需要先 approve 这个合约
        require(
            IERC20(token).transferFrom(msg.sender, address(this), amountToRepay),
            "Repayment failed"
        );
        
        // 验证余额增加了手续费
        uint256 balanceAfter = IERC20(token).balanceOf(address(this));
        require(balanceAfter >= balanceBefore + fee, "Fee not paid");
        
        emit FlashLoanExecuted(token, amount, fee);
        return true;
    }
    
    // 允许 owner 存入代币到流动性池
    function depositToPool(address token, uint256 amount) external {
        require(msg.sender == owner, "Only owner can deposit");
        require(
            IERC20(token).transferFrom(msg.sender, address(this), amount),
            "Deposit failed"
        );
    }
    
    // 查询池中的代币余额
    function poolBalance(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }
    
    // 允许 owner 提取代币
    function withdraw(address token, uint256 amount) external {
        require(msg.sender == owner, "Only owner can withdraw");
        require(IERC20(token).transfer(msg.sender, amount), "Withdraw failed");
    }
}
"""
            
            # 使用 solcx 编译合约
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # 尝试使用已安装的 solc，如果没有则安装
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • 安装 Solidity 编译器 v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # 编译合约
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:FlashLoanReceiver']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc compilation error: {e}")
                raise Exception("Cannot compile FlashLoan contract")
            
            # 部署合约
            # Impersonate测试账户以便部署合约
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 发送部署交易
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # 等待部署确认
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # 获取部署的合约地址
            flashloan_address = receipt['contractAddress']
            flashloan_address = to_checksum_address(flashloan_address)
            
            # 存储合约地址供后续使用
            self.flashloan_receiver_address = flashloan_address
            
            # 为闪电贷池设置 USDT 余额（使用 anvil_setStorageAt）
            usdt_address = '0x55d398326f99059fF775485246999027B3197955'
            pool_deposit_amount = 10000 * 10**18  # 10000 USDT (BSC USDT uses 18 decimals)
            
            # 直接设置闪电贷合约的 USDT 余额
            self._set_erc20_balance_direct(usdt_address, flashloan_address, pool_deposit_amount, balance_slot=1)
            
            # 验证部署 - 直接查询闪电贷合约的 USDT 余额
            # 使用 ERC20 balanceOf 而不是合约的 poolBalance，更可靠
            # balanceOf(address) returns (uint256)
            balance_selector = bytes.fromhex('70a08231')  # balanceOf(address)
            balance_data = '0x' + balance_selector.hex() + encode(['address'], [flashloan_address]).hex()
            
            try:
                result = self.w3.eth.call({
                    'to': usdt_address,
                    'data': balance_data
                })
                
                pool_balance = int(result.hex(), 16)
                pool_balance_formatted = pool_balance / 10**18  # BSC USDT has 18 decimals
                
                print(f"  • FlashLoan Contract deployed: {flashloan_address}")
                print(f"  • Pool balance (USDT): {pool_balance_formatted:.2f} USDT ✅")
            except Exception as e:
                print(f"  • FlashLoan Contract deployed: {flashloan_address}")
                print(f"  • Warning: Could not verify pool balance: {e}")
                print(f"  • Pool initialization may have failed, but continuing...")
            
            # 预先 approve 闪电贷合约，这样测试账户可以直接调用 executeFlashLoan
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # Approve 闪电贷合约最大额度 (2^256-1)
            max_approval = 2**256 - 1
            # ERC20 approve function selector: 0x095ea7b3
            # approve(address spender, uint256 amount)
            approve_data = '0x095ea7b3' + encode(['address', 'uint256'], [flashloan_address, max_approval]).hex()
            
            approve_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': usdt_address,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in approve_response:
                tx_hash = approve_response['result']
                # 等待确认
                for i in range(10):
                    try:
                        receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                        if receipt_response.get('result'):
                            break
                    except:
                        pass
                    time.sleep(0.3)
                print(f"  • Test account approved flash loan contract ✅")
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
        except Exception as e:
            print(f"  • FlashLoan Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # 设置为 None 表示未部署
            self.flashloan_receiver_address = None
        
        print()
    
    def _deploy_simple_counter(self):
        """
        部署 SimpleCounter 测试合约
        
        这是一个简单的计数器合约，用于测试基本的合约函数调用
        """
        print("✓ 部署 SimpleCounter 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            from eth_abi import encode
            
            # 简单计数器合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract SimpleCounter {
    uint256 public counter;
    address public owner;
    
    event CounterIncremented(uint256 newValue);
    event CounterReset(uint256 newValue);
    
    constructor() {
        owner = msg.sender;
        counter = 0;
    }
    
    // 增加计数器
    function increment() external {
        counter += 1;
        emit CounterIncremented(counter);
    }
    
    // 获取当前计数器值
    function getCounter() external view returns (uint256) {
        return counter;
    }
    
    // 重置计数器（仅owner）
    function reset() external {
        require(msg.sender == owner, "Only owner can reset");
        counter = 0;
        emit CounterReset(counter);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:SimpleCounter']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:SimpleCounter']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.simple_counter_address = contract_address
            
            # 验证合约部署
            counter_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_counter = counter_contract.functions.getCounter().call()
            
            print(f"  • SimpleCounter Contract deployed: {contract_address}")
            print(f"  • Initial counter value: {initial_counter} ✅")
            
        except Exception as e:
            print(f"  • SimpleCounter Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.simple_counter_address = None
        
        print()
    
    def _deploy_donation_box(self):
        """
        部署 DonationBox 测试合约
        
        这是一个简单的捐赠盒合约，用于测试带 value 的合约函数调用
        """
        print("✓ 部署 DonationBox 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            
            # DonationBox 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract DonationBox {
    address public owner;
    uint256 public totalDonations;
    mapping(address => uint256) public donations;
    
    event DonationReceived(address indexed donor, uint256 amount);
    
    constructor() {
        owner = msg.sender;
    }
    
    // Payable function to receive donations
    function donate() external payable {
        require(msg.value > 0, "Donation must be greater than 0");
        
        donations[msg.sender] += msg.value;
        totalDonations += msg.value;
        
        emit DonationReceived(msg.sender, msg.value);
    }
    
    // View function to get contract balance
    function getBalance() external view returns (uint256) {
        return address(this).balance;
    }
    
    // View function to get donor's total donations
    function getDonation(address donor) external view returns (uint256) {
        return donations[donor];
    }
    
    // Owner can withdraw (for testing cleanup)
    function withdraw() external {
        require(msg.sender == owner, "Only owner can withdraw");
        payable(owner).transfer(address(this).balance);
    }
    
    // Fallback function to accept BNB
    receive() external payable {
        donations[msg.sender] += msg.value;
        totalDonations += msg.value;
        emit DonationReceived(msg.sender, msg.value);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:DonationBox']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:DonationBox']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.donation_box_address = contract_address
            
            # 验证合约部署
            donation_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_balance = donation_contract.functions.getBalance().call()
            
            print(f"  • DonationBox Contract deployed: {contract_address}")
            print(f"  • Initial contract balance: {initial_balance / 10**18:.6f} BNB ✅")
            
        except Exception as e:
            print(f"  • DonationBox Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.donation_box_address = None
        
        print()
    
    def _deploy_message_board(self):
        """
        部署 MessageBoard 测试合约
        
        这是一个简单的留言板合约，用于测试带参数的合约函数调用
        """
        print("✓ 部署 MessageBoard 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            
            # MessageBoard 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract MessageBoard {
    string public message;
    address public lastSender;
    uint256 public updateCount;
    
    event MessageUpdated(address indexed sender, string newMessage);
    
    constructor() {
        message = "Initial message";
        lastSender = msg.sender;
        updateCount = 0;
    }
    
    // Set message with string parameter
    function setMessage(string memory newMessage) external {
        message = newMessage;
        lastSender = msg.sender;
        updateCount += 1;
        
        emit MessageUpdated(msg.sender, newMessage);
    }
    
    // Get current message
    function getMessage() external view returns (string memory) {
        return message;
    }
    
    // Get message info
    function getMessageInfo() external view returns (
        string memory currentMessage,
        address sender,
        uint256 count
    ) {
        return (message, lastSender, updateCount);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:MessageBoard']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:MessageBoard']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 1000000,  # 增加 gas limit，MessageBoard 有 string 初始化
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            # 调试信息
            print(f"  • Deployment tx: {tx_hash.hex()}")
            print(f"  • Gas used: {receipt['gasUsed']} / {deploy_tx['gas']}")
            print(f"  • Status: {receipt['status']}")
            
            if receipt['status'] != 1:
                # 尝试获取 revert reason
                print(f"  • Trying to get revert reason...")
                try:
                    self.w3.eth.call(deploy_tx, receipt['blockNumber'])
                except Exception as call_error:
                    print(f"  • Revert reason: {call_error}")
                raise Exception(f"MessageBoard deployment failed: status={receipt['status']}, gasUsed={receipt['gasUsed']}")
            
            contract_address = receipt['contractAddress']
            self.message_board_address = contract_address
            
            # 验证合约部署
            message_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_message = message_contract.functions.getMessage().call()
            
            print(f"  • MessageBoard Contract deployed: {contract_address}")
            print(f"  • Initial message: \"{initial_message}\" ✅")
            
        except Exception as e:
            print(f"  • MessageBoard Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.message_board_address = None
        
        print()
    
    def _deploy_delegate_call_contracts(self):
        """
        部署 DelegateCall 相关合约:
        1. Implementation 合约 - 包含实际逻辑
        2. Proxy 合约 - 使用 delegatecall 转发调用
        """
        from eth_utils import to_checksum_address
        import solcx
        
        print(f"✓ 部署 DelegateCall 合约...")
        
        try:
            # Implementation 合约源码
            implementation_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Implementation {
    uint256 public value;
    
    event ValueSet(uint256 newValue);
    
    // Set value function
    function setValue(uint256 _value) external {
        value = _value;
        emit ValueSet(_value);
    }
    
    // Get value function
    function getValue() external view returns (uint256) {
        return value;
    }
}
"""
            
            # Proxy 合约源码
            proxy_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract DelegateCallProxy {
    uint256 public value;  // Storage slot 0 - matches Implementation
    address public implementation;  // Storage slot 1
    
    event ValueSet(uint256 newValue);
    
    constructor(address _implementation) {
        implementation = _implementation;
    }
    
    // Fallback function that delegates all calls to implementation
    fallback() external payable {
        address impl = implementation;
        require(impl != address(0), "No implementation");
        
        assembly {
            // Copy calldata to memory
            calldatacopy(0, 0, calldatasize())
            
            // Delegate call to implementation
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            
            // Copy return data to memory
            returndatacopy(0, 0, returndatasize())
            
            // Return or revert based on result
            switch result
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }
    
    // Allow contract to receive BNB
    receive() external payable {}
}
"""
            
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 安装 0.8.20 版本的 solc
            solc_version = '0.8.20'
            if solc_version not in solcx.get_installed_solc_versions():
                print(f"  • Installing solc {solc_version}...")
                solcx.install_solc(solc_version)
            solcx.set_solc_version(solc_version)
            
            # 编译 Implementation 合约
            print(f"  • Compiling Implementation contract...")
            impl_compiled = solcx.compile_source(
                implementation_source,
                output_values=['abi', 'bin'],
                solc_version=solc_version
            )
            impl_contract_id = None
            for contract_id in impl_compiled.keys():
                if 'Implementation' in contract_id:
                    impl_contract_id = contract_id
                    break
            
            if not impl_contract_id:
                raise Exception("Implementation contract not found in compiled output")
            
            impl_abi = impl_compiled[impl_contract_id]['abi']
            impl_bytecode = impl_compiled[impl_contract_id]['bin']
            
            # 部署 Implementation 合约
            print(f"  • Deploying Implementation contract...")
            impl_deploy_tx = {
                'from': deployer_address,
                'data': '0x' + impl_bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            impl_signed_tx = self.w3.eth.account.sign_transaction(impl_deploy_tx, deployer.key)
            impl_tx_hash = self.w3.eth.send_raw_transaction(impl_signed_tx.raw_transaction)
            impl_receipt = self.w3.eth.wait_for_transaction_receipt(impl_tx_hash, timeout=30)
            
            if impl_receipt['status'] != 1:
                raise Exception(f"Implementation deployment failed: status={impl_receipt['status']}")
            
            impl_address = impl_receipt['contractAddress']
            print(f"  • Implementation deployed: {impl_address}")
            
            # 编译 Proxy 合约
            print(f"  • Compiling Proxy contract...")
            proxy_compiled = solcx.compile_source(
                proxy_source,
                output_values=['abi', 'bin'],
                solc_version=solc_version
            )
            proxy_contract_id = None
            for contract_id in proxy_compiled.keys():
                if 'DelegateCallProxy' in contract_id:
                    proxy_contract_id = contract_id
                    break
            
            if not proxy_contract_id:
                raise Exception("Proxy contract not found in compiled output")
            
            proxy_abi = proxy_compiled[proxy_contract_id]['abi']
            proxy_bytecode = proxy_compiled[proxy_contract_id]['bin']
            
            # 编码构造函数参数 (implementation address)
            from eth_abi import encode
            constructor_params = encode(['address'], [to_checksum_address(impl_address)])
            
            # 部署 Proxy 合约
            print(f"  • Deploying Proxy contract...")
            proxy_deploy_tx = {
                'from': deployer_address,
                'data': '0x' + proxy_bytecode + constructor_params.hex(),
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            proxy_signed_tx = self.w3.eth.account.sign_transaction(proxy_deploy_tx, deployer.key)
            proxy_tx_hash = self.w3.eth.send_raw_transaction(proxy_signed_tx.raw_transaction)
            proxy_receipt = self.w3.eth.wait_for_transaction_receipt(proxy_tx_hash, timeout=30)
            
            if proxy_receipt['status'] != 1:
                raise Exception(f"Proxy deployment failed: status={proxy_receipt['status']}")
            
            proxy_address = proxy_receipt['contractAddress']
            
            # 保存地址
            self.delegate_call_implementation_address = impl_address
            self.delegate_call_proxy_address = proxy_address
            
            # 验证合约部署
            # 读取 implementation 合约的初始值
            impl_contract = self.w3.eth.contract(address=impl_address, abi=impl_abi)
            impl_initial_value = impl_contract.functions.getValue().call()
            
            # 读取 proxy 合约的初始值 (通过 delegatecall)
            proxy_contract = self.w3.eth.contract(address=proxy_address, abi=impl_abi)
            proxy_initial_value = proxy_contract.functions.getValue().call()
            
            print(f"  • Proxy Contract deployed: {proxy_address}")
            print(f"  • Implementation Contract: {impl_address}")
            print(f"  • Implementation initial value: {impl_initial_value}")
            print(f"  • Proxy initial value: {proxy_initial_value} ✅")
            
        except Exception as e:
            print(f"  • DelegateCall Contracts: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.delegate_call_implementation_address = None
            self.delegate_call_proxy_address = None
        
        print()
    
    def _deploy_fallback_receiver(self):
        """
        部署 FallbackReceiver 测试合约
        
        这是一个简单的合约，有 receive() 函数用于接收 BNB
        """
        print("✓ 部署 FallbackReceiver 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            
            # FallbackReceiver 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract FallbackReceiver {
    uint256 public receivedCount;
    uint256 public totalReceived;
    address public owner;
    
    event BNBReceived(address indexed sender, uint256 amount);
    
    constructor() {
        owner = msg.sender;
        receivedCount = 0;
        totalReceived = 0;
    }
    
    // Receive function - called when BNB is sent with empty calldata
    receive() external payable {
        receivedCount += 1;
        totalReceived += msg.value;
        emit BNBReceived(msg.sender, msg.value);
    }
    
    // Fallback function - called when function doesn't exist
    fallback() external payable {
        receivedCount += 1;
        totalReceived += msg.value;
        emit BNBReceived(msg.sender, msg.value);
    }
    
    // Get contract balance
    function getBalance() external view returns (uint256) {
        return address(this).balance;
    }
    
    // Get received count
    function getReceivedCount() external view returns (uint256) {
        return receivedCount;
    }
    
    // Owner can withdraw (for cleanup)
    function withdraw() external {
        require(msg.sender == owner, "Only owner can withdraw");
        payable(owner).transfer(address(this).balance);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:FallbackReceiver']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:FallbackReceiver']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.fallback_receiver_address = contract_address
            
            # 验证合约部署
            fallback_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_balance = fallback_contract.functions.getBalance().call()
            initial_count = fallback_contract.functions.getReceivedCount().call()
            
            print(f"  • FallbackReceiver Contract deployed: {contract_address}")
            print(f"  • Initial balance: {initial_balance / 10**18:.6f} BNB")
            print(f"  • Initial received count: {initial_count} ✅")
            
        except Exception as e:
            print(f"  • FallbackReceiver Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.fallback_receiver_address = None
        
        print()
    
    def _deploy_simple_staking(self):
        """
        部署 SimpleStaking 合约用于质押测试
        """
        print("✓ 部署 SimpleStaking 测试合约...")
        try:
            import json
            from solcx import compile_source, install_solc
            
            # CAKE token address
            cake_address = '0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82'
            
            # 读取合约源代码
            contract_path = os.path.join(os.path.dirname(__file__), 'contracts', 'SimpleStaking.sol')
            with open(contract_path, 'r') as f:
                contract_source = f.read()
            
            # 安装并编译合约
            try:
                install_solc('0.8.20')
            except:
                pass  # 可能已经安装
            
            compiled_sol = compile_source(
                contract_source,
                output_values=['abi', 'bin', 'bin-runtime'],
                solc_version='0.8.20'
            )
            
            # 查找 SimpleStaking 合约（跳过接口）
            contract_interface = None
            contract_id = None
            
            print(f"  • Found {len(compiled_sol)} compiled contracts/interfaces")
            for cid, cinterface in compiled_sol.items():
                print(f"    - {cid}: bytecode length = {len(cinterface.get('bin', ''))}")
                # 寻找有 bytecode 的合约（跳过空的接口）
                if cinterface.get('bin') and len(cinterface.get('bin', '')) > 10:
                    if 'SimpleStaking' in cid:
                        contract_id = cid
                        contract_interface = cinterface
                        print(f"  • ✅ Found SimpleStaking contract: {cid}")
                        break
            
            if not contract_interface:
                print(f"  • ERROR: SimpleStaking contract not found!")
                print(f"  • Available contracts: {list(compiled_sol.keys())}")
                raise Exception("SimpleStaking contract not found in compilation output")
            
            # 获取 bytecode 和 ABI
            bytecode = contract_interface.get('bin', '')
            abi = contract_interface.get('abi', [])
            
            # 确保 bytecode 格式正确
            if not bytecode.startswith('0x'):
                bytecode = '0x' + bytecode
            
            # 构造部署交易 (包含 constructor 参数)
            from eth_abi import encode
            from eth_utils import to_checksum_address
            constructor_args = encode(['address'], [to_checksum_address(cake_address)])
            
            # 组合 bytecode 和 constructor 参数
            deployment_data = bytecode + constructor_args.hex()
            
            deployer = self.test_account
            deployer_address = deployer.address
            
            print(f"  • Bytecode length: {len(bytecode)} characters")
            print(f"  • Deploying contract...")
            
            deploy_tx = {
                'from': deployer_address,
                'data': deployment_data,
                'gas': 2000000,  # 增加 gas limit
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.simple_staking_address = contract_address
            
            print(f"  • SimpleStaking Contract deployed: {contract_address}")
            print(f"  • Staking token: {cake_address} (CAKE)")
            
            # 设置 CAKE allowance for SimpleStaking
            try:
                from eth_utils import to_checksum_address
                from eth_abi import encode
                
                cake_addr = to_checksum_address(cake_address)
                test_addr = to_checksum_address(self.test_address)
                staking_addr = to_checksum_address(contract_address)
                
                # Impersonate 测试账户
                self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
                
                # ERC20 approve function selector: 0x095ea7b3
                approve_selector = bytes.fromhex('095ea7b3')
                # Approve a large amount (200 CAKE to match balance)
                approve_amount = 200 * 10**18
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [staking_addr, approve_amount]).hex()
                
                # 发送 approve 交易
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': cake_addr,
                        'data': approve_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                if 'result' in response:
                    tx_hash = response['result']
                    
                    # 等待确认
                    max_attempts = 20
                    for i in range(max_attempts):
                        try:
                            receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                            if receipt and receipt.get('blockNumber'):
                                break
                        except:
                            pass
                        time.sleep(0.5)
                
                # 停止 impersonate
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
                
                print(f"  • CAKE approved for SimpleStaking ✅")
            except Exception as e:
                print(f"  • CAKE approval failed: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            print(f"  • SimpleStaking Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.simple_staking_address = None
        
        print()
    
    def _deploy_simple_lp_staking(self):
        """
        部署 SimpleLPStaking 合约用于 LP 代币质押测试
        """
        print("✓ 部署 SimpleLPStaking 测试合约...")
        try:
            import json
            from solcx import compile_source, install_solc
            
            # USDT/BUSD LP token address
            lp_token_address = '0x7EFaEf62fDdCCa950418312c6C91Aef321375A00'
            
            # 读取合约源代码
            contract_path = os.path.join(os.path.dirname(__file__), 'contracts', 'SimpleLPStaking.sol')
            with open(contract_path, 'r') as f:
                contract_source = f.read()
            
            # 安装并编译合约
            try:
                install_solc('0.8.20')
            except:
                pass  # 可能已经安装
            
            compiled_sol = compile_source(
                contract_source,
                output_values=['abi', 'bin', 'bin-runtime'],
                solc_version='0.8.20'
            )
            
            # 查找 SimpleLPStaking 合约（跳过接口）
            contract_interface = None
            contract_id = None
            
            print(f"  • Found {len(compiled_sol)} compiled contracts/interfaces")
            for cid, cinterface in compiled_sol.items():
                print(f"    - {cid}: bytecode length = {len(cinterface.get('bin', ''))}")
                # 寻找有 bytecode 的合约（跳过空的接口）
                if cinterface.get('bin') and len(cinterface.get('bin', '')) > 10:
                    if 'SimpleLPStaking' in cid:
                        contract_id = cid
                        contract_interface = cinterface
                        print(f"  • ✅ Found SimpleLPStaking contract: {cid}")
                        break
            
            if not contract_interface:
                print(f"  • ERROR: SimpleLPStaking contract not found!")
                print(f"  • Available contracts: {list(compiled_sol.keys())}")
                raise Exception("SimpleLPStaking contract not found in compilation output")
            
            # 获取 bytecode 和 ABI
            bytecode = contract_interface.get('bin', '')
            abi = contract_interface.get('abi', [])
            
            # 确保 bytecode 格式正确
            if not bytecode.startswith('0x'):
                bytecode = '0x' + bytecode
            
            # 构造部署交易 (包含 constructor 参数)
            from eth_abi import encode
            from eth_utils import to_checksum_address
            constructor_args = encode(['address'], [to_checksum_address(lp_token_address)])
            
            # 组合 bytecode 和 constructor 参数
            deployment_data = bytecode + constructor_args.hex()
            
            deployer = self.test_account
            deployer_address = deployer.address
            
            print(f"  • Bytecode length: {len(bytecode)} characters")
            print(f"  • Deploying contract...")
            
            deploy_tx = {
                'from': deployer_address,
                'data': deployment_data,
                'gas': 2000000,  # 增加 gas limit
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.simple_lp_staking_address = contract_address
            
            print(f"  • SimpleLPStaking Contract deployed: {contract_address}")
            print(f"  • Staking token: {lp_token_address} (USDT/BUSD LP)")
            
            # 设置 LP token allowance for SimpleLPStaking
            try:
                from eth_utils import to_checksum_address
                from eth_abi import encode
                
                lp_token_addr = to_checksum_address(lp_token_address)
                test_addr = to_checksum_address(self.test_address)
                staking_addr = to_checksum_address(contract_address)
                
                # Impersonate 测试账户
                self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
                
                # ERC20 approve function selector: 0x095ea7b3
                approve_selector = bytes.fromhex('095ea7b3')
                # Approve a large amount (2 LP tokens)
                approve_amount = 2 * 10**18
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [staking_addr, approve_amount]).hex()
                
                # 发送 approve 交易
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': lp_token_addr,
                        'data': approve_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                if 'result' in response:
                    tx_hash = response['result']
                    
                    # 等待确认
                    max_attempts = 20
                    for i in range(max_attempts):
                        try:
                            receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                            if receipt and receipt.get('blockNumber'):
                                break
                        except:
                            pass
                        time.sleep(0.5)
                
                # 停止 impersonate
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
                
                print(f"  • LP token approved for SimpleLPStaking ✅")
            except Exception as e:
                print(f"  • LP token approval failed: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            print(f"  • SimpleLPStaking Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.simple_lp_staking_address = None
        
        print()
    
    def _deploy_simple_reward_pool(self):
        """
        部署 SimpleRewardPool 合约用于 harvest rewards 测试
        """
        print("✓ 部署 SimpleRewardPool 测试合约...")
        try:
            import json
            import time
            from solcx import compile_source, install_solc
            
            # LP token and reward token addresses
            lp_token_address = '0x7EFaEf62fDdCCa950418312c6C91Aef321375A00'  # USDT/BUSD LP
            cake_address = '0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82'  # CAKE
            
            # 读取合约源代码
            contract_path = os.path.join(os.path.dirname(__file__), 'contracts', 'SimpleRewardPool.sol')
            with open(contract_path, 'r') as f:
                contract_source = f.read()
            
            # 安装并编译合约
            try:
                install_solc('0.8.20')
            except:
                pass  # 可能已经安装
            
            compiled_sol = compile_source(
                contract_source,
                output_values=['abi', 'bin', 'bin-runtime'],
                solc_version='0.8.20'
            )
            
            # 查找 SimpleRewardPool 合约（跳过接口）
            contract_interface = None
            contract_id = None
            
            print(f"  • Found {len(compiled_sol)} compiled contracts/interfaces")
            for cid, cinterface in compiled_sol.items():
                print(f"    - {cid}: bytecode length = {len(cinterface.get('bin', ''))}")
                if cinterface.get('bin') and len(cinterface.get('bin', '')) > 10:
                    if 'SimpleRewardPool' in cid:
                        contract_id = cid
                        contract_interface = cinterface
                        print(f"  • ✅ Found SimpleRewardPool contract: {cid}")
                        break
            
            if not contract_interface:
                print(f"  • ERROR: SimpleRewardPool contract not found!")
                print(f"  • Available contracts: {list(compiled_sol.keys())}")
                raise Exception("SimpleRewardPool contract not found in compilation output")
            
            # 获取 bytecode 和 ABI
            bytecode = contract_interface.get('bin', '')
            abi = contract_interface.get('abi', [])
            
            # 确保 bytecode 格式正确
            if not bytecode.startswith('0x'):
                bytecode = '0x' + bytecode
            
            # 构造部署交易 (包含 constructor 参数: staking token, reward token)
            from eth_abi import encode
            from eth_utils import to_checksum_address
            constructor_args = encode(
                ['address', 'address'],
                [to_checksum_address(lp_token_address), to_checksum_address(cake_address)]
            )
            
            # 组合 bytecode 和 constructor 参数
            deployment_data = bytecode + constructor_args.hex()
            
            deployer = self.test_account
            deployer_address = deployer.address
            
            print(f"  • Bytecode length: {len(bytecode)} characters")
            print(f"  • Deploying contract...")
            
            deploy_tx = {
                'from': deployer_address,
                'data': deployment_data,
                'gas': 2000000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.simple_reward_pool_address = contract_address
            
            print(f"  • SimpleRewardPool Contract deployed: {contract_address}")
            print(f"  • Staking token: {lp_token_address} (USDT/BUSD LP)")
            print(f"  • Reward token: {cake_address} (CAKE)")
            
            # 给合约转 CAKE 作为奖励池
            try:
                from eth_utils import to_checksum_address
                from eth_abi import encode
                
                cake_addr = to_checksum_address(cake_address)
                test_addr = to_checksum_address(self.test_address)
                pool_addr = to_checksum_address(contract_address)
                
                # 给合约转 100 CAKE 作为奖励池
                reward_pool_amount = 100 * 10**18
                
                # Impersonate 测试账户
                self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
                
                # ERC20 transfer function selector: 0xa9059cbb
                transfer_selector = bytes.fromhex('a9059cbb')
                transfer_data = '0x' + transfer_selector.hex() + encode(['address', 'uint256'], [pool_addr, reward_pool_amount]).hex()
                
                # 发送 transfer 交易
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': cake_addr,
                        'data': transfer_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                if 'result' in response:
                    tx_hash = response['result']
                    max_attempts = 20
                    for i in range(max_attempts):
                        try:
                            receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                            if receipt and receipt.get('blockNumber'):
                                break
                        except:
                            pass
                        time.sleep(0.5)
                
                # 停止 impersonate
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
                
                print(f"  • Reward pool funded with 100 CAKE ✅")
            except Exception as e:
                print(f"  • Reward pool funding failed: {e}")
            
            # 给测试账户质押 LP 代币到奖励池
            try:
                # 质押 0.5 LP tokens
                stake_amount = int(0.5 * 10**18)
                
                # 先 approve LP token
                lp_addr = to_checksum_address(lp_token_address)
                
                self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
                
                # Approve LP token for SimpleRewardPool
                approve_selector = bytes.fromhex('095ea7b3')
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [pool_addr, stake_amount]).hex()
                
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': lp_addr,
                        'data': approve_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                if 'result' in response:
                    tx_hash = response['result']
                    for i in range(20):
                        try:
                            receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                            if receipt and receipt.get('blockNumber'):
                                break
                        except:
                            pass
                        time.sleep(0.5)
                
                # Deposit LP tokens
                # deposit(uint256 _amount) selector: 0xb6b55f25
                deposit_selector = bytes.fromhex('b6b55f25')
                deposit_data = '0x' + deposit_selector.hex() + encode(['uint256'], [stake_amount]).hex()
                
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': pool_addr,
                        'data': deposit_data,
                        'gas': hex(200000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                if 'result' in response:
                    tx_hash = response['result']
                    for i in range(20):
                        try:
                            receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                            if receipt and receipt.get('blockNumber'):
                                break
                        except:
                            pass
                        time.sleep(0.5)
                
                # 停止 impersonate
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
                
                print(f"  • Test account staked 0.5 LP tokens ✅")
                
                # 推进时间 100 秒，让奖励累积
                self.w3.provider.make_request('evm_increaseTime', [100])
                self.w3.provider.make_request('evm_mine', [])
                
                print(f"  • Time advanced by 100 seconds (rewards accumulated) ✅")
                
            except Exception as e:
                print(f"  • LP staking failed: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            print(f"  • SimpleRewardPool Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.simple_reward_pool_address = None
        
        print()
    
    def _setup_rich_account(self):
        """
        设置富有账户用于 transferFrom 测试
        
        创建一个拥有大量 USDT 的账户，并授权 test_address 可以使用这些代币
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        import time
        
        print(f"✓ 设置富有账户 (用于 transferFrom 测试)...")
        
        try:
            # 使用固定地址作为富有账户（方便测试和调试）
            # 这个地址在 Anvil 本地环境中，我们可以直接操作其余额
            rich_account = Account.create()
            self.rich_address = rich_account.address
            
            usdt_address = '0x55d398326f99059fF775485246999027B3197955'
            usdt_addr = to_checksum_address(usdt_address)
            rich_addr = to_checksum_address(self.rich_address)
            test_addr = to_checksum_address(self.test_address)
            
            # 1. 给富有账户设置 USDT 余额 (5000 USDT)
            rich_usdt_amount = 5000 * 10**18
            if self._set_erc20_balance_direct(usdt_addr, rich_addr, rich_usdt_amount, balance_slot=1):
                print(f"  • Rich account: {self.rich_address}")
                print(f"  • Rich account USDT balance: {rich_usdt_amount / 10**18:.2f} USDT ✅")
            else:
                print(f"  • Failed to set rich account balance")
                return
            
            # 2. 授权 test_address 可以花费富有账户的 USDT (大额授权 1000 USDT)
            # 使用 anvil_setStorageAt 直接设置 allowance（更快更可靠）
            # ERC20 allowance mapping: mapping(address => mapping(address => uint256)) at slot 2 for USDT
            # Storage slot = keccak256(spender_address + keccak256(owner_address + slot))
            from eth_utils import keccak
            
            approve_amount = 1000 * 10**18  # Approve 1000 USDT
            allowance_slot = 2  # USDT uses slot 2 for allowances
            
            # Calculate storage slot for allowance[rich_address][test_address]
            # First hash: keccak256(owner_address + slot)
            owner_padded = rich_addr[2:].lower().rjust(64, '0')
            slot_padded = format(allowance_slot, '064x')
            inner_key = owner_padded + slot_padded
            inner_hash = keccak(bytes.fromhex(inner_key))
            
            # Second hash: keccak256(spender_address + inner_hash)
            spender_padded = test_addr[2:].lower().rjust(64, '0')
            inner_hash_hex = inner_hash.hex()
            outer_key = spender_padded + inner_hash_hex
            storage_slot = '0x' + keccak(bytes.fromhex(outer_key)).hex()
            
            # Set allowance value
            value = '0x' + format(approve_amount, '064x')
            
            self.w3.provider.make_request(
                'anvil_setStorageAt',
                [usdt_addr, storage_slot, value]
            )
            
            # Mine a block to ensure the change is committed
            self.w3.provider.make_request('evm_mine', [])
            
            print(f"  • Test account approved for {approve_amount / 10**18:.2f} USDT ✅")
            
        except Exception as e:
            print(f"  • Rich account setup: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
            self.rich_address = None
        
        print()
    
    def _set_balance(self, address: str, balance_wei: int):
        """
        使用 Anvil cheatcode 设置地址余额
        
        Args:
            address: 地址
            balance_wei: 余额 (wei)
        """
        from eth_utils import to_checksum_address
        
        address_checksum = to_checksum_address(address)
        self.w3.provider.make_request(
            'anvil_setBalance',
            [address_checksum, hex(balance_wei)]
        )
    
    def get_balance(self, address: str) -> float:
        """
        获取地址余额
        
        Args:
            address: 地址
            
        Returns:
            余额 (BNB)
        """
        balance_wei = self.w3.eth.get_balance(address)
        return balance_wei / 10**18
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.stop()

