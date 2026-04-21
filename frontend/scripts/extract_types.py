import json

with open(r'c:\Users\Relanto\Downloads\opp_id_1_responses_dor_extract_api_payload_20260326_103502.json') as f:
    data = json.load(f)

for a in data['answers']:
    qid = a['question_id']
    types = set()
    for c in a.get('citations', []):
        if c.get('source_type'):
            types.add(c['source_type'])
    for conflict in a.get('conflicts', []):
        for c in conflict.get('citations', []):
            if c.get('source_type'):
                types.add(c['source_type'])
    if types:
        print(f"{qid}: {', '.join(sorted(types))}")
    else:
        print(f"{qid}: none")
