-- Headless check that the typed-jinja LSP attaches and publishes diagnostics.
-- Run from the project root: nvim --headless -l scripts/verify_lsp.lua
-- Exits 0 when diagnostics appear on the bad template, 1 otherwise.

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

vim.cmd.edit(root .. '/examples/templates/greeting_bad.html')
local buf = vim.api.nvim_get_current_buf()
vim.bo[buf].filetype = 'jinja'

local attached = vim.wait(20000, function()
  return #vim.lsp.get_clients({ bufnr = buf, name = 'typed_jinja' }) > 0
end, 200)

local has_diags = vim.wait(20000, function()
  return #vim.diagnostic.get(buf) > 0
end, 200)

local diags = vim.diagnostic.get(buf)
io.write(string.format('attached=%s ready=%s diagnostics=%d\n', tostring(attached), tostring(has_diags), #diags))
for _, d in ipairs(diags) do
  io.write(string.format('  L%d C%d [%s] %s\n', d.lnum + 1, d.col + 1, d.source or '?', d.message))
end

if #diags == 0 then
  vim.cmd('cquit 1')
else
  vim.cmd('qall!')
end
