"""
Generate default NL template scores based on template characteristics.
This provides a quick fallback while the full scoring runs.
"""

import json
import glob
from pathlib import Path


def classify_template_by_heuristics(template: str) -> str:
    """Classify template difficulty using simple heuristics."""
    template_lower = template.lower()

    # Vague indicators (casual language, ambiguous terms)
    vague_indicators = [
        'i want', 'i need', 'please', 'help me',
        'can you', 'could you', 'would you',
        'somehow', 'maybe', 'approximately'
    ]

    # Precise indicators (technical terms, specific instructions)
    precise_indicators = [
        'execute', 'call', 'invoke', 'function',
        'contract at', 'address', '0x',
        'exactly', 'specific', 'precise'
    ]

    vague_count = sum(1 for indicator in vague_indicators if indicator in template_lower)
    precise_count = sum(1 for indicator in precise_indicators if indicator in template_lower)

    # Simple classification
    if vague_count > precise_count:
        return 'vague'
    elif precise_count > vague_count + 1:
        return 'precise'
    else:
        return 'moderate'


def extract_and_classify_templates():
    """Extract all templates and classify them."""
    project_root = Path(__file__).parent.parent
    question_files = glob.glob(
        str(project_root / 'bsc_quest_bench' / 'question_bank' / '**' / '*.json'),
        recursive=True
    )

    all_results = {}

    for filepath in question_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                question_id = data.get('id')
                templates = data.get('natural_language_templates', [])

                if question_id and templates:
                    question_results = []
                    for template in templates:
                        difficulty = classify_template_by_heuristics(template)
                        # Assign scores based on difficulty
                        if difficulty == 'precise':
                            score = 2.5
                        elif difficulty == 'moderate':
                            score = 5.0
                        else:  # vague
                            score = 7.5

                        question_results.append({
                            'template': template,
                            'scores': {'heuristic': score},
                            'average_score': score,
                            'difficulty': difficulty
                        })

                    all_results[question_id] = question_results
        except Exception as e:
            print(f"Error reading {filepath}: {e}")

    return all_results


def main():
    print("Generating default NL template scores using heuristics...")
    results = extract_and_classify_templates()

    output_file = Path(__file__).parent.parent / 'bsc_quest_bench' / 'nl_template_scores.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"✅ Default scores saved to {output_file}")

    # Print summary
    total_templates = sum(len(results) for results in results.values())
    difficulty_counts = {"precise": 0, "moderate": 0, "vague": 0}

    for question_results in results.values():
        for result in question_results:
            difficulty_counts[result['difficulty']] += 1

    print(f"\nTotal templates: {total_templates}")
    print(f"Precise: {difficulty_counts['precise']}")
    print(f"Moderate: {difficulty_counts['moderate']}")
    print(f"Vague: {difficulty_counts['vague']}")


if __name__ == "__main__":
    main()
