with open('frontend/src/app/admin-290123-7234878/components/BlogTab.jsx', 'r', encoding='utf-8') as f:
    text = f.read()

# Helper slugify function for frontend auto-generation
helper_code = '''
function slugifyText(text) {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\\w\\s-]/g, '')
    .replace(/[\\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
'''

# 1. Add slugifyText before BlogTab component
if "function slugifyText" not in text:
    text = text.replace("export default function BlogTab() {", helper_code + "\nexport default function BlogTab() {")

# 2. Add isSlugManual state
old_state = "  const [slug, setSlug] = useState('');"
new_state = """  const [slug, setSlug] = useState('');
  const [isSlugManual, setIsSlugManual] = useState(false);"""
if old_state in text and "isSlugManual" not in text:
    text = text.replace(old_state, new_state)

# 3. In handleCreateNew, reset isSlugManual
old_create = "    setSlug('');"
new_create = "    setSlug('');\n    setIsSlugManual(false);"
if old_create in text:
    text = text.replace(old_create, new_create, 1)

# 4. In handleEdit, set isSlugManual to true
old_edit = "    setSlug(post.slug);"
new_edit = "    setSlug(post.slug);\n    setIsSlugManual(true);"
if old_edit in text:
    text = text.replace(old_edit, new_edit, 1)

# 5. When title changes, auto-update slug if not manually edited
old_title_input = """                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Article Headline (e.g. The ATS Parser Benchmark)"
                    className="w-full bg-transparent text-xl sm:text-2xl font-bold text-white placeholder-zinc-600 focus:outline-none"
                  />"""

new_title_input = """                  <input
                    type="text"
                    value={title}
                    onChange={(e) => {
                      const newTitle = e.target.value;
                      setTitle(newTitle);
                      if (!isSlugManual) {
                        setSlug(slugifyText(newTitle));
                      }
                    }}
                    placeholder="Article Headline (e.g. The ATS Parser Benchmark)"
                    className="w-full bg-transparent text-xl sm:text-2xl font-bold text-white placeholder-zinc-600 focus:outline-none"
                  />"""

if old_title_input in text:
    text = text.replace(old_title_input, new_title_input)

# 6. Slug input: detect manual edit
old_slug_input = """                  <input
                    type="text"
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g. ats-resume-benchmark"
                    className="w-full px-3 py-1.5 rounded-lg bg-black/40 border border-white/[0.08] text-xs text-white focus:outline-none focus:border-[#C88A58]"
                  />"""

new_slug_input = """                  <div className="relative">
                    <input
                      type="text"
                      value={slug}
                      onChange={(e) => {
                        const val = e.target.value;
                        setSlug(val);
                        if (val.trim()) {
                          setIsSlugManual(true);
                        } else {
                          setIsSlugManual(false);
                          setSlug(slugifyText(title));
                        }
                      }}
                      placeholder="e.g. ats-resume-benchmark"
                      className="w-full px-3 py-1.5 rounded-lg bg-black/40 border border-white/[0.08] text-xs text-white focus:outline-none focus:border-[#C88A58]"
                    />
                    {isSlugManual && (
                      <button
                        type="button"
                        onClick={() => {
                          setIsSlugManual(false);
                          setSlug(slugifyText(title));
                        }}
                        className="absolute right-2 top-1.5 text-[10px] text-[#D49A6A] hover:underline font-mono"
                        title="Reset to title-based slug"
                      >
                        Reset auto
                      </button>
                    )}
                  </div>"""

if old_slug_input in text:
    text = text.replace(old_slug_input, new_slug_input)

# 7. Validation on handleSave: title >= 5 characters, slug can be auto or manual
old_validation = """    if (!title.trim() || !summary.trim()) {
      toast.error('Title and Summary are required.');
      return;
    }"""

new_validation = """    const cleanTitle = title.trim();
    if (!cleanTitle || cleanTitle.length < 5) {
      toast.error('Title must be at least 5 characters long.');
      return;
    }
    if (!summary.trim()) {
      toast.error('Summary is required.');
      return;
    }

    // Determine final slug
    let finalSlug = slug.trim();
    if (!finalSlug) {
      finalSlug = slugifyText(cleanTitle);
    } else {
      finalSlug = slugifyText(finalSlug);
    }"""

if old_validation in text:
    text = text.replace(old_validation, new_validation)

# 8. Payload should use finalSlug
old_payload = """        title,
        slug: slug.trim() || undefined,"""

new_payload = """        title: cleanTitle,
        slug: finalSlug || undefined,"""

if old_payload in text:
    text = text.replace(old_payload, new_payload)

with open('frontend/src/app/admin-290123-7234878/components/BlogTab.jsx', 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)

print('Updated BlogTab.jsx with auto and manual slug management!')
