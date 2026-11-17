import os

with open('frontend/src/app/pricing/page.jsx', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("import { PLANS } from '@/components/pricing/PricingModal';", "import { DEFAULT_PLANS } from '@/lib/plans';")
text = text.replace("PLANS.map", "DEFAULT_PLANS.map")

with open('frontend/src/app/pricing/page.jsx', 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)

with open('frontend/src/app/page.jsx', 'r', encoding='utf-8') as f:
    ptext = f.read()

ptext = ptext.replace("import { PLANS } from '@/components/pricing/PricingModal';", "import { DEFAULT_PLANS } from '@/lib/plans';")
ptext = ptext.replace("const [plans, setPlans] = useState(PLANS);", "const [plans, setPlans] = useState(DEFAULT_PLANS);")

with open('frontend/src/app/page.jsx', 'w', encoding='utf-8', newline='\n') as f:
    f.write(ptext)

print('Updated imports to DEFAULT_PLANS successfully')
