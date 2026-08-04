-- Headless check that the types-for-jinja LSP attaches and publishes diagnostics.
-- Run from the project root: nvim --headless -l scripts/verify_lsp.lua
-- Phase 1 checks a bad template on disk. Phase 2 makes an unsaved edit to a
-- clean template and confirms a diagnostic appears from the live buffer.
-- Phase 3 asks for completions inside a loop body. Phase 4 hovers a parameter.
-- Exits 0 only when every phase produces the expected result.

local root = vim.fn.getcwd()
local exe = root .. '/.venv/bin/types-for-jinja-lsp'
if not (vim.uv or vim.loop).fs_stat(exe) then
  exe = 'types-for-jinja-lsp'
end

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

local function open(path)
  vim.cmd('edit! ' .. vim.fn.fnameescape(path))
  local buf = vim.api.nvim_get_current_buf()
  vim.bo[buf].filetype = 'jinja'
  vim.wait(20000, function()
    return #vim.lsp.get_clients({ bufnr = buf, name = 'types_for_jinja' }) > 0
  end, 200)
  return buf
end

-- Phase 1: bad template on disk.
local bad = open(root .. '/examples/templates/greeting_bad.html.jinja')
vim.wait(20000, function() return #vim.diagnostic.get(bad) > 0 end, 200)
local disk_diags = vim.diagnostic.get(bad)
io.write(string.format('phase1 (disk) diagnostics=%d\n', #disk_diags))
for _, d in ipairs(disk_diags) do
  io.write(string.format('  L%d C%d [%s] %s\n', d.lnum + 1, d.col + 1, d.source or '?', d.message))
end

-- Phase 2: clean template, unsaved edit introduces a typo.
local ok = open(root .. '/examples/templates/greeting_ok.html.jinja')
vim.wait(3000, function() return false end, 200)
local before = vim.diagnostic.get(ok)
for i, line in ipairs(vim.api.nvim_buf_get_lines(ok, 0, -1, false)) do
  if line:find('user%.name') then
    vim.api.nvim_buf_set_lines(ok, i - 1, i, false, { (line:gsub('user%.name', 'user.nmae')) })
    break
  end
end
local live_appeared = vim.wait(20000, function() return #vim.diagnostic.get(ok) > 0 end, 200)
local live = vim.diagnostic.get(ok)
io.write(string.format('phase2 (live buffer) clean_before=%d after_edit=%d\n', #before, #live))
for _, d in ipairs(live) do
  io.write(string.format('  L%d C%d [%s] %s\n', d.lnum + 1, d.col + 1, d.source or '?', d.message))
end

-- Phase 3: completions offered inside the {% for %} body of the clean template.
local function request(buf, method, params)
  local responses = vim.lsp.buf_request_sync(buf, method, params, 10000) or {}
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

local clean = open(root .. '/examples/templates/greeting_ok.html.jinja')
local completion = request(clean, 'textDocument/completion', position(clean, 11, 13)) or {}
local items = completion.items or completion
local labels = {}
for _, item in ipairs(items) do labels[item.label] = item.detail or '' end
io.write(string.format('phase3 (completion) items=%d\n', #items))
for label, detail in pairs(labels) do io.write(string.format('  %s -- %s\n', label, detail)) end

-- Phase 4: hover over the `user` parameter reports its declared type.
local hovered = request(clean, 'textDocument/hover', position(clean, 5, 14))
local hover_value = hovered and hovered.contents and hovered.contents.value or ''
io.write(string.format('phase4 (hover) %s\n', hover_value:gsub('\n', ' ')))

local phase1_ok = #disk_diags > 0
local phase2_ok = live_appeared and #before == 0
local phase3_ok = labels['item'] ~= nil and labels['loop'] ~= nil and labels['user'] == 'user: User (parameter)'
local phase4_ok = hover_value:find('user: User', 1, true) ~= nil
io.write(string.format('phases ok: 1=%s 2=%s 3=%s 4=%s\n',
  tostring(phase1_ok), tostring(phase2_ok), tostring(phase3_ok), tostring(phase4_ok)))
if phase1_ok and phase2_ok and phase3_ok and phase4_ok then
  vim.cmd('qall!')
else
  vim.cmd('cquit 1')
end
