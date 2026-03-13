#!/usr/bin/env python3
"""
自动补全自然语言模板脚本

功能：
1. 遍历所有问题 JSON 文件
2. 分析现有模板，识别缺失的难度级别
3. 使用 LLM 生成缺失的 moderate 和 vague 难度模板
4. 更新问题文件和 nl_template_scores.json

难度定义：
- precise: 技术术语清晰，参数明确，指令直接
- moderate: 一些口语化表达，但仍包含关键参数
- vague: 口语化，信息不完整或模糊，缺少技术细节
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Any
import anthropic


# 配置
QUESTION_BANK_DIR = "/home/yangpei/work/bsc_quest_bench/bsc_quest_bench/question_bank"
NL_TEMPLATE_SCORES_FILE = "/home/yangpei/work/bsc_quest_bench/bsc_quest_bench/nl_template_scores.json"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# 难度级别定义
DIFFICULTY_LEVELS = ["precise", "moderate", "vague"]

# 模板生成提示词
TEMPLATE_GENERATION_PROMPT = """你是一个专业的自然语言模板生成器。你的任务是为区块链操作问题生成不同难度级别的自然语言模板。

问题信息：
- 标题: {title}
- 类别: {category}
- 描述: {description}
- 参数: {parameters}

现有模板（{existing_difficulty} 难度）：
{existing_templates}

请生成 {target_difficulty} 难度的模板。

难度定义：
- precise (精确/简单): 技术术语清晰，参数明确，指令直接
  例如: "Transfer {{amount}} BNB to {{to_address}}"
  例如: "Swap {amount_in} {token_in_symbol} for {token_out_symbol} on PancakeSwap"

- moderate (均衡): 一些口语化表达，但仍然包含关键参数
  例如: "Could you send about {amount} BNB over to {to_address}?"
  例如: "I'd like to exchange {amount_in} {token_in_symbol} for some {token_out_symbol} using PancakeSwap"

- vague (模糊/困难): 口语化，信息不完整或模糊，缺少技术细节
  例如: "Move {amount} BNB to this address: {to_address}"
  例如: "Get me some {token_out_symbol} for {amount_in} {token_in_symbol}"

要求：
1. 必须使用与现有模板相同的参数占位符（如 {amount}, {to_address} 等）
2. 生成 2-3 个不同的模板变体
3. 保持与问题主题和操作类型的一致性
4. {target_difficulty} 难度的模板应该比 {existing_difficulty} 更加{comparison}

