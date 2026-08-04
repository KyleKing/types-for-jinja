-- Headless check that the types-for-jinja LSP works in a real editor session.
--
-- Run through scripts/verify_lsp.sh, which builds a throwaway project first so
-- nothing is written into the repo. The server no longer runs a type checker, so
-- the phases split in two: what this server publishes on its own, and the stub it
-- writes for the project's own Python language server to check.
--
--   1. a template with no {#def #} header is reported, not silently skipped
--   2. opening a template writes its stub
--   3. an unsaved edit is in the stub before the file is saved
--   4. context-name completion inside a {% for %} body
--   5. hover over a declared parameter
--   6. attribute completion after a `.`, resolved through a language server
--   7. filter completion after `|`
--
-- Exits 0 only when every phase produces the expected result.

local root = vim.fn.getcwd()
local exe = os.getenv('TJ_LSP') or 'types-for-jinja-lsp'
local repo = os.getenv('TJ_REPO') or '.'

vim.filetype.add({
  extension = { jinja = 'jinja' },
  pattern = { ['.*%.html%.jinja'] = 'jinja' },
})

vim.lsp.config('types_for_jinja', {
  cmd = { exe },
  filetypes = { 'jinja', 'html.jinja' },
  root_markers = { 'pyproject.toml', '.git' },
})
vim.lsp.enable('types_for_jinja')

-- A real Python language server, standing in for whatever the project already runs. It is
-- what actually type-checks the generated stubs; the mirror only moves what it reports.
vim.lsp.config('pyright', {
  cmd = { 'pyright-langserver', '--stdio' },
  filetypes = { 'python' },
  root_markers = { 'pyproject.toml', '.git' },
  settings = { python = { analysis = { extraPaths = { root } } } },
})
vim.lsp.enable('pyright')

vim.opt.runtimepath:append(repo .. '/editors/nvim')
require('types_for_jinja.mirror').setup()

local function open(path)
  vim.cmd('edit! ' .. vim.fn.fnameescape(path))
  local buf = vim.api.nvim_get_current_buf()
  vim.bo[buf].filetype = 'jinja'
  vim.wait(20000, function()
    return #vim.lsp.get_clients({ bufnr = buf, name = 'types_for_jinja' }) > 0
  end, 200)
  return buf
end

local function read(path)
  local handle = io.open(path, 'r')
  if not handle then return nil end
  local text = handle:read('*a')
  handle:close()
  return text
end

local function wait_for_stub(path, needle)
  local found = vim.wait(20000, function()
    local text = read(path)
    return text ~= nil and text:find(needle, 1, true) ~= nil
  end, 200)
  return found, read(path)
end

local function request(buf, method, params)
  local responses = vim.lsp.buf_request_sync(buf, method, params, 15000) or {}
  for _, response in pairs(responses) do
    if response.result then return response.result end
  end
  return nil
end

local function position(buf, line, col)
  return {
    textDocument = vim.lsp.util.make_text_document_params(buf),
    position = { line = line - 1, character = col },
  }
end

local function labels(result)
  local items = (result and (result.items or result)) or {}
  local out = {}
  for _, item in ipairs(items) do out[item.label] = item.detail or '' end
  return out
end

local stub = root .. '/_jinja_stubs/templates/page_html_jinja.py'

-- Phase 1: a headerless template is reported by this server, which needs no checker.
local bare = open(root .. '/templates/bare.html.jinja')
vim.wait(20000, function() return #vim.diagnostic.get(bare) > 0 end, 200)
local bare_diags = vim.diagnostic.get(bare)
io.write(string.format('phase1 (no header) diagnostics=%d\n', #bare_diags))
for _, d in ipairs(bare_diags) do
  io.write(string.format('  L%d [%s] %s\n', d.lnum + 1, d.source or '?', d.message))
end

-- Phase 2: opening a template writes its stub.
local page = open(root .. '/templates/page.html.jinja')
local wrote, stub_text = wait_for_stub(stub, '_ = user.naem')
io.write(string.format('phase2 (stub written) ok=%s\n', tostring(wrote)))

-- Phase 3: an unsaved edit reaches the stub.
for i, line in ipairs(vim.api.nvim_buf_get_lines(page, 0, -1, false)) do
  if line:find('user%.naem') then
    vim.api.nvim_buf_set_lines(page, i - 1, i, false, { (line:gsub('user%.naem', 'user.nmae')) })
    break
  end
end
local edited, edited_text = wait_for_stub(stub, '_ = user.nmae')
io.write(string.format('phase3 (unsaved edit in stub) ok=%s\n', tostring(edited)))

-- Phase 4: context names inside the {% for %} body.
local names = labels(request(page, 'textDocument/completion', position(page, 8, 10)))
io.write('phase4 (context completion)\n')
for label, detail in pairs(names) do io.write(string.format('  %s -- %s\n', label, detail)) end

-- Phase 5: hover over the declared parameter.
local hovered = request(page, 'textDocument/hover', position(page, 5, 14))
local hover_value = hovered and hovered.contents and hovered.contents.value or ''
io.write(string.format('phase5 (hover) %s\n', hover_value:gsub('\n', ' ')))

-- Phase 6: attribute completion inside the loop body, resolved through a language server.
vim.api.nvim_buf_set_lines(page, 7, 8, false, { '  <li>{{ item.' })
vim.wait(1000)
local members = labels(request(page, 'textDocument/completion', position(page, 8, 14)))
local member_names = {}
for label in pairs(members) do member_names[#member_names + 1] = label end
table.sort(member_names)
io.write(string.format('phase6 (members) %s\n', table.concat(member_names, ',')))

-- Phase 7: built-in filters after a pipe.
vim.api.nvim_buf_set_lines(page, 7, 8, false, { '  <li>{{ item |' })
local filters = labels(request(page, 'textDocument/completion', position(page, 8, 15)))
io.write(string.format('phase7 (filters) length=%s\n', tostring(filters['length'])))

-- Phase 8: the mirror puts the Python server's stub diagnostics on the template.
-- Earlier phases scribbled on the buffer, so restore the fixture's own three errors first.
vim.api.nvim_buf_set_lines(page, 4, 5, false, { '<h1>Hello {{ user.naem }}</h1>' })
vim.api.nvim_buf_set_lines(page, 7, 8, false, { '  <li>{{ item.titel }} by {{ author }}</li>' })
vim.cmd('silent write')
local mirrored = {}
local appeared = vim.wait(40000, function()
  mirrored = vim.diagnostic.get(page, { namespace = vim.api.nvim_create_namespace('types_for_jinja_mirror') })
  return #mirrored >= 3
end, 500)
io.write(string.format('phase8 (mirrored) appeared=%s count=%d\n', tostring(appeared), #mirrored))
table.sort(mirrored, function(a, b)
  if a.lnum ~= b.lnum then return a.lnum < b.lnum end
  return a.col < b.col
end)
for _, d in ipairs(mirrored) do
  local text = vim.api.nvim_buf_get_lines(page, d.lnum, d.lnum + 1, false)[1] or ''
  io.write(string.format('  L%d C%d %s | on: %s\n', d.lnum + 1, d.col + 1, d.message:gsub('\n', ' '), text))
end

--- The mirrored column must land on the identifier the message is about.
local function points_at(d, word)
  local text = vim.api.nvim_buf_get_lines(page, d.lnum, d.lnum + 1, false)[1] or ''
  return text:sub(d.col + 1, d.col + #word) == word
end

local phase1_ok = #bare_diags == 1 and bare_diags[1].message:find('{#def', 1, true) ~= nil
local phase2_ok = wrote and stub_text ~= nil
local phase3_ok = edited and edited_text:find('naem', 1, true) == nil
local phase4_ok = names['item'] ~= nil and names['loop'] ~= nil and names['user'] == 'user: User (parameter)'
local phase5_ok = hover_value:find('user: User', 1, true) ~= nil
local phase6_ok = #member_names == 2 and member_names[1] == 'done' and member_names[2] == 'title'
local phase7_ok = filters['length'] ~= nil and filters['length']:find('int', 1, true) ~= nil

local on_line_5 = vim.tbl_filter(function(d) return d.lnum == 4 end, mirrored)
local on_line_8 = vim.tbl_filter(function(d) return d.lnum == 7 end, mirrored)
local phase8_ok = appeared
  and #on_line_5 == 1 and points_at(on_line_5[1], 'naem')
  and #on_line_8 == 2
  and points_at(on_line_8[1], 'titel') and points_at(on_line_8[2], 'author')

io.write(string.format('phases ok: 1=%s 2=%s 3=%s 4=%s 5=%s 6=%s 7=%s 8=%s\n',
  tostring(phase1_ok), tostring(phase2_ok), tostring(phase3_ok), tostring(phase4_ok),
  tostring(phase5_ok), tostring(phase6_ok), tostring(phase7_ok), tostring(phase8_ok)))

if phase1_ok and phase2_ok and phase3_ok and phase4_ok
  and phase5_ok and phase6_ok and phase7_ok and phase8_ok then
  vim.cmd('qall!')
else
  vim.cmd('cquit 1')
end
