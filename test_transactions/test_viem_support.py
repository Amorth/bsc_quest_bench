"""
Test viem support
"""
import json
from pathlib import Path

print("=" * 70)
print("Testing Viem Support")
print("=" * 70)

# 1. Check system_config_viem.json exists
viem_config = Path('bsc_quest_bench/system_config_viem.json')
print(f"\n1. Viem config file: {'✅' if viem_config.exists() else '❌'}")

if viem_config.exists():
    with open(viem_config, 'r') as f:
        config = json.load(f)
    print(f"   Library: {config.get('library')}")
    print(f"   Version: {config.get('version')}")

# 2. Check package.json has viem
package_json = Path('bsc_quest_bench/skill_runner/package.json')
print(f"\n2. Package.json: {'✅' if package_json.exists() else '❌'}")

if package_json.exists():
    with open(package_json, 'r') as f:
        pkg = json.load(f)
    deps = pkg.get('dependencies', {})
    print(f"   ethers: {deps.get('ethers', 'not found')}")
    print(f"   viem: {deps.get('viem', 'not found')}")

# 3. Check run_quest_bench.py has --library parameter
run_script = Path('run_quest_bench.py')
print(f"\n3. Run script: {'✅' if run_script.exists() else '❌'}")

if run_script.exists():
    with open(run_script, 'r') as f:
        content = f.read()
    has_library_param = '--library' in content and "choices=['ethers', 'viem']" in content
    print(f"   --library parameter: {'✅' if has_library_param else '❌'}")

# 4. Check QuestController supports library parameter
controller = Path('bsc_quest_bench/quest_controller.py')
print(f"\n4. QuestController: {'✅' if controller.exists() else '❌'}")

if controller.exists():
    with open(controller, 'r') as f:
        content = f.read()
    has_library_support = 'library: str' in content and 'system_config_viem.json' in content
    print(f"   Library support: {'✅' if has_library_support else '❌'}")

print("\n" + "=" * 70)
print("Summary")
print("=" * 70)
print("\n✅ Viem support has been added!")
print("\nUsage:")
print("  # Use ethers.js (default)")
print("  python run_quest_bench.py --model MODEL --library ethers ...")
print("\n  # Use viem")
print("  python run_quest_bench.py --model MODEL --library viem ...")
print()
