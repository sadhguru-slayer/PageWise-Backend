import copy
from app.ats_scorer import compute_legit_ats_evaluation

base_resume = {
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

# 1. Base Score
base_res = compute_legit_ats_evaluation(base_resume, ai_mock, jd)
print(f"Base Score: {base_res['overall_score']}, Breakdown: {base_res['category_scores']}")

# 2. Candidate adds Kubernetes to experience bullet
improved_resume = copy.deepcopy(base_resume)
improved_resume['sections_json'][0]['items'][0]['points'].append(
    'Managed containerized workloads using Kubernetes (k8s), improving cluster reliability to 99.9% uptime.'
)

improved_res = compute_legit_ats_evaluation(improved_resume, ai_mock, jd)
print(f"Improved Score: {improved_res['overall_score']}, Breakdown: {improved_res['category_scores']}")

assert improved_res['overall_score'] > base_res['overall_score'], "Score must legitimately increase when missing keyword is addressed!"
assert 'Kubernetes' in improved_res['matched_keywords'] or 'kubernetes' in [k.lower() for k in improved_res['matched_keywords']], "Kubernetes must now be matched!"

print("SUCCESS: Legitimate resume improvement raises ATS score reliably!")
