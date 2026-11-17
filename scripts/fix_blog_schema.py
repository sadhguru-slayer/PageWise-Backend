with open('backend/app/schemas.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """class BlogPostBase(BaseModel):
    title: str
    slug: str"""

replacement = """class BlogPostBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    slug: Optional[str] = Field(None, max_length=200)"""

if target in text:
    text = text.replace(target, replacement)
    with open('backend/app/schemas.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('Updated BlogPostBase in schemas.py')
else:
    print('Target not found in schemas.py')
