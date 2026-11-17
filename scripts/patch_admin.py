with open('frontend/src/app/admin-290123-7234878/page.jsx', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add import for BlogTab
import_target = "import SectionMakerTab from './components/SectionMakerTab';"
import_replacement = "import SectionMakerTab from './components/SectionMakerTab';\nimport BlogTab from './components/BlogTab';"
if import_target in text and "import BlogTab" not in text:
    text = text.replace(import_target, import_replacement)

# 2. Add sidebar button for blog
sidebar_target = """              <button
                onClick={() => setActiveTab('feedbacks')}"""
sidebar_replacement = """              <button
                onClick={() => setActiveTab('blogs')}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-xs font-semibold transition cursor-pointer text-left ${
                  activeTab === 'blogs'
                    ? 'bg-amber-500/10 text-amber-400 border border-amber-500/25 shadow-sm'
                    : 'text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60'
                }`}
                title="Editorial & Blog Articles"
              >
                <FileText className="w-4 h-4 shrink-0 text-amber-400" />
                {!sidebarCollapsed && <span>Editorial &amp; Blogs</span>}
              </button>

              <button
                onClick={() => setActiveTab('feedbacks')}"""

if sidebar_target in text and "setActiveTab('blogs')" not in text:
    text = text.replace(sidebar_target, sidebar_replacement)

# 3. Add breadcrumbs for blog
crumb_target = "{activeTab === 'feedbacks' && 'User Telemetry & Feedback'}"
crumb_replacement = "{activeTab === 'blogs' && 'Editorial & SEO Blog Posts'}\n              {activeTab === 'feedbacks' && 'User Telemetry & Feedback'}"
if crumb_target in text and "activeTab === 'blogs'" not in text:
    text = text.replace(crumb_target, crumb_replacement)

crumb_desc_target = "{activeTab === 'feedbacks' && 'User Feedbacks & Pilot Reports'}"
crumb_desc_replacement = "{activeTab === 'blogs' && 'Articles & Guides (Tiptap Rich Text)'}\n              {activeTab === 'feedbacks' && 'User Feedbacks & Pilot Reports'}"
if crumb_desc_target in text and "Articles & Guides" not in text:
    text = text.replace(crumb_desc_target, crumb_desc_replacement)

# 4. Add tab render for blog
tab_render_target = "        {/* ─── TAB: USER FEEDBACKS & PILOT REPORTS ──────────────────────────── */}"
tab_render_replacement = """        {/* ─── TAB: EDITORIAL & BLOGS (Tiptap) ──────────────────────────────── */}
        {activeTab === 'blogs' && (
          <BlogTab />
        )}

        {/* ─── TAB: USER FEEDBACKS & PILOT REPORTS ──────────────────────────── */}"""

if tab_render_target in text and "<BlogTab />" not in text:
    text = text.replace(tab_render_target, tab_render_replacement)

with open('frontend/src/app/admin-290123-7234878/page.jsx', 'w', encoding='utf-8', newline='\n') as f:
    f.write(text)

print('Successfully integrated BlogTab into Admin page.jsx!')
