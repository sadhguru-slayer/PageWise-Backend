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

ai_mock = {
    'ats_check': {
        'matched_keywords': ['Python', 'FastAPI', 'React', 'PostgreSQL', 'Docker'],
        'missing_keywords': [],
        'recommended_keywords': ['GraphQL', 'Kubernetes'],
        'overall_score': 95
    }
}

# Standalone ATS Mode (job_description is None)
res = compute_legit_ats_evaluation(sample_resume, ai_mock, job_description=None)
print("Standalone ATS Result:")
print("Overall:", res['overall_score'])
print("Grade:", res['grade'])
print("Breakdown:", res['category_scores'])
print("Improvements:", res['improvements'])

cats = res['category_scores']
weighted = round(0.30 * cats['structure_parseability'] + 0.30 * cats['content_specificity'] + 0.25 * cats['core_competencies'] + 0.15 * cats['evidence_of_impact'])
assert res['overall_score'] == weighted, f"Mismatch in standalone weighted score: {weighted} != {res['overall_score']}"

print("SUCCESS: Standalone ATS evaluation verified!")
