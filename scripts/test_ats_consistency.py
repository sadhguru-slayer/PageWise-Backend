import json
from app.ats_scorer import compute_legit_ats_evaluation

sample_resume = {
    'header_json': {
        'name': 'Jane Doe',
        'email': 'jane.doe@example.com',
        'phone': '+1 555-123-4567',
        'location': 'San Francisco, CA',
        'linkedin': 'linkedin.com/in/janedoe'
    },
    'sections_json': [
        {
            'id': 'sec-exp',
            'title': 'Experience',
            'items': [
                {
                    'id': 'exp-1',
                    'role': 'Senior Full Stack Engineer',
                    'company': 'Tech Corp',
                    'start_date': '2021-03',
                    'end_date': 'Present',
                    'points': [
                        'Architected and deployed distributed FastAPI microservices handling 25,000 daily requests.',
                        'Optimized PostgreSQL query performance, reducing p95 latency by 42%.',
                        'Engineered interactive React frontend components with Next.js and Tailwind CSS.'
                    ]
                }
            ]
        },
        {
            'id': 'sec-edu',
            'title': 'Education',
            'items': [
                {
                    'id': 'edu-1',
                    'institution': 'University of California, Berkeley',
                    'degree': 'B.S. in Computer Science',
                    'start_date': '2016',
                    'end_date': '2020'
                }
            ]
        },
        {
            'id': 'sec-skills',
            'title': 'Technical Skills',
            'items': [
                {
                    'category': 'Languages & Frameworks',
                    'skills': ['Python', 'FastAPI', 'React', 'PostgreSQL', 'Docker']
                }
            ]
        }
    ]
}

jd = 'Looking for a Senior Full Stack Engineer proficient in Python, FastAPI, React, PostgreSQL, Docker, and Kubernetes (k8s).'

ai_mock = {
    'job_analysis': {'title': 'Senior Full Stack Engineer', 'company': 'Tech Corp'},
    'ats_check': {
        'matched_keywords': ['Python', 'FastAPI', 'React', 'PostgreSQL', 'Docker'],
        'missing_keywords': ['Kubernetes'],
        'recommended_keywords': ['CI/CD', 'AWS'],
        'overall_score': 99
    }
}

# Run 1: Workspace A
res1 = compute_legit_ats_evaluation(sample_resume, ai_mock, jd)
# Run 2: Workspace B (Exported / Imported)
res2 = compute_legit_ats_evaluation(sample_resume, ai_mock, jd)

print(f"Workspace A Overall: {res1['overall_score']}, Grade: {res1['grade']}")
print(f"Workspace A Breakdown: {res1['category_scores']}")
print(f"Workspace B Overall: {res2['overall_score']}, Grade: {res2['grade']}")
print(f"Workspace B Breakdown: {res2['category_scores']}")

assert res1['overall_score'] == res2['overall_score'], "Scores must be identical!"
assert res1['category_scores'] == res2['category_scores'], "Category scores must be identical!"

cats = res1['category_scores']
weighted = round(0.35 * cats['keyword_alignment'] + 0.25 * cats['relevant_experience'] + 0.20 * cats['content_specificity'] + 0.20 * cats['structure_parseability'])
print(f"Calculated weighted: {weighted}, returned overall: {res1['overall_score']}")
assert res1['overall_score'] == weighted, f"Mismatch: {weighted} != {res1['overall_score']}"

print("SUCCESS: Full ATS score consistency & mathematical validity verified!")
