-- Headless check that the typed-jinja LSP attaches and publishes diagnostics.
-- Run from the project root: nvim --headless -l scripts/verify_lsp.lua
-- Phase 1 checks a bad template on disk. Phase 2 makes an unsaved edit to a
-- clean template and confirms a diagnostic appears from the live buffer.
-- Exits 0 only when both phases produce the expected diagnostics.

local root = vim.fn.getcwd()
local exe = root .. '/.venv/bin/typed-jinja-lsp'
if not (vim.uv or vim.loop).fs_stat(exe) then
  exe = 'typed-jinja-lsp'
end

vim.filetype.add({
  extension = { jinja = 'jinja' },
  pattern = { ['.*%.html%.jinja'] = 'jinja' },
})

vim.lsp.config('typed_jinja', {
  cmd = { exe },
  filetypes = { 'jinja', 'html.jinja' },
  root_markers = { 'pyproject.toml', '.git' },
})
vim.lsp.enable('typed_jinja')

local function open(path)
  vim.cmd.edit(path)
  local buf = vim.api.nvim_get_current_buf()
  vim.bo[buf].filetype = 'jinja'
  vim.wait(20000, function()
    return #vim.lsp.get_clients({ bufnr = buf, name = 'typed_jinja' }) > 0
  end, 200)
  return buf
end

-- Phase 1: bad template on disk.
local bad = open(root .. '/examples/templates/greeting_bad.html')
vim.wait(20000, function() return #vim.diagnostic.get(bad) > 0 end, 200)
local disk_diags = vim.diagnostic.get(bad)
io.write(string.format('phase1 (disk) diagnostics=%d\n', #disk_diags))
for _, d in ipairs(disk_diags) do
  io.write(string.format('  L%d C%d [%s] %s\n', d.lnum + 1, d.col + 1, d.source or '?', d.message))
end

-- Phase 2: clean template, unsaved edit introduces a typo.
local ok = open(root .. '/examples/templates/greeting_ok.html')
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

local phase1_ok = #disk_diags > 0
local phase2_ok = live_appeared and #before == 0
if phase1_ok and phase2_ok then
  vim.cmd('qall!')
else
  vim.cmd('cquit 1')
end