请直接返回 JSON 数组格式的模板列表，不要包含其他解释：
["模板1", "模板2", "模板3"]
"""


def load_json_file(file_path: str) -> Dict[str, Any]:
    """加载 JSON 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json_file(file_path: str, data: Dict[str, Any], indent: int = 2):
    """保存 JSON 文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def extract_parameters(template: str) -> List[str]:
    """从模板中提取参数占位符"""
    return re.findall(r'\{(\w+)\}', template)


def get_all_question_files() -> List[Path]:
    """获取所有问题 JSON 文件"""
    question_bank = Path(QUESTION_BANK_DIR)
    return sorted(question_bank.rglob("*.json"))


def analyze_existing_templates(templates: List[str], nl_scores: Dict[str, List[Dict]]) -> Dict[str, List[str]]:
    """分析现有模板的难度分布"""
    difficulty_map = {
        "precise": [],
        "moderate": [],
        "vague": []
    }

    # 从 nl_template_scores.json 中获取难度信息
    for template in templates:
        found = False
        for question_id, scored_templates in nl_scores.items():
            for scored_template in scored_templates:
                if scored_template["template"] == template:
                    difficulty = scored_template.get("difficulty", "precise")
                    difficulty_map[difficulty].append(template)
                    found = True
                    break
            if found:
                break

        # 如果在 nl_scores 中找不到，默认为 precise
        if not found:
            difficulty_map["precise"].append(template)

    return difficulty_map


def generate_templates_with_llm(
    question_data: Dict[str, Any],
    existing_templates: List[str],
    existing_difficulty: str,
    target_difficulty: str,
    client: anthropic.Anthropic
) -> List[str]:
    """使用 LLM 生成新模板"""

    # 确定比较词
    difficulty_order = {"precise": 0, "moderate": 1, "vague": 2}
    if difficulty_order[target_difficulty] > difficulty_order[existing_difficulty]:
        comparison = "口语化和模糊"
    else:
        comparison = "精确和技术化"

    # 构建提示词
    prompt = TEMPLATE_GENERATION_PROMPT.format(
        title=question_data.get("title", ""),
        category=question_data.get("category", ""),
        description="\n".join(question_data.get("description", [])[:3]),  # 只取前3行描述
        parameters=json.dumps(list(question_data.get("parameters", {}).keys()), ensure_ascii=False),
        existing_difficulty=existing_difficulty,
        existing_templates="\n".join([f"- {t}" for t in existing_templates]),
        target_difficulty=target_difficulty,
        comparison=comparison
    )

    try:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text.strip()

        # 尝试解析 JSON 响应
        # 移除可能的 markdown 代码块标记
        response_text = re.sub(r'^```json\s*', '', response_text)
        response_text = re.sub(r'\s*```$', '', response_text)

        new_templates = json.loads(response_text)

        if isinstance(new_templates, list):
            return new_templates
        else:
            print(f"警告: LLM 返回的不是列表格式")
            return []

    except Exception as e:
        print(f"错误: 生成模板失败 - {e}")
        return []


def update_question_file(file_path: Path, new_templates: List[str]):
    """更新问题文件，添加新模板"""
    data = load_json_file(str(file_path))

    # 获取现有模板
    existing_templates = data.get("natural_language_templates", [])

    # 添加新模板（去重）
    for template in new_templates:
        if template not in existing_templates:
            existing_templates.append(template)

    data["natural_language_templates"] = existing_templates
    save_json_file(str(file_path), data)


def update_nl_template_scores(
    nl_scores: Dict[str, List[Dict]],
    question_id: str,
    new_templates: List[str],
    difficulty: str
):
    """更新 nl_template_scores.json"""
    if question_id not in nl_scores:
        nl_scores[question_id] = []

    for template in new_templates:
        # 检查是否已存在
        exists = any(t["template"] == template for t in nl_scores[question_id])
        if not exists:
            nl_scores[question_id].append({
                "template": template,
                "scores": {},
                "average_score": 0.0,
                "difficulty": difficulty
            })


def main():
    """主函数"""
    if not ANTHROPIC_API_KEY:
        print("错误: 请设置 ANTHROPIC_API_KEY 环境变量")
        return

    # 初始化 Anthropic 客户端
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 加载 nl_template_scores.json
    print(f"加载 {NL_TEMPLATE_SCORES_FILE}...")
    nl_scores = load_json_file(NL_TEMPLATE_SCORES_FILE)

    # 获取所有问题文件
    question_files = get_all_question_files()
    print(f"找到 {len(question_files)} 个问题文件")

    # 统计信息
    stats = {
        "total_files": len(question_files),
        "processed": 0,
        "moderate_added": 0,
        "vague_added": 0,
        "errors": 0
    }

    # 遍历每个问题文件
    for idx, file_path in enumerate(question_files, 1):
        try:
            print(f"\n[{idx}/{len(question_files)}] 处理: {file_path.name}")

            # 加载问题数据
            question_data = load_json_file(str(file_path))
            question_id = question_data.get("id")

            if not question_id:
                print(f"  警告: 文件缺少 id 字段，跳过")
                continue

            # 获取现有模板
            existing_templates = question_data.get("natural_language_templates", [])
            if not existing_templates:
                print(f"  警告: 没有现有模板，跳过")
                continue

            # 分析现有模板的难度分布
            difficulty_map = analyze_existing_templates(existing_templates, nl_scores)

            print(f"  现有模板分布: precise={len(difficulty_map['precise'])}, "
                  f"moderate={len(difficulty_map['moderate'])}, vague={len(difficulty_map['vague'])}")

            # 生成缺失的模板
            all_new_templates = []

            # 生成 moderate 模板
            if len(difficulty_map["moderate"]) == 0 and len(difficulty_map["precise"]) > 0:
                print(f"  生成 moderate 模板...")
                moderate_templates = generate_templates_with_llm(
                    question_data,
                    difficulty_map["precise"],
                    "precise",
                    "moderate",
                    client
                )
                if moderate_templates:
                    print(f"    生成了 {len(moderate_templates)} 个 moderate 模板")
                    all_new_templates.extend(moderate_templates)
                    update_nl_template_scores(nl_scores, question_id, moderate_templates, "moderate")
                    stats["moderate_added"] += len(moderate_templates)

            # 生成 vague 模板
            if len(difficulty_map["vague"]) == 0:
                print(f"  生成 vague 模板...")
                # 优先使用 moderate 作为基础，如果没有则使用 precise
                base_templates = difficulty_map["moderate"] if difficulty_map["moderate"] else difficulty_map["precise"]
                base_difficulty = "moderate" if difficulty_map["moderate"] else "precise"

                vague_templates = generate_templates_with_llm(
                    question_data,
                    base_templates,
                    base_difficulty,
                    "vague",
                    client
                )
                if vague_templates:
                    print(f"    生成了 {len(vague_templates)} 个 vague 模板")
                    all_new_templates.extend(vague_templates)
                    update_nl_template_scores(nl_scores, question_id, vague_templates, "vague")
                    stats["vague_added"] += len(vague_templates)

            # 更新问题文件
            if all_new_templates:
                update_question_file(file_path, all_new_templates)
                print(f"  ✓ 已更新问题文件")

            stats["processed"] += 1

        except Exception as e:
            print(f"  ✗ 错误: {e}")
            stats["errors"] += 1

    # 保存更新后的 nl_template_scores.json
    print(f"\n保存 {NL_TEMPLATE_SCORES_FILE}...")
    save_json_file(NL_TEMPLATE_SCORES_FILE, nl_scores)

    # 打印统计信息
    print("\n" + "="*60)
    print("处理完成！")
    print("="*60)
    print(f"总文件数: {stats['total_files']}")
    print(f"成功处理: {stats['processed']}")
    print(f"添加 moderate 模板: {stats['moderate_added']}")
    print(f"添加 vague 模板: {stats['vague_added']}")
    print(f"错误数: {stats['errors']}")
    print("="*60)


if __name__ == "__main__":
    main()
